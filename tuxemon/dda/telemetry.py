"""Telemetry system for recording structured battle events in Tuxemon battles.

Telemetry events are structured according to the DDA Telemetry Event Contract.
Each event is represented as a `TelemetryEvent` and includes a turn number,
battle ID, event type, and payload data.
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import BoundedSemaphore
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from tuxemon.constants.paths import USER_RECORDING_DIR
from tuxemon.dda.types import (
    ActionData,
    ActionType,
    MonsterSnapshotData,
    OutcomesType,
    SnapshotPhase,
    TelemetryEvent,
    TelemetryEventType,
)

if TYPE_CHECKING:
    from tuxemon.combat.action_queue import EnqueuedAction
    from tuxemon.monster.monster import Monster


logger = logging.getLogger(__name__)


# Regular expressions for validating battle IDs and avoiding Windows device names.
_BATTLE_ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}")
_WINDOWS_DEVICE = re.compile(r"CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9]", re.I)


def sanitize_battle_id(battle_id: str) -> str:
    """Sanitize and validate the given battle ID."""
    if not _BATTLE_ID.fullmatch(battle_id) or _WINDOWS_DEVICE.fullmatch(battle_id):
        raise ValueError(f"Unsafe telemetry battle ID: {battle_id!r}")
    return battle_id


class TelemetryRecorder:
    """Collects battle observations without changing game state.

    Observations are recorded in memory and optionally passed to a callback.
    The recorder ensures that a final snapshot and battle-ended event are preserved
    if possible, and uses background export for persistence.

       * Does not modify game state.
       * Records events in memory and optionally calls a callback.
       * Ensures a final snapshot and battle-ended event are preserved if possible.
       * Does not write to disk directly; uses background export for persistence.
    """

    def __init__(
        self,
        battle_id: str | None = None,
        output_dir: Path | None = None,
        *,
        on_event: Callable[[TelemetryEvent], None] | None = None,
        max_events: int = 4096,
    ) -> None:
        self._battle_id = sanitize_battle_id(
            str(uuid4()) if battle_id is None else battle_id
        )
        if type(max_events) is not int or max_events < 3:
            raise ValueError("Telemetry requires room for at least three events.")
        self.output_dir = output_dir or USER_RECORDING_DIR / "telemetry"
        self.events: list[TelemetryEvent] = []
        self._max_events = max_events
        self._dropped_events = 0
        self.on_event = on_event
        self._ended_event: TelemetryEvent | None = None

    @property
    def battle_id(self) -> str:
        return self._battle_id

    def record(
        self,
        event_type: TelemetryEventType,
        turn: int,
        data: dict[str, Any],
    ) -> TelemetryEvent:
        """Record a single observation."""

        if turn < 0:
            raise ValueError("Turn must not be negative.")
        if event_type == TelemetryEventType.MONSTER_SNAPSHOT:
            phase = data.get("snapshot_phase")
            if phase not in SnapshotPhase.members():
                raise ValueError(f"Unknown snapshot phase: {phase!r}")
        if self._ended_event is not None:
            raise RuntimeError("Cannot record events after battle end.")

        event = TelemetryEvent(
            event_type=event_type,
            battle_id=self.battle_id,
            turn=turn,
            data=deepcopy(data),
        )
        self._store_event(event)
        self._notify_event(event)

        logger.info(
            "Recorded telemetry event: battle=%s event=%s turn=%s",
            self.battle_id,
            event.event_type,
            turn,
        )
        return deepcopy(event)

    def _store_event(self, event: TelemetryEvent) -> None:
        if event.event_type == TelemetryEventType.BATTLE_ENDED:
            if self._dropped_events:
                event.data["dropped_events"] = self._dropped_events
            self._ended_event = event
            self.events.append(event)
        else:
            # Keep slots for the final snapshot and the terminal event.
            final_snapshot = (
                event.event_type == TelemetryEventType.MONSTER_SNAPSHOT
                and event.data.get("snapshot_phase") == SnapshotPhase.FINAL
            )
            reserved = 1 if final_snapshot else 2
            if len(self.events) < self._max_events - reserved:
                self.events.append(event)
            else:
                self._dropped_events += 1
                if self._dropped_events == 1:
                    logger.warning(
                        "Telemetry buffer full for battle %s; JSONL will be incomplete",
                        self.battle_id,
                    )

    def _notify_event(self, event: TelemetryEvent) -> None:
        if self.on_event is not None:
            try:
                self.on_event(deepcopy(event))
            except Exception:
                logger.exception(
                    "Telemetry consumer failed: battle=%s event=%s turn=%s",
                    self.battle_id,
                    event.event_type,
                    event.turn,
                )

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
        *,
        aborted: bool = False,
    ) -> TelemetryEvent:
        """Record the end of a battle."""

        if self._ended_event is not None:
            return deepcopy(self._ended_event)
        if outcome not in OutcomesType.members():
            raise ValueError(f"Unknown battle outcome: {outcome!r}")

        data: dict[str, Any] = {"outcome": outcome}
        if aborted:
            if outcome != OutcomesType.UNKNOWN:
                raise ValueError("An interrupted battle has an unknown outcome.")
            data["aborted"] = True
        return self.record(TelemetryEventType.BATTLE_ENDED, turn, data)

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
        action_kind = ActionType.UNKNOWN

        for method_type, kind in (
            (Item, ActionType.ITEM),
            (Status, ActionType.STATUS),
            (Technique, ActionType.TECHNIQUE)
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
            user_is_player=self._is_user_player(action.user),
            method=self._entity_slug(method),
            action_kind=action_kind,
            target=self._entity_slug(action.target),
            target_instance_id=self._entity_id(action.target)
        )

        return self.record(
            TelemetryEventType.ACTION,
            turn, action_data.to_dict()
        )

    def record_switch(
        self,
        turn: int,
        incoming: Monster,
        outgoing: Monster | None = None,
    ) -> TelemetryEvent:
        """Records a monster entering play. Without an outgoing monster,
        the entry replaces a defeated one, so it is forced."""

        return self.record(
            TelemetryEventType.SWITCH,
            turn,
            {
                "incoming": self._entity_slug(incoming),
                "incoming_instance_id": self._entity_id(incoming),
                "incoming_owner_instance_id": self._user_owner_id(incoming),
                "incoming_is_player": self._is_user_player(incoming),
                "outgoing": self._entity_slug(outgoing),
                "outgoing_instance_id": self._entity_id(outgoing),
                "forced": outgoing is None or outgoing.is_fainted,
            },
        )

    def record_monsters(
        self,
        turn: int,
        monsters: list[Monster],
        snapshot_phase: SnapshotPhase = SnapshotPhase.DECISION,
    ) -> TelemetryEvent:
        """Records the state of all monsters in the battle."""

        return self.record(
            event_type=TelemetryEventType.MONSTER_SNAPSHOT,
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

        if not self.events:
            return path

        path.parent.mkdir(parents=True, exist_ok=True)
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
            temporary_path = None
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

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
    def _is_user_player(user: Any) -> bool | None:
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


class TelemetryExporter:
    """Write completed battles off the game loop, with a bounded backlog.

    Ensures that telemetry export does not block the main game loop and handles
    retries and queue management for completed battles.

    * Uses a bounded semaphore to limit concurrent export jobs.
    * Retries failed exports once before logging an error.
    * Provides a `close` method to wait for all pending exports to complete.
    """

    def __init__(self) -> None:
        self._slots = BoundedSemaphore(8)
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="battle-telemetry"
        )

    def submit(self, recorder: TelemetryRecorder) -> None:
        """Submit a telemetry recorder for background export.

        Raises a `RuntimeError` if the export queue is full.
        """

        if not self._slots.acquire(blocking=False):
            raise RuntimeError(f"Telemetry export queue full: {recorder.battle_id}")
        try:
            job = self._executor.submit(self._write, recorder)
        except RuntimeError:
            self._slots.release()
            raise
        job.add_done_callback(
            lambda completed: self._export_done(completed, recorder.battle_id)
        )

    def _export_done(self, job: Future[None], battle_id: str) -> None:
        """Callback invoked when a background export job completes.

        Releases the semaphore slot and logs any errors encountered during export.
        """
        self._slots.release()
        if error := job.exception():
            logger.error(
                "Could not export battle telemetry: %s", battle_id, exc_info=error
            )

    @staticmethod
    def _write(recorder: TelemetryRecorder) -> None:
        try:
            recorder.write()
        except OSError:
            logger.warning(
                "Retrying telemetry export for battle %s",
                recorder.battle_id,
                exc_info=True,
            )
            recorder.write()

    def close(self) -> None:
        self._executor.shutdown(wait=True)
