"""Player model for the Tuxemon Dynamic Difficulty Adjustment (DDA) system.

This module defines the PlayerModel class, which maintains a sliding window of recent battles,
tracks the player's performance, and updates combat indicators based on observed telemetry events.
"""

import logging
from collections import deque
from copy import deepcopy
from dataclasses import replace

from tuxemon.dda.indicators import calculate_combat_indicators
from tuxemon.dda.types import (
    BattleRecord,
    OutcomesType,
    PlayerIndicators,
    SnapshotPhase,
    TelemetryEvent,
    TelemetryEventType,
)

logger = logging.getLogger(__name__)


class PlayerModel:
    """Represents the player's model in the DDA system.

    The model maintains a sliding window of recent battles and tracks the player's
    performance, including fainted monsters and combat indicators.

    * Maintains a sliding window of recent battles.
    * Tracks fainted monsters and combat indicators.
    * Ensures events are processed in chronological order.
    * Handles battle start, monster snapshots, and battle end events.
    """

    def __init__(self, window: int = 10) -> None:
        if type(window) is not int or window < 1:
            raise ValueError("Window size must be at least 1.")

        self._recent: deque[BattleRecord] = deque(maxlen=window)
        self.reset()

    def reset(self) -> None:
        """Reset the player's model state."""
        self._recent.clear()
        self._battle_id: str | None = None
        self._baseline: TelemetryEvent | None = None
        self._fainted: set[str] = set()
        self._current: BattleRecord | None = None
        self._unavailable_reason: str | None = None
        self._roster_changed = False
        self._last_turn = 0
        self._closed = True

    def _mark_unavailable(self, reason: str | None) -> None:
        self._current = None
        self._unavailable_reason = reason
        logger.error(
            "Battle indicators unavailable for %s: %s",
            self._battle_id, reason
        )

    def observe(self, event: TelemetryEvent) -> None:
        """Observe a new telemetry event and update the player's model state accordingly."""

        if event.event_type == TelemetryEventType.BATTLE_STARTED:
            self._start_battle(event)
            return

        if self._closed or event.battle_id != self._battle_id:
            return
        if event.turn < self._last_turn:
            self._mark_unavailable("Events must arrive in chronological order")
            return
        self._last_turn = event.turn

        if event.event_type == TelemetryEventType.MONSTER_SNAPSHOT:
            self._observe_snapshot(event)
        elif event.event_type == TelemetryEventType.BATTLE_ENDED:
            self._finish_battle(event)

    def _start_battle(self, event: TelemetryEvent) -> None:
        if event.battle_id == self._battle_id or any(
            row.battle_id == event.battle_id for row in self._recent
        ):
            return
        self._battle_id = event.battle_id
        self._baseline = None
        self._fainted.clear()
        self._current = None
        self._unavailable_reason = None
        self._roster_changed = False
        self._last_turn = event.turn
        self._closed = False

    def _observe_snapshot(self, event: TelemetryEvent) -> None:
        """Observe a monster snapshot and update the player's model state.

        This method processes a telemetry event of type MONSTER_SNAPSHOT, calculates combat indicators,
        and updates the current battle record. If the roster has changed or indicators are unavailable,
        the player model may be marked as unavailable.
        """

        if self._roster_changed:
            return

        # Attempt to calculate combat indicators based on the current snapshot and the baseline.
        try:
            baseline = self._baseline
            if baseline is None:
                if (
                    event.turn != 1
                    or event.data.get("snapshot_phase") != SnapshotPhase.DECISION
                ):
                    raise ValueError("The first snapshot must be turn 1 decision")
                baseline = event
            assessment = calculate_combat_indicators(baseline, event)
        except ValueError as error:
            self._mark_unavailable(str(error))
            return

        if assessment.roster_changed:
            self._roster_changed = True
        if assessment.indicators is None:
            self._mark_unavailable(assessment.unavailable_reason)
            return
        combat = assessment.indicators

        if self._baseline is None:
            self._baseline = deepcopy(baseline)
        self._unavailable_reason = None

        initially_fit = {
            member["instance_id"]: member["is_player"]
            for member in baseline.data["monsters"]
            if not member["fainted"]
        }

        self._fainted.update(
            member["instance_id"] for member in event.data["monsters"]
            if member["fainted"] and member["instance_id"] in initially_fit
        )

        self._current = BattleRecord(
            battle_id=event.battle_id,
            turns=event.turn,
            combat=combat,
            health_phase=event.data["snapshot_phase"],
            player_fainted=sum(
                initially_fit[key] for key in self._fainted
            ),
            opponents_fainted=sum(
                not initially_fit[key] for key in self._fainted
            ),
        )

    def _finish_battle(self, event: TelemetryEvent) -> None:
        """Finalize the current battle and update the player's model state.

        This method processes a telemetry event indicating the end of a battle,
        validates the outcome, ensures the final snapshot is available, and
        updates the recent battle history. If the battle was aborted or the final
        snapshot is missing, the player model may be marked as unavailable.
        """

        if event.data.get("aborted") is True:
            self._baseline = None
            self._fainted.clear()
            self._current = None
            self._unavailable_reason = "Battle aborted"
            self._closed = True
            return

        outcome = event.data["outcome"]
        if outcome not in OutcomesType.members():
            self._mark_unavailable("Invalid battle outcome")
            self._closed = True
            return
        if self._current is None:
            if self._unavailable_reason is None:
                self._mark_unavailable("Missing final snapshot")
            self._closed = True
            return
        if (
            self._current.health_phase != SnapshotPhase.FINAL
            or self._current.turns != event.turn
        ):
            self._mark_unavailable("Missing final snapshot")
            self._closed = True
            return

        completed = replace(
            self._current,
            outcome=outcome,
            turns=event.turn
        )
        self._current = completed
        self._recent.append(completed)
        self._closed = True

    def get_indicators(self) -> PlayerIndicators:
        # Creates as dict representation of the current and recent
        # battle records, along with aggregated statistics.
        outcomes = {
            outcome: sum(
                row.outcome == outcome for row in self._recent
            )
            for outcome in OutcomesType.members()
        }

        # Calculate the average number of turns across recent battles, if any.
        average_turns = (
            sum(row.turns for row in self._recent) / len(self._recent)
            if self._recent else None
        )

        return PlayerIndicators(
            current=deepcopy(self._current),
            recent=tuple(self._recent),
            sample_size=len(self._recent),
            outcomes=outcomes,
            average_turns=average_turns,
            unavailable_reason=self._unavailable_reason,
        )
