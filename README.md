# Vibe Wars — Starter Kit

Build an autonomous bot. At the deadline your code is frozen: no edits, no
human control, no internet, no AI calls during the match. Your bot plays
alone, on maps it has never seen, against opponents you have never seen.

**You need Python 3.9+. Nothing else. No pip install.**

## Start here

```bash
python check.py     # is my bot valid?
python play.py      # watch it play
```

Both should work immediately. If they don't, fix that before writing
anything — ask an organizer.

Then open **`my_bot.py`** and make it yours. It's the only file you have to
edit. What's in there now is only a legal starting point: it walks toward
the first resource it can see and does nothing else.

## The loop

```bash
python play.py                  # one match, full turn log
python play.py --seed 42        # a different map
python play.py --seeds 20       # how does it do across 20 maps?
python check.py                 # still legal?
```

**The tournament uses seeds you have never seen**, so `--seeds` shows you
far more than any single map does.

## Before you submit

```bash
python conformance.py
```

This runs your bot the way the admission gate does: isolated subprocess,
200 ms decision deadline, four full matches against the chaos sparring bots
in `sparring.py`. **If this fails, your submission is rejected.** Run it
early, not at the deadline — you cannot fix it afterwards.

**The admission rule:** a bot that crashes, times out, behaves differently
between runs, or makes even **one illegal action** in the admission matches
is rejected. The organizers' gate plays your bot against different
opponents than the kit's, so check every action against the view (energy,
range, bounds, cooldown) instead of assuming a situation can't happen.

## The game on one screen

Four bots, a walled 12×12 arena, 40 turns. Details and every number are in
`docs/RULES.md`; this is the map of what exists.

**Ways to score**
- **Kills** — melee (adjacent), `SHOOT` along a line, blasts, shoves. Part
  of a kill waits in a tag on the floor (Kill Confirmed). Bonuses for First
  Blood, streak shutdowns, assists, revenge, multi-kills, clutch kills,
  killing your nemesis, and killing whoever wears the **crown** (the current
  leader).
- **Cargo** — collect resources, carry them, bank them by standing on your own
  base. Dying spills everything you carry for someone else to take.
- **The Core** — pick it up, carry it to an uplink pad, survive the countdown.
  Enemies standing next to a planted Core can defuse it for points of their
  own. It comes back after every uplink or defuse.
- **Overtime** — the last 8 turns pay double for everything.

**What you will run into**
- Nobody is out for good: a killed bot respawns at its base a few turns later,
  briefly protected.
- Walls change every match; you only see what is in range and in line of
  sight. Some bots are visible to everyone (wearing the crown, carrying the
  Core or a big load, waiting on its own planted Core, on a killing streak, or
  having just fought).
- Crates drop items — railgun, airstrike, medpack, smoke, radar — and each
  match uses only some of them. Once a match, a legendary crate is announced
  before it lands.
- Kill streaks unlock a radar sweep, then an airstrike.
- One fixed special ability per bot (`DASH`, `BLINK`, `SHIELD`, `BOMB`,
  `SHOVE`).
- **Before every map your bot secretly picks a role and buys upgrades**
  (`ROLE` and `buy(shop)` in `my_bot.py`). HUNTER, HAULER, RUNNER and WARDEN
  each pay more for one way of scoring and cost you somewhere else; no role
  is also allowed. Nobody can see your role or what you bought. Credits carry
  between maps, and the further down you finished, the more you get.
- In a series, the last map's winner starts the next one wearing the crown,
  and rivalries carry over as nemeses.
- Your bot can taunt: any action can carry an emote from a fixed list.
- You see your own score and rank, never anyone else's score.

## What you need to read

- **`docs/RULES.md`** — every mechanic and number in the game. Nothing is
  hidden from you.
- **`docs/BOT_SDK_CONTRACT.md`** — what `decide(view)` receives and must
  return.

There is no single right way to play, and nothing in this kit tells you
one. Kills, cargo and the Core all score, nobody is ever knocked out for
good, and you can never see how far ahead or behind you are, only your rank.
How well a plan does depends on what the other three bots do, and you will
not know who they are until the match.

## You submit one file

**Only `my_bot.py` is submitted, and its bot class must be called `MyBot`.**
Put every helper function and class inside it. A second file you import works on your laptop and does not exist at the
tournament. Import only `vibe_sdk` and these standard modules: `math`,
`random`, `heapq`, `bisect`, `collections`, `itertools`, `functools`,
`operator`, `dataclasses`, `typing`, `enum`, `copy`, `statistics`,
`fractions`, `decimal`, `numbers`, `string`, `re`, `array`, `abc`, `time`,
`hashlib`, `json`, `cmath`. Calls like `eval`, `exec`, `open`, `globals` and
double-underscore tricks (`__builtins__`, `__class__`, ...) are not allowed.
`check.py` tells you if your file breaks a rule, before you find out at
submission.

## The one rule about your code

`decide(view)` is called once per turn and must return one `Action`, and
`buy(shop)` once per map, each within 200 ms. Both must behave **identically given identical
inputs**. No `time.time()`, no unseeded
`random`, no reading files, no network. If your bot isn't reproducible, the
result can't be verified, and `check.py` will tell you.

You keep one bot object for a whole match, so `self.anything = ...` persists
between turns.

## Writing opponents

There are no sample strategies in this kit, on purpose. `sparring.py` has
chaos bots that act at random (they find crashes; how you score against them
means nothing), and `play.py --vs` takes any bot you write:

```bash
python play.py --vs sparring:ChaosShove --seeds 20
python play.py --vs rival:RivalBot --seeds 20
```

## Things that break a bot

- An illegal action loses the turn (and gets you rejected at admission).
  Check energy, range, bounds and cooldown first.
- Crashing loses the turn. Three failures in a row and you're switched off
  for the rest of the match.
- `decide()` and `buy()` have a hard **200 ms** deadline, and the tournament
  machine is busier than your laptop. Aim for tens of milliseconds. A late
  answer counts as no answer.
- Fog of war means most things are usually **not** in your view. Empty lists
  and missing keys are normal, not edge cases.
- Not every item exists in every match (`view["item_pool"]`), and the wall
  layout changes every match (`view["walls"]`).
- `vibe_sdk.geometry` is the engine's own wall code, so your bot can agree
  with the engine about line of sight and shot paths exactly.

Good luck.
