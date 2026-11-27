import json
from copy import deepcopy
from datetime import datetime

import pytest

from tuxemon.dda.controller import ObservationController
from tuxemon.dda.knowledge import load_dda_settings
from tuxemon.dda.player_model import PlayerModel
from tuxemon.dda.telemetry import TelemetryRecorder
from tuxemon.dda.types import TelemetryEvent, TelemetryEventType


@pytest.fixture
def observation(tmp_path):
    settings = load_dda_settings("tuxemon")
    assert settings.enabled and settings.mode == "observation"
    model = PlayerModel()
    recorder = TelemetryRecorder(output_dir=tmp_path, on_event=model.observe)
    controller = ObservationController(settings, model, recorder)
    recorder.record_battle_start(0, "trainer", "single")
    return controller, recorder


def snapshot(recorder, turn, player_hp=10):
    monsters = [
        {
            "instance_id": name,
            "owner_instance_id": name,
            "is_player": is_player,
            "current_hp": hp,
            "max_hp": 10,
            "fainted": hp == 0,
        }
        for name, is_player, hp in (
            ("player", True, player_hp),
            ("opponent", False, 10),
        )
    ]
    return recorder.record(
        TelemetryEventType.MONSTER_SNAPSHOT,
        turn,
        {"snapshot_phase": "decision", "monsters": monsters},
    )


def test_observation_records_once_without_mutating_snapshot(observation):
    controller, recorder = observation
    event = snapshot(recorder, 1)
    original = deepcopy(event.data)

    controller.analyze(1, True)
    controller.analyze(1, True)

    analyses = [
        event
        for event in recorder.events
        if event.event_type == TelemetryEventType.DDA_ANALYSIS
    ]
    assert len(analyses) == 1
    assert event.data == original
    assert analyses[0].data["mode"] == "observation"
    assert analyses[0].data["config_version"] == 1
    assert analyses[0].data["indicators"]["player_health"] == 1.0
    assert analyses[0].data["pressure"] == pytest.approx(0.5)
    assert analyses[0].data["memberships"]
    assert analyses[0].data["activated_rules"]


def test_failed_or_stale_snapshot_is_never_analyzed(observation):
    controller, recorder = observation
    snapshot(recorder, 1)
    controller.analyze(1, False)
    controller.analyze(2, True)

    analyses = [
        event.data
        for event in recorder.events
        if event.event_type == TelemetryEventType.DDA_ANALYSIS
    ]
    assert len(analyses) == 2
    assert all(item["pressure"] is None for item in analyses)
    assert all(item["unavailable_reason"] for item in analyses)


def test_observation_replays_and_closes_without_leaking_state(observation):
    controller, recorder = observation
    snapshot(recorder, 1)
    controller.analyze(1, True)
    snapshot(recorder, 2, player_hp=5)
    controller.analyze(2, True)
    controller.close()
    controller.analyze(3, True)

    replay = PlayerModel()
    analyses = []
    for line in recorder.write().read_text(encoding="utf-8").splitlines():
        raw = json.loads(line)
        event = TelemetryEvent(
            event_type=TelemetryEventType(raw["event_type"]),
            battle_id=raw["battle_id"],
            turn=raw["turn"],
            data=raw["data"],
            timestamp=datetime.fromisoformat(raw["timestamp"]),
            schema_version=raw["schema_version"],
        )
        replay.observe(event)
        if event.event_type == TelemetryEventType.DDA_ANALYSIS:
            current = replay.get_indicators().current
            assert current is not None
            assert event.data["indicators"]["player_health"] == (
                current.combat.player_health
            )
            analyses.append(event.data)

    assert len(analyses) == 2
    assert analyses[1]["indicators"]["player_health"] == 0.5


def test_disabled_mode_cannot_construct_controller(observation):
    _, recorder = observation
    settings = load_dda_settings("tuxemon").model_copy(
        update={"mode": "disabled"}
    )
    with pytest.raises(ValueError, match="observation"):
        ObservationController(settings, PlayerModel(), recorder)


def test_missing_indicators_produce_unavailable_analysis(observation):
    controller, recorder = observation
    controller.analyze(1, True)

    analysis = recorder.events[-1]
    assert analysis.event_type == TelemetryEventType.DDA_ANALYSIS
    assert analysis.data["indicators"] is None
    assert analysis.data["pressure"] is None
    assert analysis.data["unavailable_reason"]


def test_controllers_are_isolated_between_battles(observation, tmp_path):
    first, first_recorder = observation
    snapshot(first_recorder, 1)
    first.analyze(1, True)
    first.close()

    model = PlayerModel()
    recorder = TelemetryRecorder(output_dir=tmp_path, on_event=model.observe)
    second = ObservationController(load_dda_settings("tuxemon"), model, recorder)
    recorder.record_battle_start(0, "trainer", "single")
    snapshot(recorder, 1)
    second.analyze(1, True)

    assert recorder.events[-1].event_type == TelemetryEventType.DDA_ANALYSIS
    assert recorder.events[-1].data["pressure"] == pytest.approx(0.5)
