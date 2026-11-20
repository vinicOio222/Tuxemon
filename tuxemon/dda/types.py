"""Types and data structures for the Tuxemon battle telemetry system.

This module defines enums and data classes used to represent various aspects of the battle telemetry system,
including snapshot phases, telemetry event types, outcomes, action types, and structured representations
of actions, monster snapshots, battle records, and telemetry events.

All enums provide a `members` static method that returns the set of valid string values for that enum.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tuxemon.dda.indicators import CombatIndicators


TELEMETRY_SCHEMA_VERSION: str = "0.1.1"


# Enums
# Enums for snapshot phases, telemetry event types, outcomes, and action types.
# --------------------------------------------------
class SnapshotPhase(str, Enum):
    DECISION = "decision"
    BEFORE_REWARDS = "before_rewards"
    AFTER_REWARDS = "after_rewards"
    FINAL = "final"

    @staticmethod
    def members() -> set[str]:
        return {phase.value for phase in SnapshotPhase}


class TelemetryEventType(str, Enum):
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
    WIN = "win"
    LOSS = "loss"
    DRAW = "draw"
    ESCAPED = "escaped"
    UNKNOWN = "unknown"

    @staticmethod
    def members() -> set[str]:
        return {outcome.value for outcome in OutcomesType}


class ActionType(str, Enum):
    ITEM = "item"
    STATUS = "status"
    TECHNIQUE = "technique"
    UNKNOWN = "unknown"

    @staticmethod
    def members() -> set[str]:
        return {action_type.value for action_type in ActionType}


# Data Classes
# Data classes for representing actions, monster snapshots, battle records, and telemetry events.
# --------------------------------------------------
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


@dataclass(frozen=True)
class PlayerIndicators:
    """Aggregated indicators of the player's performance over recent battles."""

    current: BattleRecord | None = None
    sample_size: int
    average_turns: float | None = None
    recent: tuple[BattleRecord, ...] = field(default_factory=tuple)
    outcomes: dict[str, int] = field(default_factory=dict)
    unavailable_reason: str | None = None


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
