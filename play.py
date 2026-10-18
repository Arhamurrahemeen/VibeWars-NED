"""Watch your bot play a match.

    python play.py                         # your bot vs 3 copies of itself
    python play.py --seed 42                # a different map
    python play.py --quiet                  # scores only
    python play.py --vs rival:RivalBot      # against another bot you wrote
    python play.py --seeds 20               # summary over 20 maps

Opponents default to copies of your own bot. `--vs` takes any bot class,
including the chaos bots in sparring.py (`--vs sparring:ChaosBomb`).

The tournament uses seeds you have never seen.
"""
import argparse
from collections import Counter
from pathlib import Path
import sys


def load(spec, default_module="my_bot", default_class="MyBot"):
    if spec is None:
        module_name, class_name = default_module, default_class
    elif ":" in spec:
        module_name, class_name = spec.split(":", 1)
    else:
        module_name, class_name = spec, default_class
    module = __import__(module_name)
    bot_class = getattr(module, class_name, None)
    if bot_class is None:
        raise SystemExit(f"No class {class_name!r} in {module_name}.py")
    return bot_class


def build_field(mine, rival):
    """Four bots: yours plus three opponents."""
    if rival is None:
        return {
            "YOU": mine("YOU"),
            "COPY_1": mine("COPY_1"),
            "COPY_2": mine("COPY_2"),
            "COPY_3": mine("COPY_3"),
        }
    return {
        "YOU": mine("YOU"),
        "RIVAL_1": rival("RIVAL_1"),
        "RIVAL_2": rival("RIVAL_2"),
        "RIVAL_3": rival("RIVAL_3"),
    }


def summarize(result):
    final = result["bots"]["YOU"]
    events = [e for e in result["events"] if e.get("actor") == "YOU"]
    return {
        "won": result["winner"] == "YOU",
        "place": result["ranking"].index("YOU") + 1,
        "score": final["score"],
        "banked": final.get("banked_value", 0),
        "unbanked_at_end": final.get("cargo_value", 0),
        "kills": final.get("kills", 0),
        "deaths": final.get("deaths", 0),
        "assists": final.get("assists", 0),
        "illegal": sum(e["type"] == "INVALID_ACTION" for e in events),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--module", default="my_bot")
    parser.add_argument("--class", dest="class_name", default="MyBot")
    parser.add_argument("--vs", help="opponent as module or module:Class")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--seeds", type=int, help="play N maps and summarize")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    sys.path.insert(0, str(Path.cwd()))
    from engine.game import run_match

    mine = load(None, args.module, args.class_name)
    rival = load(args.vs) if args.vs else None

    if args.seeds:
        tally = Counter()
        totals = Counter()
        for seed in range(args.seeds):
            result = run_match(build_field(mine, rival), seed=seed, verbose=False)
            stats = summarize(result)
            tally["wins"] += stats["won"]
            tally[f"place_{stats['place']}"] += 1
            totals["score"] += stats["score"]
            totals["banked"] += stats["banked"]
            totals["unbanked"] += stats["unbanked_at_end"]
            totals["illegal"] += stats["illegal"]
            for key in ("kills", "deaths", "assists"):
                totals[key] += stats[key]

        print(f"\n{args.seeds} maps")
        print(f"  wins            {tally['wins']}/{args.seeds}")
        places = " ".join(
            f"{place}st/nd/rd/th={tally[f'place_{place}']}".replace(
                "st/nd/rd/th", ["st", "nd", "rd", "th"][place - 1],
            )
            for place in range(1, 5)
        )
        print(f"  placements      {places}")
        print(f"  avg score       {totals['score'] / args.seeds:.1f}")
        print(f"  avg banked      {totals['banked'] / args.seeds:.1f}")
        print(f"  avg unbanked    {totals['unbanked'] / args.seeds:.1f}  (still carried at the end: scores nothing)")
        print(
            f"  avg K/D/A       {totals['kills'] / args.seeds:.1f} / "
            f"{totals['deaths'] / args.seeds:.1f} / {totals['assists'] / args.seeds:.1f}"
        )
        if totals["illegal"]:
            print(f"  ILLEGAL ACTIONS {totals['illegal']}  <- run check.py")
        print()
        return 0

    result = run_match(build_field(mine, rival), seed=args.seed, verbose=not args.quiet)
    stats = summarize(result)
    print(
        f"\nYOU placed {stats['place']}/4  score={stats['score']}  "
        f"banked={stats['banked']}  unbanked_at_end={stats['unbanked_at_end']}  "
        f"K/D/A={stats['kills']}/{stats['deaths']}/{stats['assists']}"
    )
    if stats["illegal"]:
        print(f"WARNING: {stats['illegal']} illegal actions -- run check.py")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
