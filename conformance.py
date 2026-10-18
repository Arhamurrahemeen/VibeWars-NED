"""Submission gate: runs your bot the way the tournament will.

    python conformance.py
    python conformance.py --module my_bot --class MyBot --json-out report.json

`check.py` runs your bot in-process, which is fast and gives good error
messages. This runs it the way the organizers' admission gate does: in an
isolated subprocess, with the 200 ms decision deadline, through the same
checks in the same order:

  1. it loads in isolation (2 s allowed) and reports its ABILITY / ROLE;
  2. its opening decision is legal and identical when repeated;
  3. buy() gives the same answer twice for the same shop;
  4. four full matches, your bot rotated through every corner, each played
     twice: no crash, no timeout, no illegal action, identical both times.

The organizers run the same four seeds against their own opponents, which
you do not have. Here the opponents are the chaos sparring bots from
sparring.py: they shove, bomb, blink and fight at random so your bot meets
odd situations. Passing here is strong evidence, not a guarantee: a bot that
only breaks against one particular opponent behaviour can still fail at
admission, so also test against rivals you write (`play.py --vs`).

Exit code 0 means your submission passed.
"""
import argparse
import json
from pathlib import Path
import sys

from sandbox.runner import SandboxedBot, SubmissionLoadError, inspect_submission

SUBMISSION_ID = "SUBMISSION"
# Public practice seeds -- the same ones the admission gate uses.
PUBLIC_SEEDS = (3, 10, 18, 28)
CORNER_RING = (0, 1, 3, 2)
BUY_PROBES = ((4, 0, ()), (7, 1, (4,)), (10, 2, (4, 4)))


def _sandbox(module, class_name, metadata, timeout):
    return SandboxedBot(module, class_name, SUBMISSION_ID, timeout=timeout, metadata=metadata)


def _opening(module, class_name, metadata, timeout, seed):
    """The first decision of a match, checked for legality."""
    from engine.actions import InvalidAction, validate
    from engine.board import build_initial_state
    from engine.resolver import begin_turn
    from engine.view import build_view

    state = build_initial_state(
        [SUBMISSION_ID, "OPPONENT_0", "OPPONENT_1", "OPPONENT_2"], seed,
        spawn_indices=[0, 1, 3, 2],
    )
    state.bots[SUBMISSION_ID].ability = metadata["ability"]
    begin_turn(state)
    bot = _sandbox(module, class_name, metadata, timeout)
    try:
        action = bot.decide(build_view(state, SUBMISSION_ID))
        diagnostic = bot.last_diagnostic
    finally:
        bot.close()
    if diagnostic:
        return None, f"{diagnostic['kind']}: {diagnostic['detail']}"
    try:
        validate(action, state.bots[SUBMISSION_ID], state)
    except (InvalidAction, AttributeError, TypeError) as exc:
        return action, f"illegal opening action: {exc}"
    return action, None


def _buy_probe(module, class_name, metadata, timeout):
    from engine.loadout import normalize_buy, shop_offer

    bot = _sandbox(module, class_name, metadata, timeout)
    results, errors = [], []
    try:
        for credits, map_index, placements in BUY_PROBES:
            purchase = bot.buy(shop_offer(credits, map_index, placements))
            if bot.last_diagnostic:
                errors.append(f"{bot.last_diagnostic['kind']}: {bot.last_diagnostic['detail']}")
            role, items, reason = normalize_buy(purchase, credits, metadata.get("role"))
            if reason:
                errors.append(f"with {credits} credits: {reason}")
            results.append((role, items))
    finally:
        bot.close()
    return results, errors


def _case(module, class_name, metadata, timeout, seed, index):
    from engine.game import run_match
    from sparring import LINEUPS

    name, opponents = LINEUPS[index % len(LINEUPS)]
    bots = {SUBMISSION_ID: _sandbox(module, class_name, metadata, timeout)}
    bots.update({f"OPPONENT_{i}": cls(f"OPPONENT_{i}") for i, cls in enumerate(opponents)})
    rotation = index % len(CORNER_RING)
    spawns = list(CORNER_RING[rotation:] + CORNER_RING[:rotation])
    return name, spawns, run_match(bots, seed, False, spawn_indices=spawns)


def evaluate(module, class_name, seeds=PUBLIC_SEEDS, timeout=0.2):
    from engine import ACTION_PROTOCOL_VERSION, config

    report = {
        "submission": {"module": module, "class": class_name},
        "action_protocol_version": ACTION_PROTOCOL_VERSION,
        "rules_version": config.RULES_VERSION,
        "checks": [],
        "cases": [],
        "passed": False,
    }

    def record(name, passed, detail):
        report["checks"].append({"name": name, "passed": bool(passed), "detail": detail})
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}: {detail}")
        return passed

    try:
        metadata = inspect_submission(module, class_name, timeout=timeout)
    except (SubmissionLoadError, ValueError, OSError) as exc:
        record("loads_in_isolation", False, str(exc))
        return report
    record("loads_in_isolation", True,
           f"loaded {class_name} with ability={metadata.get('ability')!r}, role={metadata.get('role')!r}")

    first, error_a = _opening(module, class_name, metadata, timeout, seeds[0])
    second, error_b = _opening(module, class_name, metadata, timeout, seeds[0])
    if not record("opening_action", error_a is None and error_b is None, error_a or error_b or repr(first)):
        return report
    if not record("opening_determinism", first == second,
                  "identical" if first == second else f"first={first!r}, second={second!r}"):
        return report

    buys_a, buy_errors = _buy_probe(module, class_name, metadata, timeout)
    buys_b, _ = _buy_probe(module, class_name, metadata, timeout)
    summary = "; ".join(
        f"{credits}cr -> {role or 'no role'} {items or 'nothing'}"
        for (credits, _, _), (role, items) in zip(BUY_PROBES, buys_a)
    )
    if buy_errors:
        summary += " | WARNING, that map buys nothing: " + "; ".join(buy_errors[:3])
    if not record("buy_phase", buys_a == buys_b,
                  summary if buys_a == buys_b else f"buy() is not deterministic: {buys_a} vs {buys_b}"):
        return report

    all_ok = True
    for index, seed in enumerate(seeds):
        try:
            name, spawns, first = _case(module, class_name, metadata, timeout, seed, index)
            _, _, second = _case(module, class_name, metadata, timeout, seed, index)
        except Exception as exc:
            all_ok = record(f"case_{index + 1}", False, f"match failed: {exc}") and all_ok
            continue
        failures = [
            event for event in first["events"]
            if event.get("actor") == SUBMISSION_ID
            and event["type"] in ("BOT_FAILURE", "BOT_CRASH", "INVALID_ACTION")
        ]
        accepted = sum(
            event["type"] == "ACTION_ACCEPTED" and event["actor"] == SUBMISSION_ID
            for event in first["events"]
        )
        deterministic = first == second
        passed = not failures and deterministic and accepted > 0
        detail = f"{accepted} actions"
        if failures:
            first_failure = failures[0]
            why = first_failure.get("reason") or first_failure.get("detail") or first_failure.get("error") or ""
            kinds = sorted({event.get("kind") or event["type"] for event in failures})
            detail += f", {len(failures)} failures {kinds} -- turn {first_failure['turn']}: {why}"
        if not deterministic:
            detail += ", NOT deterministic"
        report["cases"].append({
            "lineup": name, "seed": seed, "corner": spawns[0], "passed": passed,
            "accepted_actions": accepted, "deterministic": deterministic, "failures": failures[:5],
        })
        print(f"  [{'PASS' if passed else 'FAIL'}] case {index + 1} ({name}, seed {seed}, corner {spawns[0]}): {detail}")
        all_ok = passed and all_ok

    report["passed"] = all_ok and bool(report["cases"]) and all(c["passed"] for c in report["checks"])
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--module", default="my_bot")
    parser.add_argument("--class", dest="class_name", default="MyBot")
    parser.add_argument("--timeout", type=float, default=0.2, help="decision deadline in seconds (tournament: 0.2)")
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()

    sys.path.insert(0, str(Path.cwd()))
    print(f"\nTournament conformance: {args.module}.py :: {args.class_name}\n")
    report = evaluate(args.module, args.class_name, timeout=args.timeout)

    if report["passed"]:
        print("\nRESULT: PASS -- this is what the admission gate checks.\n")
    else:
        print(
            "\nRESULT: FAIL -- this submission would be rejected.\n"
            "Common causes: an illegal action in some situation (read the turn\n"
            "and reason above), decide() too slow for the 200 ms deadline, or\n"
            "behaviour that changes between runs.\n"
        )
    if args.json_out:
        args.json_out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
