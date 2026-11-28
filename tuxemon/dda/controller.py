"""Battle-local DDA observation without adaptation.

This module provides a controller for observing DDA decision snapshots
without applying any adjustments.
"""

from __future__ import annotations

import logging
from dataclasses import asdict

from tuxemon.dda.fuzzy import MamdaniFuzzyMachine
from tuxemon.dda.knowledge import DDASettings
from tuxemon.dda.player_model import PlayerModel
from tuxemon.dda.telemetry import TelemetryRecorder
from tuxemon.dda.types import (
    DDAAnalysisMode,
    SnapshotPhase,
    TelemetryEventType,
)

logger = logging.getLogger(__name__)


class ObservationController:
    """Analyze the current decision snapshot at most once per turn.

    This controller does not apply any adjustments; it only observes
    and records the current decision snapshot.

    * Observations are emitted as `dda_analysis` events with the following fields:
      - `mode`: Always `observation`.
      - `config_version`: DDA schema version used for inference.
      - `indicators`: Current combat indicators, or `None` if unavailable.
      - `memberships`: Fuzzy membership degrees, or empty when unavailable.
      - `activated_rules`: Names of activated rules, or empty when unavailable.
      - `pressure`: Estimated relative pressure, or `None` when unavailable.
      - `unavailable_reason`: Reason when indicators or pressure are unavailable.
    """

    def __init__(
        self,
        settings: DDASettings,
        player_model: PlayerModel,
        recorder: TelemetryRecorder,
    ) -> None:
        if (
            not settings.enabled
            or settings.mode != DDAAnalysisMode.OBSERVATION
            or settings.fuzzy is None
        ):
            raise ValueError("Enabled observation settings are required.")

        self._machine = MamdaniFuzzyMachine.from_settings(settings.fuzzy)
        self._config_version = settings.version
        self._player_model = player_model
        self._recorder = recorder
        self._last_turn = 0
        self._closed = False

    def analyze(self, turn: int, snapshot_recorded: bool) -> None:
        """Analyze the current decision snapshot for the given turn."""

        # Skip analysis if the controller is closed or
        # the turn is not newer than the last analyzed turn.
        if self._closed or turn <= self._last_turn:
            return
        self._last_turn = turn

        indicators = self._player_model.get_indicators()
        current = indicators.current

        # Determine the reason for unavailability if any.
        if not snapshot_recorded:
            reason = "Decision snapshot recording failed."
        elif current is None:
            reason = (
                indicators.unavailable_reason or "Decision indicators missing."
            )
        elif (
            current.battle_id != self._recorder.battle_id
            or current.turns != turn
            or current.health_phase != SnapshotPhase.DECISION
        ):
            reason = (
                "Decision indicators are stale or belong to another battle."
            )
        else:
            result = self._machine.evaluate(current.combat)

            # Prepare the data for recording the DDA analysis result.
            data = {
                "mode": DDAAnalysisMode.OBSERVATION,
                "config_version": self._config_version,
                "indicators": asdict(current.combat),
                "memberships": result.memberships,
                "activated_rules": list(result.activated_rules),
                "pressure": result.pressure,
                "unavailable_reason": result.unavailable_reason,
            }
            self._recorder.record(
                TelemetryEventType.DDA_ANALYSIS,
                turn,
                data,
            )
            logger.info(
                "DDA analysis: %s", {**data, "mode": data["mode"].value}
            )
            return

        # Record the reason for unavailability
        # when analysis could not be performed.
        data = {
            "mode": DDAAnalysisMode.OBSERVATION,
            "config_version": self._config_version,
            "indicators": None,
            "memberships": {},
            "activated_rules": [],
            "pressure": None,
            "unavailable_reason": reason,
        }
        self._recorder.record(
            TelemetryEventType.DDA_ANALYSIS,
            turn,
            data,
        )
        logger.info("DDA analysis: %s", {**data, "mode": data["mode"].value})

    def close(self) -> None:
        self._closed = True
