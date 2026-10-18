# Vibe Wars Bot SDK Contract — action protocol 2.0

This is the participant-facing programming contract. Tournament submissions
target action protocol `2.0` and must import only from `vibe_sdk`
(`Bot`, `Action`, the `ABILITIES` / `ROLES` / `SHOP` / `DIRECTIONS` /
`DIRECTION_DELTAS` constants, and the `geometry` module); organizer engine
modules are private
implementation details.

`vibe_sdk.geometry` is the engine's own wall code, shipped unchanged:
`line_clear(walls, ax, ay, bx, by)`, `shot_path(walls, width, height, x, y,
direction, max_range)` and `step_open(walls, width, height, x, y, dx, dy)`,
where `walls` is a set of `(x, y)` tuples built from `view["walls"]`.

## Minimal bot

```python
from vibe_sdk import Action, Bot


class MyBot(Bot):
    ABILITY = "DASH"

    def decide(self, view):
        return Action.move("SOUTHEAST")
```

The submitted class must subclass `Bot`, accept `bot_id` through the inherited
constructor (or a compatible override), and implement `decide(view)`. `ABILITY`
is fixed for the whole match and is either `None` or one of `DASH`, `SHIELD`,
`BLINK`, `BOMB`, or `SHOVE`.

`decide` must return exactly one SDK `Action` before the decision deadline.
Returning `None`, returning another object, raising, exiting, or exceeding the
deadline loses the turn and fails conformance. Action legality—including
energy, range, visibility, board bounds, cooldown, and target existence—is
checked against the same start-of-turn state shown in `view`.

## Roles and the buy phase

```python
class MyBot(Bot):
    ABILITY = "DASH"
    ROLE = "HAULER"            # default role: HUNTER, HAULER, RUNNER, WARDEN or None

    def buy(self, shop):
        # shop = {"credits": 4, "prices": {"ARMOR": 2, ...}, "roles": [...],
        #         "map": 1, "your_placements": [3, 1], "credit_cap": 10}
        if shop["credits"] >= 4:
            return {"role": "HAULER", "items": ["POCKETS", "ARMOR"]}
        return None             # keep ROLE, buy nothing
```

`buy(shop)` is optional. It runs once before every map, in the same worker
and under the same deadline as `decide`, and its result is recorded in the
match artifact. It must be deterministic. It may switch role per map.
Whatever it returns is validated by the engine; anything malformed, unknown,
duplicated, over budget or a second `KIT_` item buys **nothing** (role falls
back to `ROLE` if the role itself is invalid). A crash or timeout in `buy`
also buys nothing — it is never a lost turn and does not end the worker.
`shop` never contains anything about another bot. Rules and prices:
`docs/RULES.md` → Roles and the buy phase.

## Time limits

- `decide(view)` and `buy(shop)`: **200 ms** each, wall-clock. A late answer
  is a timeout: the turn is lost (for `buy`, nothing is bought).
- Loading your file and creating the bot: 2 s.
- The tournament machine runs many matches at once, so your bot gets less
  CPU than on your laptop. Aim well under the limit (tens of milliseconds).

Three failures in a row (crash, timeout or no Action) switch your bot off
for the rest of that match. A successful decision resets the count.

## State and determinism

One bot object lives in one isolated worker for the duration of a match.
Instance fields therefore persist between turns, including across your own
deaths: the object is not recreated when your bot
respawns. They do not persist into another match. A submission must produce
identical behavior when the same match seed, opponents, participant order, and
spawn assignment are repeated. Do not use wall-clock time, unseeded randomness,
process IDs, filesystem state, or other ambient inputs for decisions.

`decide` is **not called while your bot is dead**. The first view after a
respawn has you on (or next to) your base with `self.protected` true.

## Observation shape

Each `view` is a JSON-compatible dictionary with these top-level fields:

- `turn`, `max_turns`, `bot_count`
- `self`: `id`, `x`, `y`, `hp`, `energy`, `score`, `rank` (1 = leading),
  `kills`, `deaths`, `streak`, `protected`, `marked`, `carrying_core`,
  `cargo_value`, `cargo_units`, `cargo_capacity`, `base` (`x`, `y`),
  `ability`, `ability_ready`, `scan_active`, `item` (your held item or
  `None`), `radar_active`, `overshield_active`, `reaper_active`, `crowned`,
  `nemesis` (a bot ID or `None`), `revenge_target` (who last killed you),
  `series_streak` (maps you won in a row before this one), `role`,
  `loadout` (the items you bought), `max_hp`, `uplinks` (yours this map).
  Role and loadout appear **only** in your own `self`, and your credits only
  in `buy(shop)` — never anything of a rival's.
- `board`: `width`, `height`
- `walls`: every wall cell as `[x, y]` (the whole map, always), and `layout`:
  the name of this match's wall template
- `vision_range`: your effective vision range for this decision (SCAN
  included). Cells are visible only within range **and** line of sight.
- `visible_enemies`: each with `id`, `x`, `y`, `hp`, `cargo_value`,
  `carrying_core`, `streak`, `crowned`, `crown_bounty`, `nemesis` (true if it
  is yours), `revenge` (true if it last killed you), `has_item`, `protected`,
  `marked`, `mark_reasons` (`CROWN`, `CORE`, `PLANTER`, `CARGO`, `ON_FIRE`,
  `LOUD`, or `RADAR` while your radar runs) and `in_vision`. Enemies inside your vision
  are listed (except one inside smoke more than 1 cell from you);
  **marked** enemies are listed wherever they are, with `in_vision: false`
  when outside your vision. ATTACK needs an enemy adjacent to you.
- `visible_resources`: `id`, `x`, `y`, `value`, `loot` (true for a spilled
  cargo pile, which never earns the hot-pickup bonus)
- `visible_bombs`: every live bomb in vision **and every airstrike marker
  anywhere**, each with `x`, `y`, `kind` (`BOMB`, `AIRSTRIKE` or `ORBITAL`),
  `turns_until_detonation`, `blast_radius`, and `mine` (whether your bot
  placed it). Both damage their owner too, so your own appear here and must
  be avoided like anyone else's.
- `crates`: every crate on the board (`id`, `x`, `y`, `legendary`; never its
  contents)
- `legendary_incoming`: `{x, y, lands_in}` during the 2-turn warning, else
  `None`
- `tags`: Kill Confirmed tags in sight (`id`, `x`, `y`, `victim`, `mine`,
  `turns_left`)
- `smokes`: every smoke cloud (`x`, `y`, `radius`, `turns_left`)
- `item_pool`: the item types that can appear in this match
- `visible_core`: always present. `status` (`INACTIVE`, `GROUND`, `CARRIED`,
  `PLANTED`), `x`, `y`, `carried_by`, `planted_by`, `uplink_in`,
  `defuse_progress`, `defuse_needed`, `spawns_in`
- `uplink_pads`: the four `[x, y]` cells where a carried Core plants itself
- `overtime_turn`: the turn Overtime (double points) begins
- `active_events`: includes `OVERTIME` once it has started

Absent enemies and objectives are intentionally omitted by fog of war. Never
infer truth from list ordering. **Other bots' scores are never shown** — only
your own score and your rank.

Collecting a resource loads cargo; it scores only when the bot reaches its own
base. Dying spills the whole load onto the floor for anyone to take. Supply
waves land on a seeded schedule that differs every match. See `docs/RULES.md`.

A bomb detonates at the **start** of a turn, before any bot decides, and
damages every bot in its radius, its owner included. A radius-1 blast cannot
be left in a single move. See the BOMB section of `docs/RULES.md`.

## Actions

Directions are `NORTH`, `SOUTH`, `EAST`, `WEST`, `NORTHEAST`, `NORTHWEST`,
`SOUTHEAST`, `SOUTHWEST`. `vibe_sdk.DIRECTION_DELTAS` maps each to its
`(dx, dy)`; `y` grows southward.

- `Action.move(direction)` — moving into a wall or an occupied cell is legal
  but blocked (`MOVE_BLOCKED`); moving off the board is illegal
- `Action.attack(bot_id)` — an adjacent bot
- `Action.shoot(direction)` — hits the first bot within 4 cells on that line,
  resolved after movement
- `Action.collect(resource_id)`, `Action.collect(crate_id)` or
  `Action.collect("CORE")`
- `Action.use_item()` for MEDPACK/SMOKE/RADAR,
  `Action.use_item(direction=...)` for RAILGUN,
  `Action.use_item(x=..., y=...)` for AIRSTRIKE
- `Action.scan()`
- `Action.defend()`
- `Action.ability(direction=...)` for DASH/BLINK
- `Action.ability()` for SHIELD/BOMB
- `Action.shove(bot_id)` for SHOVE (an adjacent enemy)
- `Action.use_item(x=..., y=...)` also for ORBITAL; `Action.use_item()` for
  OVERSHIELD and REAPER
- Any action can carry an emote: `Action.move("EAST").taunt("CATCH_ME")`. See
  the allowed list in `docs/RULES.md`; anything else is ignored.

Full costs and mechanics are defined in `docs/RULES.md`.

## Local validation

Run the same gate used before tournament admission:

```bash
python conformance.py --module my_bot --class MyBot
```

It runs your bot isolated, with the 200 ms deadline, through the same steps
as the organizers' admission gate: it loads; its opening decision is legal
and repeatable; `buy()` is deterministic; and four full matches (seeds 3, 10,
18, 28, your bot rotated through every corner, each played twice) show **no
crash, no timeout, no illegal action and identical results**. The command
exits `0` only when all of that passes.

**Admission rule:** a submission that crashes, times out, behaves
differently between runs, or makes even one illegal action in the admission
matches is rejected. The organizers' gate uses their own opponents; the
kit's uses the chaos sparring bots in `sparring.py`. Passing locally is
strong evidence, not a guarantee, so guard every action against the view
(energy, range, bounds, cooldown) rather than assuming a situation cannot
happen. Passing proves compatibility and reliability, not strategic
strength.
