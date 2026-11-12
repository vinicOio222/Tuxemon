"""Telemetry system for recording structured battle events in Tuxemon battles."""

from __future__ import annotations

import json
import logging
import os

from collections.abc import Callable
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from tuxemon.constants.paths import USER_RECORDING_DIR
from tuxemon.dda.types import (
    ActionData,
    MonsterSnapshotData,
    TelemetryEvent,
    SnapshotPhase,
    TelemetryEventType,
)

if TYPE_CHECKING:
    from tuxemon.combat.action_queue import EnqueuedAction
    from tuxemon.monster.monster import Monster


logger = logging.getLogger(__name__)


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
        self._ended_event: TelemetryEvent | None = None
    
    def record(
        self,
        event_type: TelemetryEventType,
        turn: int,
        data: dict[str, Any]
    ) -> TelemetryEvent:
        """Record a single observation."""
        
        if turn < 0:
            raise ValueError("Turn must not be negative.")
        if event_type == TelemetryEventType.MONSTER_SNAPSHOT.value:
            phase = data.get("snapshot_phase")
            if phase not in SnapshotPhase.members():
                raise ValueError(f"Unknown snapshot phase: {phase!r}")
        if self._ended_event is not None:
            raise RuntimeError("Cannot record events after battle end.")

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
            TelemetryEventType.BATTLE_STARTED.value,
            turn,
            {"combat_type": combat_type, "battle_mode": battle_mode},
        )
        
    def record_battle_end(
        self,
        turn: int,
        outcome: str,
    ) -> TelemetryEvent:
        """Record the end of a battle."""
        
        if self._ended_event is not None:
            return deepcopy(self._ended_event)
        if outcome != "win":
            raise ValueError("Only the win outcome is supported.")

        event = self.record(
            TelemetryEventType.BATTLE_ENDED.value,
            turn,
            {"outcome": outcome}
        )
        self._ended_event = event
        return deepcopy(event)
    
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
        
        # Create a structured representation of the action data.
        action_data = ActionData(
            execution="attempt",
            user=self._entity_slug(action.user),
            user_instance_id=self._entity_id(action.user),
            user_owner_instance_id=self._user_owner_id(action.user),
            user_is_player=self._user_is_player(action.user),
            method=self._entity_slug(method),
            action_kind=action_kind,
            target=self._entity_slug(action.target),
            target_instance_id=self._entity_id(action.target)
        )
        
        return self.record(
            TelemetryEventType.ACTION.value,
            turn, action_data.to_dict()
        )
        
    def record_monsters(
        self,
        turn: int,
        monsters: list[Monster],
        snapshot_phase: str = "decision",
    ) -> TelemetryEvent:
        """Records the state of all monsters in the battle."""
        
        return self.record(
            event_type=TelemetryEventType.MONSTER_SNAPSHOT.value,
            turn=turn,
            data={
                "snapshot_phase": snapshot_phase,
                "monsters": [
                    self._get_monster_data(monster)
                    for monster in monsters
                ]
            }
        )
        
    def write(self, output_path: Path | None = None) -> Path:
        """Append pending events to a JSONL file atomically."""
        
        path = output_path or self.output_dir / f"{self.battle_id}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)

        if not self.events:
            return path

        # Creates a temporary file to avoid partial writes in case of errors.
        # The temporary file is then renamed to the target path atomically.
        temporary_path: Path | None = None
        
        try:
            with NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                if path.exists():
                    with path.open("r", encoding="utf-8") as existing:
                        for line in existing:
                            temporary.write(line)
                for event in self.events:
                    temporary.write(
                        json.dumps(event.to_dict(), ensure_ascii=True) + "\n"
                    )
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, path)
        except Exception:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise

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
    def _user_owner_id(user: Any) -> str | None:
        """Return the trainer ID associated with an action user."""
        
        owner = getattr(user, "owner", None)
        if owner is not None:
            return TelemetryRecorder._entity_id(owner)
        return TelemetryRecorder._entity_id(user)

    @staticmethod
    def _user_is_player(user: Any) -> bool | None:
        """Return the team identity associated with an action user."""
        
        owner = getattr(user, "owner", None)
        if owner is not None:
            return getattr(owner, "is_player", None)
        return getattr(user, "is_player", None)
        
    @staticmethod
    def _get_monster_data(monster: Monster) -> dict[str, Any]:
        """Return a structured representation of a monster."""
        
        # Get the owner of the monster, if it exists.
        owner = monster.owner
        
        return MonsterSnapshotData(
            owner_instance_id=str(owner.instance_id) if owner is not None else None,
            owner_slug=owner.slug if owner is not None else None,
            is_player=owner.is_player if owner is not None else None,
            instance_id=str(monster.instance_id),
            slug=monster.slug,
            level=monster.level,
            current_hp=monster.current_hp,
            max_hp=monster.hp,
            hp_ratio=monster.hp_ratio,
            fainted=monster.is_fainted,
            statuses=[
                status.slug
                for status in monster.status.get_statuses()
            ],
        ).to_dict()
