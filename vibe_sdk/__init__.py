from .bot import Bot
from engine.actions import Action
from engine import ACTION_PROTOCOL_VERSION
from engine import geometry
from engine.config import ABILITIES as _ABILITIES
from engine.config import ROLES as _ROLES
from engine.config import SHOP as _SHOP
from engine.state import DIRECTIONS as _DIRECTIONS

ABILITIES = tuple(sorted(_ABILITIES))
ROLES = tuple(_ROLES)
SHOP = dict(_SHOP)
DIRECTIONS = tuple(_DIRECTIONS)
DIRECTION_DELTAS = dict(_DIRECTIONS)

__all__ = [
    "ABILITY_PROTOCOL_VERSION",
    "ABILITIES",
    "ACTION_PROTOCOL_VERSION",
    "Action",
    "Bot",
    "DIRECTIONS",
    "DIRECTION_DELTAS",
    "ROLES",
    "SHOP",
    "geometry",
]

ABILITY_PROTOCOL_VERSION = "1.0"
