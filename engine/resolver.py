import random
import hashlib
from collections import Counter, defaultdict
from . import config
from .state import DIRECTIONS, Bomb, Crate, Resource, Smoke, Tag
from .actions import validate, InvalidAction
from .board import nearest_free_cell, rotational_orbit
from .geometry import shot_path, step_open

def _log(state, turn, event_type, **payload):
    state.events.append({"turn": turn, "type": event_type, **payload})

def _score(state, turn, bot, points, reason, **extra):
    if not points:
        return
    if "OVERTIME" in state.active_events and reason in config.OVERTIME_DOUBLED_REASONS:
        points *= config.OVERTIME_SCORE_MULTIPLIER
        extra = {**extra, "overtime": True}
    bot.score += points
    _log(state, turn, "SCORE", actor=bot.id, points=points, reason=reason, **extra)

def _is_protected(bot, turn):
    return turn < bot.protected_until

def _attack_impact(state, turn, attacker, target):
    material = (
        f"{state.seed}|combat|{turn}|"
        f"{attacker.base_x},{attacker.base_y}|{target.base_x},{target.base_y}"
    ).encode()
    span = config.ATTACK_DAMAGE_MAX - config.ATTACK_DAMAGE_MIN + 1
    roll = int.from_bytes(hashlib.sha256(material).digest()[:8], "big") % span
    damage = config.ATTACK_DAMAGE_MIN + roll
    if damage <= config.ATTACK_DAMAGE_MIN + 2:
        impact = "GLANCING"
    elif damage >= config.ATTACK_DAMAGE_MAX - 2:
        impact = "POWER"
    else:
        impact = "SOLID"
    return damage, impact

def _hits_wall(state, bot, action, start, dest):
    if action.type == "ABILITY" and bot.ability == "BLINK":
        return dest in state.walls
    dx, dy = DIRECTIONS[action.direction]
    x, y = start
    while (x, y) != dest:
        if not step_open(state.walls, state.width, state.height, x, y, dx, dy):
            return True
        x, y = x + dx, y + dy
    return False

def _shot_impact(state, turn, shooter, target):
    material = (
        f"{state.seed}|shot|{turn}|"
        f"{shooter.base_x},{shooter.base_y}|{target.base_x},{target.base_y}"
    ).encode()
    span = config.SHOOT_DAMAGE_MAX - config.SHOOT_DAMAGE_MIN + 1
    roll = int.from_bytes(hashlib.sha256(material).digest()[:8], "big") % span
    damage = config.SHOOT_DAMAGE_MIN + roll
    if damage <= config.SHOOT_DAMAGE_MIN + 1:
        impact = "GLANCING"
    elif damage >= config.SHOOT_DAMAGE_MAX - 1:
        impact = "POWER"
    else:
        impact = "SOLID"
    return damage, impact

def _cargo_drop_cell(state, bot):
    taken = {
        (resource.x, resource.y)
        for resource in state.resources.values()
        if not resource.collected
    }
    if state.core.active:
        taken.add((state.core.x, state.core.y))
    return nearest_free_cell(state, bot.x, bot.y, taken)

def _drop_cargo(state, turn, bot):
    if not bot.cargo_value:
        return
    dropped = int(bot.cargo_value * config.CARGO_DROP_FRACTION)
    units, bot.cargo_value, bot.cargo_units = bot.cargo_units, 0, 0
    if dropped <= 0:
        return

    cell = _cargo_drop_cell(state, bot)
    if cell is None:
        return
    key = f"L{turn}_{bot.id}"
    state.resources[key] = Resource(
        id=key, x=cell[0], y=cell[1], value=dropped, loot=True,
    )
    _log(
        state, turn, "CARGO_DROP", actor=bot.id, resource=key,
        x=cell[0], y=cell[1], value=dropped, units=units,
    )

def _grant_streak_power(state, turn, killer):
    if killer.streak == config.STREAK_RADAR_AT:
        killer.radar_until = max(killer.radar_until, turn + 1 + config.RADAR_DURATION)
        _log(state, turn, "STREAK_REWARD", actor=killer.id, reward="RADAR", streak=killer.streak)
    elif killer.streak == config.STREAK_AIRSTRIKE_AT:
        discarded, killer.item = killer.item, "AIRSTRIKE"
        _log(state, turn, "STREAK_REWARD", actor=killer.id, reward="AIRSTRIKE",
             streak=killer.streak, discarded=discarded)

def _apply_damage(state, turn, bot, damage):
    if damage <= 0:
        return False
    if bot.hp - damage <= 0 and turn < bot.overshield_until:
        bot.hp = 1
        bot.overshield_until = 0
        _log(state, turn, "OVERSHIELD_SAVE", actor=bot.id, absorbed=damage)
        return False
    bot.hp -= damage
    return bot.hp <= 0

def _resolve_deaths(state, turn, deaths, shove_credit=None):
    if not deaths:
        return
    shove_credit = shove_credit or {}
    crown_before = state.crown_holder
    streak_before = {bot_id: bot.streak for bot_id, bot in state.bots.items()}
    revenge_before = {bot_id: bot.last_killed_by for bot_id, bot in state.bots.items()}
    killed_by_now = {}
    dying = {victim.id for victim, _, _ in deaths}
    first_blood_open = not state.first_blood_taken
    first_blood_awarded = set()

    for victim, killer_ids, cause in sorted(deaths, key=lambda item: item[0].id):
        killer_ids = sorted(k for k in killer_ids if k != victim.id)
        victim.hp = 0
        victim.alive = False
        victim.deaths += 1
        victim.streak = 0
        victim.respawn_turn = turn + victim.respawn_delay
        core = state.core
        guarded = victim.carrying_core or (
            core.status == "PLANTED" and (
                core.planted_by == victim.id
                or max(abs(victim.x - core.x), abs(victim.y - core.y)) <= config.WARDEN_GUARD_RADIUS
            )
        )
        if victim.carrying_core:
            victim.carrying_core = False
            state.core.carried_by = None
            state.core.x, state.core.y = victim.x, victim.y
            _log(state, turn, "CORE_DROP", actor=victim.id, x=victim.x, y=victim.y)
        _drop_cargo(state, turn, victim)
        if victim.item is not None:
            taken = {(c.x, c.y) for c in state.crates.values()}
            cell = nearest_free_cell(state, victim.x, victim.y, taken)
            if cell is not None:
                crate_id = f"C{turn}_{victim.id}"
                state.crates[crate_id] = Crate(id=crate_id, x=cell[0], y=cell[1], item=victim.item)
                _log(state, turn, "CRATE_SPAWN", crate=crate_id, x=cell[0], y=cell[1], dropped_by=victim.id)
            victim.item = None
        _log(
            state, turn, "ELIMINATION", target=victim.id, attackers=killer_ids,
            cause=cause, respawn_turn=victim.respawn_turn,
        )

        victim_streak = streak_before[victim.id]
        crowned = victim.id == crown_before
        tag_share = 0
        for killer_id in killer_ids:
            killer = state.bots[killer_id]
            last = killer.last_kill_of.get(victim.id)
            repeat = last is not None and turn - last <= config.REPEAT_KILL_WINDOW
            base = config.REPEAT_KILL_SCORE if repeat else config.KILL_SCORE
            share = min(config.KILL_TAG_SHARE, base) if config.KILL_CONFIRMED else 0
            tag_share = max(tag_share, share)
            penalty = config.HAULER_KILL_PENALTY if killer.role == "HAULER" else 0
            _score(
                state, turn, killer, max(0, base - share - penalty),
                "REPEAT_KILL" if repeat else "KILL", target=victim.id,
            )
            if turn < killer.reaper_until:
                _score(state, turn, killer, base, "REAPER", target=victim.id)
            if killer.role == "HUNTER":
                _score(state, turn, killer, config.HUNTER_KILL_BONUS, "HUNTER", target=victim.id)
                _score(
                    state, turn, killer,
                    config.HUNTER_RAMPAGE_PER_LEVEL * streak_before[killer_id],
                    "RAMPAGE", target=victim.id, streak=streak_before[killer_id] + 1,
                )
            if victim.role == "HUNTER":
                _score(state, turn, killer, config.HUNTER_BOUNTY, "HUNTER_BOUNTY", target=victim.id)
            if killer.role == "WARDEN" and guarded:
                _score(state, turn, killer, config.WARDEN_GUARD_BONUS, "GUARD", target=victim.id)
            if streak_before[killer_id] >= config.ON_FIRE_STREAK:
                _score(state, turn, killer, config.ON_FIRE_KILL_BONUS, "ON_FIRE", target=victim.id)
            if victim_streak >= 2:
                cap = max(config.SHUTDOWN_BOUNTY)
                bounty = config.SHUTDOWN_BOUNTY[min(victim_streak, cap)]
                _score(state, turn, killer, bounty, "SHUTDOWN", target=victim.id,
                       victim_streak=victim_streak)
            if first_blood_open and killer_id not in first_blood_awarded:
                first_blood_awarded.add(killer_id)
                _score(state, turn, killer, config.FIRST_BLOOD_BONUS, "FIRST_BLOOD",
                       target=victim.id)
            if crowned:
                bounty = config.CROWN_BOUNTY + config.SERIES_STREAK_BOUNTY * max(
                    0, victim.series_streak - 1,
                )
                _score(state, turn, killer, bounty, "CROWN", target=victim.id)
            if killer.nemesis == victim.id:
                _score(state, turn, killer, config.NEMESIS_BONUS, "NEMESIS", target=victim.id)
            if revenge_before[killer_id] == victim.id:
                killer.last_killed_by = None
                _score(state, turn, killer, config.REVENGE_BONUS, "REVENGE", target=victim.id)
            state.kills_this_turn[killer_id] = state.kills_this_turn.get(killer_id, 0) + 1
            if state.kills_this_turn[killer_id] >= 2:
                _score(state, turn, killer, config.MULTI_KILL_BONUS, "MULTI_KILL",
                       target=victim.id, count=state.kills_this_turn[killer_id])
            if cause in ("BOMB", "AIRSTRIKE", "ORBITAL") and killer_id not in shove_credit.get(victim.id, ()):
                _score(state, turn, killer, config.BLAST_KILL_BONUS, "BLAST", target=victim.id)
            if killer_id in shove_credit.get(victim.id, ()):
                _score(state, turn, killer, config.BLAST_KILL_BONUS, "SHOVE_KILL", target=victim.id)
            if killer_id not in dying and 0 < killer.hp <= config.CLUTCH_KILL_HP:
                _score(state, turn, killer, config.CLUTCH_KILL_BONUS, "CLUTCH", target=victim.id)
            killer.kills += 1
            killer.last_kill_of[victim.id] = turn
            if killer_id not in dying:
                killer.streak += 1
                killer.best_streak = max(killer.best_streak, killer.streak)
                if killer.streak == config.ON_FIRE_STREAK:
                    _log(state, turn, "ON_FIRE", actor=killer_id, streak=killer.streak)
                _grant_streak_power(state, turn, killer)
        if killer_ids:
            state.first_blood_taken = True
            killed_by_now[victim.id] = killer_ids[0]
            if tag_share:
                tag_id = f"K{turn}_{victim.id}"
                state.tags[tag_id] = Tag(
                    id=tag_id, x=victim.x, y=victim.y, victim=victim.id,
                    killers=list(killer_ids),
                    expires_turn=turn + 1 + config.TAG_DURATION,
                )
                _log(state, turn, "TAG_DROP", tag=tag_id, x=victim.x, y=victim.y,
                     victim=victim.id, killers=list(killer_ids), value=tag_share)

        for helper_id, last_hit in sorted(victim.recent_damage.items()):
            if helper_id in killer_ids or helper_id == victim.id:
                continue
            if turn - last_hit < config.ASSIST_WINDOW:
                helper = state.bots[helper_id]
                helper.assists += 1
                _score(state, turn, helper, config.ASSIST_SCORE, "ASSIST", target=victim.id)
        victim.recent_damage.clear()

    for victim_id, killer_id in killed_by_now.items():
        state.bots[victim_id].last_killed_by = killer_id

def _blast_cells(state, bomb):
    cells = {}
    radius = bomb.radius
    for x in range(bomb.x - radius, bomb.x + radius + 1):
        for y in range(bomb.y - radius, bomb.y + radius + 1):
            if not (0 <= x < state.width and 0 <= y < state.height):
                continue
            distance = max(abs(x - bomb.x), abs(y - bomb.y))
            if distance > radius:
                continue
            if radius == 0 or distance == 0:
                damage = bomb.damage
            else:
                span = bomb.damage - bomb.edge_damage
                damage = bomb.damage - int(span * distance / radius)
            cells[(x, y)] = damage
    return cells

def _detonate_bombs(state, turn):
    due = sorted(
        (bomb for bomb in state.bombs.values() if turn >= bomb.detonates_turn),
        key=lambda bomb: bomb.id,
    )
    if not due:
        return

    exploded = []
    queue = list(due)
    seen = set()
    damage_at = defaultdict(int)
    owners_at = defaultdict(set)
    kinds_at = defaultdict(set)

    while queue:
        bomb = queue.pop(0)
        if bomb.id in seen:
            continue
        seen.add(bomb.id)
        exploded.append(bomb)
        cells = _blast_cells(state, bomb)
        for cell, damage in cells.items():
            damage_at[cell] = max(damage_at[cell], damage)
            owners_at[cell].add(bomb.owner_id)
            kinds_at[cell].add(bomb.kind)

        if config.BOMB_CHAINS:
            for other in sorted(state.bombs.values(), key=lambda b: b.id):
                if other.id in seen:
                    continue
                if (other.x, other.y) in cells:
                    queue.append(other)

    for bomb in exploded:
        state.bombs.pop(bomb.id, None)
        _log(
            state, turn, "BOMB_EXPLODED", actor=bomb.owner_id, bomb=bomb.id,
            x=bomb.x, y=bomb.y, radius=bomb.radius, kind=bomb.kind,
        )

    deaths = []
    shove_credit = {}
    for bot in sorted(state.alive_bots(), key=lambda b: b.id):
        damage = damage_at.get((bot.x, bot.y))
        if not damage:
            continue
        if _is_protected(bot, turn):
            _log(state, turn, "BOMB_DAMAGE", actor=bot.id, damage=0,
                 x=bot.x, y=bot.y, protected=True)
            continue
        if bot.shielded:
            damage = int(damage * (1 - config.SHIELD_DAMAGE_REDUCTION))
        elif bot.defending:
            damage = int(damage * (1 - config.DEFEND_DAMAGE_REDUCTION))
        owners = sorted(owners_at[(bot.x, bot.y)] - {bot.id})
        for owner_id in owners:
            bot.recent_damage[owner_id] = turn
        _log(
            state, turn, "BOMB_DAMAGE", actor=bot.id,
            damage=damage, x=bot.x, y=bot.y,
        )
        if _apply_damage(state, turn, bot, damage):
            killers = list(owners)
            shover = bot.shoved_by
            if (
                shover and shover != bot.id
                and turn - bot.shoved_turn <= config.SHOVE_KILL_WINDOW
            ):
                shove_credit.setdefault(bot.id, set()).add(shover)
                if shover not in killers:
                    killers.append(shover)
            kinds = kinds_at[(bot.x, bot.y)]
            cause = next(iter(kinds)) if len(kinds) == 1 else "BOMB"
            deaths.append((bot, sorted(killers), cause))
    _resolve_deaths(state, turn, deaths, shove_credit)

def _respawn_bots(state, turn):
    for bot in sorted(state.bots.values(), key=lambda b: b.id):
        if bot.alive or bot.respawn_turn is None or turn < bot.respawn_turn:
            continue
        taken = {(other.x, other.y) for other in state.alive_bots()}
        cell = nearest_free_cell(state, bot.base_x, bot.base_y, taken)
        if cell is None:
            continue
        bot.x, bot.y = cell
        bot.alive = True
        bot.hp = bot.max_hp
        bot.energy = config.START_ENERGY
        bot.respawn_turn = None
        bot.defending = False
        bot.shielded = False
        bot.scanning = False
        bot.protected_until = turn + config.SPAWN_PROTECTION_TURNS
        _log(
            state, turn, "RESPAWN", actor=bot.id, x=bot.x, y=bot.y,
            protected_until=bot.protected_until,
        )

def _process_events(state, turn):
    for event_type in [k for k, expiry in state.active_events.items() if turn >= expiry]:
        del state.active_events[event_type]
        _log(state, turn, "EVENT_ENDED", event=event_type)

    for smoke_id in [k for k, smoke in state.smokes.items() if turn >= smoke.expires_turn]:
        del state.smokes[smoke_id]
        _log(state, turn, "SMOKE_CLEARED", smoke=smoke_id)

    for tag_id in [k for k, tag in state.tags.items() if turn >= tag.expires_turn]:
        del state.tags[tag_id]
        _log(state, turn, "TAG_EXPIRED", tag=tag_id)

    _detonate_bombs(state, turn)
    _respawn_bots(state, turn)

    legendary = state.legendary
    if legendary:
        if turn == legendary["turn"] - config.LEGENDARY_WARNING_TURNS:
            _log(state, turn, "LEGENDARY_INCOMING", x=legendary["x"], y=legendary["y"],
                 lands_turn=legendary["turn"])
        if turn == legendary["turn"]:
            state.crates["LEGENDARY"] = Crate(
                id="LEGENDARY", x=legendary["x"], y=legendary["y"], item=legendary["item"],
            )
            _log(state, turn, "LEGENDARY_DROP", crate="LEGENDARY",
                 x=legendary["x"], y=legendary["y"])

    _update_crown(state, turn)

    if turn == state.max_turns - config.OVERTIME_TURNS:
        state.active_events["OVERTIME"] = state.max_turns + 1
        _log(state, turn, "EVENT_TRIGGERED", event="OVERTIME")

    core = state.core
    if not core.active and turn >= core.spawn_turn:
        core.x, core.y = config.CORE_POSITIONS[
            (state.seed + core.spawns) % len(config.CORE_POSITIONS)
        ]
        core.active = True
        core.spawns += 1
        core.carried_by = core.planted_by = core.defuser = None
        core.uplink_turn = None
        core.defuse_progress = 0
        _log(state, turn, "CORE_SPAWN", x=core.x, y=core.y)

    if turn in state.supply_schedule:
        _spawn_supply_wave(state, turn)

    if turn in state.crate_schedule:
        _drop_crates(state, turn)

    due = [ev for ev in state.event_schedule if ev[0] == turn]
    for trigger_turn, event_type in due:
        if event_type == "BLOOD_MOON":
            state.active_events["BLOOD_MOON"] = turn + config.BLOOD_MOON_DURATION
            _log(state, turn, "EVENT_TRIGGERED", event="BLOOD_MOON")
        elif event_type == "RESOURCE_RUSH":
            _spawn_resource_rush(state, turn)
            _log(state, turn, "EVENT_TRIGGERED", event="RESOURCE_RUSH")

def _update_crown(state, turn):
    if not state.bots:
        return
    ranked = sorted(state.bots.values(), key=lambda b: (-b.score, b.id))
    if len(ranked) > 1 and ranked[0].score == ranked[1].score:
        return
    leader = ranked[0].id
    if leader != state.crown_holder:
        previous, state.crown_holder = state.crown_holder, leader
        _log(state, turn, "CROWN", actor=leader, previous=previous)

def _occupied_cells(state):
    occupied = {(b.x, b.y) for b in state.alive_bots()}
    occupied.update((r.x, r.y) for r in state.resources.values() if not r.collected)
    occupied.update((c.x, c.y) for c in state.crates.values())
    occupied.update(config.CORE_POSITIONS)
    occupied.update(state.pads)
    occupied.update(state.walls)
    return occupied

def _drop_crates(state, turn):
    if not state.item_pool or config.CRATE_COUNT % 4:
        return
    rng = random.Random(f"{state.seed}-crate_drop-{turn}")
    occupied = _occupied_cells(state)
    margin = config.CRATE_INNER_MARGIN
    for _ in range(200):
        x = rng.randint(margin, state.width - 1 - margin)
        y = rng.randint(margin, state.height - 1 - margin)
        orbit = rotational_orbit(x, y, state.width, state.height)
        if len(set(orbit)) == 4 and not any(cell in occupied for cell in orbit):
            break
    else:
        _log(state, turn, "CRATE_DROP_SKIPPED", reason="no free symmetric orbit")
        return
    for index, (cx, cy) in enumerate(orbit):
        crate_id = f"C{turn}_{index}"
        state.crates[crate_id] = Crate(id=crate_id, x=cx, y=cy, item=None)
        _log(state, turn, "CRATE_SPAWN", crate=crate_id, x=cx, y=cy)
    _log(state, turn, "CRATE_DROP", count=len(orbit))

def _roll_crate_item(state, crate, rank):
    pool = list(state.item_pool)
    weights = [
        rank if item in config.POWER_ITEMS else config.UTILITY_ITEM_WEIGHT
        for item in pool
    ]
    rng = random.Random(f"{state.seed}-crate_open-{crate.id}-{rank}")
    return rng.choices(pool, weights=weights, k=1)[0]

def _use_item(state, turn, bot, action):
    item = bot.item
    bot.item = None
    _log(state, turn, "ITEM_USED", actor=bot.id, item=item,
         direction=action.direction, x=action.x, y=action.y)
    if item == "MEDPACK":
        healed = min(bot.max_hp, bot.hp + config.MEDPACK_HEAL) - bot.hp
        bot.hp += healed
        _log(state, turn, "ITEM_MEDPACK", actor=bot.id, healed=healed)
    elif item == "SMOKE":
        smoke_id = f"S{turn}_{bot.id}"
        state.smokes[smoke_id] = Smoke(
            id=smoke_id, owner_id=bot.id, x=bot.x, y=bot.y,
            radius=config.SMOKE_RADIUS,
            expires_turn=turn + 1 + config.SMOKE_DURATION,
        )
        _log(state, turn, "ITEM_SMOKE", actor=bot.id, smoke=smoke_id,
             x=bot.x, y=bot.y, radius=config.SMOKE_RADIUS)
    elif item == "RADAR":
        bot.radar_until = turn + 1 + config.RADAR_DURATION
        _log(state, turn, "ITEM_RADAR", actor=bot.id, until=bot.radar_until)
    elif item == "AIRSTRIKE":
        strike_id = f"A{turn}_{bot.id}"
        state.bombs[strike_id] = Bomb(
            id=strike_id, owner_id=bot.id, x=action.x, y=action.y,
            detonates_turn=turn + config.AIRSTRIKE_FUSE_TURNS,
            kind="AIRSTRIKE", radius=config.AIRSTRIKE_RADIUS,
            damage=config.AIRSTRIKE_DAMAGE, edge_damage=config.AIRSTRIKE_EDGE_DAMAGE,
            global_visible=True,
        )
        _log(state, turn, "ITEM_AIRSTRIKE", actor=bot.id, bomb=strike_id,
             x=action.x, y=action.y, lands_turn=turn + config.AIRSTRIKE_FUSE_TURNS)
    elif item == "ORBITAL":
        strike_id = f"O{turn}_{bot.id}"
        state.bombs[strike_id] = Bomb(
            id=strike_id, owner_id=bot.id, x=action.x, y=action.y,
            detonates_turn=turn + config.ORBITAL_FUSE_TURNS,
            kind="ORBITAL", radius=config.ORBITAL_RADIUS,
            damage=config.ORBITAL_DAMAGE, edge_damage=config.ORBITAL_EDGE_DAMAGE,
            global_visible=True,
        )
        _log(state, turn, "ITEM_ORBITAL", actor=bot.id, bomb=strike_id,
             x=action.x, y=action.y, lands_turn=turn + config.ORBITAL_FUSE_TURNS)
    elif item == "OVERSHIELD":
        bot.overshield_until = turn + 1 + config.OVERSHIELD_TURNS
        _log(state, turn, "ITEM_OVERSHIELD", actor=bot.id, until=bot.overshield_until)
    elif item == "REAPER":
        bot.reaper_until = turn + 1 + config.REAPER_TURNS
        _log(state, turn, "ITEM_REAPER", actor=bot.id, until=bot.reaper_until)
    return item

def _spawn_orbits(state, rng, count, margin, value_min, value_max, prefix, turn):
    if count % 4:
        raise ValueError("Resource spawns must be divisible by 4 for rotational fairness.")
    occupied = _occupied_cells(state)
    placed = 0
    attempts = 0
    while placed < count and attempts < 200:
        attempts += 1
        x = rng.randint(margin, state.width - 1 - margin)
        y = rng.randint(margin, state.height - 1 - margin)
        orbit = rotational_orbit(x, y, state.width, state.height)
        if (
            len(set(orbit)) != 4
            or placed + len(orbit) > count
            or any(cell in occupied for cell in orbit)
        ):
            continue
        value = rng.randint(value_min, value_max)
        for resource_x, resource_y in orbit:
            occupied.add((resource_x, resource_y))
            key = f"{prefix}{turn}_{placed}"
            state.resources[key] = Resource(
                id=key, x=resource_x, y=resource_y, value=value,
            )
            _log(
                state, turn, "RESOURCE_SPAWN",
                resource=key, x=resource_x, y=resource_y, value=value,
            )
            placed += 1
    return placed

def _spawn_supply_wave(state, turn):
    rng = random.Random(f"{state.seed}-supply_wave-{turn}")
    placed = _spawn_orbits(
        state, rng, config.SUPPLY_WAVE_COUNT, config.SUPPLY_WAVE_INNER_MARGIN,
        config.SUPPLY_WAVE_VALUE_MIN, config.SUPPLY_WAVE_VALUE_MAX, "SW", turn,
    )
    if placed:
        _log(state, turn, "SUPPLY_WAVE", count=placed)
    else:
        _log(state, turn, "SUPPLY_WAVE_SKIPPED", reason="no free symmetric orbit")

def _spawn_resource_rush(state, turn):
    rng = random.Random(f"{state.seed}-resource_rush-{turn}")
    _spawn_orbits(
        state, rng, config.RESOURCE_RUSH_COUNT, config.RESOURCE_RUSH_INNER_MARGIN,
        config.RESOURCE_RUSH_VALUE_MIN, config.RESOURCE_RUSH_VALUE_MAX, "RR", turn,
    )

def _pickup_tags(state, turn):
    by_cell = {(b.x, b.y): b for b in state.alive_bots()}
    for tag_id in sorted(state.tags):
        tag = state.tags[tag_id]
        bot = by_cell.get((tag.x, tag.y))
        if bot is None:
            continue
        del state.tags[tag_id]
        if bot.id in tag.killers:
            _log(state, turn, "TAG_CONFIRMED", actor=bot.id, tag=tag_id, victim=tag.victim)
            _score(state, turn, bot, config.KILL_TAG_SHARE, "CONFIRM", target=tag.victim)
        else:
            _log(state, turn, "TAG_DENIED", actor=bot.id, tag=tag_id, victim=tag.victim,
                 killers=list(tag.killers))
            _score(state, turn, bot, config.DENY_SCORE, "DENY", target=tag.victim)

def _resolve_shoves(state, turn, valid, incoming):
    shoves = [
        (bot_id, action.target) for bot_id, action in sorted(valid.items())
        if action.type == "ABILITY" and state.bots[bot_id].ability == "SHOVE"
    ]
    if not shoves:
        return
    positions = {(b.x, b.y) for b in state.alive_bots()}
    planned = {}
    shoved_by = defaultdict(list)
    for shover_id, target_id in shoves:
        shover, target = state.bots[shover_id], state.bots[target_id]
        if not target.alive or max(abs(target.x - shover.x), abs(target.y - shover.y)) != 1:
            _log(state, turn, "SHOVE_MISSED", actor=shover_id, target=target_id)
            continue
        shoved_by[target_id].append(shover_id)
        dx = (target.x > shover.x) - (target.x < shover.x)
        dy = (target.y > shover.y) - (target.y < shover.y)
        planned[target_id] = (dx, dy)
    landing_counts = Counter(
        (state.bots[t].x + d[0], state.bots[t].y + d[1]) for t, d in planned.items()
    )
    for target_id in sorted(shoved_by):
        target = state.bots[target_id]
        shovers = shoved_by[target_id]
        dx, dy = planned[target_id]
        landing = (target.x + dx, target.y + dy)
        clear = (
            len(shovers) == 1
            and step_open(state.walls, state.width, state.height, target.x, target.y, dx, dy)
            and landing not in positions
            and landing_counts[landing] == 1
        )
        for shover_id in shovers:
            target.shoved_by, target.shoved_turn = shover_id, turn
        if clear:
            positions.discard((target.x, target.y))
            target.x, target.y = landing
            positions.add(landing)
            if target.carrying_core:
                state.core.x, state.core.y = landing
            _log(state, turn, "SHOVE", actor=shovers[0], target=target_id,
                 x=landing[0], y=landing[1])
        else:
            for shover_id in shovers:
                incoming[target_id].append(
                    (shover_id, config.SHOVE_SLAM_DAMAGE, "SLAM", "SHOVE_SLAM", {}),
                )

def _retire_core(state, turn):
    core = state.core
    core.active = False
    core.carried_by = core.planted_by = core.defuser = None
    core.uplink_turn = None
    core.defuse_progress = 0
    core.spawn_turn = turn + 1 + config.CORE_RESPAWN_DELAY

def _resolve_core(state, turn):
    core = state.core
    if not core.active:
        return

    if core.status == "CARRIED":
        carrier = state.bots[core.carried_by]
        if (carrier.x, carrier.y) in state.pads:
            carrier.carrying_core = False
            core.carried_by = None
            core.planted_by = carrier.id
            core.x, core.y = carrier.x, carrier.y
            core.uplink_turn = turn + config.UPLINK_TURNS
            core.defuse_progress = 0
            _log(
                state, turn, "CORE_PLANTED", actor=carrier.id, x=core.x, y=core.y,
                uplink_turn=core.uplink_turn,
            )
            return

    if core.status != "PLANTED":
        return

    defusers = sorted(
        bot.id for bot in state.alive_bots()
        if bot.id != core.planted_by
        and max(abs(bot.x - core.x), abs(bot.y - core.y)) <= config.DEFUSE_RANGE
    )
    if not defusers:
        core.defuse_progress = 0
        core.defuser = None
    else:
        core.defuse_progress += 1
        core.defuser = defusers[0]
        _log(
            state, turn, "CORE_DEFUSING", actors=defusers,
            progress=core.defuse_progress, needed=config.DEFUSE_TURNS,
        )
        if core.defuse_progress >= config.DEFUSE_TURNS:
            _log(state, turn, "CORE_DEFUSED", actors=defusers, planter=core.planted_by)
            for defuser_id in defusers:
                defuser = state.bots[defuser_id]
                defuser.defuses += 1
                _score(state, turn, defuser, config.DEFUSE_SCORE, "DEFUSE")
                if defuser.role == "WARDEN":
                    _score(state, turn, defuser, config.WARDEN_DEFUSE_BONUS, "WARDEN")
            _retire_core(state, turn)
            return

    if turn >= core.uplink_turn:
        planter = state.bots[core.planted_by]
        planter.uplinks += 1
        planter.core_captured = True
        _log(state, turn, "CORE_UPLINK", actor=planter.id, x=core.x, y=core.y)
        _score(state, turn, planter, config.UPLINK_SCORE, "UPLINK")
        if planter.role == "RUNNER":
            _score(
                state, turn, planter,
                config.RUNNER_UPLINK_BONUS + config.RUNNER_CHAIN_BONUS * (planter.uplinks - 1),
                "UPLINK_CHAIN", chain=planter.uplinks,
            )
        _retire_core(state, turn)

def begin_turn(state):
    if state.turn_prepared:
        return

    turn = state.turn
    state.kills_this_turn = {}
    _process_events(state, turn)

    regen = config.ENERGY_REGEN_PER_TURN
    if "OVERTIME" in state.active_events:
        regen *= config.OVERTIME_ENERGY_MULTIPLIER
    for bot in state.bots.values():
        if not bot.alive:
            continue
        bot.energy = min(config.MAX_ENERGY, bot.energy + regen)
        bot.defending = False
        bot.shielded = False

    state.turn_prepared = True

def apply_turn(state, decisions: dict):
    turn = state.turn
    begin_turn(state)

    valid = {}
    for bot_id in sorted(state.bots.keys()):
        bot = state.bots[bot_id]
        if not bot.alive:
            continue
        action = decisions.get(bot_id)
        try:
            validate(action, bot, state)
            valid[bot_id] = action
        except InvalidAction as e:
            _log(state, turn, "INVALID_ACTION", actor=bot_id, reason=str(e))
        except Exception as e:
            _log(
                state,
                turn,
                "INVALID_ACTION",
                actor=bot_id,
                reason=f"Malformed Action object ({type(e).__name__})",
            )

    for bot in state.bots.values():
        if bot.alive:
            bot.scanning = False

    for bot_id, action in valid.items():
        extra = {"x": action.x, "y": action.y} if action.type == "USE_ITEM" else {}
        emote = action.say if isinstance(action.say, str) and action.say in config.EMOTES else None
        if emote:
            extra["say"] = emote
        _log(
            state,
            turn,
            "ACTION_ACCEPTED",
            actor=bot_id,
            action=action.type,
            direction=action.direction,
            target=action.target,
            energy_cost=config.ACTION_COSTS[action.type],
            **extra,
        )
        if emote:
            _log(state, turn, "TAUNT", actor=bot_id, emote=emote)
        bot = state.bots[bot_id]
        bot.energy -= config.ACTION_COSTS[action.type]
        if action.type in config.LOUD_ACTIONS or (
            action.type == "USE_ITEM" and bot.item in config.LOUD_ITEMS
        ):
            bot.loud_until = turn + 1 + config.LOUD_REVEAL_TURNS
        if (
            _is_protected(bot, turn)
            and action.type in config.SPAWN_PROTECTION_BREAKING_ACTIONS
        ):
            bot.protected_until = turn
            _log(state, turn, "PROTECTION_ENDED", actor=bot_id)

    railguns = {}
    for bot_id, action in valid.items():
        bot = state.bots[bot_id]
        if action.type == "USE_ITEM":
            if _use_item(state, turn, bot, action) == "RAILGUN":
                railguns[bot_id] = action.direction
        elif action.type == "DEFEND":
            bot.defending = True
            _log(state, turn, "DEFEND", actor=bot_id)
        elif action.type == "SCAN":
            bot.scanning = True
            _log(state, turn, "SCAN", actor=bot_id)
        elif action.type == "ABILITY":
            bot.ability_ready_turn = turn + bot.cooldown_turns
            if bot.ability == "SHIELD":
                bot.shielded = True
                _log(state, turn, "ABILITY_SHIELD", actor=bot_id)
            elif bot.ability == "BOMB":
                digest = hashlib.sha256(
                    f"{state.seed}|bomb|{bot_id}|{turn}".encode()
                ).hexdigest()[:12]
                bomb_id = f"B{digest}"
                state.bombs[bomb_id] = Bomb(
                    id=bomb_id, owner_id=bot_id, x=bot.x, y=bot.y,
                    detonates_turn=turn + config.BOMB_FUSE_TURNS,
                    kind="BOMB", radius=config.BOMB_BLAST_RADIUS,
                    damage=config.BOMB_DAMAGE, edge_damage=config.BOMB_EDGE_DAMAGE,
                )
                _log(
                    state, turn, "BOMB_PLACED", actor=bot_id, bomb=bomb_id,
                    x=bot.x, y=bot.y, fuse=config.BOMB_FUSE_TURNS,
                )

    start_pos = {b.id: (b.x, b.y) for b in state.bots.values() if b.alive}
    move_dest = {}
    move_path = {}

    for bot_id, action in valid.items():
        bot = state.bots[bot_id]
        bx, by = start_pos[bot_id]

        if action.type == "MOVE":
            dx, dy = DIRECTIONS[action.direction]
            move_dest[bot_id] = (bx + dx, by + dy)
            move_path[bot_id] = []

        elif action.type == "ABILITY" and bot.ability == "DASH":
            dx, dy = DIRECTIONS[action.direction]
            mid = (bx + dx, by + dy)
            dest = (bx + dx * config.DASH_DISTANCE, by + dy * config.DASH_DISTANCE)
            move_dest[bot_id] = dest
            move_path[bot_id] = [mid]

        elif action.type == "ABILITY" and bot.ability == "BLINK":
            dx, dy = DIRECTIONS[action.direction]
            dest = (bx + dx * config.BLINK_DISTANCE, by + dy * config.BLINK_DISTANCE)
            move_dest[bot_id] = dest
            move_path[bot_id] = []

    dest_counts = Counter(move_dest.values())
    occupied_start = set(start_pos.values())

    for bot_id, dest in move_dest.items():
        contested = dest_counts[dest] > 1
        dest_blocked = dest in occupied_start and dest != start_pos[bot_id]
        path_blocked = any(cell in occupied_start for cell in move_path[bot_id])
        wall_blocked = _hits_wall(
            state, state.bots[bot_id], valid[bot_id], start_pos[bot_id], dest,
        )
        if contested or dest_blocked or path_blocked or wall_blocked:
            action = valid[bot_id]
            via = action.type if action.type == "MOVE" else f"ABILITY_{state.bots[bot_id].ability}"
            _log(
                state, turn, "MOVE_BLOCKED", actor=bot_id, via=via, x=dest[0], y=dest[1],
                reason="WALL" if wall_blocked else "BOT",
            )
            continue
        bot = state.bots[bot_id]
        bot.x, bot.y = dest
        if bot.carrying_core:
            state.core.x, state.core.y = dest
        move_type = valid[bot_id].type if valid[bot_id].type == "MOVE" else f"ABILITY_{bot.ability}"
        _log(state, turn, "MOVE", actor=bot_id, via=move_type, x=dest[0], y=dest[1])

    incoming = defaultdict(list)
    _resolve_shoves(state, turn, valid, incoming)
    for bot_id, action in valid.items():
        if action.type == "ATTACK":
            target = state.bots[action.target]
            base, impact = _attack_impact(state, turn, state.bots[bot_id], target)
            incoming[action.target].append((bot_id, base, impact, "ATTACK", {}))

    positions = {(b.x, b.y): b.id for b in state.alive_bots()}
    for bot_id, action in valid.items():
        if action.type != "SHOOT":
            continue
        shooter = state.bots[bot_id]
        path = shot_path(
            state.walls, state.width, state.height,
            shooter.x, shooter.y, action.direction, config.SHOOT_RANGE,
        )
        hit_id = None
        end = path[-1] if path else (shooter.x, shooter.y)
        for cell in path:
            occupant = positions.get(cell)
            if occupant is not None and occupant != bot_id:
                hit_id, end = occupant, cell
                break
        shot = {
            "direction": action.direction,
            "from_x": shooter.x, "from_y": shooter.y,
            "x": end[0], "y": end[1],
        }
        if hit_id is None:
            _log(state, turn, "SHOT", actor=bot_id, target=None, damage=0, **shot)
            continue
        base, impact = _shot_impact(state, turn, shooter, state.bots[hit_id])
        incoming[hit_id].append((bot_id, base, impact, "SHOT", shot))

    for bot_id, direction in railguns.items():
        shooter = state.bots[bot_id]
        path = shot_path(
            state.walls, state.width, state.height,
            shooter.x, shooter.y, direction, max(state.width, state.height),
        )
        victims = [positions[cell] for cell in path if positions.get(cell, bot_id) != bot_id]
        end = path[-1] if path else (shooter.x, shooter.y)
        _log(
            state, turn, "RAILGUN", actor=bot_id, direction=direction,
            from_x=shooter.x, from_y=shooter.y, x=end[0], y=end[1], targets=victims,
        )
        for victim_id in victims:
            incoming[victim_id].append(
                (bot_id, config.RAILGUN_DAMAGE, "RAILGUN", "RAILGUN_HIT", {}),
            )

    deaths = []
    for target_id in sorted(incoming):
        target = state.bots[target_id]
        if not target.alive:
            continue
        protected = _is_protected(target, turn)
        reduction = 0.0
        if target.shielded:
            reduction = config.SHIELD_DAMAGE_REDUCTION
        elif target.defending:
            reduction = config.DEFEND_DAMAGE_REDUCTION

        total_dmg = 0
        hitters = []
        for attacker_id, base_dmg, impact, kind, extra in incoming[target_id]:
            if "BLOOD_MOON" in state.active_events:
                base_dmg = int(base_dmg * config.BLOOD_MOON_DAMAGE_MULTIPLIER)
            dmg = 0 if protected else int(base_dmg * (1 - reduction))
            total_dmg += dmg
            if dmg > 0:
                if attacker_id not in hitters:
                    hitters.append(attacker_id)
                target.recent_damage[attacker_id] = turn
            _log(
                state, turn, kind, actor=attacker_id,
                target=target_id, damage=dmg,
                impact="PROTECTED" if protected else impact,
                **extra,
            )

        if _apply_damage(state, turn, target, total_dmg):
            kinds = {hit[3] for hit in incoming[target_id]}
            cause = (
                "RAILGUN" if kinds == {"RAILGUN_HIT"}
                else "SHOT" if kinds == {"SHOT"}
                else "SHOVE" if kinds == {"SHOVE_SLAM"}
                else "ATTACK"
            )
            deaths.append((target, hitters, cause))
    _resolve_deaths(state, turn, deaths)

    for bot_id, action in valid.items():
        if action.type != "COLLECT":
            continue
        bot = state.bots[bot_id]
        if not bot.alive:
            continue
        if action.target == "CORE":
            state.core.carried_by = bot_id
            bot.carrying_core = True
            _log(state, turn, "CORE_PICKUP", actor=bot_id)
        elif action.target in state.crates:
            crate = state.crates.pop(action.target)
            if crate.item is None:
                rank = sorted(
                    state.bots.values(), key=lambda b: (-b.score, b.id),
                ).index(bot) + 1
                crate.item = _roll_crate_item(state, crate, rank)
            discarded, bot.item = bot.item, crate.item
            _log(
                state, turn, "CRATE_OPENED", actor=bot_id, crate=crate.id,
                item=crate.item, discarded=discarded,
            )
        else:
            res = state.resources.get(action.target)
            if res and not res.collected:
                res.collected = True
                hot = not res.loot and any(
                    other.id != bot_id
                    and max(abs(other.x - bot.x), abs(other.y - bot.y))
                    <= config.HOT_PICKUP_RADIUS
                    for other in state.alive_bots()
                )
                value = int(res.value * config.HOT_PICKUP_MULTIPLIER) if hot else res.value
                bot.cargo_value += value
                bot.cargo_units += 1
                bot.resources_collected += 1
                _log(
                    state, turn, "COLLECT", actor=bot_id, resource=res.id,
                    value=value, hot=hot, cargo_value=bot.cargo_value,
                    cargo_units=bot.cargo_units,
                )

    for bot in sorted(state.alive_bots(), key=lambda b: b.id):
        if bot.cargo_value and (bot.x, bot.y) == (bot.base_x, bot.base_y):
            banked, units = bot.cargo_value, bot.cargo_units
            bot.banked_value += banked
            bot.cargo_value = 0
            bot.cargo_units = 0
            _log(
                state, turn, "CARGO_BANKED", actor=bot.id,
                value=banked, units=units,
            )
            rate = {
                "HUNTER": config.HUNTER_BANK_MULTIPLIER,
                "WARDEN": config.WARDEN_BANK_MULTIPLIER,
            }.get(bot.role, 1)
            _score(state, turn, bot, int(banked * rate), "BANK", units=units)
            if bot.role == "HAULER" and units >= 3:
                multiplier = config.HAULER_HAUL_4 if units >= 4 else config.HAULER_HAUL_3
                _score(state, turn, bot, int(banked * (multiplier - 1)), "BIG_HAUL", units=units)

    _pickup_tags(state, turn)
    _resolve_core(state, turn)

    state.turn += 1
    state.turn_prepared = False
