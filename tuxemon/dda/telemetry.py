from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from dataclasses import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from tuxemon.combat.action_queue import EnqueuedAction
from tuxemon.constants.paths import USER_RECORDING_DIR
from tuxemon.monster.monster import Monster


@dataclass(frozen=True)
class TelemetryEvent:
    """A single structred observation from a battle."""
    
    event_type: str
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
        battle_id: str,
        output_dir: Path = USER_RECORDING_DIR,
    ):
        self.battle_id = battle_id
        self.output_dir = output_dir
        self.events: list[TelemetryEvent] = []
         
    def record(
        self,
        event_type: str,
        turn: int,
        data: dict[str, Any]
    ) -> TelemetryEvent:
        """Record a single observation."""
        event = TelemetryEvent(
            event_type=event_type,
            battle_id=self.battle_id,
            turn=turn,
            timestamp=datetime.now(timezone.utc).isoformat(),
            data=data,
        )
        self.events.append(event)
        return event
    
    def record_battle_start(
        self,
        turn: int,
        combat_type: str,
        battle_mode: str
    ) -> TelemetryEvent:
        """Record the start of a battle."""
        return self.record(
            "battle_started",
            turn,
            {"combat_type:": combat_type, "battle_mode": battle_mode},
        )
        
    def record_battle_end(
        self,
        turn: int,
        outcome: str,
    ) -> TelemetryEvent:
        return self.record(
            "battle_ended",
            turn,
            {"outcome": outcome}
        )
    
    def record_action(
        self,
        turn: int,
        action: EnqueuedAction
    ) -> TelemetryEvent:
        """Records an action taken by a monster."""
        method = action.method
        user = action.user
        return self.record(
            "action",
            turn,
            {
                "user": self._entity_slug(user),
                "method": self._entity_slug(method),
                "target": self._entity_slug(action.target)
            }
        )
        
    def record_monsters(
        self,
        turn: int,
        monsters: list[Monster]
    ) -> TelemetryEvent:
        """Records the state of all monsters in the battle."""
        return self.record(
            event_type="monster_snapshot",
            turn=turn,
            data={
                "monsters": [
                    self._monster_data(monster) for monster in monsters
                ]
            }
        )
        
    def write(self, output_path: Path | None = None) -> Path:
        """Write the recorded events to a JSON file."""
        path = output_path or self.output_dir / f"{self.battle_id}.jsonl"
        
        if path is None:
            telemetry_dir = USER_RECORDING_DIR / "telemetry"
            path = telemetry_dir / f"{self.battle_id}.jsonl"
            
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
        return {
           "instance_id": monster.instance_id,
           "slug": monster.slug, 
           "level": monster.level,
           "current_hp": monster.current_hp,
           "max_hp": monster.max_hp,
           "hp_ratio": monster.hp_ratio,
           "fainted": monster.is_fainted,
           "statuses": [
                status.slug
                for status in monster.status.get_statuses()
            ],  
        }
    