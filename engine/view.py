import hashlib
import random

from . import config
from .board import chebyshev, effective_vision
from .geometry import line_clear
from .tiebreak import rank_all

def mark_reasons(bot, turn, core=None, crown_holder=None):
    if not bot.alive:
        return []
    reasons = []
    if bot.id == crown_holder:
        reasons.append("CROWN")
    if turn < bot.loud_until:
        reasons.append("LOUD")
    if core is not None and core.planted_by == bot.id:
        reasons.append("PLANTER")
    if bot.carrying_core:
        reasons.append("CORE")
    if bot.cargo_value >= config.CARGO_BEACON_VALUE:
        reasons.append("CARGO")
    if bot.streak >= config.ON_FIRE_STREAK:
        reasons.append("ON_FIRE")
    return reasons

def crown_bounty(bot):
    return config.CROWN_BOUNTY + config.SERIES_STREAK_BOUNTY * max(0, bot.series_streak - 1)

def build_view(state, bot_id):
    bot = state.bots[bot_id]
    turn = state.turn

    vision = effective_vision(state, bot)

    def sees(x, y):
        return (
            chebyshev(bot.x, bot.y, x, y) <= vision
            and line_clear(state.walls, bot.x, bot.y, x, y)
        )

    def in_smoke(x, y):
        return chebyshev(bot.x, bot.y, x, y) > 1 and any(
            smoke.covers(x, y) for smoke in state.smokes.values()
        )

    radar = turn < bot.radar_until

    visible_enemies = []
    for other in state.bots.values():
        if other.id == bot_id or not other.alive:
            continue
        in_vision = sees(other.x, other.y) and not in_smoke(other.x, other.y)
        reasons = mark_reasons(other, turn, state.core, state.crown_holder)
        if radar:
            reasons = [*reasons, "RADAR"]
        if not in_vision and not reasons:
            continue
        visible_enemies.append({
            "id": other.id, "x": other.x, "y": other.y,
            "hp": other.hp,
            "carrying_core": other.carrying_core,
            "cargo_value": other.cargo_value,
            "streak": other.streak,
            "crowned": other.id == state.crown_holder,
            "crown_bounty": crown_bounty(other) if other.id == state.crown_holder else 0,
            "nemesis": other.id == bot.nemesis,
            "revenge": other.id == bot.last_killed_by,
            "has_item": other.item is not None,
            "protected": turn < other.protected_until,
            "marked": bool(reasons),
            "mark_reasons": reasons,
            "in_vision": in_vision,
        })

    enemy_ids = "|".join(sorted(enemy["id"] for enemy in visible_enemies))
    shuffle_material = f"{state.seed}|{turn}|{bot_id}|{enemy_ids}".encode()
    shuffle_seed = int.from_bytes(hashlib.sha256(shuffle_material).digest()[:8], "big")
    random.Random(shuffle_seed).shuffle(visible_enemies)

    visible_resources = []
    for res in state.resources.values():
        if res.collected:
            continue
        if sees(res.x, res.y):
            visible_resources.append({
                "id": res.id, "x": res.x, "y": res.y, "value": res.value,
                "loot": res.loot,
            })

    visible_bombs = []
    for bomb in state.bombs.values():
        if bomb.global_visible or sees(bomb.x, bomb.y):
            visible_bombs.append({
                "id": bomb.id, "x": bomb.x, "y": bomb.y,
                "kind": bomb.kind,
                "mine": bomb.owner_id == bot_id,
                "turns_until_detonation": max(0, bomb.detonates_turn - turn),
                "blast_radius": bomb.radius,
            })
    visible_bombs.sort(key=lambda item: item["id"])

    crates = sorted(
        (
            {"id": c.id, "x": c.x, "y": c.y, "legendary": c.id == "LEGENDARY"}
            for c in state.crates.values()
        ),
        key=lambda item: item["id"],
    )
    tags = sorted(
        (
            {"id": t.id, "x": t.x, "y": t.y, "victim": t.victim,
             "mine": bot_id in t.killers, "turns_left": max(0, t.expires_turn - turn)}
            for t in state.tags.values() if sees(t.x, t.y)
        ),
        key=lambda item: item["id"],
    )
    legendary = None
    drop = state.legendary
    if drop and drop["turn"] - config.LEGENDARY_WARNING_TURNS <= turn < drop["turn"]:
        legendary = {"x": drop["x"], "y": drop["y"], "lands_in": drop["turn"] - turn}
    smokes = sorted(
        (
            {"x": s.x, "y": s.y, "radius": s.radius,
             "turns_left": max(0, s.expires_turn - turn)}
            for s in state.smokes.values()
        ),
        key=lambda item: (item["x"], item["y"]),
    )

    core = state.core
    core_info = {
        "status": core.status,
        "x": core.x, "y": core.y,
        "carried_by": core.carried_by,
        "planted_by": core.planted_by,
        "uplink_in": (core.uplink_turn - turn) if core.uplink_turn is not None else None,
        "defuse_progress": core.defuse_progress,
        "defuse_needed": config.DEFUSE_TURNS,
        "spawns_in": max(0, core.spawn_turn - turn) if not core.active else 0,
    }

    ability_ready = bot.ability is not None and turn >= bot.ability_ready_turn

    rank = rank_all(state).index(bot_id) + 1

    return {
        "turn": turn,
        "max_turns": state.max_turns,
        "self": {
            "id": bot.id, "x": bot.x, "y": bot.y, "hp": bot.hp,
            "energy": bot.energy, "score": bot.score, "rank": rank,
            "kills": bot.kills, "deaths": bot.deaths, "streak": bot.streak,
            "protected": turn < bot.protected_until,
            "carrying_core": bot.carrying_core,
            "cargo_value": bot.cargo_value,
            "cargo_units": bot.cargo_units,
            "cargo_capacity": bot.cargo_capacity,
            "marked": bool(mark_reasons(bot, turn, state.core, state.crown_holder)),
            "base": {"x": bot.base_x, "y": bot.base_y},
            "ability": bot.ability,
            "ability_ready": ability_ready,
            "scan_active": bot.scanning,
            "item": bot.item,
            "radar_active": radar,
            "overshield_active": turn < bot.overshield_until,
            "reaper_active": turn < bot.reaper_until,
            "crowned": bot_id == state.crown_holder,
            "role": bot.role,
            "loadout": list(bot.loadout),
            "max_hp": bot.max_hp,
            "uplinks": bot.uplinks,
            "nemesis": bot.nemesis,
            "revenge_target": bot.last_killed_by,
            "series_streak": bot.series_streak,
        },
        "board": {"width": state.width, "height": state.height},
        "walls": sorted([x, y] for x, y in state.walls),
        "layout": state.layout,
        "vision_range": vision,
        "bot_count": len(state.bots),
        "visible_enemies": visible_enemies,
        "visible_resources": visible_resources,
        "visible_bombs": visible_bombs,
        "crates": crates,
        "tags": tags,
        "legendary_incoming": legendary,
        "smokes": smokes,
        "item_pool": list(state.item_pool),
        "visible_core": core_info,
        "uplink_pads": [list(pad) for pad in state.pads],
        "overtime_turn": state.max_turns - config.OVERTIME_TURNS,
        "active_events": sorted(state.active_events.keys()),
    }
