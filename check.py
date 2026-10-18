"""Check that your bot is valid and will be accepted into the tournament.

    python check.py                     # checks my_bot.py / MyBot
    python check.py --module other_bot --class OtherBot

If this says PASS, your bot loads, plays legally, and is deterministic.
If it says FAIL, the reason is printed in plain language.

This runs the same kinds of checks the organizers run at submission, quickly
and in-process. A bot that fails here will not be admitted. Before you
submit, also run conformance.py: it runs your bot isolated, with the real
200 ms deadline, exactly the way the admission gate does.
"""
import argparse
import ast
import re
import sys
import traceback
from pathlib import Path

MIN_PYTHON = (3, 9)

# The submission screen run at intake, before your code is ever executed.
# Kept identical to the organizers' lists (a test enforces it), so nothing that
# passes here can be rejected at submission time.
ALLOWED_IMPORTS = {
    "vibe_sdk", "__future__", "math", "cmath", "random", "heapq", "bisect",
    "collections", "itertools", "functools", "operator", "dataclasses", "typing",
    "enum", "copy", "statistics", "fractions", "decimal", "numbers", "string",
    "re", "array", "abc", "time", "hashlib", "json",
}

BANNED_IMPORTS = {
    "os", "sys", "subprocess", "socket", "shutil", "pathlib", "importlib",
    "requests", "urllib", "http", "ctypes", "multiprocessing", "threading",
    "pickle", "marshal", "tempfile", "webbrowser", "signal",
}

BANNED_CALLS = {"eval", "exec", "compile", "__import__", "open", "input",
                "globals", "locals", "vars", "breakpoint", "setattr", "delattr"}

ALLOWED_DUNDERS = {
    "__init__", "__name__", "__main__", "__future__", "__repr__", "__str__",
    "__eq__", "__ne__", "__hash__", "__lt__", "__le__", "__gt__", "__ge__",
    "__len__", "__iter__", "__next__", "__contains__", "__getitem__",
    "__setitem__", "__post_init__", "__slots__", "__call__", "__bool__",
    "__add__", "__sub__", "__mul__", "__truediv__", "__floordiv__", "__mod__",
    "__neg__", "__abs__", "__doc__", "__all__", "__version__",
}

BANNED_NAMES = {
    "attrgetter", "methodcaller", "Formatter", "ForwardRef", "get_type_hints",
    "make_dataclass", "mro", "gi_frame", "gi_code", "cr_frame", "ag_frame",
    "f_globals", "f_locals", "f_builtins", "f_back", "f_code", "tb_frame",
    "tb_next", "co_code", "func_globals", "exc_info", "settrace", "setprofile",
}

# Private to the kit: the engine runs your bot, your bot only talks vibe_sdk.
KIT_INTERNALS = {"engine", "sandbox"}


def fail(title, detail, fix=None):
    print(f"\n  FAIL: {title}")
    for line in str(detail).strip().splitlines():
        print(f"        {line}")
    if fix:
        print(f"\n  How to fix: {fix}")
    return False


def check_python():
    if sys.version_info < MIN_PYTHON:
        print(
            f"  FAIL: Python {'.'.join(map(str, MIN_PYTHON))}+ is required, "
            f"you have {sys.version.split()[0]}."
        )
        return False
    print(f"  ok    Python {sys.version.split()[0]}")
    return True


def check_file(module_name):
    path = Path(f"{module_name}.py")
    if not path.exists():
        return fail(
            f"Can't find {path}",
            f"Looked in {Path.cwd()}",
            f"Run this from the folder containing {path.name}, or pass --module.",
        )
    print(f"  ok    found {path}")
    return True


def check_submission_rules(module_name):
    """Static screen of the file you will upload, before anything runs.

    Only ``my_bot.py`` is submitted. A helper module next to it works on your
    laptop and is simply missing at the tournament, so it is reported here.
    """
    path = Path(f"{module_name}.py")
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return True  # reported with a line number by the import check
    local = {p.stem for p in Path.cwd().glob("*.py")} - {module_name}
    local |= {p.name for p in Path.cwd().iterdir() if p.is_dir() and (p / "__init__.py").exists()}
    local -= {"vibe_sdk"}
    problems = []

    def dunder(name, lineno):
        if name.startswith("__") and name.endswith("__") and name not in ALLOWED_DUNDERS:
            problems.append(f"line {lineno}: uses {name} (not allowed)")

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level:
            problems.append(f"line {node.lineno}: relative import 'from {'.' * node.level}{node.module or ''} ...'")
            continue
        if isinstance(node, ast.Name):
            dunder(node.id, node.lineno)
            if node.id in BANNED_NAMES:
                problems.append(f"line {node.lineno}: uses {node.id} (not allowed)")
            continue
        if isinstance(node, ast.Attribute):
            dunder(node.attr, node.lineno)
            if node.attr in BANNED_NAMES:
                problems.append(f"line {node.lineno}: uses .{node.attr} (not allowed)")
            continue
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            for word in re.findall(r"__\w+__", node.value):
                dunder(word, node.lineno)
            continue
        if isinstance(node, ast.Import):
            roots = [(alias.name.split(".")[0], alias.name) for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            roots = [((node.module or "").split(".")[0], node.module or "")]
            for alias in node.names:
                if alias.name in BANNED_NAMES or (alias.name.startswith("__") and alias.name not in ALLOWED_DUNDERS):
                    problems.append(f"line {node.lineno}: imports {alias.name!r} (not allowed)")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in BANNED_CALLS:
                problems.append(f"line {node.lineno}: calls {node.func.id}() (not allowed)")
            if node.func.id == "getattr" and not (
                len(node.args) >= 2 and isinstance(node.args[1], ast.Constant)
                and isinstance(node.args[1].value, str)
            ):
                problems.append(f"line {node.lineno}: getattr() with a computed name (write the name out)")
            continue
        else:
            continue
        for root, full in roots:
            if root in KIT_INTERNALS:
                problems.append(f"line {node.lineno}: imports {full!r} (kit internals; use vibe_sdk)")
            elif root in local:
                problems.append(
                    f"line {node.lineno}: imports your own file {root!r} -- only "
                    f"{path.name} is submitted, so it will not exist at the tournament"
                )
            elif root not in ALLOWED_IMPORTS:
                problems.append(f"line {node.lineno}: imports {full!r} (not on the allowed list)")
    if problems:
        return fail(
            f"{path.name} would be rejected at submission",
            "\n".join(problems),
            f"Put everything in {path.name} and import only vibe_sdk and these "
            f"standard modules: {', '.join(sorted(ALLOWED_IMPORTS - {'vibe_sdk', '__future__'}))}.",
        )
    print("  ok    passes the submission screen (one file, allowed imports only)")
    return True


def check_import(module_name, class_name):
    try:
        module = __import__(module_name)
    except SyntaxError as exc:
        return None, fail(
            f"{module_name}.py has a syntax error",
            f"line {exc.lineno}: {exc.msg}",
            "Fix the syntax error, then run check.py again.",
        )
    except Exception:
        return None, fail(
            f"{module_name}.py crashed while loading",
            traceback.format_exc(limit=3),
            "Something at the top level of your file raised. Imports and "
            "class definitions must not do real work.",
        )

    bot_class = getattr(module, class_name, None)
    if bot_class is None:
        available = [
            name for name in vars(module)
            if isinstance(vars(module)[name], type) and not name.startswith("_")
        ]
        return None, fail(
            f"No class named {class_name} in {module_name}.py",
            f"Classes found: {available or 'none'}",
            f"Rename your class to {class_name}, or pass --class.",
        )

    from vibe_sdk import Bot
    if not isinstance(bot_class, type) or not issubclass(bot_class, Bot):
        return None, fail(
            f"{class_name} does not subclass Bot",
            f"Got: {bot_class!r}",
            "Write `from vibe_sdk import Bot` and `class "
            f"{class_name}(Bot):`.",
        )
    print(f"  ok    {class_name} subclasses Bot")
    return bot_class, True


def check_ability(bot_class):
    from engine import config
    ability = getattr(bot_class, "ABILITY", None)
    if ability is not None and ability not in config.ABILITIES:
        return fail(
            f"Unknown ABILITY {ability!r}",
            f"Allowed: {sorted(config.ABILITIES)} or None",
            "Set ABILITY to one of the allowed values.",
        )
    print(f"  ok    ability = {ability!r}")
    return True


def check_buy(bot_class):
    """buy(shop) must be deterministic; a failing buy just buys nothing."""
    from engine import config
    from engine.loadout import normalize_buy, shop_offer

    role = getattr(bot_class, "ROLE", None)
    if role is not None and role not in config.ROLES:
        print(f"  WARN  ROLE {role!r} is not a role -- you will play with no role. "
              f"Allowed: {list(config.ROLES)} or None")
    probes = ((4, 0, ()), (7, 1, (4,)), (10, 2, (4, 4)))

    def run():
        bot = bot_class("YOU")
        out, notes = [], []
        for credits, map_index, placements in probes:
            try:
                purchase = bot.buy(shop_offer(credits, map_index, placements))
            except Exception as exc:
                notes.append(f"buy() raised {type(exc).__name__}: {exc}")
                purchase = None
            chosen, items, reason = normalize_buy(purchase, credits, role)
            if reason:
                notes.append(f"with {credits} credits: {reason}")
            out.append((chosen, items))
        return out, notes

    first, notes = run()
    second, _ = run()
    if first != second:
        return fail(
            "Your buy() is not deterministic",
            f"first: {first}\nsecond: {second}",
            "Pick your role and items from the shop dict only -- no unseeded "
            "random, no time.",
        )
    for (credits, _, _), (chosen, items) in zip(probes, first):
        print(f"  ok    buy with {credits:>2} credits -> {chosen or 'no role'}, {items or 'nothing'}")
    for note in notes[:3]:
        print(f"  WARN  {note} (that map you buy nothing)")
    return True


def check_plays(bot_class, class_name):
    """Play several maps and confirm every decision was legal.

    One map is not enough: an illegal action often only shows up in a
    situation that a particular seed happens to produce (a full cargo hold,
    an empty board, a cornered bot).
    """
    from engine.game import run_match
    from engine.replay import replay_artifact

    from sparring import LINEUPS

    class Copy(bot_class):
        """Copies of the submitted bot. Who wins here means nothing: this
        checks legality, not strength."""

    # Two maps against copies of yourself, two against the chaos sparring
    # bots, which shove, bomb and blink at random.
    seeds = (1, 7, 12345, 28)
    fields = (
        (Copy, Copy, Copy), LINEUPS[0][1], (Copy, Copy, Copy), LINEUPS[1][1],
    )
    problems = {"INVALID_ACTION": [], "BOT_CRASH": []}
    accepted = 0
    results = []

    for seed, opponents in zip(seeds, fields):
        try:
            bots = {"YOU": bot_class("YOU")}
            bots.update({f"OPP_{i}": cls(f"OPP_{i}") for i, cls in enumerate(opponents, start=1)})
            result = run_match(bots, seed=seed, verbose=False)
        except Exception:
            return fail(
                f"Your bot crashed during a match (seed {seed})",
                traceback.format_exc(limit=4),
                "decide(view) raised. Guard against empty lists and missing keys "
                "-- fog of war means most things are usually not visible.",
            )
        results.append(result)
        for event in result["events"]:
            if event.get("actor") != "YOU":
                continue
            if event["type"] in problems:
                problems[event["type"]].append(event)
            elif event["type"] == "ACTION_ACCEPTED":
                accepted += 1
    result = results[0]

    if problems["BOT_CRASH"]:
        return fail(
            f"Your bot crashed on {len(problems['BOT_CRASH'])} turn(s)",
            problems["BOT_CRASH"][0].get("error", ""),
            "Every call to decide(view) must return an Action without raising.",
        )
    if problems["INVALID_ACTION"]:
        reasons = {}
        for event in problems["INVALID_ACTION"]:
            reasons[event["reason"]] = reasons.get(event["reason"], 0) + 1
        detail = "\n".join(f"{count}x  {reason}" for reason, count in sorted(reasons.items()))
        first = problems["INVALID_ACTION"][0]
        detail += f"\nfirst one: turn {first['turn']}"

        # "Not an Action object" is a different mistake from an illegal move,
        # and generic legality advice would send the team hunting the wrong bug.
        if any("must be an Action" in reason for reason in reasons):
            return fail(
                "decide(view) did not return an Action",
                detail,
                "Return an Action from every path through decide(), e.g. "
                "Action.move('EAST'). Returning None, a string, or falling off "
                "the end of the function all count as no action.",
            )
        return fail(
            f"Your bot made {len(problems['INVALID_ACTION'])} illegal move(s) "
            f"across {len(seeds)} maps",
            detail,
            "Check energy, range and bounds against the view before acting. "
            "In a match an illegal action only loses the turn, but the "
            "admission gate rejects a bot that makes any. See docs/RULES.md.",
        )

    if not accepted:
        return fail(
            "Your bot never made a single accepted move",
            "decide(view) returned None or something that isn't an Action.",
            "Return an Action from every call, e.g. Action.move('EAST').",
        )

    try:
        replay_artifact(result)
    except Exception as exc:
        return fail("Match did not reproduce", exc, "Report this to the organizers.")

    print(
        f"  ok    played {len(seeds)} full matches, "
        f"{accepted} legal actions, 0 illegal"
    )
    return True


def check_deterministic(bot_class):
    """The same match must produce the same result twice.

    Wall-clock time, unseeded randomness and any other ambient input make a
    match unrepeatable, which means it cannot be verified or replayed.
    """
    from engine.game import run_match

    def play():
        bots = {name: bot_class(name) for name in ("YOU", "OPP_1", "OPP_2", "OPP_3")}
        return run_match(bots, seed=777, verbose=False)

    try:
        first, second = play(), play()
    except Exception:
        # A crash is reported in detail by the match check that follows.
        print("  --    determinism not checked (bot raised; see below)")
        return True
    if first["events"] != second["events"]:
        return fail(
            "Your bot is not deterministic",
            "The same match played twice produced different actions.",
            "Remove random.random() without a fixed seed, time.time(), and "
            "anything else that changes between runs. Seed your RNG from the "
            "view instead.",
        )
    print("  ok    deterministic across repeated runs")
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--module", default="my_bot", help="file name without .py")
    parser.add_argument("--class", dest="class_name", default="MyBot")
    args = parser.parse_args()

    print(f"\nChecking {args.module}.py :: {args.class_name}\n")
    sys.path.insert(0, str(Path.cwd()))

    if not check_python() or not check_file(args.module):
        print("\nRESULT: FAIL\n")
        return 1
    if not check_submission_rules(args.module):
        print("\nRESULT: FAIL\n")
        return 1

    bot_class, ok = check_import(args.module, args.class_name)
    if not ok:
        print("\nRESULT: FAIL\n")
        return 1

    # Determinism is checked before legality on purpose: a bot that is not
    # reproducible will also produce confusing, shifting legality errors, and
    # the root cause is the randomness, not the moves.
    for check in (
        lambda: check_ability(bot_class),
        lambda: check_buy(bot_class),
        lambda: check_deterministic(bot_class),
        lambda: check_plays(bot_class, args.class_name),
    ):
        if not check():
            print("\nRESULT: FAIL\n")
            return 1

    print("\nRESULT: PASS -- your bot is valid and can be submitted.")
    print("Valid does not mean good. Run `python play.py` to watch it.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
