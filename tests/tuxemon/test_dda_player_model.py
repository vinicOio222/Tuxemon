import json
from datetime import datetime

import pytest

from tuxemon.dda.player_model import PlayerModel
from tuxemon.dda.telemetry import TelemetryRecorder
from tuxemon.dda.types import TelemetryEvent, TelemetryEventType


@pytest.mark.parametrize(
    "outcome",
    [
        pytest.param("win", id="win"),
        pytest.param("loss", id="loss"),
    ],
)
def test_model_keeps_pre_reward_health_through_reward_snapshots(outcome):
    model = PlayerModel()
    battle_id = "test-battle"

    def observe(event_type, turn, data):
        model.observe(TelemetryEvent(event_type, battle_id, turn, data))

    def monsters(player_hp, opponent_hp):
        return [
            {
                "instance_id": "player-mon",
                "owner_instance_id": "player",
                "is_player": True,
                "current_hp": player_hp,
                "max_hp": 10,
                "fainted": player_hp == 0,
            },
            {
                "instance_id": "opponent-mon",
                "owner_instance_id": "opponent",
                "is_player": False,
                "current_hp": opponent_hp,
                "max_hp": 10,
                "fainted": opponent_hp == 0,
            },
        ]

    observe(TelemetryEventType.BATTLE_STARTED, 0, {})
    observe(
        TelemetryEventType.MONSTER_SNAPSHOT,
        1,
        {"snapshot_phase": "decision", "monsters": monsters(10, 10)},
    )
    observe(
        TelemetryEventType.MONSTER_SNAPSHOT,
        2,
        {"snapshot_phase": "before_rewards", "monsters": monsters(6, 0)},
    )
    observe(
        TelemetryEventType.MONSTER_SNAPSHOT,
        2,
        {"snapshot_phase": "after_rewards", "monsters": monsters(10, 0)},
    )
    after_rewards = model.get_indicators().current
    assert after_rewards is not None
    assert after_rewards.health_phase == "after_rewards"
    assert after_rewards.combat.player_health == 0.6
    observe(
        TelemetryEventType.MONSTER_SNAPSHOT,
        2,
        {"snapshot_phase": "final", "monsters": monsters(10, 0)},
    )
    observe(
        TelemetryEventType.BATTLE_ENDED,
        2,
        {"outcome": outcome},
    )

    indicators = model.get_indicators()
    assert indicators.sample_size == 1
    assert indicators.outcomes[outcome] == 1
    assert indicators.recent[0].health_phase == "final"
    assert indicators.recent[0].combat.player_health == 0.6


def test_captured_monster_moving_to_player_team_is_not_an_error():
    model = PlayerModel()
    battle_id = "capture-battle"

    def observe(event_type, turn, data):
        model.observe(TelemetryEvent(event_type, battle_id, turn, data))

    def monster(instance_id, owner, is_player, hp):
        return {
            "instance_id": instance_id,
            "owner_instance_id": owner,
            "is_player": is_player,
            "current_hp": hp,
            "max_hp": 10,
            "fainted": hp == 0,
        }

    observe(TelemetryEventType.BATTLE_STARTED, 0, {})
    observe(
        TelemetryEventType.MONSTER_SNAPSHOT,
        1,
        {
            "snapshot_phase": "decision",
            "monsters": [
                monster("player-mon", "player", True, 10),
                monster("wild-mon", "wild", False, 10),
            ],
        },
    )
    observe(
        TelemetryEventType.MONSTER_SNAPSHOT,
        2,
        {
            "snapshot_phase": "final",
            "monsters": [
                monster("player-mon", "player", True, 10),
                monster("wild-mon", "player", True, 4),
            ],
        },
    )
    observe(TelemetryEventType.BATTLE_ENDED, 2, {"outcome": "win"})

    indicators = model.get_indicators()
    assert indicators.sample_size == 1
    assert indicators.recent[0].outcome == "win"


def test_recorder_delivers_events_to_player_model():
    model = PlayerModel()
    recorder = TelemetryRecorder(on_event=model.observe)
    initial_monsters = [
        {
            "instance_id": "player-mon",
            "owner_instance_id": "player",
            "is_player": True,
            "current_hp": 10,
            "max_hp": 10,
            "fainted": False,
        },
        {
            "instance_id": "opponent-mon",
            "owner_instance_id": "opponent",
            "is_player": False,
            "current_hp": 10,
            "max_hp": 10,
            "fainted": False,
        },
    ]
    final_monsters = [
        {**initial_monsters[0], "current_hp": 8},
        {**initial_monsters[1], "current_hp": 0, "fainted": True},
    ]

    recorder.record_battle_start(0, "trainer", "single")
    recorder.record(
        TelemetryEventType.MONSTER_SNAPSHOT,
        1,
        {"snapshot_phase": "decision", "monsters": initial_monsters},
    )
    recorder.record(
        TelemetryEventType.MONSTER_SNAPSHOT,
        2,
        {"snapshot_phase": "before_rewards", "monsters": final_monsters},
    )
    recorder.record(
        TelemetryEventType.MONSTER_SNAPSHOT,
        2,
        {"snapshot_phase": "final", "monsters": final_monsters},
    )
    recorder.record_battle_end(2, "win")

    indicators = model.get_indicators()
    assert indicators.sample_size == 1
    assert indicators.outcomes["win"] == 1
    assert indicators.recent[0].combat.player_health == 0.8


def test_invalid_snapshot_cannot_be_saved_as_a_current_result():
    model = PlayerModel()
    recorder = TelemetryRecorder(on_event=model.observe)
    baseline = [
        {
            "instance_id": name,
            "owner_instance_id": name,
            "is_player": is_player,
            "current_hp": 10,
            "max_hp": 10,
            "fainted": False,
        }
        for name, is_player in (("player", True), ("opponent", False))
    ]
    recorder.record_battle_start(0, "trainer", "single")
    recorder.record(
        TelemetryEventType.MONSTER_SNAPSHOT,
        1,
        {"snapshot_phase": "decision", "monsters": baseline},
    )
    recorder.record(
        TelemetryEventType.MONSTER_SNAPSHOT,
        2,
        {"snapshot_phase": "final", "monsters": baseline[:1]},
    )
    recorder.record_battle_end(2, "win")

    result = model.get_indicators()
    assert result.current is None
    assert result.sample_size == 0
    assert result.unavailable_reason == "Roster changes are not supported"


def test_battle_without_final_snapshot_does_not_save_old_indicators():
    model = PlayerModel()
    recorder = TelemetryRecorder(on_event=model.observe)
    monsters = [
        {
            "instance_id": name,
            "owner_instance_id": name,
            "is_player": is_player,
            "current_hp": 10,
            "max_hp": 10,
            "fainted": False,
        }
        for name, is_player in (("player", True), ("opponent", False))
    ]
    recorder.record_battle_start(0, "trainer", "single")
    recorder.record(
        TelemetryEventType.MONSTER_SNAPSHOT,
        1,
        {"snapshot_phase": "decision", "monsters": monsters},
    )
    recorder.record_battle_end(2, "win")

    result = model.get_indicators()
    assert result.current is None
    assert result.sample_size == 0
    assert result.unavailable_reason == "Missing final snapshot"


def test_level_up_updates_resources_and_preserves_observed_faints():
    model = PlayerModel()
    recorder = TelemetryRecorder(on_event=model.observe)
    baseline = [
        {
            "instance_id": name,
            "owner_instance_id": name,
            "is_player": is_player,
            "current_hp": 10,
            "max_hp": 10,
            "fainted": False,
        }
        for name, is_player in (("player", True), ("opponent", False))
    ]
    recorder.record_battle_start(0, "trainer", "single")
    recorder.record(
        TelemetryEventType.MONSTER_SNAPSHOT,
        1,
        {"snapshot_phase": "decision", "monsters": baseline},
    )
    defeated = [
        {**baseline[0], "current_hp": 5},
        {**baseline[1], "current_hp": 0, "fainted": True},
    ]
    recorder.record(
        TelemetryEventType.MONSTER_SNAPSHOT,
        2,
        {"snapshot_phase": "before_rewards", "monsters": defeated},
    )
    after_level = [{**defeated[0], "current_hp": 7, "max_hp": 12}, defeated[1]]
    recorder.record(
        TelemetryEventType.MONSTER_SNAPSHOT,
        2,
        {"snapshot_phase": "after_rewards", "monsters": after_level},
    )
    current = model.get_indicators().current
    assert current is not None
    assert current.health_phase == "after_rewards"
    assert current.combat.player_health == pytest.approx(0.5)
    assert current.opponents_fainted == 1


def test_roster_change_remains_unavailable_even_if_roster_returns():
    model = PlayerModel()
    recorder = TelemetryRecorder(on_event=model.observe)
    monsters = [
        {
            "instance_id": name,
            "owner_instance_id": name,
            "is_player": is_player,
            "current_hp": 10,
            "max_hp": 10,
            "fainted": False,
        }
        for name, is_player in (("player", True), ("opponent", False))
    ]
    recorder.record_battle_start(0, "trainer", "single")
    recorder.record(
        TelemetryEventType.MONSTER_SNAPSHOT,
        1,
        {"snapshot_phase": "decision", "monsters": monsters},
    )
    recorder.record(
        TelemetryEventType.MONSTER_SNAPSHOT,
        2,
        {"snapshot_phase": "decision", "monsters": monsters[:1]},
    )
    recorder.record(
        TelemetryEventType.MONSTER_SNAPSHOT,
        3,
        {"snapshot_phase": "final", "monsters": monsters},
    )
    recorder.record_battle_end(3, "win")
    result = model.get_indicators()
    assert result.current is None
    assert result.unavailable_reason == "Roster changes are not supported"
    assert result.sample_size == 0


def test_invalid_health_clears_previous_result_and_valid_snapshot_recovers():
    model = PlayerModel()
    recorder = TelemetryRecorder(on_event=model.observe)
    monsters = [
        {
            "instance_id": name,
            "owner_instance_id": name,
            "is_player": is_player,
            "current_hp": 10,
            "max_hp": 10,
            "fainted": False,
        }
        for name, is_player in (("player", True), ("opponent", False))
    ]
    recorder.record_battle_start(0, "trainer", "single")
    recorder.record(
        TelemetryEventType.MONSTER_SNAPSHOT,
        1,
        {"snapshot_phase": "decision", "monsters": monsters},
    )
    invalid = [{**monsters[0], "current_hp": -1}, monsters[1]]
    recorder.record(
        TelemetryEventType.MONSTER_SNAPSHOT,
        2,
        {"snapshot_phase": "decision", "monsters": invalid},
    )
    unavailable = model.get_indicators()
    assert unavailable.current is None
    assert unavailable.unavailable_reason == "Health outside valid bounds"

    recorder.record(
        TelemetryEventType.MONSTER_SNAPSHOT,
        3,
        {"snapshot_phase": "final", "monsters": monsters},
    )
    recorder.record_battle_end(3, "win")
    recovered = model.get_indicators()
    assert recovered.unavailable_reason is None
    assert recovered.recent[0].turns == 3


def test_complete_jsonl_replay_matches_live_indicators(tmp_path):
    model = PlayerModel()
    live_results = []

    def observe(event):
        model.observe(event)
        live_results.append(model.get_indicators())

    recorder = TelemetryRecorder(output_dir=tmp_path, on_event=observe)
    monsters = [
        {
            "instance_id": name,
            "owner_instance_id": name,
            "is_player": is_player,
            "current_hp": 10,
            "max_hp": 10,
            "fainted": False,
        }
        for name, is_player in (("player", True), ("opponent", False))
    ]
    recorder.record_battle_start(0, "trainer", "single")
    recorder.record(
        TelemetryEventType.MONSTER_SNAPSHOT,
        1,
        {"snapshot_phase": "decision", "monsters": monsters},
    )
    after_level = [{**monsters[0], "current_hp": 8, "max_hp": 12}, monsters[1]]
    recorder.record(
        TelemetryEventType.MONSTER_SNAPSHOT,
        2,
        {"snapshot_phase": "after_rewards", "monsters": after_level},
    )
    recorder.record(
        TelemetryEventType.MONSTER_SNAPSHOT,
        2,
        {"snapshot_phase": "final", "monsters": after_level},
    )
    recorder.record_battle_end(2, "win")

    replay = PlayerModel()
    replay_results = []
    for line in recorder.write().read_text(encoding="utf-8").splitlines():
        data = json.loads(line)
        event = TelemetryEvent(
            event_type=TelemetryEventType(data["event_type"]),
            battle_id=data["battle_id"],
            turn=data["turn"],
            data=data["data"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            schema_version=data["schema_version"],
        )
        replay.observe(event)
        replay_results.append(replay.get_indicators())
    assert replay_results == live_results
