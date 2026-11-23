"""Per-campaign DDA settings read from a mod's dda.yaml.

A campaign enables DDA by shipping mods/<slug>/dda.yaml with `enabled: true`.
A missing or invalid file leaves DDA disabled. The chosen value is stored in a
game variable when the campaign starts, so saved games keep their choice.
"""

from __future__ import annotations

import logging

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from tuxemon.constants.paths import mods_folder
from tuxemon.database.yaml_utils import load_yaml

logger = logging.getLogger(__name__)

DDA_VARIABLE: str = "dda_enabled"


class DDASettings(BaseModel):
    """Validated contents of a mod's dda.yaml."""

    model_config = ConfigDict(extra="forbid")

    version: int = Field(..., ge=1, description="Schema version.")
    enabled: bool = Field(False, description="Whether DDA is active.")


def load_dda_enabled(mod_slug: str) -> bool:
    """Return whether the mod enables DDA. Missing or invalid files disable it."""
    path = mods_folder / mod_slug / "dda.yaml"
    if not path.is_file():
        return False
    try:
        settings = DDASettings.model_validate(load_yaml(path) or {})
    except (OSError, yaml.YAMLError, ValidationError) as e:
        logger.warning(
            f"Invalid dda.yaml for mod '{mod_slug}', DDA disabled: {e}"
        )
        return False
    return settings.enabled
