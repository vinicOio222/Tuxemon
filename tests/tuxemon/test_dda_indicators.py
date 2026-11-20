import pytest

from tuxemon.dda.indicators import calculate_combat_indicators
from tuxemon.dda.types import TelemetryEvent, TelemetryEventType


def snapshot(turn, player_hp, opponent_hp):
    monsters = []

    for team, health_values in (
        ("player", player_hp),
        ("opponent", opponent_hp),
    ):
        for index, hp in enumerate(health_values):
            monsters.append(
                {
                    "instance_id": f"{team}-{index}",
                    "owner_instance_id": team,
                    "is_player": team == "player",
                    "current_hp": hp,
                    "max_hp": 100,
                    "fainted": hp == 0,
                }
            )

    return TelemetryEvent(
        event_type=TelemetryEventType.MONSTER_SNAPSHOT,
        battle_id="test-battle",
        turn=turn,
        data={
            "snapshot_phase": "decision",
            "monsters": monsters,
        },
    )


@pytest.mark.parametrize(
    "player_hp, opponent_hp, expected",
    [
        pytest.param(
            [60, 60],
            [60, 60],
            (0.60, 0.60, 1.0, 1.0),
            id="balanced",
        ),
        pytest.param(
            [80, 80],
            [50, 0],
            (0.80, 0.25, 1.0, 0.5),
            id="advantage",
        ),
        pytest.param(
            [50, 0],
            [80, 80],
            (0.25, 0.80, 0.5, 1.0),
            id="disadvantage",
        ),
    ],
)
def test_combat_indicators(player_hp, opponent_hp, expected):
    initial = snapshot(1, [100, 100], [100, 100])
    current = snapshot(2, player_hp, opponent_hp)

    result = calculate_combat_indicators(initial, current).indicators

    assert result.player_health == pytest.approx(expected[0])
    assert result.opponent_health == pytest.approx(expected[1])
    assert result.player_availability == pytest.approx(expected[2])
    assert result.opponent_availability == pytest.approx(expected[3])


def test_uses_current_maximum_hp_after_level_up():
    initial = snapshot(1, [100], [100])
    current = snapshot(2, [100], [100])

    current.data["monsters"][0]["max_hp"] = 150

    result = calculate_combat_indicators(initial, current).indicators

    assert result.player_health == pytest.approx(100 / 150)


def test_excludes_monsters_already_fainted_from_baseline():
    initial = snapshot(1, [100, 0], [100])
    current = snapshot(2, [25, 100], [100])

    result = calculate_combat_indicators(initial, current).indicators

    assert result.player_health == pytest.approx(0.25)
    assert result.player_availability == 1


def test_duplicate_ids_and_missing_owner_are_rejected():
    initial = snapshot(1, [100], [100])
    current = snapshot(2, [100], [100])
    current.data["monsters"][1]["instance_id"] = "player-0"
    with pytest.raises(ValueError, match="duplicate monster ID"):
        calculate_combat_indicators(initial, current)

    current = snapshot(2, [100], [100])
    current.data["monsters"][0]["owner_instance_id"] = None
    with pytest.raises(ValueError, match="Unknown monster owner"):
        calculate_combat_indicators(initial, current)

    current = snapshot(2, [100], [100])
    current.data["monsters"][1]["owner_instance_id"] = "player"
    with pytest.raises(ValueError, match="multiple teams"):
        calculate_combat_indicators(initial, current)


def test_roster_change_is_reported_as_unavailable_result():
    initial = snapshot(1, [100], [100])
    current = snapshot(2, [100], [100])
    current.data["monsters"].pop()

    result = calculate_combat_indicators(initial, current)

    assert result.indicators is None
    assert result.roster_changed is True
    assert result.unavailable_reason == "Roster changes are not supported"
