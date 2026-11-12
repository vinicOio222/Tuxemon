from enum import Enum
from dataclasses import asdict, dataclass, field
from typing import Any


# Enums
class SnapshotPhase(str, Enum):
    """Enumeration of snapshot phases in a battle."""
    
    DECISION = "decision"
    BEFORE_REWARDS = "before_rewards"
    AFTER_REWARDS = "after_rewards"
    FINAL = "final"
    
    @staticmethod
    def members() -> set[str]:
        return {phase.value for phase in SnapshotPhase}
    

class TelemetryEventType(str, Enum):
    """Enumeration of telemetry event types."""
    
    ACTION = "action"
    BATTLE_ENDED = "battle_ended"
    BATTLE_STARTED = "battle_started"
    MONSTER_SNAPSHOT = "monster_snapshot"
    
    @staticmethod
    def members() -> set[str]:
        return {
            event_type.value
            for event_type in TelemetryEventType
        }


class OutcomesType(str, Enum):
    """Enumeration of possible battle outcomes."""
    
    WIN = "win"
    LOSS = "loss"
    DRAW = "draw"
    ESCAPED = "escaped"
    
    @staticmethod
    def members() -> set[str]:
        return {outcome.value for outcome in OutcomesType}


# Data Classes
@dataclass(frozen=True)
class ActionData:
    """A structured representation of an action taken by a monster."""

    execution: str
    user: str | None
    user_instance_id: str | None
    user_owner_instance_id: str | None
    user_is_player: bool | None
    method: str | None
    action_kind: str
    target: str | None
    target_instance_id: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MonsterSnapshotData:
    """A structured representation of a monster's state."""
    
    owner_slug: str | None
    owner_instance_id: str | None
    is_player: bool | None
    instance_id: str
    slug: str
    level: int
    current_hp: int
    max_hp: int
    hp_ratio: float
    fainted: bool
    statuses: list[str] = field(..., default_factory=list)
    
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BattleRecord:
    """A record of a battle's outcome and relevant statistics."""
    
    battle_id: str
    turns: int
    outcome: str | None
    health_phase: str
    player_fainted: int
    opponents_fainted: int
    outcome: str | None = None
    
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
    

@dataclass(frozen=True)
class PlayerIndicators:
    """Aggregated indicators of the player's performance over recent battles."""
    
    current: BattleRecord | None
    recent: tuple[BattleRecord, ...] = field(..., default_factory=tuple)
    sample_size: int
    outcomes: dict[str, int] = field(..., default_factory=dict)
    average_turns: float | None
    
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
