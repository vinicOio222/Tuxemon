"""Mamdani fuzzy inference for normalized battle indicators."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from math import isfinite
from typing import TYPE_CHECKING

from tuxemon.dda.indicators import CombatIndicators
from tuxemon.dda.types import FuzzyTerms

if TYPE_CHECKING:
    from tuxemon.dda.knowledge import FuzzySettings


@dataclass(frozen=True)
class FuzzyResult:
    """Pressure estimate and details that explain the inference."""

    pressure: float | None
    memberships: dict[str, float]
    activated_rules: tuple[str, ...]
    unavailable_reason: str | None = None


@dataclass(frozen=True)
class FuzzyRule:
    """A rule loaded from the campaign's DDA configuration."""

    name: str
    player: FuzzyTerms
    opponent: FuzzyTerms
    pressure: FuzzyTerms


def membership(term: FuzzyTerms, value: float) -> float:
    """Return a low, moderate, or high membership degree for [0, 1]."""

    if not isinstance(term, FuzzyTerms):
        raise ValueError(f"Unknown fuzzy term: {term!r}")
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not isfinite(value)
        or not 0.0 <= value <= 1.0
    ):
        raise ValueError("Membership input must be finite and between 0 and 1.")

    if term is FuzzyTerms.LOW:
        return max(0.0, 1.0 - 2.0 * value)
    if term is FuzzyTerms.MODERATE:
        return max(0.0, 1.0 - abs(2.0 * value - 1.0))
    return max(0.0, 2.0 * value - 1.0)


class MamdaniFuzzyMachine:
    """Estimate relative combat pressure without changing the battle."""

    def __init__(
        self, rules: Iterable[FuzzyRule], centroid_steps: int
    ) -> None:
        self.rules = tuple(rules)
        if not self.rules:
            raise ValueError("At least one fuzzy rule must be provided.")
        if type(centroid_steps) is not int or centroid_steps < 1:
            raise ValueError("Centroid steps must be a positive integer.")
        self.centroid_steps = centroid_steps

        rule_names: set[str] = set()
        for rule in self.rules:
            if not isinstance(rule, FuzzyRule):
                raise TypeError("Rules must be FuzzyRule instances.")
            if (
                not isinstance(rule.name, str)
                or not rule.name.strip()
                or rule.name in rule_names
            ):
                raise ValueError("Rule names must be non-empty and unique.")
            if not isinstance(rule.player, FuzzyTerms):
                raise ValueError(f"Invalid player term: {rule.player!r}")
            if not isinstance(rule.opponent, FuzzyTerms):
                raise ValueError(f"Invalid opponent term: {rule.opponent!r}")
            if not isinstance(rule.pressure, FuzzyTerms):
                raise ValueError(f"Invalid pressure term: {rule.pressure!r}")
            rule_names.add(rule.name)

    @classmethod
    def from_settings(cls, settings: FuzzySettings) -> MamdaniFuzzyMachine:
        """Create a machine using the validated rules from dda.yaml."""

        rules = (
            FuzzyRule(
                name=rule.name,
                player=rule.player,
                opponent=rule.opponent,
                pressure=rule.pressure,
            )
            for rule in settings.rules
        )
        return cls(rules, centroid_steps=settings.centroid_steps)

    def evaluate(self, indicators: CombatIndicators) -> FuzzyResult:
        """Fuzzify, apply configured rules, aggregate, and defuzzify."""

        if not isinstance(indicators, CombatIndicators):
            return FuzzyResult(
                pressure=None,
                memberships={},
                activated_rules=(),
                unavailable_reason="Combat indicators are missing or invalid.",
            )

        values = {
            "player_health": indicators.player_health,
            "player_availability": indicators.player_availability,
            "opponent_health": indicators.opponent_health,
            "opponent_availability": indicators.opponent_availability,
        }
        for name, value in values.items():
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not isfinite(value)
                or not 0.0 <= value <= 1.0
            ):
                return FuzzyResult(
                    pressure=None,
                    memberships={},
                    activated_rules=(),
                    unavailable_reason=(
                        f"Combat indicator {name!r} must be finite and "
                        "between 0 and 1."
                    ),
                )

        # Initial model assumption: health and availability have equal weight.
        strengths = {
            "player": (
                values["player_health"] + values["player_availability"]
            )
            / 2.0,
            "opponent": (
                values["opponent_health"] + values["opponent_availability"]
            )
            / 2.0,
        }

        memberships: dict[str, float] = {}
        for name, value in values.items():
            for term in FuzzyTerms:
                memberships[f"{name}.{term.value}"] = membership(term, value)

        strength_memberships: dict[str, dict[FuzzyTerms, float]] = {}
        for side, strength in strengths.items():
            strength_memberships[side] = {}
            for term in FuzzyTerms:
                degree = membership(term, strength)
                strength_memberships[side][term] = degree
                memberships[f"{side}_strength.{term.value}"] = degree

        output_activations = {term: 0.0 for term in FuzzyTerms}
        activated_rules: list[str] = []
        for rule in self.rules:
            activation = min(
                strength_memberships["player"][rule.player],
                strength_memberships["opponent"][rule.opponent],
            )
            if activation > 0.0:
                activated_rules.append(rule.name)
                output_activations[rule.pressure] = max(
                    output_activations[rule.pressure],
                    activation,
                )

        for term, activation in output_activations.items():
            memberships[f"pressure.{term.value}"] = activation

        if not activated_rules:
            return FuzzyResult(
                pressure=None,
                memberships=memberships,
                activated_rules=(),
                unavailable_reason="No fuzzy rules were activated.",
            )

        # Mamdani min implication, max aggregation, and sampled centroid.
        numerator = 0.0
        denominator = 0.0
        for step in range(self.centroid_steps + 1):
            output_value = step / self.centroid_steps
            degree = max(
                min(output_activations[term], membership(term, output_value))
                for term in FuzzyTerms
            )
            numerator += output_value * degree
            denominator += degree

        if denominator == 0.0:
            return FuzzyResult(
                pressure=None,
                memberships=memberships,
                activated_rules=tuple(activated_rules),
                unavailable_reason="Aggregated output has zero membership.",
            )

        return FuzzyResult(
            pressure=numerator / denominator,
            memberships=memberships,
            activated_rules=tuple(activated_rules),
        )
