# Vibe Wars — Rules

Every mechanic and number in the game. The engine in this kit is the game
itself: if this document and the engine ever disagree, the engine decides.

## The match in one paragraph
Four bots, one walled 12×12 arena, 40 turns. Bots score by **killing each
other** (up close or with ranged shots), by **carrying resources home**, and
by **planting the Core** (or defusing someone else's). The last 8 turns are
**Overtime**: every point counts double. Nobody is ever
knocked out for good: a killed bot respawns at its base a few turns later.
Dying costs you whatever you were carrying, your killing streak and time —
never the points you already banked. You can see your own score and your
rank, but never how far ahead or behind you are. Before each map every bot
secretly picks a **role** and buys upgrades with credits.

## Board
- 12×12 grid, 40 turns per match. A match always runs its full length.
- Each bot's base is one corner. Which corner you start in changes from map
  to map.
- The Core spawns on one of the four central tiles, chosen by seed.
- 4 initial resources, placed as one rotationally symmetric four-cell orbit
  per seed. Every resource in an orbit has the same value (8–22), so every
  corner gets the same resources. Most resources arrive later through supply
  waves.

## Walls
- Every match uses one of several wall layouts, chosen by seed. The layout is
  rotated four ways around the centre, so every corner faces exactly the same
  walls. The full wall list is in every view (`view["walls"]`, `view["layout"]`).
- **Walls block movement, shots and vision.**
- **The squeeze rule:** nothing — a bot, a shot or a line of sight — can slip
  diagonally between two walls that touch at a corner.
- **Base pockets:** every layout walls in each base so that no straight line
  leads into the spawn tile from outside. A respawning bot cannot be shot
  from a distance. Each pocket has two open exits.
- Walking (or dashing) into a wall is not illegal; the move is simply
  blocked (`MOVE_BLOCKED` with `reason: "WALL"`) and the energy is spent.
  BLINK teleports over walls but is blocked if it would land on one.
- `vibe_sdk.geometry` is the engine's own code for `line_clear`,
  `shot_path` and `step_open`.

## Movement
- **Eight directions:** `NORTH`, `SOUTH`, `EAST`, `WEST`, `NORTHEAST`,
  `NORTHWEST`, `SOUTHEAST`, `SOUTHWEST`. One cell per MOVE.
- Distance is Chebyshev: the number of moves between two cells on an open
  board is `max(|dx|, |dy|)`. Range and vision use the same distance.

## Bot stats
- HP 70, energy 50 (max 50, regenerates +5/turn).
- Vision range 3, and **line of sight**: you see a cell only if no wall
  blocks the straight line between your cell and it. Line of sight is
  symmetric — if you can see a bot, it can see you. SCAN spends the current
  action to grant +3 vision range in the bot's next decision view.

## Actions and costs
MOVE (1 energy), ATTACK (5), SHOOT (6), SCAN (8), COLLECT (2), DEFEND (2),
ABILITY (10), USE_ITEM (4). One action per bot per turn.

## Combat
- **ATTACK** hits one adjacent bot (range 1, diagonals included; walls never
  block a melee hit, not even the squeeze rule). A seeded
  impact roll deals 16–24 damage, labelled GLANCING (16–18), SOLID (19–21) or
  POWER (22–24). It lands even if the target moves away the same turn.
- **SHOOT(direction)** fires along one of the 8 directions, up to 4 cells, and
  hits the **first bot on the line** for 10–14. It is stopped by walls (and
  the squeeze rule). A shot resolves **after movement**: a target that steps
  off the line is not hit, and a bot that steps onto the line is. A
  spawn-protected bot absorbs the shot and takes nothing.
- Every roll comes from the match seed, turn and spawn identities, so it is
  reproducible and cannot be influenced by choosing a bot name. BLOOD_MOON
  multiplies all ATTACK, SHOOT, RAILGUN and SHOVE-slam damage by 1.5. Blasts
  (BOMB, AIRSTRIKE, ORBITAL) are not boosted.
- DEFEND halves incoming damage for that turn; SHIELD cuts it by 70%.
- **Fighting is loud.** A bot that ATTACKs or SHOOTs is marked (visible to
  everyone, reason `LOUD`) in the next turn's views.

## Death and respawn
- A bot whose HP reaches 0 is killed. It leaves the board and **does not
  decide** until it respawns 3 turns later (killed on turn `t`, back on turn
  `t + 3`) at its own base with full HP and energy. If the base tile is
  occupied it appears on the nearest free (non-wall) cell.
- **Everything it was carrying spills** onto the floor as one pile that anyone
  can collect. If it was carrying the Core, the Core drops where it died. A
  held item drops as a crate.
- Its streak resets to 0. **Banked score is never lost.**
- **Spawn protection:** for 2 turns after respawning a bot takes no damage
  from anything. It ends immediately if the bot uses ATTACK, SHOOT, COLLECT,
  ABILITY or USE_ITEM. Other bots see `protected: true`.

## Scoring
| Event | Points |
|---|---|
| Kill | +40 (+25 now, +15 when you confirm its tag — see Kill Confirmed) |
| Kill of a bot you already killed within the last 8 turns | +15 instead of +40 (all of it in the tag) |
| Crown kill — the victim was wearing the crown | +30 (+15 more per extra map it had won in a row) |
| Nemesis — you killed whoever killed you most last map | +15 |
| Revenge — you killed the bot that last killed you | +15 |
| Multi-kill — every extra kill credited to you in the same turn | +20 |
| Blast — your own bomb, airstrike or orbital made the kill | +10 |
| Shove kill — a bot you shoved died to a blast within 2 turns | +10, and you share the kill |
| Clutch — you made the kill while on 15 HP or less | +15 |
| Tag confirmed (yours) / denied (anyone else's) | +15 / +10 |
| First Blood (the first kill of the match) | +20 |
| Shutdown — the victim's streak was 2 / 3 / 4 / 5+ | +10 / +20 / +30 / +40 |
| On Fire — you kill while your own streak is 3+ | +10 |
| Assist — you damaged the victim in the last 3 turns but did not get the kill | +10 |
| Cargo banked at your base | the cargo's value |
| Core uplinked (your plant survives its countdown) | +60 |
| Core defused (shared by every enemy in range when it completes) | +40 |

Your role adds its own rows (see Roles below).

**Overtime:** from turn 32 (the last 8 turns) every row above pays double,
and energy regenerates at +10/turn. Rows stack: one kill can earn several of
them at once.

- **Streak** = kills since your last death.
- Every attacker that landed damage on the turn a bot died gets the kill.
- A bot killed by its own bomb gives nobody any points.
- Every score change appears in the match log as a `SCORE` event with the
  points and the reason.

## The crown
At the start of every turn the bot with the **strictly highest score** wears
the crown (a tie keeps the current holder). The crown holder is marked —
visible to everyone, reason `CROWN` — and killing it pays the crown bounty.
You learn who leads, never by how much.

## Kill Confirmed
A kill pays part of its value at once and drops a **tag** where the victim
died (`view["tags"]`, visible like resources). At the end of any turn, a bot
standing on a tag picks it up automatically:
- one of the tag's killers **confirms** it (+15);
- anyone else — including the victim, back from respawn — **denies** it
  (+10), and the killer never gets the rest.

Tags expire after 6 turns.

## Killstreak powers
- Reaching a **3-kill streak**: an automatic radar sweep — you see every enemy
  for 3 turns.
- Reaching a **5-kill streak**: an AIRSTRIKE goes into your item slot,
  replacing whatever you held.

## Taunts
Any action may carry one emote, `Action.defend().taunt("GG")`, shown in the
match feed. Allowed: `GG`, `NICE`, `OOPS`, `TOO_SLOW`, `WATCH_THIS`, `RIP`,
`BOOM`, `HELLO`, `THANKS`, `CATCH_ME`. Anything else is ignored; a taunt never
makes an action illegal and never changes what it does.

## Series carry-over
The maps of one group are played in order, and some context carries from
each map into the next:
- **The previous map's winner starts the next map wearing the crown.**
- A team that has won several maps in a row carries a bigger crown bounty
  (+15 per extra win).
- Your **nemesis** (`view["self"]["nemesis"]`) is whoever killed you most last
  map (no nemesis on a tie). Killing your nemesis pays +15.
- Credits (see below).

Nothing else carries over: every map starts with fresh HP, energy, scores
and an empty board.

## Roles and the buy phase
Before every map each bot picks a **role** and spends **credits** in the
shop. Nobody else can see either: not in any view, not in the shop, not in
the scores you can read.

### Roles
A role makes one way of scoring pay more and costs you somewhere else.
Picking no role (`None`) is legal and has no bonus and no cost.

| Role | Pays more for | Costs you |
|---|---|---|
| HUNTER | +10 per kill, plus Rampage: +5 per kill for each kill already on your streak | banks cargo at 0.85×; **whoever kills you gets +25** |
| HAULER | +1 cargo capacity; banking 3 units at once pays 1.25×, 4 or more 1.5× | kills pay 10 less |
| RUNNER | +10 per uplink, +10 more for each earlier uplink this map; ability recharges 2 turns faster | 5 less max HP |
| WARDEN | +20 per defuse; Guard: +20 for killing a Core carrier, a live planter, or anyone within 2 cells of a planted Core | can never pick up the Core; banks at 0.9×; 1 less cargo capacity |

Role bonuses double in Overtime like everything else.

### The shop
| Item | Price | Effect |
|---|---|---|
| ARMOR | 2 | +15 max HP (rivals only ever see your HP) |
| POCKETS | 2 | +1 cargo capacity |
| QUICK_RESPAWN | 3 | respawn 1 turn sooner |
| OVERCLOCK | 3 | ability recharges 2 turns faster (never below 3 turns) |
| SCOPE | 2 | +1 vision range |
| KIT_RAILGUN | 3 | start holding a RAILGUN |
| KIT_MEDPACK | 2 | start holding a MEDPACK |
| KIT_SMOKE | 2 | start holding a SMOKE |
| KIT_RADAR | 2 | start holding a RADAR |

Each item can be bought once, and at most one KIT, because you have one item
slot. A kit item is held like any other: opening a crate swaps it out.

### Credits
- Everyone starts the first map of a series with **4 credits**.
- After every map: **+3**, plus a placement bonus of **+0 / +1 / +2 / +3**
  for finishing 1st / 2nd / 3rd / 4th, plus **+1 for every map in a row you
  have not won (up to +2)**. The winner earns the fewest.
- Unspent credits carry over. You can never hold more than **10**.

### How a bot buys
Implement `buy(self, shop)`; it is called once before every map. `shop` holds
your credits, the prices, the roles, the map number and your own previous
placements — nothing about any rival. Return
`{"role": "HUNTER", "items": ["ARMOR", "SCOPE"]}`, or `None` to keep your
class's `ROLE` and buy nothing. **Anything invalid — an unknown name, a
duplicate, two kits, more than you can afford, a crash, a timeout — buys
nothing.** It is never illegal and you still play the map. `buy()` has the
same time limit as `decide()` and must be deterministic.

## Cargo: collect, carry, bank
Resources are **not** scored when collected. Collecting loads the resource
into the bot's cargo hold; the points only count once the bot stands on its
own base tile, which banks the entire load automatically.

- Cargo capacity is 4 resource units (roles and POCKETS change it; see
  `view["self"]["cargo_capacity"]`). A full hold cannot collect again until
  it banks.
- **Hot pickup:** collecting a resource while any other bot is within 2 cells
  loads it at **1.3× its value**. Spilled cargo piles never get the hot bonus
  again.
- Dying spills the whole load (see above). Unbanked cargo is worth nothing
  when the match ends.

## Marked bots
A bot is **marked**, and visible to every other bot anywhere on the board,
while it:
- wears the crown (`CROWN`), or
- carries the Core (`CORE`), or
- has a planted Core counting down (`PLANTER`), or
- carries 60 or more cargo (`CARGO`), or
- is **On Fire** (a streak of 3 or more, `ON_FIRE`), or
- fought last turn (`LOUD`: it used ATTACK, SHOOT, RAILGUN, AIRSTRIKE or
  ORBITAL).

Marks ignore walls and vision range.

Marked bots appear in `visible_enemies` with `marked: true`, their reasons in
`mark_reasons`, and `in_vision: false` if they are outside your normal vision.

## What you can and cannot see
- Bots, resources and bombs within your vision range and line of sight.
- Airstrike markers, crates and smoke clouds anywhere.
- The whole wall layout.
- Marked bots anywhere.
- The Core's position and state, always, and the uplink pads.
- Your own score and your **rank** (1–4). Never another bot's score.

## Special abilities
One ability per bot, fixed for the whole match (a class attribute on the Bot
subclass). 6-turn cooldown after use.

| Ability | Effect |
|---|---|
| DASH | Move 2 cells in a straight line in any of the 8 directions. Both cells must be clear of bots and walls. |
| BLINK | Teleport 3 cells in a straight line in any of the 8 directions, over walls and bots. Only the landing cell must be clear. |
| SHIELD | 70% incoming damage reduction for the turn. |
| BOMB | Drop a bomb on your own tile. It detonates 3 turns later over a radius of 1: 45 damage at the centre, 25 at the edge. |
| SHOVE | `Action.shove(bot_id)` on an adjacent enemy. After movement it is pushed one cell straight away from you. If that cell is a wall, a bot or the edge — or two bots shove it at once — it is slammed for 15 damage instead. |

### BOMB in detail
- **Visible to everyone.** Any bot within vision sees it in
  `view["visible_bombs"]`, with `turns_until_detonation` and `blast_radius`,
  plus `mine` saying whether it is your own.
- **Detonates at the start of a turn, before any bot decides.**
- **It damages its owner.** A radius-1 blast cannot be left in one step.
- **Blasts chain.** A detonation sets off any other bomb inside its area.
- **One live bomb per bot.** Placing a second while the first is ticking is
  illegal.
- Reduced by SHIELD (70%) or DEFEND (50%); blocked by spawn protection.
  Because the blast lands before anyone decides, the SHIELD or DEFEND that
  counts is the one used on the **previous** turn — the turn the bomb shows
  `turns_until_detonation: 1`. The same applies to AIRSTRIKE and ORBITAL.
- A bomb does not block movement.

## Resolution model
Fully simultaneous:
- All actions are validated against the same start-of-turn state.
- Two bots moving to the same cell: both moves fail.
- Moving into a cell occupied at the start of the turn fails, even if that
  occupant is moving away (no swap-through).
- Melee uses start-of-turn positions; shots use positions after movement.
  All damage on a target in one turn is summed before anyone dies, so two
  bots hitting each other can both die, and everyone who landed damage on
  the killing turn gets the kill.

Order within a turn: events expire, bombs detonate, killed bots respawn,
Overtime and the Core spawn, supply waves and events trigger, energy
regenerates — then bots decide —
then abilities, movement, melee and shots, collection, banking, and the
Core (plant, then defuse, then uplink) resolve.

## Supply waves
The arena refills on a seeded cadence: a wave drops one rotationally
symmetric four-cell orbit of equal-value resources (12–26) in the inner arena,
announced the turn it lands. The first wave lands between turns 12–15, then
every 8–10 turns. Timing and placement differ every match.

## The Core
1. **Spawn.** It first comes online at turn 8 on one of the four central
   tiles (`visible_core.status` is `INACTIVE` until then, with `spawns_in`).
2. **Pick up.** Stand on it and COLLECT "CORE". It moves with you and you are
   marked. If you are killed, it drops where you died.
3. **Plant.** Step onto any **uplink pad** while carrying it and it plants
   itself at the end of that turn. There are four pads (`view["uplink_pads"]`),
   one on each mid-edge between two bases. While your plant counts down you
   are marked (`PLANTER`).
4. **Uplink.** If the plant survives 3 turns (planted at the end of turn `t`,
   uplinks at the end of turn `t + 3`), the planter scores +60 — even if it
   has died in the meantime.
5. **Defuse.** If any enemy of the planter is **within 1 cell** of the
   planted Core at the end of 2 consecutive turns, it is defused: every enemy
   in range at that moment scores +40 and the uplink never happens. A turn
   with no enemy in range resets the progress. Defuse is checked before
   uplink, so a defuse completed on the countdown's last turn wins.
6. **Respawn.** After an uplink or a defuse the Core goes `INACTIVE` and comes
   back at the centre 4 turns later, on the next of the four central tiles
   in a fixed order.

The Core's full state is always public: `status` (`INACTIVE`, `GROUND`,
`CARRIED`, `PLANTED`), position, `carried_by`, `planted_by`, `uplink_in`,
`defuse_progress` / `defuse_needed` and `spawns_in`.

## Crates and items
Supply crates drop on a seeded schedule (first between turns 9–12, then every
9–11 turns) as one rotationally symmetric orbit of four, visible to everyone
(`view["crates"]`). Stand on one and COLLECT its id to take the item inside.

- **One item at a time.** Opening a crate while holding an item swaps it: the
  old item is discarded. Rivals see `has_item: true`, never which item.
- **What is inside is rolled when you open it, weighted by your rank:** the
  further behind you are, the likelier a power item (RAILGUN, AIRSTRIKE).
  Likelier, never certain.
- **Not every item appears every match.** Each match draws 4 of the 5 item
  types; the pool is listed in `view["item_pool"]`.
- **USE_ITEM** (4 energy) spends it:

| Item | Use | Effect |
|---|---|---|
| RAILGUN | `Action.use_item(direction=...)` | Fires along the line to the first wall or the board edge and hits **every** bot on it for 25. Resolves after movement, like SHOOT. |
| AIRSTRIKE | `Action.use_item(x=..., y=...)` | Aimed at **any** cell, even in fog. Lands at the start of the turn after next over a radius of 1 (40 centre, 25 edge). The marker is visible to everyone everywhere the moment it is called. |
| MEDPACK | `Action.use_item()` | Heals 40 HP, never above your max HP (70; see `view["self"]["max_hp"]` with ARMOR or as RUNNER). |
| SMOKE | `Action.use_item()` | A 3×3 cloud on your cell for 3 turns. A bot inside smoke is hidden from anyone more than 1 cell away (marks still show). |
| RADAR | `Action.use_item()` | For 3 turns you see every enemy on the board. |

- RAILGUN, AIRSTRIKE and ORBITAL are loud. An airstrike kill is credited to
  the bot that called it; it damages its caller too if the caller stands in it.
- A killed bot's held item drops as a crate where it died.

### The legendary drop
Once per match, on a seeded turn between 18 and 23, a **legendary crate**
lands on a seeded cell near the centre. Everyone is warned 2 turns before it
lands (`view["legendary_incoming"]`: where, and in how many turns). Its item:

| Legendary | Use | Effect |
|---|---|---|
| ORBITAL | `Action.use_item(x=..., y=...)` | Like an airstrike but radius 2: 60 centre, 30 edge. Lands 2 turns later; visible to everyone. |
| OVERSHIELD | `Action.use_item()` | For 3 turns, the next hit that would kill you leaves you on 1 HP instead. |
| REAPER | `Action.use_item()` | For 5 turns, every kill you make pays its kill points twice. |

## Overtime
The final 8 turns (from turn 32) are Overtime, announced as an event:
**every SCORE is doubled** — kills, bounties, assists, banked cargo, uplinks
and defuses — and energy regenerates twice as fast.

## Dynamic events
Deterministic per match seed. Every match gets each event once, in a seeded
order: the first between turns 8–12, the next 10–14 turns later.

| Event | Effect | Duration |
|---|---|---|
| BLOOD_MOON | ATTACK, SHOOT, RAILGUN and SHOVE-slam damage ×1.5 (blasts unchanged) | 6 turns |
| RESOURCE_RUSH | Spawns one rotationally symmetric orbit of 4 equal-value resources (8–22) in the inner arena | instant; resources persist |

Events start or expire at the beginning of a turn, before bots receive
their views.

## Win condition
Highest score when the match ends. Being killed never removes points you
have already scored; cargo you are still carrying at the end scores nothing.

## Tiebreak
If scores are tied, in order:
1. More kills.
2. Fewer deaths.
3. More cargo banked.
4. More resources collected.
5. Bot ID, ascending — absolute last resort, so the result is always
   deterministic.
