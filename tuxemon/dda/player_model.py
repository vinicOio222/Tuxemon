from collections import deque
from copy import deepcopy
from typing import Any

from tuxemon.dda.indicators import calculate_combat_indicators
from tuxemon.dda.telemetry import TelemetryEvent, TelemetryEventType


class PlayerModel:
    """Represents the player's model in the DDA system."""
    
    def __init__(self, window: int = 10) -> None:
        if type(window) is not int or window < 1:
            raise ValueError("Window size must be at least 1.")
        self._recent: deque[dict[str, Any]] = deque(maxlen=window)
        self.reset()
        
    def reset(self) -> None:
        """Reset the player's model state."""
        self._recent.clear()
        self._battle_id: str | None = None
        self._baseline: TelemetryEvent | None = None
        self._fainted: set[str] = set()
        self._current: dict[str, Any] = {}
        self._closed = True
        
    def observe(self, event: TelemetryEvent) -> None:
        """Observe a new telemetry event and update the player's model state accordingly."""
        
        if event.event_type == TelemetryEventType.BATTLE_STARTED:
            if event.battle_id == self._battle_id or any(
                row["battle_id"] == event.battle_id for row in self._recent
            ):
                return
            self._battle_id = event.battle_id
            self._baseline = None
            self._fainted.clear()
            self._current = {}
            self._closed = False
            return
        
        if self._closed or event.battle_id != self._battle_id:
            return
        if event.turn < self._current.get("turns", 0):
            raise ValueError("Events must arrive in chronological order.")
        
        # Process the event based on its type and update the player's model state accordingly.
        if event.event_type == TelemetryEventType.MONSTER_SNAPSHOT:
            if self._baseline is None:
                if event.turn != 1 or event.data["snapshot_phase"] != "decision":
                    raise ValueError("The first snapshot must be turn 1 decision.")
                self._baseline = deepcopy(event)
            
            baseline = self._baseline
            combat = calculate_combat_indicators(baseline, event)
            initially_fit = {
                member["instance_id"]: member["is_player"]
                for member in baseline.data["monsters"] if not member["fainted"]
            }
            self._fainted.update(
                member["instance_id"] for member in event.data["monsters"]
                if member["fainted"] and member["instance_id"] in initially_fit
            )
            self._current = {
                "battle_id": event.battle_id, "turns": event.turn,
                "combat": combat, "health_phase": event.data["snapshot_phase"],
                "player_fainted": sum(initially_fit[key] for key in self._fainted),
                "opponents_fainted": sum(not initially_fit[key] for key in self._fainted),
            }
        elif event.event_type == TelemetryEventType.BATTLE_ENDED:
            outcome = event.data["outcome"]
            if outcome not in {"win", "loss", "draw", "escaped"} or not self._current:
                raise ValueError("Missing observations or invalid outcome.")
            self._current.update(outcome=outcome, turns=event.turn)
            self._recent.append(deepcopy(self._current))
            self._closed = True
            
    def get_indicators(self) -> dict[str, Any]:
        return {
            "current": deepcopy(self._current),
            "recent": tuple(deepcopy(self._recent)),
            "sample_size": len(self._recent),
            "outcomes": {
                outcome: sum(row["outcome"] == outcome for row in self._recent)
                for outcome in ("win", "loss", "draw", "escaped")
            },
            "average_turns": (
                sum(row["turns"] for row in self._recent) / len(self._recent)
                if self._recent else None
            )
        }
