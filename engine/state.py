from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any

from .geometry import DIRECTIONS

@dataclass
class BotState:
    id: str
    x: int
    y: int
    base_x: int
    base_y: int
    hp: int
    energy: int
    score: int = 0
    alive: bool = True
    carrying_core: bool = False
    defending: bool = False
    scanning: bool = False
    core_captured: bool = False
    uplinks: int = 0
    defuses: int = 0
    resources_collected: int = 0
    cargo_value: int = 0
    cargo_units: int = 0
    banked_value: int = 0

    kills: int = 0
    deaths: int = 0
    assists: int = 0
    streak: int = 0
    best_streak: int = 0
    respawn_turn: Optional[int] = None
    protected_until: int = 0
    loud_until: int = 0
    recent_damage: Dict[str, int] = field(default_factory=dict)
    last_kill_of: Dict[str, int] = field(default_factory=dict)

    item: Optional[str] = None
    radar_until: int = 0
    overshield_until: int = 0
    reaper_until: int = 0

    role: Optional[str] = None
    max_hp: int = 70
    cargo_capacity: int = 4
    respawn_delay: int = 3
    cooldown_turns: int = 6
    vision_bonus: int = 0
    loadout: List[str] = field(default_factory=list)

    last_killed_by: Optional[str] = None
    nemesis: Optional[str] = None
    series_streak: int = 0
    shoved_by: Optional[str] = None
    shoved_turn: int = -99

    ability: Optional[str] = None
    ability_ready_turn: int = 0
    shielded: bool = False

    @property
    def eliminations(self):
        return self.kills

@dataclass
class Resource:
    id: str
    x: int
    y: int
    value: int
    collected: bool = False
    loot: bool = False

@dataclass
class CoreObject:
    x: int
    y: int
    carried_by: Optional[str] = None
    active: bool = False
    spawn_turn: int = 0
    planted_by: Optional[str] = None
    uplink_turn: Optional[int] = None
    defuse_progress: int = 0
    defuser: Optional[str] = None
    spawns: int = 0

    @property
    def status(self):
        if not self.active:
            return "INACTIVE"
        if self.planted_by is not None:
            return "PLANTED"
        if self.carried_by is not None:
            return "CARRIED"
        return "GROUND"

    @property
    def extracted(self):
        return not self.active

@dataclass
class Bomb:
    id: str
    owner_id: str
    x: int
    y: int
    detonates_turn: int
    kind: str = "BOMB"
    radius: int = 1
    damage: int = 45
    edge_damage: int = 25
    global_visible: bool = False

@dataclass
class Crate:
    id: str
    x: int
    y: int
    item: str

@dataclass
class Tag:
    id: str
    x: int
    y: int
    victim: str
    killers: List[str]
    expires_turn: int

@dataclass
class Smoke:
    id: str
    owner_id: str
    x: int
    y: int
    radius: int
    expires_turn: int

    def covers(self, x, y):
        return max(abs(x - self.x), abs(y - self.y)) <= self.radius

@dataclass
class GameState:
    turn: int
    max_turns: int
    width: int
    height: int
    bots: Dict[str, BotState]
    resources: Dict[str, Resource]
    core: CoreObject
    seed: int = 0
    walls: frozenset = frozenset()
    layout: str = "open"
    pads: tuple = ()
    bombs: Dict[str, Bomb] = field(default_factory=dict)
    crates: Dict[str, Crate] = field(default_factory=dict)
    smokes: Dict[str, Smoke] = field(default_factory=dict)
    tags: Dict[str, Tag] = field(default_factory=dict)
    crown_holder: Optional[str] = None
    legendary: Optional[Dict[str, Any]] = None
    series: Dict[str, Any] = field(default_factory=dict)
    loadouts: Dict[str, Any] = field(default_factory=dict)
    kills_this_turn: Dict[str, int] = field(default_factory=dict)
    item_pool: tuple = ()
    crate_schedule: List[int] = field(default_factory=list)
    active_events: Dict[str, int] = field(default_factory=dict)
    event_schedule: List[tuple] = field(default_factory=list)
    supply_schedule: List[int] = field(default_factory=list)
    events: List[Dict[str, Any]] = field(default_factory=list)
    first_blood_taken: bool = False
    turn_prepared: bool = False

    def alive_bots(self):
        return [b for b in self.bots.values() if b.alive]
