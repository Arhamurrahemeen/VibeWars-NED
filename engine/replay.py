import argparse
import json
from pathlib import Path

from . import config
from . import ACTION_PROTOCOL_VERSION, ENGINE_VERSION
from .actions import Action
from .board import CORNER_SPAWNS, build_initial_state
from .game import _snapshot_initial_state, snapshot_final_bots
from .loadout import apply_loadout, normalize_buy
from .resolver import apply_turn
from .tiebreak import determine_winner, rank_all

class ReplayMismatch(ValueError):
    pass

_NON_AUTHORITATIVE_EVENT_TYPES = {
    "ACTION_ACCEPTED",
    "INVALID_ACTION",
    "BOT_CRASH",
    "BOT_FAILURE",
    "MATCH_END",
}

def _effect_events(events):
    return [
        event for event in events
        if event.get("type") not in _NON_AUTHORITATIVE_EVENT_TYPES
    ]

def replay_artifact(artifact, on_turn=None):
    expected_fingerprint = artifact.get("rules_fingerprint")
    current_fingerprint = config.rules_fingerprint()
    if expected_fingerprint != current_fingerprint:
        raise ReplayMismatch(
            f"Rules fingerprint mismatch: artifact={expected_fingerprint!r}, "
            f"current={current_fingerprint!r}"
        )
    if artifact.get("engine_version") != ENGINE_VERSION:
        raise ReplayMismatch(
            f"Engine version mismatch: artifact={artifact.get('engine_version')!r}, "
            f"current={ENGINE_VERSION!r}"
        )
    if artifact.get("action_protocol_version") != ACTION_PROTOCOL_VERSION:
        raise ReplayMismatch(
            "Action protocol version mismatch: "
            f"artifact={artifact.get('action_protocol_version')!r}, "
            f"current={ACTION_PROTOCOL_VERSION!r}"
        )

    initial = artifact["initial_state"]
    bot_ids = artifact.get("participant_order")
    if not isinstance(bot_ids, list) or len(bot_ids) != len(set(bot_ids)):
        raise ReplayMismatch("Artifact has no valid explicit participant order")
    if set(bot_ids) != set(initial["bots"]):
        raise ReplayMismatch("Participant order does not match initial-state bot IDs")
    spawn_indices = []
    for bot_id in bot_ids:
        bot = initial["bots"][bot_id]
        base = (bot["base_x"], bot["base_y"])
        try:
            spawn_indices.append(CORNER_SPAWNS.index(base))
        except ValueError as exc:
            raise ReplayMismatch(f"Unknown spawn position for {bot_id}: {base}") from exc

    state = build_initial_state(
        bot_ids, artifact["seed"], spawn_indices=spawn_indices,
        series=initial.get("series"),
    )
    for bot_id, bot in initial["bots"].items():
        state.bots[bot_id].ability = bot["ability"]

    for bot_id in bot_ids:
        entry = (initial.get("loadouts") or {}).get(bot_id)
        if entry is None:
            raise ReplayMismatch(f"No recorded loadout for {bot_id}")
        credits = state.series["credits"].get(bot_id, config.START_CREDITS)
        role, items, reason = normalize_buy(
            {"role": entry["role"], "items": entry["items"]}, credits,
        )
        if reason or entry["credits"] != credits or (role, items) != (entry["role"], entry["items"]):
            raise ReplayMismatch(f"Loadout for {bot_id} is not valid or not affordable")
        apply_loadout(state.bots[bot_id], role, items)
        state.loadouts[bot_id] = dict(entry)

    if _snapshot_initial_state(state) != initial:
        raise ReplayMismatch("Initial state does not match the seeded board")

    accepted_by_turn = {}
    for event in artifact["events"]:
        if event["type"] != "ACTION_ACCEPTED":
            continue
        accepted_by_turn.setdefault(event["turn"], {})[event["actor"]] = Action(
            type=event["action"],
            direction=event.get("direction"),
            target=event.get("target"),
            x=event.get("x"),
            y=event.get("y"),
            say=event.get("say"),
        )

    for turn in range(artifact["turns_played"]):
        if state.turn != turn:
            raise ReplayMismatch(f"Replay turn drift: expected {turn}, got {state.turn}")
        apply_turn(state, accepted_by_turn.get(turn, {}))
        if on_turn is not None:
            on_turn(state)

    replayed_effects = _effect_events(state.events)
    artifact_effects = _effect_events(artifact["events"])
    if replayed_effects != artifact_effects:
        mismatch_index = next(
            (
                index for index, (replayed, recorded) in enumerate(
                    zip(replayed_effects, artifact_effects)
                )
                if replayed != recorded
            ),
            min(len(replayed_effects), len(artifact_effects)),
        )
        replayed = (
            replayed_effects[mismatch_index]
            if mismatch_index < len(replayed_effects) else "<missing>"
        )
        recorded = (
            artifact_effects[mismatch_index]
            if mismatch_index < len(artifact_effects) else "<missing>"
        )
        raise ReplayMismatch(
            f"Replayed game effects diverge at index {mismatch_index}: "
            f"replayed={replayed!r}, artifact={recorded!r}"
        )

    reproduced = {
        "winner": determine_winner(state),
        "scores": {bot_id: bot.score for bot_id, bot in state.bots.items()},
        "ranking": rank_all(state),
        "bots": snapshot_final_bots(state),
        "turns_played": state.turn,
    }

    for field in ("winner", "scores", "ranking", "bots", "turns_played"):
        if reproduced[field] != artifact[field]:
            raise ReplayMismatch(f"Replayed {field} does not match artifact")
    return reproduced

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact", type=Path)
    args = parser.parse_args()
    artifact = json.loads(args.artifact.read_text(encoding="utf-8"))
    reproduced = replay_artifact(artifact)
    print(
        f"Replay verified: winner={reproduced['winner']} "
        f"turns={reproduced['turns_played']}"
    )

if __name__ == "__main__":
    main()
