from math import isfinite

import pytest

from tuxemon.dda.fuzzy import FuzzyRule, MamdaniFuzzyMachine, membership
from tuxemon.dda.indicators import CombatIndicators
from tuxemon.dda.knowledge import FuzzyRuleSettings, FuzzySettings
from tuxemon.dda.types import FuzzyTerms


@pytest.fixture
def fuzzy_settings() -> FuzzySettings:
    return FuzzySettings(
        centroid_steps=100,
        rules=[
            FuzzyRuleSettings(
                name="player_low_opponent_low",
                player=FuzzyTerms.LOW,
                opponent=FuzzyTerms.LOW,
                pressure=FuzzyTerms.MODERATE,
            ),
            FuzzyRuleSettings(
                name="player_low_opponent_moderate",
                player=FuzzyTerms.LOW,
                opponent=FuzzyTerms.MODERATE,
                pressure=FuzzyTerms.HIGH,
            ),
            FuzzyRuleSettings(
                name="player_low_opponent_high",
                player=FuzzyTerms.LOW,
                opponent=FuzzyTerms.HIGH,
                pressure=FuzzyTerms.HIGH,
            ),
            FuzzyRuleSettings(
                name="player_moderate_opponent_low",
                player=FuzzyTerms.MODERATE,
                opponent=FuzzyTerms.LOW,
                pressure=FuzzyTerms.LOW,
            ),
            FuzzyRuleSettings(
                name="player_moderate_opponent_moderate",
                player=FuzzyTerms.MODERATE,
                opponent=FuzzyTerms.MODERATE,
                pressure=FuzzyTerms.MODERATE,
            ),
            FuzzyRuleSettings(
                name="player_moderate_opponent_high",
                player=FuzzyTerms.MODERATE,
                opponent=FuzzyTerms.HIGH,
                pressure=FuzzyTerms.HIGH,
            ),
            FuzzyRuleSettings(
                name="player_high_opponent_low",
                player=FuzzyTerms.HIGH,
                opponent=FuzzyTerms.LOW,
                pressure=FuzzyTerms.LOW,
            ),
            FuzzyRuleSettings(
                name="player_high_opponent_moderate",
                player=FuzzyTerms.HIGH,
                opponent=FuzzyTerms.MODERATE,
                pressure=FuzzyTerms.LOW,
            ),
            FuzzyRuleSettings(
                name="both_high",
                player=FuzzyTerms.HIGH,
                opponent=FuzzyTerms.HIGH,
                pressure=FuzzyTerms.MODERATE,
            ),
        ]
    )


@pytest.mark.parametrize(
    ("term", "value", "expected"),
    [
        pytest.param(FuzzyTerms.LOW, 0.0, 1.0, id="low_at_zero"),
        pytest.param(FuzzyTerms.LOW, 0.5, 0.0, id="low_at_half"),
        pytest.param(
            FuzzyTerms.MODERATE, 0.0, 0.0, id="moderate_at_zero"
        ),
        pytest.param(
            FuzzyTerms.MODERATE, 0.5, 1.0, id="moderate_at_half"
        ),
        pytest.param(
            FuzzyTerms.MODERATE, 1.0, 0.0, id="moderate_at_one"
        ),
        pytest.param(FuzzyTerms.HIGH, 0.5, 0.0, id="high_at_half"),
        pytest.param(FuzzyTerms.HIGH, 1.0, 1.0, id="high_at_one"),
    ],
)
def test_membership_function(term, value, expected) -> None:
    assert membership(term, value) == expected


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(-0.1, id="below_range"),
        pytest.param(1.1, id="above_range"),
        pytest.param(float("nan"), id="nan"),
        pytest.param(float("inf"), id="infinite"),
        pytest.param(True, id="boolean"),
    ],
)
def test_membership_rejects_invalid_values(value) -> None:
    with pytest.raises(ValueError):
        membership(FuzzyTerms.MODERATE, value)


def test_machine_uses_validated_settings_rules(
    fuzzy_settings: FuzzySettings,
) -> None:
    machine = MamdaniFuzzyMachine.from_settings(fuzzy_settings)

    result = machine.evaluate(CombatIndicators(0.2, 0.8, 0.2, 0.8))

    assert result.pressure is not None
    assert isfinite(result.pressure)
    assert 0.5 < result.pressure <= 1.0
    assert "player_low_opponent_high" in result.activated_rules
    assert all(
        isfinite(degree) and 0.0 <= degree <= 1.0
        for degree in result.memberships.values()
    )


def test_membership_functions_overlap() -> None:
    for value in (0.25, 0.75):
        total = sum(membership(term, value) for term in FuzzyTerms)
        assert total == pytest.approx(1.0)


def test_centroid_steps_come_from_fuzzy_settings(
    fuzzy_settings: FuzzySettings,
) -> None:
    settings = FuzzySettings.model_validate(
        {**fuzzy_settings.model_dump(), "centroid_steps": 37}
    )

    machine = MamdaniFuzzyMachine.from_settings(settings)

    assert machine.centroid_steps == 37


@pytest.mark.parametrize(
    "steps",
    [
        pytest.param(9, id="too_few"),
        pytest.param(10001, id="too_many"),
    ],
)
def test_fuzzy_settings_reject_out_of_range_centroid_steps(
    fuzzy_settings: FuzzySettings, steps: int
) -> None:
    settings_data = fuzzy_settings.model_dump()
    settings_data["centroid_steps"] = steps
    with pytest.raises(ValueError):
        FuzzySettings.model_validate(settings_data)


def test_pressure_trends_reverse_with_team_advantage(
    fuzzy_settings: FuzzySettings,
) -> None:
    machine = MamdaniFuzzyMachine.from_settings(fuzzy_settings)
    player_advantage = machine.evaluate(
        CombatIndicators(0.9, 0.1, 0.9, 0.1)
    )
    opponent_advantage = machine.evaluate(
        CombatIndicators(0.1, 0.9, 0.1, 0.9)
    )

    assert player_advantage.pressure is not None
    assert opponent_advantage.pressure is not None
    assert player_advantage.pressure < 0.5
    assert opponent_advantage.pressure > 0.5


@pytest.mark.parametrize(
    "resource_level",
    [
        pytest.param(0.1, id="both_weakened"),
        pytest.param(0.9, id="both_healthy"),
    ],
)
def test_balanced_teams_produce_moderate_pressure(
    fuzzy_settings: FuzzySettings, resource_level: float
) -> None:
    result = MamdaniFuzzyMachine.from_settings(fuzzy_settings).evaluate(
        CombatIndicators(
            resource_level,
            resource_level,
            resource_level,
            resource_level,
        )
    )

    assert result.pressure == pytest.approx(0.5, abs=0.02)


def test_no_activated_rule_returns_unavailable() -> None:
    machine = MamdaniFuzzyMachine(
        (
            FuzzyRule(
                "both_moderate",
                FuzzyTerms.MODERATE,
                FuzzyTerms.MODERATE,
                FuzzyTerms.MODERATE,
            ),
        ),
        centroid_steps=100,
    )
    result = machine.evaluate(
        CombatIndicators(0.0, 1.0, 0.0, 1.0)
    )

    assert result.pressure is None
    assert result.activated_rules == ()
    assert result.unavailable_reason == "No fuzzy rules were activated."


def test_invalid_indicators_are_rejected(
    fuzzy_settings: FuzzySettings,
) -> None:
    result = MamdaniFuzzyMachine.from_settings(fuzzy_settings).evaluate(
        CombatIndicators(float("nan"), 0.5, 0.5, 0.5)
    )
    assert result.pressure is None
    assert result.unavailable_reason is not None


def test_repeated_input_produces_deterministic_result(
    fuzzy_settings: FuzzySettings,
) -> None:
    machine = MamdaniFuzzyMachine.from_settings(fuzzy_settings)
    indicators = CombatIndicators(0.35, 0.7, 0.45, 0.6)

    assert machine.evaluate(indicators) == machine.evaluate(indicators)
