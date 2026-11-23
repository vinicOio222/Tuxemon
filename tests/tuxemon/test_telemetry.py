import json
from datetime import datetime, timezone
from threading import Event
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from tuxemon.base_client import BaseClient
from tuxemon.combat.machine import CombatPhase
from tuxemon.dda.player_model import PlayerModel
from tuxemon.dda.telemetry import TelemetryExporter, TelemetryRecorder
from tuxemon.dda.types import OutcomesType, TelemetryEventType
from tuxemon.monster.monster import Monster
from tuxemon.monster.stats import BasicStats
from tuxemon.monster.status import MonsterStatusHandler
from tuxemon.states.combat_state import CombatState


@pytest.fixture
def monster():
    monster = Monster.__new__(Monster)
    monster.instance_id = uuid4()
    monster.owner = None
    monster.slug = "test_monster"
    monster.experience_handler = SimpleNamespace(level=5)
    monster.base_stats = BasicStats(hp=40)
    monster.current_hp = 10
    monster.status = MonsterStatusHandler()
    return monster


def test_recorder_generates_battle_id_and_writes_jsonl(tmp_path):
    recorder = TelemetryRecorder(output_dir=tmp_path)
    recorder.record_battle_start(0, "trainer", "single")
    recorder.record_battle_end(4, "win")

    output_path = recorder.write()

    assert recorder.battle_id
    assert output_path == tmp_path / f"{recorder.battle_id}.jsonl"
    events = [
        json.loads(line) for line in output_path.read_text().splitlines()
    ]
    assert [event["event_type"] for event in events] == [
        "battle_started",
        "battle_ended",
    ]
    assert events[0]["data"] == {
        "combat_type": "trainer",
        "battle_mode": "single",
    }
    assert events[1]["data"] == {"outcome": "win"}


@pytest.mark.parametrize(
    "outcome",
    [
        pytest.param(outcome.value, id=outcome.value)
        for outcome in OutcomesType
    ],
)
def test_recorder_accepts_supported_battle_outcomes(outcome):
    recorder = TelemetryRecorder()

    event = recorder.record_battle_end(4, outcome)

    assert event.event_type is TelemetryEventType.BATTLE_ENDED
    assert event.data == {"outcome": outcome}


def test_recorder_rejects_unknown_battle_outcome():
    recorder = TelemetryRecorder()

    with pytest.raises(ValueError, match="Unknown battle outcome"):
        recorder.record_battle_end(4, "invalid")


def test_event_keeps_datetime_and_serializes_it_as_iso8601():
    recorder = TelemetryRecorder()

    event = recorder.record_battle_start(0, "trainer", "single")
    serialized = event.to_dict()

    assert isinstance(event.timestamp, datetime)
    assert event.timestamp.tzinfo == timezone.utc
    assert (
        datetime.fromisoformat(serialized["timestamp"]).tzinfo == timezone.utc
    )
    assert serialized["event_type"] == "battle_started"


def test_monster_snapshot_uses_real_health_properties_and_writes_jsonl(
    tmp_path, monster
):
    recorder = TelemetryRecorder(output_dir=tmp_path)

    recorder.record_monsters(1, [monster])
    output_path = recorder.write()

    event = json.loads(output_path.read_text())
    assert event["data"]["snapshot_phase"] == "decision"
    assert event["data"]["monsters"] == [
        {
            "owner_instance_id": None,
            "owner_slug": None,
            "is_player": None,
            "instance_id": str(monster.instance_id),
            "slug": "test_monster",
            "level": 5,
            "current_hp": 10,
            "max_hp": 40,
            "hp_ratio": 0.25,
            "fainted": False,
            "statuses": [],
        }
    ]


def test_decision_phase_records_monsters_and_processes_decisions(
    tmp_path, monster
):
    state = MagicMock(spec=CombatState)
    state.event_bus = MagicMock()
    state.session = MagicMock()
    state.combat_session = MagicMock()
    state.combat_session.turn = 1
    state.combat_session.players = [
        SimpleNamespace(monsters=[monster]),
        SimpleNamespace(monsters=[]),
    ]
    state.telemetry_recorder = TelemetryRecorder(output_dir=tmp_path)
    state._decision_queue = []

    CombatState.transition_phase(state, CombatPhase.DECISION)
    output_path = state.telemetry_recorder.write()

    event = json.loads(output_path.read_text())
    assert event["event_type"] == "monster_snapshot"
    assert event["turn"] == 1
    assert event["data"]["snapshot_phase"] == "decision"
    assert len(event["data"]["monsters"]) == 1
    assert event["data"]["monsters"][0]["instance_id"] == str(
        monster.instance_id
    )
    state.combat_session.check_decisions.assert_called_once_with(state.session)
    state.combat_session.initialize_hit_chances.assert_called_once_with()
    state.process_player_decisions.assert_called_once_with()


@pytest.mark.parametrize(
    "snapshot_phase",
    [
        pytest.param("decision", id="decision"),
        pytest.param("before_rewards", id="before_rewards"),
        pytest.param("after_rewards", id="after_rewards"),
        pytest.param("final", id="final"),
    ],
)
def test_record_monsters_accepts_snapshot_phase(
    tmp_path, monster, snapshot_phase
):
    recorder = TelemetryRecorder(output_dir=tmp_path)

    event = recorder.record_monsters(
        5, [monster], snapshot_phase=snapshot_phase
    )

    assert event.data["snapshot_phase"] == snapshot_phase


def test_record_monsters_rejects_unknown_snapshot_phase(tmp_path, monster):
    recorder = TelemetryRecorder(output_dir=tmp_path)

    with pytest.raises(ValueError, match="Unknown snapshot phase"):
        recorder.record_monsters(5, [monster], snapshot_phase="invalid")


def test_battle_end_writes_final_snapshot_once(tmp_path, monster):
    state = MagicMock(spec=CombatState)
    state.dda_enabled = True
    state.combat_session = SimpleNamespace(
        turn=5,
        players=[SimpleNamespace(monsters=[monster])],
    )
    state.telemetry_recorder = TelemetryRecorder(output_dir=tmp_path)
    state.client = SimpleNamespace(
        config=SimpleNamespace(dda_telemetry_export=True),
        telemetry_exporter=SimpleNamespace(
            submit=lambda recorder: recorder.write()
        ),
    )
    state.telemetry_outcome = None
    state.telemetry_export_queued = False
    state.telemetry_final_snapshot_recorded = False
    state.telemetry_end_recorded = False

    CombatState._save_battle_telemetry(state, "win")
    CombatState._save_battle_telemetry(state, "win")

    path = tmp_path / f"{state.telemetry_recorder.battle_id}.jsonl"
    events = [json.loads(line) for line in path.read_text().splitlines()]
    assert [event["event_type"] for event in events] == [
        "monster_snapshot",
        "battle_ended",
    ]
    assert events[0]["data"]["snapshot_phase"] == "final"
    assert events[0]["data"]["monsters"][0]["current_hp"] == 10
    assert events[1]["data"]["outcome"] == "win"
    assert state.telemetry_export_queued is True


def test_battle_end_skips_export_when_dda_export_is_disabled(
    tmp_path, monster
):
    state = MagicMock(spec=CombatState)
    state.dda_enabled = True
    state.combat_session = SimpleNamespace(
        turn=5,
        players=[SimpleNamespace(monsters=[monster])],
    )
    state.telemetry_recorder = TelemetryRecorder(output_dir=tmp_path)
    submit = MagicMock()
    state.client = SimpleNamespace(
        config=SimpleNamespace(dda_telemetry_export=False),
        telemetry_exporter=SimpleNamespace(submit=submit),
    )
    state.telemetry_outcome = None
    state.telemetry_export_queued = False
    state.telemetry_final_snapshot_recorded = False
    state.telemetry_end_recorded = False

    CombatState._save_battle_telemetry(state, "win")

    submit.assert_not_called()
    assert not state.telemetry_export_queued
    assert len(state.telemetry_recorder.events) == 2


def test_battle_end_skips_telemetry_when_campaign_dda_is_disabled(
    tmp_path, monster
):
    state = MagicMock(spec=CombatState)
    state.dda_enabled = False
    state.combat_session = SimpleNamespace(
        turn=5,
        players=[SimpleNamespace(monsters=[monster])],
    )
    state.telemetry_recorder = TelemetryRecorder(output_dir=tmp_path)
    submit = MagicMock()
    state.client = SimpleNamespace(
        config=SimpleNamespace(dda_telemetry_export=True),
        telemetry_exporter=SimpleNamespace(submit=submit),
    )
    state.telemetry_outcome = None
    state.telemetry_export_queued = False
    state.telemetry_final_snapshot_recorded = False
    state.telemetry_end_recorded = False

    CombatState._save_battle_telemetry(state, "win")

    submit.assert_not_called()
    assert not state.telemetry_export_queued
    assert state.telemetry_recorder.events == []
    assert not list(tmp_path.iterdir())


def test_end_combat_retries_rejected_telemetry_export(tmp_path, monster):
    state = MagicMock(spec=CombatState)
    state.dda_enabled = True
    recorder = TelemetryRecorder(output_dir=tmp_path)
    state.telemetry_recorder = recorder
    state.telemetry_outcome = "win"
    state.telemetry_export_queued = False
    state.telemetry_final_snapshot_recorded = False
    state.telemetry_end_recorded = False
    player = SimpleNamespace(
        monsters=[monster], battle_last_used_item_slug=None
    )
    state.combat_session = SimpleNamespace(
        turn=5, players=[player], reset=MagicMock()
    )
    state.event_bus = MagicMock()
    state.client = MagicMock()
    state.unregister_event_handlers = MagicMock()
    state.clear_combat_states = MagicMock()
    state._save_battle_telemetry = lambda *args, **kwargs: (
        CombatState._save_battle_telemetry(state, *args, **kwargs)
    )
    state.finalize_telemetry.side_effect = lambda: (
        CombatState.finalize_telemetry(state)
    )
    state._captured_mon_is_new = False
    state._captured_mon = None

    attempts = 0

    def fail_once(pending):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("Telemetry export queue full")
        pending.write()

    state.client.telemetry_exporter.submit.side_effect = fail_once

    CombatState._save_battle_telemetry(state, "win")
    assert not state.telemetry_export_queued
    assert len(recorder.events) == 2

    CombatState.end_combat(state)

    assert state.telemetry_export_queued
    assert attempts == 2
    output_path = tmp_path / f"{recorder.battle_id}.jsonl"
    events = [
        json.loads(line) for line in output_path.read_text().splitlines()
    ]
    assert [event["event_type"] for event in events] == [
        "monster_snapshot",
        "battle_ended",
    ]


def test_escape_saves_telemetry_before_session_reset(tmp_path, monster):
    state = MagicMock(spec=CombatState)
    state.dda_enabled = True
    state.telemetry_recorder = TelemetryRecorder(output_dir=tmp_path)
    state.client = SimpleNamespace(
        config=SimpleNamespace(dda_telemetry_export=True),
        telemetry_exporter=SimpleNamespace(
            submit=lambda recorder: recorder.write()
        ),
    )
    state.telemetry_outcome = None
    state.telemetry_export_queued = False
    state.telemetry_final_snapshot_recorded = False
    state.telemetry_end_recorded = False
    variables = {"run": True}
    monster.end_combat = MagicMock()
    state.session = MagicMock()
    state.ai_manager = MagicMock()
    state.combat_session = SimpleNamespace(
        turn=3,
        players=[SimpleNamespace(monsters=[monster])],
        get_variable=variables.get,
    )
    state._save_battle_telemetry = lambda outcome: (
        CombatState._save_battle_telemetry(state, outcome)
    )

    CombatState._on_clean_combat(state)

    path = tmp_path / f"{state.telemetry_recorder.battle_id}.jsonl"
    events = [json.loads(line) for line in path.read_text().splitlines()]
    assert [event["event_type"] for event in events] == [
        "monster_snapshot",
        "battle_ended",
    ]
    assert events[0]["turn"] == 3
    assert events[1]["data"]["outcome"] == "escaped"
    assert state.telemetry_export_queued is True


@pytest.mark.parametrize(
    "battle_id",
    [
        pytest.param("../escape", id="parent-posix"),
        pytest.param(r"..\escape", id="parent-windows"),
        pytest.param("C:drive", id="drive-relative"),
        pytest.param("NUL", id="reserved-device"),
    ],
)
def test_recorder_rejects_unsafe_battle_ids(tmp_path, battle_id):
    with pytest.raises(ValueError, match="Unsafe telemetry battle ID"):
        TelemetryRecorder(battle_id, output_dir=tmp_path)


def test_failed_atomic_append_preserves_file_and_pending_events(
    tmp_path, monkeypatch
):
    recorder = TelemetryRecorder(output_dir=tmp_path)
    recorder.record_battle_start(0, "trainer", "single")
    path = recorder.write()
    before = path.read_bytes()
    recorder.record_battle_end(1, "win")

    def fail_replace(source, destination):
        assert destination == path
        assert len(source.read_text().splitlines()) == 2
        raise OSError("disk unavailable")

    with monkeypatch.context() as patch:
        patch.setattr("tuxemon.dda.telemetry.os.replace", fail_replace)
        with pytest.raises(OSError, match="disk unavailable"):
            recorder.write()

    assert path.read_bytes() == before
    assert list(tmp_path.iterdir()) == [path]
    recorder.write()
    recorder.write()
    assert [
        json.loads(line)["event_type"]
        for line in path.read_text().splitlines()
    ] == [
        "battle_started",
        "battle_ended",
    ]


def test_buffer_preserves_final_records_and_reports_drops(tmp_path, caplog):
    observed = []
    recorder = TelemetryRecorder(
        output_dir=tmp_path, on_event=observed.append, max_events=4
    )
    recorder.record_battle_start(0, "trainer", "single")
    for turn in range(1, 4):
        recorder.record_monsters(turn, [])
    recorder.record_monsters(4, [], snapshot_phase="final")
    recorder.record_battle_end(4, "win")
    recorder.record_battle_end(4, "loss")

    assert len(recorder.events) == 4
    assert len(observed) == 6
    events = [
        json.loads(line) for line in recorder.write().read_text().splitlines()
    ]
    assert [event["turn"] for event in events] == [0, 1, 4, 4]
    assert events[2]["data"]["snapshot_phase"] == "final"
    assert events[3]["data"] == {"outcome": "win", "dropped_events": 2}
    assert caplog.text.count("JSONL will be incomplete") == 1


def test_game_cleanup_exports_an_interrupted_battle_once(tmp_path):
    client = MagicMock()
    client.telemetry_exporter = TelemetryExporter()
    model = PlayerModel()
    state = MagicMock(spec=CombatState)
    state.dda_enabled = True
    state.client = client
    state.combat_session = SimpleNamespace(turn=2)
    state.telemetry_recorder = TelemetryRecorder(
        output_dir=tmp_path, on_event=model.observe
    )
    state.telemetry_outcome = None
    state.telemetry_export_queued = False
    state.telemetry_final_snapshot_recorded = False
    state.telemetry_end_recorded = False
    state.telemetry_recorder.record_battle_start(0, "trainer", "single")
    state._save_battle_telemetry.side_effect = lambda *args, **kwargs: (
        CombatState._save_battle_telemetry(state, *args, **kwargs)
    )
    state.finalize_telemetry.side_effect = lambda: (
        CombatState.finalize_telemetry(state)
    )
    client.state_manager.active_states = [state, MagicMock()]

    BaseClient.perform_cleanup(client)
    state.finalize_telemetry()

    path = tmp_path / f"{state.telemetry_recorder.battle_id}.jsonl"
    events = [json.loads(line) for line in path.read_text().splitlines()]
    assert [event["event_type"] for event in events] == [
        "battle_started",
        "battle_ended",
    ]
    assert events[-1]["turn"] == 2
    assert events[-1]["data"] == {"outcome": "unknown", "aborted": True}
    assert model.get_indicators().sample_size == 0


def test_exporter_retries_write_without_waiting_in_submit(
    tmp_path, monkeypatch
):
    recorder = TelemetryRecorder(output_dir=tmp_path)
    recorder.record_battle_end(1, "win")
    exporter = TelemetryExporter()
    started = Event()
    release = Event()
    write = recorder.write
    attempts = 0

    def block_then_fail():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            started.set()
            if not release.wait(timeout=5):
                raise TimeoutError("submit did not release the game loop")
            raise OSError("temporary write failure")
        return write()

    monkeypatch.setattr(recorder, "write", block_then_fail)
    try:
        exporter.submit(recorder)
        assert started.wait(timeout=5)
        assert attempts == 1
        assert not list(tmp_path.iterdir())
    finally:
        release.set()
        exporter.close()
    assert attempts == 2
    assert json.loads(write().read_text())["data"] == {"outcome": "win"}


def test_switch_flags_forced_entries_and_keeps_outgoing_monster(
    tmp_path, monster
):
    recorder = TelemetryRecorder(output_dir=tmp_path)
    fainted = monster
    fainted.current_hp = 0
    incoming = SimpleNamespace(
        slug="agnite", instance_id=uuid4(), owner=None, is_fainted=False
    )
    voluntary_out = SimpleNamespace(
        slug="cataspike", instance_id=uuid4(), owner=None, is_fainted=False
    )

    after_faint = recorder.record_switch(3, incoming, fainted)
    voluntary = recorder.record_switch(4, incoming, voluntary_out)
    replacement = recorder.record_switch(5, incoming)

    assert after_faint.event_type == TelemetryEventType.SWITCH
    assert after_faint.data["outgoing"] == "test_monster"
    assert after_faint.data["forced"] is True
    assert voluntary.data["forced"] is False
    assert replacement.data["outgoing"] is None
    assert replacement.data["forced"] is True


def test_rewards_record_health_and_level_before_and_after(
    tmp_path, monster, monkeypatch
):
    state = MagicMock(spec=CombatState)
    state.session = MagicMock()
    state.combat_session = MagicMock()
    state.combat_session.turn = 3
    state.combat_session.players = [SimpleNamespace(monsters=[monster])]
    state.telemetry_recorder = TelemetryRecorder(output_dir=tmp_path)
    reward_system = MagicMock()

    def award_rewards(defeated):
        monster.experience_handler.level = 6
        monster.base_stats.hp = 44
        monster.current_hp = 14
        return SimpleNamespace(winners=[], prize=0, messages=[], update=False)

    reward_system.award_rewards.side_effect = award_rewards
    monkeypatch.setattr(
        "tuxemon.states.combat_state.RewardSystem",
        MagicMock(return_value=reward_system),
    )

    CombatState.award_experience_and_money(state, monster)
    path = state.telemetry_recorder.write()
    events = [json.loads(line) for line in path.read_text().splitlines()]

    assert [event["data"]["snapshot_phase"] for event in events] == [
        "before_rewards",
        "after_rewards",
    ]
    before = events[0]["data"]["monsters"][0]
    after = events[1]["data"]["monsters"][0]
    assert (before["level"], before["current_hp"], before["max_hp"]) == (
        5,
        10,
        40,
    )
    assert (after["level"], after["current_hp"], after["max_hp"]) == (
        6,
        14,
        44,
    )
