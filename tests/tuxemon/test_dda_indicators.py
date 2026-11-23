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


@pytest.mark.parametrize(
    "mutate, reason",
    [
        pytest.param(
            lambda monsters: monsters[1].update(instance_id="player-0"),
            "duplicate monster ID",
            id="duplicate-id",
        ),
        pytest.param(
            lambda monsters: monsters[0].update(owner_instance_id=None),
            "Unknown monster owner",
            id="missing-owner",
        ),
        pytest.param(
            lambda monsters: monsters[1].update(owner_instance_id="player"),
            "multiple teams",
            id="owner-in-two-teams",
        ),
        pytest.param(
            lambda monsters: monsters[0].update(max_hp=0),
            "Health outside valid bounds",
            id="zero-max-hp",
        ),
        pytest.param(
            lambda monsters: monsters[0].update(current_hp=float("nan")),
            "Invalid numeric health",
            id="nan-hp",
        ),
        pytest.param(
            lambda monsters: monsters[0].update(fainted=True),
            "Invalid fainted state",
            id="inconsistent-fainted",
        ),
    ],
)
def test_invalid_snapshot_data_is_reported_as_unavailable(mutate, reason):
    initial = snapshot(1, [100], [100])
    current = snapshot(2, [100], [100])
    mutate(current.data["monsters"])

    result = calculate_combat_indicators(initial, current)

    assert result.indicators is None
    assert reason in result.unavailable_reason
    assert result.roster_changed is False


@pytest.mark.parametrize(
    "player_hp, opponent_hp",
    [
        pytest.param([], [100], id="no-player-monsters"),
        pytest.param([0], [100], id="player-fainted-at-start"),
    ],
)
def test_team_without_initially_available_monsters_is_unavailable(
    player_hp, opponent_hp
):
    initial = snapshot(1, player_hp, opponent_hp)
    current = snapshot(2, player_hp, opponent_hp)

    result = calculate_combat_indicators(initial, current)

    assert result.indicators is None
    assert (
        result.unavailable_reason
        == "A team has no initially available monsters"
    )


def test_roster_change_is_reported_as_unavailable_result():
    initial = snapshot(1, [100], [100])
    current = snapshot(2, [100], [100])
    current.data["monsters"].pop()

    result = calculate_combat_indicators(initial, current)

    assert result.indicators is None
    assert result.roster_changed is True
    assert result.unavailable_reason == "Roster changes are not supported"


def test_asymmetric_teams_are_averaged_per_team():
    initial = snapshot(1, [100], [100, 100, 100])
    current = snapshot(2, [100], [0, 100, 50])

    result = calculate_combat_indicators(initial, current).indicators

    assert result.player_health == pytest.approx(1.0)
    assert result.opponent_health == pytest.approx(150 / 300)
    assert result.opponent_availability == pytest.approx(2 / 3)


def test_captured_monster_keeps_its_baseline_team():
    initial = snapshot(1, [100], [100, 100])
    current = snapshot(2, [100], [100, 100])
    captured = current.data["monsters"][1]
    captured.update(owner_instance_id="player", is_player=True)

    result = calculate_combat_indicators(initial, current).indicators

    assert result.player_health == pytest.approx(1.0)
    assert result.opponent_health == pytest.approx(1.0)
    assert result.opponent_availability == pytest.approx(1.0)


def test_owner_change_without_capture_is_unavailable():
    initial = snapshot(1, [100, 100], [100])
    current = snapshot(2, [100, 100], [100])
    current.data["monsters"][0]["owner_instance_id"] = "other-player"

    result = calculate_combat_indicators(initial, current)

    assert result.indicators is None
    assert result.unavailable_reason == "Monster ownership changed"
