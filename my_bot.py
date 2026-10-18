"""Your bot. This is the only file you have to edit and the only file you submit.

v5 HAULER with DASH. Rules, checked top to bottom every turn:
  0. Safety: standing in a visible blast zone -> step out (DEFEND if trapped).
  1. Low HP (<= 30): MEDPACK / OVERSHIELD / SMOKE if held, else flee from any
     enemy within 3 (DEFEND if there is nowhere better to stand).
     Fleeing is OFF (FLEE_AT_LOW_HP) -- it measured worse.
  2. Use the held item when it pays: RAILGUN on a line with enemies,
     AIRSTRIKE/ORBITAL on an enemy safely far away, MEDPACK when 40 HP down,
     RADAR at once, OVERSHIELD/REAPER with an enemy within 2.
  3. An unprotected enemy next to us -> ATTACK it (lowest HP first). Optional
     cap on hits in a row on one bot (ATTACK_CAP) -- OFF, it measured worse.
  4. An unprotected enemy first on a clear shot line within 4 -> SHOOT it.
     Rules 2-4 are skipped when carrying cargo and home is close to the
     deadline, or while carrying a Core that can still uplink.
  5. Standing on a resource with room in the hold -> COLLECT it.
     Rules 5 and 8 skip a resource we could not still carry home in time.
  6. Hold full, or carrying cargo and only just enough turns left -> go home.
     Overtime timing: a full hold close to Overtime waits beside base so it
     banks at double; in Overtime, cargo goes home when nothing is in sight.
  7. Core: carrying it -> nearest uplink pad (while it can still uplink, this
     beats rules 2, 3, 4 and 6). On the ground within 3 steps, hold empty,
     and we can still uplink before the end -> fetch and collect it. Planted
     by an enemy and reachable before uplink -> stand next to it to defuse.
  8. A resource in sight -> walk to the nearest one (by path length).
  9. Kill tags we can reach before they expire, and crates (when our item
     slot is empty, or the legendary one) -> walk there; COLLECT a crate.
     Crates are OFF (OPEN_CRATES) -- they measured worse; tags stay on.
 10. Otherwise patrol the inner arena, where supply waves land.
DASH replaces a MOVE on urgent trips (rules 0, 1, 6, 7) when both cells are
clear and landing still leaves us on a shortest path.
Anything unexpected falls back to DEFEND, which is always legal.
"""
from collections import deque

from vibe_sdk import DIRECTION_DELTAS, Action, Bot, geometry

# Patrol loop around the centre (supply waves land in the inner arena).
WAYPOINTS = ((4, 4), (7, 4), (7, 7), (4, 7))
# A full hold this many turns (or fewer) before Overtime waits to bank in it.
OVERTIME_HOLD = 6
# Carrying cargo with home within this many turns of the deadline: don't fight.
LATE_SLACK = 3
# Fetch a grounded Core only when it is this close and the hold is empty.
CORE_DETOUR = 3
# Rule 1 kicks in at this HP; enemies this close count as a threat.
LOW_HP = 30
THREAT_RANGE = 3
# Rule 3: consecutive hits on one bot before giving up on it, unless it is
# within one minimum hit (16) of dying. None turns the cap off.
ATTACK_CAP = None
KILL_HP = 16
# Rule 9: ignore crates further than this.
CRATE_RANGE = 8
# Switched off because they measured worse in round-robins against v4:
# fleeing at low HP (rule 1) and walking to crates (rule 9). Tags stay on.
FLEE_AT_LOW_HP = False
OPEN_CRATES = False
# Keep this much energy after a DASH (it costs 10).
DASH_MIN_ENERGY = 15


def cheb(a, b):
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


class MyBot(Bot):
    ABILITY = "DASH"
    ROLE = "HAULER"

    def __init__(self, bot_id):
        super().__init__(bot_id)
        self.waypoint = None
        self.attack_run = (None, 0)

    def buy(self, shop):
        credits = shop.get("credits", 0) if isinstance(shop, dict) else 0
        # Chosen by paired tests (same seat, same seeds): QUICK_RESPAWN is the
        # best extra (+17-24 score); SCOPE, OVERCLOCK and KIT_MEDPACK were not
        # worth their credits. With exactly 4 credits POCKETS + ARMOR still wins.
        if credits >= 7:
            items = ["POCKETS", "ARMOR", "QUICK_RESPAWN"]
        elif credits >= 5:
            items = ["ARMOR", "QUICK_RESPAWN"]
        elif credits >= 4:
            items = ["POCKETS", "ARMOR"]
        elif credits >= 2:
            items = ["ARMOR"]
        else:
            items = []
        return {"role": "HAULER", "items": items}

    def decide(self, view):
        action = None
        try:
            action = self._decide(view)
        except Exception:
            pass
        if type(action) is not Action:
            action = Action.defend()
        if action.type == "ATTACK":
            same = action.target == self.attack_run[0]
            self.attack_run = (action.target, self.attack_run[1] + 1 if same else 1)
        else:
            self.attack_run = (None, 0)
        return action

    # ------------------------------------------------------------------ rules

    def _decide(self, view):
        me = view["self"]
        board = view["board"]
        self.w, self.h = board["width"], board["height"]
        self.walls = {tuple(cell) for cell in view.get("walls") or []}
        self.energy = me["energy"]
        self.dash_ready = me.get("ability") == "DASH" and bool(me.get("ability_ready"))
        pos = (me["x"], me["y"])
        self.pos = pos

        enemies = [
            e for e in view.get("visible_enemies") or []
            if isinstance(e.get("id"), str) and isinstance(e.get("x"), int) and isinstance(e.get("y"), int)
        ]
        resources = view.get("visible_resources") or []
        self.bots = {(e["x"], e["y"]) for e in enemies}
        self.danger = self._danger_cells(view.get("visible_bombs") or [])
        self._strict = self._loose = None
        item = me.get("item")
        can_use = item is not None and self.energy >= 4

        # Rule 0: get out of a blast zone.
        if pos in self.danger:
            action = self._go(lambda c: c not in self.danger, urgent=True)
            return action or Action.defend()

        # Rule 1: low HP -> heal, protect, or run.
        threats = [e for e in enemies if cheb(pos, (e["x"], e["y"])) <= THREAT_RANGE]
        if me["hp"] <= LOW_HP and not me.get("protected"):
            if can_use and item == "MEDPACK":
                return Action.use_item()
            if threats:
                if can_use and item in ("OVERSHIELD", "SMOKE"):
                    return Action.use_item()
                if FLEE_AT_LOW_HP:
                    return self._flee(threats) or Action.defend()

        room = me["cargo_units"] < me["cargo_capacity"]
        base = (me["base"]["x"], me["base"]["y"])
        turns_left = view["max_turns"] - view["turn"]
        # Distance home from every cell (walls only); moves are reversible.
        home = self._bfs(base, set())

        def worth_collecting(cell, dist_to):
            # Arrive, collect next turn, then walk home before the match ends.
            back = home.get(cell, (None,))[0]
            return back is not None and dist_to + back <= turns_left - 2

        # A carried Core that can still uplink outranks banking and fighting:
        # plant at the end of turn t, uplink at the end of t + 3.
        pads = {tuple(pad) for pad in view.get("uplink_pads") or []}
        pad_dist = None
        if me.get("carrying_core") and pads:
            found = self._nearest(lambda c: c in pads)
            pad_dist = found[0] if found else None
        core_run = pad_dist is not None and pad_dist + 3 <= turns_left

        # Late game with cargo aboard: no fights, they would cost the bank.
        if core_run:
            fight = False
        elif me["cargo_units"] > 0:
            home_dist = self._distance(base)
            fight = home_dist is not None and home_dist + LATE_SLACK < turns_left
        else:
            fight = True

        # Rule 2: use the held item when it pays.
        if fight and can_use:
            action = self._use_item(item, me, enemies)
            if action:
                return action

        # Rule 3: melee an adjacent, unprotected enemy (weakest first).
        if fight and self.energy >= 5:
            run_target, run_length = self.attack_run
            adjacent = [
                e for e in enemies
                if not e.get("protected") and cheb(pos, (e["x"], e["y"])) == 1
                and not (ATTACK_CAP and e["id"] == run_target
                         and run_length >= ATTACK_CAP and e["hp"] > KILL_HP)
            ]
            if adjacent:
                target = min(adjacent, key=lambda e: (e["hp"], e["id"]))
                return Action.attack(target["id"])

        # Rule 4: shoot an unprotected enemy that is first on a clear line.
        if fight and self.energy >= 6:
            by_cell = {(e["x"], e["y"]): e for e in enemies}
            shots = []
            for name in DIRECTION_DELTAS:
                for cell in geometry.shot_path(self.walls, self.w, self.h, pos[0], pos[1], name, 4):
                    if cell in by_cell:
                        enemy = by_cell[cell]
                        if not enemy.get("protected"):
                            shots.append((enemy["hp"], enemy["id"], name))
                        break
            if shots:
                return Action.shoot(min(shots)[2])

        # Rule 5: collect what we stand on.
        if room and self.energy >= 2 and worth_collecting(pos, 0):
            for res in resources:
                if (res.get("x"), res.get("y")) == pos and isinstance(res.get("id"), str):
                    return Action.collect(res["id"])

        # Rule 6: bank when full, or when the match is about to end. Banking in
        # Overtime pays double, so a full hold that would bank just before it
        # waits next to base instead; in Overtime, any cargo goes home once
        # there is nothing left in sight to collect.
        if me["cargo_units"] > 0 and pos != base and not core_run:
            turn = view["turn"]
            overtime = view.get("overtime_turn", view["max_turns"])
            in_overtime = turn >= overtime
            dist = self._distance(base)
            if dist is not None and dist >= turns_left - 1:
                action = self._go(lambda c: c == base, urgent=True)
                if action:
                    return action
            if (not room or (in_overtime and not resources)) and not me.get("carrying_core"):
                if dist == 1 and 0 < overtime - turn <= OVERTIME_HOLD and self.energy >= 2:
                    return Action.defend()
                action = self._go(lambda c: c == base, urgent=True)
                if action:
                    return action

        # Rule 7: the Core. Carry it to a pad, pick it up if we can still
        # uplink in time, or defuse an enemy plant we can reach in time.
        core = view.get("visible_core") or {}
        core_cell = (core.get("x"), core.get("y"))
        status = core.get("status")
        if me.get("carrying_core") and pads:
            action = self._go(lambda c: c in pads, urgent=True)
            if action:
                return action
        elif status == "GROUND" and me.get("role") != "WARDEN" and pads:
            if core_cell == pos:
                if self.energy >= 2:
                    return Action.collect("CORE")
            else:
                from_core = self._bfs(core_cell, set())
                to_pad = min((from_core[p][0] for p in pads if p in from_core), default=None)
                to_core = self._distance(core_cell)
                # Only a short detour with an empty hold: long Core runs cost more
                # banked cargo and kills than the uplink pays (measured). Reach it,
                # collect, walk to a pad, then survive the 3-turn countdown.
                if (to_pad is not None and to_core is not None
                        and to_core <= CORE_DETOUR and me["cargo_units"] == 0
                        and to_core + to_pad + 4 <= turns_left):
                    action = self._go(lambda c: c == core_cell)
                    if action:
                        return action
        elif status == "PLANTED" and core.get("planted_by") != me["id"]:
            def in_range(c):
                return cheb(c, core_cell) <= 1
            if in_range(pos):
                return Action.defend()
            found = self._nearest(in_range)
            if found and found[0] <= (core.get("uplink_in") or 0):
                return self._move(found[1])

        # Rule 8: nearest visible resource.
        if room:
            cells = {
                (r["x"], r["y"]) for r in resources
                if (r["x"], r["y"]) != pos
                and worth_collecting((r["x"], r["y"]), self._distance((r["x"], r["y"])) or 99)
            }
            if cells:
                action = self._go(lambda c: c in cells)
                if action:
                    return action

        # Rule 9: kill tags, then crates worth opening.
        crates = [
            c for c in view.get("crates") or []
            if OPEN_CRATES and isinstance(c.get("id"), str)
            and (item is None or c.get("legendary"))
        ]
        if self.energy >= 2:
            for crate in crates:
                if (crate.get("x"), crate.get("y")) == pos:
                    return Action.collect(crate["id"])
        goals = set()
        for tag in view.get("tags") or []:
            cell = (tag.get("x"), tag.get("y"))
            dist = self._distance(cell)
            # Picked up at the end of a turn we end on it, before it expires.
            if cell != pos and dist is not None and dist <= (tag.get("turns_left") or 0):
                goals.add(cell)
        for crate in crates:
            cell = (crate.get("x"), crate.get("y"))
            dist = self._distance(cell)
            if cell != pos and dist is not None and dist <= CRATE_RANGE:
                goals.add(cell)
        if goals:
            action = self._go(lambda c: c in goals)
            if action:
                return action

        # Rule 10: patrol the inner arena.
        if self.waypoint is None:
            self.waypoint = min(
                range(len(WAYPOINTS)),
                key=lambda i: (cheb(WAYPOINTS[i], base), i),
            )
        for _ in range(len(WAYPOINTS)):
            target = self._open_cell_near(WAYPOINTS[self.waypoint])
            if target != pos:
                action = self._go(lambda c: c == target)
                if action:
                    return action
            self.waypoint = (self.waypoint + 1) % len(WAYPOINTS)

        return Action.defend()

    def _use_item(self, item, me, enemies):
        pos = self.pos
        targets = [e for e in enemies if not e.get("protected")]
        near = [e for e in enemies if cheb(pos, (e["x"], e["y"])) <= 2]
        if item == "RAILGUN":
            by_cell = {(e["x"], e["y"]): e for e in targets}
            best = None
            for name in DIRECTION_DELTAS:
                path = geometry.shot_path(self.walls, self.w, self.h, pos[0], pos[1], name, max(self.w, self.h))
                hit = [by_cell[c] for c in path if c in by_cell]
                if hit:
                    key = (-len(hit), min(e["hp"] for e in hit), name)
                    if best is None or key < best:
                        best = key
            if best:
                return Action.use_item(direction=best[2])
        elif item in ("AIRSTRIKE", "ORBITAL"):
            # Stay outside the blast even if we step toward it before it lands.
            safe = 3 if item == "AIRSTRIKE" else 4
            far = [e for e in targets if e.get("in_vision") and cheb(pos, (e["x"], e["y"])) >= safe]
            if far:
                target = min(far, key=lambda e: (e["hp"], e["id"]))
                return Action.use_item(x=int(target["x"]), y=int(target["y"]))
        elif item == "MEDPACK":
            if me["hp"] <= me.get("max_hp", 70) - 40:
                return Action.use_item()
        elif item == "RADAR":
            return Action.use_item()
        elif item in ("OVERSHIELD", "REAPER"):
            if near:
                return Action.use_item()
        return None

    # --------------------------------------------------------------- helpers

    def _danger_cells(self, bombs):
        cells = set()
        for bomb in bombs:
            r = bomb.get("blast_radius", 1)
            for x in range(bomb["x"] - r, bomb["x"] + r + 1):
                for y in range(bomb["y"] - r, bomb["y"] + r + 1):
                    cells.add((x, y))
        return cells

    def _open_cell_near(self, cell):
        # Some layouts wall over a waypoint; use the closest open cell instead.
        if cell not in self.walls:
            return cell
        open_cells = (
            (x, y) for x in range(self.w) for y in range(self.h)
            if (x, y) not in self.walls
        )
        return min(open_cells, key=lambda c: (cheb(c, cell), c))

    def _bfs(self, start, blocked):
        """{cell: (distance, first direction)} from start."""
        seen = {start: (0, None)}
        queue = deque([start])
        while queue:
            x, y = queue.popleft()
            dist, first = seen[(x, y)]
            for name, (dx, dy) in DIRECTION_DELTAS.items():
                nxt = (x + dx, y + dy)
                if nxt in seen or nxt in blocked:
                    continue
                if not geometry.step_open(self.walls, self.w, self.h, x, y, dx, dy):
                    continue
                seen[nxt] = (dist + 1, first or name)
                queue.append(nxt)
        return seen

    def _maps(self):
        # Strict avoids bots and blast zones; loose (walls only) is the backup.
        if self._strict is None:
            self._strict = self._bfs(self.pos, self.bots | self.danger)
            self._loose = self._bfs(self.pos, set())
        return self._strict, self._loose

    def _nearest(self, is_goal):
        """(distance, first direction) to the closest goal cell, or None."""
        for reach in self._maps():
            best = None
            for cell, (dist, first) in reach.items():
                if first and is_goal(cell) and (best is None or (dist, cell) < best[:2]):
                    best = (dist, cell, first)
            if best:
                return best[0], best[2]
        return None

    def _distance(self, target):
        for reach in self._maps():
            if target in reach:
                return reach[target][0]
        return None

    def _go(self, is_goal, urgent=False):
        """Action toward the closest goal: DASH when urgent and it saves a turn."""
        found = self._nearest(is_goal)
        if not found:
            return None
        dist, first = found
        if urgent and dist >= 2:
            landing = self._dash_landing(first)
            if landing:
                after = self._bfs(landing, self.bots | self.danger)
                rest = min((d for c, (d, _) in after.items() if is_goal(c)), default=None)
                if rest is not None and rest <= dist - 2:
                    return Action.ability(direction=first)
        return self._move(first)

    def _dash_landing(self, direction):
        """Landing cell if a DASH that way is ready, affordable and unblocked."""
        if not self.dash_ready or self.energy < DASH_MIN_ENERGY:
            return None
        dx, dy = DIRECTION_DELTAS.get(direction, (0, 0))
        x, y = self.pos
        mid, landing = (x + dx, y + dy), (x + 2 * dx, y + 2 * dy)
        if not (geometry.step_open(self.walls, self.w, self.h, x, y, dx, dy)
                and geometry.step_open(self.walls, self.w, self.h, mid[0], mid[1], dx, dy)):
            return None
        if mid in self.bots or landing in self.bots or landing in self.danger:
            return None
        return landing

    def _flee(self, threats):
        """Step (or DASH) to the open cell farthest from every threat."""
        cells = [(t["x"], t["y"]) for t in threats]

        def gap(cell):
            return min(cheb(cell, t) for t in cells)

        best = (gap(self.pos), 0, None, None)
        for name, (dx, dy) in DIRECTION_DELTAS.items():
            step = (self.pos[0] + dx, self.pos[1] + dy)
            if (geometry.step_open(self.walls, self.w, self.h, self.pos[0], self.pos[1], dx, dy)
                    and step not in self.bots and step not in self.danger):
                if (gap(step), 1) > best[:2]:
                    best = (gap(step), 1, "MOVE", name)
            landing = self._dash_landing(name)
            if landing and (gap(landing), 2) > best[:2]:
                best = (gap(landing), 2, "DASH", name)
        if best[2] == "DASH":
            return Action.ability(direction=best[3])
        if best[2] == "MOVE":
            return self._move(best[3])
        return None

    def _move(self, direction):
        dx, dy = DIRECTION_DELTAS.get(direction, (0, 0))
        nx, ny = self.pos[0] + dx, self.pos[1] + dy
        if self.energy >= 1 and (dx or dy) and 0 <= nx < self.w and 0 <= ny < self.h:
            return Action.move(direction)
        return Action.defend()
