"""Telemetry system for recording structured battle events in Tuxemon battles."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from tuxemon.constants.paths import USER_RECORDING_DIR

if TYPE_CHECKING:
    from tuxemon.combat.action_queue import EnqueuedAction
    from tuxemon.monster.monster import Monster


logger = logging.getLogger(__name__)


class TelemetryEventType(str,Enum):
    """Types of telemetry events.
    
    Attributes:
        BATTLE_STARTED: Indicates the start of a battle.
        BATTLE_ENDED: Indicates the end of a battle.
        ACTION: Represents an action taken by a monster.
        MONSTER_SNAPSHOT: Represents a snapshot of a monster's state.
    """
    
    BATTLE_STARTED = "battle_started"
    BATTLE_ENDED = "battle_ended"
    ACTION = "action"
    MONSTER_SNAPSHOT = "monster_snapshot"


@dataclass(frozen=True)
class TelemetryEvent:
    """A single structured observation from a battle.
    
    Attributes:
        event_type: The type of the event.
        battle_id: The unique identifier of the battle.
        turn: The turn number when the event occurred.
        timestamp: The timestamp of the event in ISO 8601 format.
        data: Additional data associated with the event.
    """
    
    event_type: TelemetryEventType
    battle_id: str
    turn: int
    timestamp: str
    data: dict[str, Any]
    
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
    
    
class TelemetryRecorder:
    """Collects battle observations without changing game state."""
    
    def __init__(
        self,
        battle_id: str | None = None,
        output_dir: Path | None = None,
        *,
        on_event: Callable[[TelemetryEvent], None] | None = None
    ) -> None:
        self.battle_id = battle_id or str(uuid4())
        self.output_dir = output_dir or USER_RECORDING_DIR / "telemetry"
        self.events: list[TelemetryEvent] = []
        self.on_event = on_event
    
    def record(
        self,
        event_type: TelemetryEventType,
        turn: int,
        data: dict[str, Any]
    ) -> TelemetryEvent:
        """Record a single observation."""
        event = TelemetryEvent(
            event_type=event_type,
            battle_id=self.battle_id,
            turn=turn,
            timestamp=datetime.now(timezone.utc).isoformat(),
            data=deepcopy(data),
        )
        self.events.append(event)
        
        if self.on_event is not None:
            try:
                self.on_event(deepcopy(event))
            except Exception:
                logger.exception(
                    "Telemetry consumer failed: battle=%s event=%s turn=%s",
                    self.battle_id,
                    event.event_type,
                    turn,
                )
        
        return deepcopy(event)
    
    def record_battle_start(
        self,
        turn: int,
        combat_type: str,
        battle_mode: str
    ) -> TelemetryEvent:
        """Record the start of a battle."""
        return self.record(
            TelemetryEventType.BATTLE_STARTED,
            turn,
            {"combat_type": combat_type, "battle_mode": battle_mode},
        )
        
    def record_battle_end(
        self,
        turn: int,
        outcome: str,
    ) -> TelemetryEvent:
        return self.record(
            TelemetryEventType.BATTLE_ENDED,
            turn,
            {"outcome": outcome}
        )
    
    def record_action(
        self,
        turn: int,
        action: EnqueuedAction
    ) -> TelemetryEvent:
        """Records an action taken by a monster."""
        
        from tuxemon.item.item import Item
        from tuxemon.status.status import Status
        from tuxemon.technique.technique import Technique
        
        method = action.method
        action_kind = "unknown"
        
        for method_type, kind in (
            (Item, "item"),
            (Status, "status"),
            (Technique, "technique")
        ):
            if isinstance(method, method_type):
                action_kind = kind
                break
            
        return self.record(
            TelemetryEventType.ACTION,
            turn,
            {
                "user": self._entity_slug(action.user),
                "user_instance_id": self._entity_id(action.user),
                "method": self._entity_slug(method),
                "action_kind": action_kind,
                "target": self._entity_slug(action.target),
                "target_instance_id": self._entity_id(action.target)
            }
        )
        
    def record_monsters(
        self,
        turn: int,
        monsters: list[Monster],
        snapshot_phase: str = "decision",
    ) -> TelemetryEvent:
        """Records the state of all monsters in the battle."""
        return self.record(
            event_type=TelemetryEventType.MONSTER_SNAPSHOT,
            turn=turn,
            data={
                "snapshot_phase": snapshot_phase,
                "monsters": [
                    self._monster_data(monster) for monster in monsters
                ]
            }
        )
        
    def write(self, output_path: Path | None = None) -> Path:
        """Write the recorded events to a JSON file."""
        
        path = output_path or self.output_dir / f"{self.battle_id}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        
        with path.open("w", encoding="utf-8") as f:
            for event in self.events:
                f.write(
                    json.dumps(
                        event.to_dict(),
                        ensure_ascii=True
                    )
                    + "\n"
                )
        
        self.events.clear()
        return path
    
    @staticmethod
    def _entity_id(entity: Any) -> str | None:
        """Return the instance ID of an entity as a string, if available."""
        instance_id = getattr(entity, "instance_id", None)
        return str(instance_id) if instance_id is not None else None

    @staticmethod
    def _entity_slug(entity: Any) -> str | None:
        """Return a string representation of an entity."""
        
        if entity is None:
            return None
        
        return getattr(
            entity,
            "slug",
            getattr(entity, "name", None)
        )
        
    @staticmethod
    def _monster_data(monster: Monster) -> dict[str, Any]:
        """Return a dictionary representation of a monster."""
        
        owner = monster.owner
        
        return {
            "owner_instance_id": str(owner.instance_id) if owner is not None else None,
            "owner_slug": owner.slug if owner is not None else None,
            "is_player": owner.is_player if owner is not None else None,
            "instance_id": str(monster.instance_id),
            "slug": monster.slug, 
            "level": monster.level,
            "current_hp": monster.current_hp,
            "max_hp": monster.hp,
            "hp_ratio": monster.hp_ratio,
            "fainted": monster.is_fainted,
            "statuses": [
                status.slug
                for status in monster.status.get_statuses()
            ],  
        }
    