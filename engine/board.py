import random
from . import config
from .state import GameState, BotState, Resource, CoreObject

CORNER_SPAWNS = [
    (0, 0),
    (config.MAP_SIZE - 1, 0),
    (0, config.MAP_SIZE - 1),
    (config.MAP_SIZE - 1, config.MAP_SIZE - 1),
]

CORNER_RING = [0, 1, 3, 2]

def default_spawn_indices(bot_count: int, seed: int):
    if not 2 <= bot_count <= len(CORNER_SPAWNS):
        raise ValueError(f"Board supports 2 to {len(CORNER_SPAWNS)} bots.")

    rotation = seed % len(CORNER_RING)
    ring = CORNER_RING[rotation:] + CORNER_RING[:rotation]
    if bot_count == 2:
        return [ring[0], ring[2]]
    return ring[:bot_count]

def rotational_orbit(x, y, width, height):
    if width != height:
        raise ValueError("Rotational resource fairness requires a square board.")
    size = width
    return [
        (x, y),
        (size - 1 - y, x),
        (size - 1 - x, size - 1 - y),
        (y, size - 1 - x),
    ]

def build_walls(seed: int):
    rng = random.Random(f"{seed}-walls")
    name = rng.choice(sorted(config.WALL_TEMPLATES))
    walls = set()
    for x, y in [*config.BASE_POCKET_WALLS, *config.WALL_TEMPLATES[name]]:
        walls.update(rotational_orbit(x, y, config.MAP_SIZE, config.MAP_SIZE))
    return name, frozenset(walls)

def _build_legendary(seed: int, walls, pads):
    if not config.LEGENDARY_ENABLED:
        return None
    rng = random.Random(f"{seed}-legendary")
    turn = rng.randint(config.LEGENDARY_TURN_MIN, config.LEGENDARY_TURN_MAX)
    blocked = set(walls) | set(pads) | set(config.CORE_POSITIONS)
    candidates = sorted({
        cell
        for x, y in ((4, 4), (5, 3), (3, 5), (5, 4), (4, 5))
        for cell in rotational_orbit(x, y, config.MAP_SIZE, config.MAP_SIZE)
        if cell not in blocked
    })
    x, y = rng.choice(candidates)
    return {"turn": turn, "x": x, "y": y, "item": rng.choice(config.LEGENDARY_ITEMS)}

def normalize_series(series, bot_ids):
    series = dict(series or {})
    ids = set(bot_ids)
    crown = series.get("crown")

    def counts(key, cap=None):
        out = {}
        for bot_id, value in sorted((series.get(key) or {}).items()):
            if bot_id in ids and isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                out[bot_id] = min(value, cap) if cap is not None else value
        return out

    return {
        "credits": counts("credits", config.CREDIT_CAP),
        "loss_streaks": counts("loss_streaks"),
        "history": {
            bot_id: [int(p) for p in places]
            for bot_id, places in sorted((series.get("history") or {}).items())
            if bot_id in ids and isinstance(places, list)
        },
        "crown": crown if crown in ids else None,
        "streaks": {
            bot_id: int(streak)
            for bot_id, streak in sorted((series.get("streaks") or {}).items())
            if bot_id in ids and isinstance(streak, int) and streak > 0
        },
        "nemesis": {
            bot_id: rival
            for bot_id, rival in sorted((series.get("nemesis") or {}).items())
            if bot_id in ids and rival in ids and rival != bot_id
        },
    }

def build_initial_state(bot_ids, seed: int, spawn_indices=None, series=None) -> GameState:
    if not isinstance(bot_ids, (list, tuple)):
        raise TypeError("bot_ids must be a list or tuple.")
    if not 2 <= len(bot_ids) <= len(CORNER_SPAWNS):
        raise ValueError(f"Board supports 2 to {len(CORNER_SPAWNS)} bots.")
    if any(not isinstance(bot_id, str) or not bot_id for bot_id in bot_ids):
        raise ValueError("Every bot ID must be a non-empty string.")
    if len(set(bot_ids)) != len(bot_ids):
        raise ValueError("Bot IDs must be unique.")
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise TypeError("seed must be an integer.")
    if spawn_indices is None:
        spawn_indices = default_spawn_indices(len(bot_ids), seed)
    if not isinstance(spawn_indices, (list, tuple)):
        raise TypeError("spawn_indices must be a list or tuple.")
    if len(spawn_indices) != len(bot_ids):
        raise ValueError("A spawn index is required for every bot.")
    if len(set(spawn_indices)) != len(spawn_indices):
        raise ValueError("Bots cannot share a spawn corner.")
    if any(
        not isinstance(index, int)
        or isinstance(index, bool)
        or not 0 <= index < len(CORNER_SPAWNS)
        for index in spawn_indices
    ):
        raise ValueError("Spawn indices must identify one of the four corners.")

    rng = random.Random(seed)

    if config.NUM_RESOURCES % 4:
        raise ValueError("NUM_RESOURCES must be divisible by 4 for rotational fairness.")

    bots = {}
    for i, bid in enumerate(bot_ids):
        bx, by = CORNER_SPAWNS[spawn_indices[i]]
        bots[bid] = BotState(
            id=bid,
            x=bx,
            y=by,
            base_x=bx,
            base_y=by,
            hp=config.START_HP,
            energy=config.START_ENERGY,
            max_hp=config.START_HP,
            cargo_capacity=config.CARGO_CAPACITY,
            respawn_delay=config.RESPAWN_DELAY,
            cooldown_turns=config.ABILITY_COOLDOWN_TURNS,
        )

    center = config.CORE_POSITIONS[seed % len(config.CORE_POSITIONS)]
    layout, walls = build_walls(seed)

    occupied = {(b.x, b.y) for b in bots.values()}
    occupied.update(config.CORE_POSITIONS)
    occupied.update(walls)

    resources = {}
    placed = 0
    rid = 0
    while placed < config.NUM_RESOURCES:
        x = rng.randint(0, config.MAP_SIZE - 1)
        y = rng.randint(0, config.MAP_SIZE - 1)
        orbit = rotational_orbit(x, y, config.MAP_SIZE, config.MAP_SIZE)
        if len(set(orbit)) != 4 or any(cell in occupied for cell in orbit):
            continue
        value = rng.randint(config.RESOURCE_VALUE_MIN, config.RESOURCE_VALUE_MAX)
        for resource_x, resource_y in orbit:
            occupied.add((resource_x, resource_y))
            key = f"R{rid}"
            resources[key] = Resource(
                id=key, x=resource_x, y=resource_y, value=value,
            )
            rid += 1
            placed += 1

    core = CoreObject(
        x=center[0], y=center[1], active=False,
        spawn_turn=config.CORE_FIRST_SPAWN_TURN,
    )
    pads = tuple(rotational_orbit(*config.UPLINK_PAD_CELL, config.MAP_SIZE, config.MAP_SIZE))
    if any(pad in walls for pad in pads):
        raise ValueError(f"Wall template {layout!r} covers an uplink pad.")

    event_schedule = _build_event_schedule(rng)
    supply_schedule = _build_supply_schedule(rng)
    item_pool, crate_schedule = _build_crates(seed)
    legendary = _build_legendary(seed, walls, pads)
    series = normalize_series(series, bot_ids)
    for bot_id, bot in bots.items():
        bot.series_streak = series["streaks"].get(bot_id, 0)
        bot.nemesis = series["nemesis"].get(bot_id)

    return GameState(
        turn=0,
        max_turns=config.MAX_TURNS,
        width=config.MAP_SIZE,
        height=config.MAP_SIZE,
        bots=bots,
        resources=resources,
        core=core,
        seed=seed,
        walls=walls,
        layout=layout,
        pads=pads,
        event_schedule=event_schedule,
        supply_schedule=supply_schedule,
        item_pool=item_pool,
        crate_schedule=crate_schedule,
        legendary=legendary,
        series=series,
        crown_holder=series["crown"],
    )

def _build_crates(seed: int):
    if not config.CRATES_ENABLED:
        return (), []
    rng = random.Random(f"{seed}-crates")
    pool = tuple(sorted(rng.sample(config.ITEM_TYPES, config.ITEM_POOL_SIZE)))
    schedule = []
    turn = rng.randint(config.CRATE_FIRST_MIN, config.CRATE_FIRST_MAX)
    while turn < config.MAX_TURNS - 2:
        schedule.append(turn)
        turn += rng.randint(config.CRATE_GAP_MIN, config.CRATE_GAP_MAX)
    return pool, schedule

def _build_supply_schedule(rng: random.Random):
    if not config.SUPPLY_WAVE_ENABLED:
        return []
    schedule = []
    turn = rng.randint(config.SUPPLY_WAVE_FIRST_MIN, config.SUPPLY_WAVE_FIRST_MAX)
    while turn < config.MAX_TURNS:
        schedule.append(turn)
        turn += rng.randint(config.SUPPLY_WAVE_GAP_MIN, config.SUPPLY_WAVE_GAP_MAX)
    return schedule

def _build_event_schedule(rng: random.Random):
    event_types = list(config.EVENT_TYPES)
    rng.shuffle(event_types)
    schedule = []
    turn = rng.randint(config.EVENT_FIRST_TRIGGER_MIN, config.EVENT_FIRST_TRIGGER_MAX)
    for event_type in event_types:
        if turn >= config.MAX_TURNS:
            break
        schedule.append((turn, event_type))
        turn += rng.randint(config.EVENT_GAP_MIN, config.EVENT_GAP_MAX)
    return schedule

def chebyshev(x1, y1, x2, y2):
    return max(abs(x1 - x2), abs(y1 - y2))

def effective_vision(state, bot):
    vision = config.VISION_RANGE + bot.vision_bonus
    if bot.scanning:
        vision += config.SCAN_VISION_BONUS
    return vision

def in_bounds(x, y):
    return 0 <= x < config.MAP_SIZE and 0 <= y < config.MAP_SIZE

def nearest_free_cell(state, x, y, taken):
    taken = set(taken) | state.walls
    if (x, y) not in taken and in_bounds(x, y):
        return x, y
    for radius in range(1, max(state.width, state.height)):
        ring = sorted(
            (cx, cy)
            for cx in range(x - radius, x + radius + 1)
            for cy in range(y - radius, y + radius + 1)
            if max(abs(cx - x), abs(cy - y)) == radius
            and 0 <= cx < state.width and 0 <= cy < state.height
            and (cx, cy) not in taken
        )
        if ring:
            return ring[0]
    return None
