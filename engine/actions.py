from dataclasses import dataclass
from typing import Optional
from . import config
from .state import DIRECTIONS
from .board import chebyshev, in_bounds

@dataclass
class Action:
    type: str
    direction: Optional[str] = None
    target: Optional[str] = None
    x: Optional[int] = None
    y: Optional[int] = None
    say: Optional[str] = None

    def taunt(self, emote):
        self.say = emote
        return self

    @staticmethod
    def shove(target_bot_id):
        return Action(type="ABILITY", target=target_bot_id)

    @staticmethod
    def use_item(direction=None, x=None, y=None):
        return Action(type="USE_ITEM", direction=direction, x=x, y=y)

    @staticmethod
    def move(direction):
        return Action(type="MOVE", direction=direction)

    @staticmethod
    def attack(target_bot_id):
        return Action(type="ATTACK", target=target_bot_id)

    @staticmethod
    def shoot(direction):
        return Action(type="SHOOT", direction=direction)

    @staticmethod
    def collect(target_id):
        return Action(type="COLLECT", target=target_id)

    @staticmethod
    def scan():
        return Action(type="SCAN")

    @staticmethod
    def defend():
        return Action(type="DEFEND")

    @staticmethod
    def ability(direction=None, target=None):
        return Action(type="ABILITY", direction=direction, target=target)

class InvalidAction(Exception):
    pass

def _require_direction(action, what):
    if not isinstance(action.direction, str) or action.direction not in DIRECTIONS:
        raise InvalidAction(f"{what} requires one of {sorted(DIRECTIONS)}")
    return DIRECTIONS[action.direction]

def validate(action: Action, actor, state):
    if type(action) is not Action:
        raise InvalidAction("Action must be an Action object")
    if not isinstance(action.type, str) or action.type not in config.ACTION_COSTS:
        raise InvalidAction("Unknown or missing action type")

    cost = config.ACTION_COSTS[action.type]
    if actor.energy < cost:
        raise InvalidAction(f"Not enough energy for {action.type}")

    if action.type == "MOVE":
        dx, dy = _require_direction(action, "MOVE")
        if not in_bounds(actor.x + dx, actor.y + dy):
            raise InvalidAction("Move out of bounds")

    elif action.type == "SHOOT":
        _require_direction(action, "SHOOT")

    elif action.type == "ATTACK":
        if not isinstance(action.target, str):
            raise InvalidAction("Attack requires a target bot ID")
        if action.target == actor.id:
            raise InvalidAction("A bot cannot attack itself")
        target = state.bots.get(action.target)
        if target is None or not target.alive:
            raise InvalidAction("Attack target does not exist or is not on the board")
        if chebyshev(actor.x, actor.y, target.x, target.y) > config.ATTACK_RANGE:
            raise InvalidAction("Target out of attack range")

    elif action.type == "COLLECT":
        if not isinstance(action.target, str):
            raise InvalidAction("Collect requires a resource ID or CORE")
        if action.target == "CORE":
            core = state.core
            if actor.role == "WARDEN" and config.WARDEN_NO_CORE:
                raise InvalidAction("A WARDEN defends the Core; it cannot carry it")
            if core.status != "GROUND":
                raise InvalidAction(f"Core is not available to pick up ({core.status})")
            if chebyshev(actor.x, actor.y, core.x, core.y) > 0:
                raise InvalidAction("Not standing on the Core")
        elif action.target in state.crates:
            crate = state.crates[action.target]
            if chebyshev(actor.x, actor.y, crate.x, crate.y) > 0:
                raise InvalidAction("Not standing on the crate")
        else:
            res = state.resources.get(action.target)
            if res is None or res.collected:
                raise InvalidAction("Resource does not exist or already collected")
            if chebyshev(actor.x, actor.y, res.x, res.y) > 0:
                raise InvalidAction("Not standing on the resource")
            if actor.cargo_units >= actor.cargo_capacity:
                raise InvalidAction("Cargo hold is full; bank at base first")

    elif action.type == "USE_ITEM":
        if actor.item is None:
            raise InvalidAction("No item to use")
        if actor.item == "RAILGUN":
            _require_direction(action, "RAILGUN")
        elif actor.item in ("AIRSTRIKE", "ORBITAL"):
            if any(
                not isinstance(value, int) or isinstance(value, bool)
                for value in (action.x, action.y)
            ):
                raise InvalidAction(f"{actor.item} requires integer x and y")
            if not in_bounds(action.x, action.y):
                raise InvalidAction(f"{actor.item} target out of bounds")

    elif action.type == "ABILITY":
        if actor.ability not in config.ABILITIES:
            raise InvalidAction("Bot has no assigned ability")
        if state.turn < actor.ability_ready_turn:
            raise InvalidAction("Ability on cooldown")

        if actor.ability in ("DASH", "BLINK"):
            dx, dy = _require_direction(action, actor.ability)
            dist = config.DASH_DISTANCE if actor.ability == "DASH" else config.BLINK_DISTANCE
            if not in_bounds(actor.x + dx * dist, actor.y + dy * dist):
                raise InvalidAction(f"{actor.ability} destination out of bounds")

        elif actor.ability == "SHOVE":
            if not isinstance(action.target, str) or action.target == actor.id:
                raise InvalidAction("SHOVE requires an enemy bot ID")
            target = state.bots.get(action.target)
            if target is None or not target.alive:
                raise InvalidAction("SHOVE target does not exist or is not on the board")
            if chebyshev(actor.x, actor.y, target.x, target.y) > 1:
                raise InvalidAction("SHOVE target must be adjacent")

        elif actor.ability == "BOMB":
            live = sum(
                1 for bomb in state.bombs.values()
                if bomb.owner_id == actor.id and bomb.kind == "BOMB"
            )
            if live >= config.BOMB_MAX_ACTIVE_PER_BOT:
                raise InvalidAction(
                    f"Already has {live} live bomb(s); wait for detonation"
                )

    return True
