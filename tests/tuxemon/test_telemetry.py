import json
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from tuxemon.combat.machine import CombatPhase
from tuxemon.dda.telemetry import TelemetryRecorder
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
    events = [json.loads(line) for line in output_path.read_text().splitlines()]
    assert [event["event_type"] for event in events] == [
        "battle_started",
        "battle_ended",
    ]
    assert events[0]["data"] == {
        "combat_type": "trainer",
        "battle_mode": "single",
    }
    assert events[1]["data"] == {"outcome": "win"}


def test_monster_snapshot_uses_real_health_properties_and_writes_jsonl(
    tmp_path, monster
):
    recorder = TelemetryRecorder(output_dir=tmp_path)

    recorder.record_monsters(1, [monster])
    output_path = recorder.write()

    event = json.loads(output_path.read_text())
    assert event["data"]["snapshot_phase"] == "decision"
    assert event["data"]["monsters"] == [{
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
    }]


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


def test_record_monsters_accepts_snapshot_phase(tmp_path, monster):
    recorder = TelemetryRecorder(output_dir=tmp_path)

    event = recorder.record_monsters(5, [monster], snapshot_phase="final")

    assert event.data["snapshot_phase"] == "final"


def test_battle_end_writes_final_snapshot_once(tmp_path, monster):
    state = MagicMock(spec=CombatState)
    state.combat_session = SimpleNamespace(
        turn=5,
        players=[SimpleNamespace(monsters=[monster])],
    )
    state.telemetry_recorder = TelemetryRecorder(output_dir=tmp_path)
    state.telemetry_saved = False

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
    assert state.telemetry_saved is True


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
        return SimpleNamespace(
            winners=[], prize=0, messages=[], update=False
        )

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
        5, 10, 40
    )
    assert (after["level"], after["current_hp"], after["max_hp"]) == (
        6, 14, 44
    )