from . import config
from . import ACTION_PROTOCOL_VERSION, ENGINE_VERSION
from .board import build_initial_state
from .loadout import apply_loadout, income, normalize_buy, shop_offer, spend
from .resolver import apply_turn, begin_turn
from .view import build_view
from .tiebreak import determine_winner, rank_all

def _snapshot_initial_state(state):
    return {
        "turn": state.turn,
        "max_turns": state.max_turns,
        "width": state.width,
        "height": state.height,
        "seed": state.seed,
        "bots": {
            bot_id: {
                "x": bot.x,
                "y": bot.y,
                "base_x": bot.base_x,
                "base_y": bot.base_y,
                "hp": bot.hp,
                "energy": bot.energy,
                "ability": bot.ability,
            }
            for bot_id, bot in state.bots.items()
        },
        "resources": {
            resource_id: {"x": resource.x, "y": resource.y, "value": resource.value}
            for resource_id, resource in state.resources.items()
        },
        "core": {"x": state.core.x, "y": state.core.y, "spawn_turn": state.core.spawn_turn},
        "uplink_pads": [list(pad) for pad in state.pads],
        "layout": state.layout,
        "walls": sorted([x, y] for x, y in state.walls),
        "event_schedule": [list(event) for event in state.event_schedule],
        "supply_schedule": list(state.supply_schedule),
        "item_pool": list(state.item_pool),
        "crate_schedule": list(state.crate_schedule),
        "legendary": dict(state.legendary) if state.legendary else None,
        "series": state.series,
        "loadouts": {bot_id: dict(entry) for bot_id, entry in sorted(state.loadouts.items())},
    }

def bot_killers(state, bot_id):
    counts = {}
    for event in state.events:
        if event["type"] == "ELIMINATION" and event["target"] == bot_id:
            for killer in event["attackers"]:
                counts[killer] = counts.get(killer, 0) + 1
    return sorted(counts.items())

def next_series_context(artifact, previous=None):
    previous = previous or {}
    winner = artifact["winner"]
    old_streaks = previous.get("streaks", {})
    streaks = {winner: old_streaks.get(winner, 0) + 1}
    nemesis = {}
    for bot_id, final in artifact["bots"].items():
        killers = final.get("killed_by", {})
        if not killers:
            continue
        top = max(killers.values())
        leaders = [k for k, count in killers.items() if count == top]
        if len(leaders) == 1:
            nemesis[bot_id] = leaders[0]

    loadouts = artifact.get("initial_state", {}).get("loadouts", {})
    old_losses = previous.get("loss_streaks", {})
    old_history = previous.get("history", {})
    credits, loss_streaks, history = {}, {}, {}
    for position, bot_id in enumerate(artifact["ranking"]):
        entry = loadouts.get(bot_id, {})
        left = entry.get("credits", config.START_CREDITS) - entry.get("spent", 0)
        losing = 0 if position == 0 else old_losses.get(bot_id, 0) + 1
        loss_streaks[bot_id] = losing
        earned = income(position, losing)
        credits[bot_id] = min(config.CREDIT_CAP, left + earned)
        history[bot_id] = [*old_history.get(bot_id, []), position + 1]
    return {
        "crown": winner, "streaks": streaks, "nemesis": nemesis,
        "credits": credits, "loss_streaks": loss_streaks, "history": history,
    }

def snapshot_final_bots(state):
    return {
        bid: {
            "score": bot.score,
            "alive": bot.alive,
            "hp": bot.hp,
            "energy": bot.energy,
            "x": bot.x,
            "y": bot.y,
            "kills": bot.kills,
            "deaths": bot.deaths,
            "assists": bot.assists,
            "best_streak": bot.best_streak,
            "killed_by": dict(bot_killers(state, bid)),
            "eliminations": bot.kills,
            "core_captured": bot.core_captured,
            "uplinks": bot.uplinks,
            "defuses": bot.defuses,
            "resources_collected": bot.resources_collected,
            "cargo_value": bot.cargo_value,
            "cargo_units": bot.cargo_units,
            "banked_value": bot.banked_value,
            "role": bot.role,
            "loadout": list(bot.loadout),
            "max_hp": bot.max_hp,
            "item": bot.item,
        }
        for bid, bot in state.bots.items()
    }

def run_match(bots: dict, seed: int, verbose: bool = True, spawn_indices=None,
              series=None):
    if not isinstance(bots, dict):
        raise TypeError("bots must be a dictionary of bot_id -> bot instance.")
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise TypeError("seed must be an integer.")
    if not 2 <= len(bots) <= 4:
        raise ValueError("A match requires between 2 and 4 bots.")
    for bot_id, bot in bots.items():
        if not isinstance(bot_id, str) or not bot_id:
            raise ValueError("Every bot ID must be a non-empty string.")
        if not callable(getattr(bot, "decide", None)):
            raise TypeError(f"Bot {bot_id!r} must provide a callable decide(view) method.")

    bot_ids = list(bots.keys())
    state = build_initial_state(bot_ids, seed, spawn_indices=spawn_indices, series=series)

    for bot_id, bot_instance in bots.items():
        ability = getattr(bot_instance, "ABILITY", None)
        if ability is not None and ability not in config.ABILITIES:
            raise ValueError(f"Bot {bot_id!r} declares unknown ability {ability!r}.")
        state.bots[bot_id].ability = ability

    for bot_id, bot_instance in bots.items():
        credits = state.series["credits"].get(bot_id, config.START_CREDITS)
        history = state.series["history"].get(bot_id, [])
        offer = shop_offer(credits, len(history), history)
        purchase, note = None, None
        buy = getattr(bot_instance, "buy", None)
        if callable(buy):
            try:
                purchase = buy(offer)
            except (Exception, SystemExit) as exc:
                note = f"buy() raised {type(exc).__name__}"
            diagnostic = getattr(bot_instance, "last_diagnostic", None)
            if diagnostic and note is None:
                note = f"buy() {diagnostic.get('kind', 'FAILED')}"
        role, items, reason = normalize_buy(
            purchase, credits, getattr(bot_instance, "ROLE", None),
        )
        apply_loadout(state.bots[bot_id], role, items)
        state.loadouts[bot_id] = {
            "role": role, "items": items, "credits": credits,
            "spent": spend(items), "note": note or reason,
        }

    initial_state = _snapshot_initial_state(state)
    rules = config.rules_snapshot()
    rules_fingerprint = config.rules_fingerprint()
    participants = {
        bot_id: {
            "module": type(bot).__module__,
            "class": type(bot).__qualname__,
            "ability": state.bots[bot_id].ability,
        }
        for bot_id, bot in bots.items()
    }

    if verbose:
        print(f"=== MATCH START (seed={seed}) ===")
        print(
            f"Bots: {bot_ids}  Map: {state.width}x{state.height} "
            f"'{state.layout}' ({len(state.walls)} walls)  Turns: {state.max_turns}"
        )
        abilities = {bid: state.bots[bid].ability for bid in bot_ids}
        print(f"Abilities: {abilities}\n")

    try:
        while state.turn < state.max_turns:
            turn_no = state.turn
            events_before = len(state.events)
            begin_turn(state)
            decisions = {}
            for bot_id, bot_instance in bots.items():
                bot_state = state.bots[bot_id]
                if not bot_state.alive:
                    continue
                view = build_view(state, bot_id)
                try:
                    decisions[bot_id] = bot_instance.decide(view)
                    diagnostic = getattr(bot_instance, "last_diagnostic", None)
                    if diagnostic:
                        state.events.append({
                            "turn": turn_no,
                            "type": "BOT_FAILURE",
                            "actor": bot_id,
                            "kind": diagnostic.get("kind", "UNKNOWN"),
                            "detail": diagnostic.get("detail", ""),
                        })
                except (Exception, SystemExit) as e:
                    decisions[bot_id] = None
                    detail = str(e) or type(e).__name__
                    state.events.append({"turn": turn_no, "type": "BOT_CRASH", "actor": bot_id, "error": detail})

            apply_turn(state, decisions)

            if verbose:
                for ev in state.events[events_before:]:
                    message = _format_event(ev)
                    if message:
                        print(f"T{turn_no:02d}  {message}")
    finally:
        for bot_instance in bots.values():
            close = getattr(bot_instance, "close", None)
            if callable(close):
                close()

    final_scores = {bid: b.score for bid, b in state.bots.items()}
    winner = determine_winner(state)
    ranking = rank_all(state)
    final_bots = snapshot_final_bots(state)
    state.events.append({
        "turn": state.turn,
        "type": "MATCH_END",
        "winner": winner,
        "scores": final_scores.copy(),
        "ranking": ranking.copy(),
        "rules_fingerprint": rules_fingerprint,
        "engine_version": ENGINE_VERSION,
        "action_protocol_version": ACTION_PROTOCOL_VERSION,
    })

    if verbose:
        print(f"\n=== MATCH END (turn {state.turn}) ===")
        for bid in ranking:
            bot = state.bots[bid]
            print(
                f"  {bid:12s} score={bot.score:<5d} "
                f"K/D/A={bot.kills}/{bot.deaths}/{bot.assists} "
                f"banked={bot.banked_value}"
            )
        print(f"\nWINNER: {winner}  SCORE: {final_scores[winner]}")

    return {
        "winner": winner,
        "scores": final_scores,
        "ranking": ranking,
        "bots": final_bots,
        "participants": participants,
        "participant_order": bot_ids,
        "initial_state": initial_state,
        "rules": rules,
        "rules_version": config.RULES_VERSION,
        "rules_fingerprint": rules_fingerprint,
        "engine_version": ENGINE_VERSION,
        "action_protocol_version": ACTION_PROTOCOL_VERSION,
        "turns_played": state.turn,
        "events": state.events,
        "seed": seed,
    }

def _format_event(ev):
    t = ev["type"]
    if t == "MOVE":
        return f"{ev['actor']} -> {ev['via']} to ({ev['x']},{ev['y']})"
    if t == "MOVE_BLOCKED":
        return f"{ev['actor']} -> {ev['via']} to ({ev['x']},{ev['y']}) blocked"
    if t == "ATTACK":
        return f"{ev['actor']} -> ATTACK {ev['target']} ({ev['damage']} dmg, {ev['impact']})"
    if t == "SHOT":
        if ev["target"] is None:
            return f"{ev['actor']} -> SHOOT {ev['direction']} (miss, stops at ({ev['x']},{ev['y']}))"
        return (
            f"{ev['actor']} -> SHOOT {ev['direction']} hits {ev['target']} "
            f"({ev['damage']} dmg, {ev['impact']})"
        )
    if t == "ELIMINATION":
        attackers = ", ".join(ev["attackers"]) or "nobody"
        return (
            f"{attackers} -> KILLED {ev['target']} ({ev['cause']}, "
            f"respawns T{ev['respawn_turn']})"
        )
    if t == "SCORE":
        overtime = " x2 OVERTIME" if ev.get("overtime") else ""
        return f"{ev['actor']} +{ev['points']} ({ev['reason']}{overtime})"
    if t == "RESPAWN":
        return f"{ev['actor']} -> RESPAWNED at ({ev['x']},{ev['y']})"
    if t == "PROTECTION_ENDED":
        return f"{ev['actor']} -> spawn protection ended"
    if t == "ON_FIRE":
        return f"*** {ev['actor']} IS ON FIRE ({ev['streak']} streak) ***"
    if t == "COLLECT":
        hot = " HOT" if ev.get("hot") else ""
        return (
            f"{ev['actor']} -> COLLECT {ev['resource']} ({ev['value']}{hot} "
            f"loaded, cargo={ev['cargo_value']})"
        )
    if t == "CARGO_BANKED":
        return f"{ev['actor']} -> BANKED {ev['units']} cargo (+{ev['value']})"
    if t == "CARGO_DROP":
        return (
            f"{ev['actor']} -> DROPPED {ev['value']} cargo at "
            f"({ev['x']},{ev['y']})"
        )
    if t == "CORE_PICKUP":
        return f"{ev['actor']} -> picked up CORE"
    if t == "CORE_SPAWN":
        return f"*** CORE ONLINE at ({ev['x']},{ev['y']}) ***"
    if t == "CORE_PLANTED":
        return (
            f"*** {ev['actor']} PLANTS THE CORE at ({ev['x']},{ev['y']}) "
            f"-- uplink end of T{ev['uplink_turn']} ***"
        )
    if t == "CORE_DEFUSING":
        return f"{', '.join(ev['actors'])} -> defusing ({ev['progress']}/{ev['needed']})"
    if t == "CORE_DEFUSED":
        return f"*** {', '.join(ev['actors'])} DEFUSE {ev['planter']}'s CORE ***"
    if t == "CORE_UPLINK":
        return f"*** {ev['actor']} UPLINKS THE CORE ***"
    if t == "CORE_DROP":
        return f"{ev['actor']} -> dropped CORE at ({ev['x']},{ev['y']})"
    if t == "SCAN":
        return f"{ev['actor']} -> SCAN"
    if t == "DEFEND":
        return f"{ev['actor']} -> DEFEND"
    if t == "ABILITY_SHIELD":
        return f"{ev['actor']} -> ABILITY: SHIELD"
    if t == "BOMB_PLACED":
        return f"{ev['actor']} -> BOMB placed at ({ev['x']},{ev['y']})"
    if t == "BOMB_EXPLODED":
        return f"*** {ev['actor']}'s BOMB EXPLODES at ({ev['x']},{ev['y']}) ***"
    if t == "BOMB_DAMAGE":
        return f"{ev['actor']} -> caught in blast ({ev['damage']} dmg)"
    if t in ("RESOURCE_SPAWN", "CRATE_SPAWN", "SMOKE_CLEARED"):
        return None
    if t == "CRATE_DROP":
        return f"*** CRATE DROP: {ev['count']} supply crates ***"
    if t == "CRATE_OPENED":
        return f"{ev['actor']} -> opens a crate: {ev['item']}"
    if t == "ITEM_USED":
        return f"{ev['actor']} -> uses {ev['item']}"
    if t == "ITEM_MEDPACK":
        return f"{ev['actor']} -> heals +{ev['healed']}"
    if t == "ITEM_SMOKE":
        return f"{ev['actor']} -> pops SMOKE at ({ev['x']},{ev['y']})"
    if t == "ITEM_RADAR":
        return f"{ev['actor']} -> RADAR sweep"
    if t == "ITEM_AIRSTRIKE":
        return (
            f"*** {ev['actor']} CALLS AN AIRSTRIKE on ({ev['x']},{ev['y']}) "
            f"-- lands T{ev['lands_turn']} ***"
        )
    if t == "RAILGUN":
        hit = ", ".join(ev["targets"]) or "nobody"
        return f"*** {ev['actor']} fires a RAILGUN {ev['direction']}: {hit} ***"
    if t == "RAILGUN_HIT":
        return f"{ev['actor']} -> RAILGUN hits {ev['target']} ({ev['damage']} dmg)"
    if t == "SUPPLY_WAVE":
        return f"*** SUPPLY WAVE: {ev['count']} resources dropped ***"
    if t == "EVENT_TRIGGERED":
        return f"*** EVENT: {ev['event']} ***"
    if t == "EVENT_ENDED":
        return f"*** {ev['event']} ended ***"
    if t == "INVALID_ACTION":
        return f"{ev['actor']} -> INVALID ({ev['reason']})"
    if t == "BOT_CRASH":
        return f"{ev['actor']} -> CRASHED ({ev['error']})"
    if t == "BOT_FAILURE":
        return f"{ev['actor']} -> {ev['kind']} ({ev['detail']})"
    if t == "MATCH_END":
        return f"MATCH END -> {ev['winner']} wins"
    if t == "ACTION_ACCEPTED":
        return None
    return str(ev)
