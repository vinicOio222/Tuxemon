from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tuxemon.dda.indicators import CombatIndicators


TELEMETRY_SCHEMA_VERSION = "1.0.0"


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
    SWITCH = "switch"
    
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
    UNKNOWN = "unknown"
    
    @staticmethod
    def members() -> set[str]:
        return {outcome.value for outcome in OutcomesType}


class ActionType(str, Enum):
    """Enumeration of action types."""

    ITEM = "item"
    STATUS = "status"
    TECHNIQUE = "technique"
    UNKNOWN = "unknown"

    @staticmethod
    def members() -> set[str]:
        return {action_type.value for action_type in ActionType}


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
    statuses: list[str] = field(default_factory=list)
    
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BattleRecord:
    """A record of a battle's outcome and relevant statistics."""
    
    battle_id: str
    turns: int
    health_phase: str
    combat: CombatIndicators
    player_fainted: int
    opponents_fainted: int
    outcome: str | None = None
    
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
    

@dataclass(frozen=True)
class PlayerIndicators:
    """Aggregated indicators of the player's performance over recent battles."""
    
    current: BattleRecord | None
    sample_size: int
    average_turns: float | None
    recent: tuple[BattleRecord, ...] = field(default_factory=tuple)
    outcomes: dict[str, int] = field(default_factory=dict)
    
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TelemetryEvent:
    """Represents a telemetry event in the battle system."""

    event_type: TelemetryEventType
    battle_id: str
    turn: int
    data: dict[str, Any]
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    schema_version: str = TELEMETRY_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        event = asdict(self)
        event["event_type"] = self.event_type.value
        event["timestamp"] = self.timestamp.isoformat()
        return event
