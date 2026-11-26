"""Per-campaign DDA settings read from a mod's dda.yaml.

A campaign enables DDA by shipping mods/<slug>/dda.yaml with `enabled: true`.
A missing or invalid file leaves DDA disabled. The chosen value is stored in a
game variable when the campaign starts, so saved games keep their choice.
"""

from __future__ import annotations

import logging
from typing import Literal

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from tuxemon.constants.paths import mods_folder
from tuxemon.database.yaml_utils import load_yaml
from tuxemon.dda.types import FuzzyTerms

logger = logging.getLogger(__name__)

DDA_VARIABLE: str = "dda_enabled"


class FuzzyRuleSettings(BaseModel):
    """Validated contents of a fuzzy rule in dda.yaml."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, description="Name of the fuzzy rule.")
    player: FuzzyTerms
    opponent: FuzzyTerms
    pressure: FuzzyTerms

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        name = value.strip()
        if not name:
            raise ValueError("Rule name must not be blank.")
        return name


class FuzzySettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rules: list[FuzzyRuleSettings] = Field(..., min_length=1)
    centroid_steps: int = Field(
        ...,
        ge=10,
        le=10000,
        description="Number of intervals used for centroid defuzzification.",
    )

    @model_validator(mode="after")
    def validate_rule_table(self) -> FuzzySettings:
        names = [rule.name for rule in self.rules]
        if len(names) != len(set(names)):
            raise ValueError("Fuzzy rule names must be unique.")

        combinations = [(rule.player, rule.opponent) for rule in self.rules]
        if len(combinations) != len(set(combinations)):
            raise ValueError("Fuzzy antecedent combinations must be unique.")

        expected = {
            (player, opponent)
            for player in FuzzyTerms
            for opponent in FuzzyTerms
        }
        missing = expected - set(combinations)
        if missing:
            raise ValueError("Fuzzy rules must cover all team-strength terms.")
        return self


class DDASettings(BaseModel):
    """Validated contents of a mod's dda.yaml."""

    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = Field(..., description="Supported schema version.")
    enabled: bool = Field(False, description="Whether DDA is active.")
    fuzzy: FuzzySettings | None = None

    @model_validator(mode="after")
    def check_fuzzy_rules(self) -> DDASettings:
        if self.enabled and self.fuzzy is None:
            raise ValueError("Enabled DDA requires fuzzy rules.")
        return self


def load_dda_settings(mod_slug: str) -> DDASettings:
    """Load validated campaign settings; missing or invalid files disable DDA."""
    path = mods_folder / mod_slug / "dda.yaml"
    if not path.is_file():
        return DDASettings(version=1, enabled=False)
    try:
        settings = DDASettings.model_validate(load_yaml(path) or {})
    except (OSError, yaml.YAMLError, ValidationError) as e:
        logger.warning(
            "Invalid dda.yaml for mod '%s', DDA disabled: %s", mod_slug, e
        )
        return DDASettings(version=1, enabled=False)
    return settings


def load_dda_enabled(mod_slug: str) -> bool:
    """Return whether the mod enables DDA."""
    return load_dda_settings(mod_slug).enabled
