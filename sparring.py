"""Chaos sparring partners: not good, just unpredictable.

check.py and conformance.py play your bot against these, and so can you:

    python play.py --vs sparring:ChaosShove --seeds 20

They do a bit of everything at random -- walk at you, hit you, shove you,
drop bombs, blink, call airstrikes, grab the Core, buy random gear -- so your
bot meets the situations that only show up when a rival does something odd.
They are deterministic, so a failure here reproduces exactly. They are not a
strategy and they are not the organizers' opponents; beating them means
nothing, crashing against them means a lot.
"""
import hashlib
import random

from vibe_sdk import DIRECTION_DELTAS, Action, Bot

COST = {"MOVE": 1, "ATTACK": 5, "SHOOT": 6, "SCAN": 8, "COLLECT": 2,
        "DEFEND": 2, "ABILITY": 10, "USE_ITEM": 4}


class ChaosBot(Bot):
    ABILITY = None

    def _rng(self, *parts):
        material = "|".join(str(p) for p in (self.id, *parts)).encode()
        return random.Random(int.from_bytes(hashlib.sha256(material).digest()[:8], "big"))

    def buy(self, shop):
        rng = self._rng("buy", shop["map"], shop["credits"])
        role = rng.choice([*shop["roles"], None])
        items, credits, kit = [], shop["credits"], False
        names = sorted(shop["prices"])
        rng.shuffle(names)
        for name in names:
            price = shop["prices"][name]
            if price > credits or (name.startswith("KIT_") and kit) or rng.random() < 0.4:
                continue
            items.append(name)
            credits -= price
            kit = kit or name.startswith("KIT_")
        return {"role": role, "items": items}

    def decide(self, view):
        me = view["self"]
        rng = self._rng(view["turn"], me["x"], me["y"], me["hp"], me["energy"])
        width, height = view["board"]["width"], view["board"]["height"]
        energy = me["energy"]

        def inside(x, y):
            return 0 <= x < width and 0 <= y < height

        def toward(x, y):
            dx = (x > me["x"]) - (x < me["x"])
            dy = (y > me["y"]) - (y < me["y"])
            for name, delta in DIRECTION_DELTAS.items():
                if delta == (dx, dy):
                    return name
            return None

        enemies = [e for e in view["visible_enemies"] if e["in_vision"]]
        adjacent = sorted(
            e["id"] for e in enemies
            if max(abs(e["x"] - me["x"]), abs(e["y"] - me["y"])) <= 1
        )
        options = []

        if adjacent and energy >= COST["ATTACK"]:
            options += [Action.attack(rng.choice(adjacent))] * 3
        if enemies and energy >= COST["SHOOT"]:
            target = rng.choice(enemies)
            direction = toward(target["x"], target["y"])
            if direction:
                options.append(Action.shoot(direction))

        ability = me["ability"]
        if ability and me["ability_ready"] and energy >= COST["ABILITY"]:
            if ability == "SHOVE" and adjacent:
                options += [Action.shove(rng.choice(adjacent))] * 2
            elif ability in ("DASH", "BLINK"):
                reach = 2 if ability == "DASH" else 3
                dirs = [name for name, (dx, dy) in sorted(DIRECTION_DELTAS.items())
                        if inside(me["x"] + dx * reach, me["y"] + dy * reach)]
                if dirs:
                    options.append(Action.ability(direction=rng.choice(dirs)))
            elif ability == "BOMB":
                if not any(b["mine"] and b["kind"] == "BOMB" for b in view["visible_bombs"]):
                    options.append(Action.ability())
            elif ability == "SHIELD" and enemies:
                options.append(Action.ability())

        item = me["item"]
        if item and energy >= COST["USE_ITEM"]:
            if item == "RAILGUN" and enemies:
                direction = toward(enemies[0]["x"], enemies[0]["y"])
                if direction:
                    options.append(Action.use_item(direction=direction))
            elif item in ("AIRSTRIKE", "ORBITAL"):
                spot = rng.choice(view["visible_enemies"]) if view["visible_enemies"] else None
                x, y = (spot["x"], spot["y"]) if spot else (rng.randrange(width), rng.randrange(height))
                options.append(Action.use_item(x=x, y=y))
            elif item in ("MEDPACK", "SMOKE", "RADAR", "OVERSHIELD", "REAPER"):
                options.append(Action.use_item())

        if energy >= COST["COLLECT"]:
            here = (me["x"], me["y"])
            core = view["visible_core"]
            if core["status"] == "GROUND" and (core["x"], core["y"]) == here and me["role"] != "WARDEN":
                options += [Action.collect("CORE")] * 3
            for crate in view["crates"]:
                if (crate["x"], crate["y"]) == here:
                    options.append(Action.collect(crate["id"]))
            if me["cargo_units"] < me["cargo_capacity"]:
                for res in view["visible_resources"]:
                    if (res["x"], res["y"]) == here:
                        options.append(Action.collect(res["id"]))

        if energy >= COST["DEFEND"] and rng.random() < 0.1:
            options.append(Action.defend())
        if energy >= COST["SCAN"] and rng.random() < 0.05:
            options.append(Action.scan())

        # Usually walk: at an enemy, at the Core, or anywhere.
        if energy >= COST["MOVE"]:
            goals = [(e["x"], e["y"]) for e in view["visible_enemies"]]
            core = view["visible_core"]
            if core["status"] in ("GROUND", "PLANTED"):
                goals.append((core["x"], core["y"]))
            goal = rng.choice(goals) if goals and rng.random() < 0.7 else None
            direction = toward(*goal) if goal else None
            if direction is None:
                direction = rng.choice([
                    name for name, (dx, dy) in sorted(DIRECTION_DELTAS.items())
                    if inside(me["x"] + dx, me["y"] + dy)
                ])
            options += [Action.move(direction)] * 3

        action = rng.choice(options) if options else Action.defend()
        if rng.random() < 0.08:
            action = action.taunt(rng.choice(["GG", "OOPS", "WATCH_THIS", "CATCH_ME"]))
        return action


class ChaosDash(ChaosBot):
    ABILITY = "DASH"


class ChaosBlink(ChaosBot):
    ABILITY = "BLINK"


class ChaosShove(ChaosBot):
    ABILITY = "SHOVE"


class ChaosBomb(ChaosBot):
    ABILITY = "BOMB"


class ChaosShield(ChaosBot):
    ABILITY = "SHIELD"


# The line-ups check.py and conformance.py use.
LINEUPS = (
    ("brawl", (ChaosShove, ChaosDash, ChaosBomb)),
    ("blast_zone", (ChaosBomb, ChaosBlink, ChaosShield)),
    ("pushers", (ChaosShove, ChaosShove, ChaosBlink)),
    ("mixed", (ChaosDash, ChaosShield, ChaosBot)),
)
