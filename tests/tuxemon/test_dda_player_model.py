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
def test_model_uses_combat_snapshots_not_reward_snapshot(outcome):
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
    recorder.record_battle_end(2, "win")

    indicators = model.get_indicators()
    assert indicators.sample_size == 1
    assert indicators.outcomes["win"] == 1
    assert indicators.recent[0].combat.player_health == 0.8
