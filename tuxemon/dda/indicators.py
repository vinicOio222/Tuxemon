"""Indicators and assessments for Tuxemon combat snapshots.

This module defines classes and functions for assessing combat snapshots in Tuxemon battles,
including indicators for player and opponent health and availability, as well as functions for
indexing and summarizing snapshot data.
"""

from dataclasses import dataclass
from math import isfinite

from tuxemon.dda.types import TelemetryEvent, TelemetryEventType


@dataclass(frozen=True)
class CombatIndicators:
    """Represents combat indicators for a battle."""

    player_health: float
    opponent_health: float
    player_availability: float
    opponent_availability: float


@dataclass(frozen=True)
class CombatAssessment:
    """Result of comparing two snapshots, with indicators or the reason they are unavailable."""

    indicators: CombatIndicators | None
    unavailable_reason: str | None = None
    roster_changed: bool = False


@dataclass(frozen=True)
class SnapshotMember:
    """Represents a member of a combat snapshot."""

    owner_id: str
    is_player: bool
    current_hp: float
    max_hp: float
    fainted: bool


def _index_snapshot(event: TelemetryEvent) -> dict[str, SnapshotMember]:
    """Indexes the monsters in a snapshot by their instance IDs."""

    if event.event_type != TelemetryEventType.MONSTER_SNAPSHOT:
        raise ValueError("Expected a monster snapshot")
    if event.data.get("snapshot_phase") not in {
        "decision", "before_rewards", "after_rewards", "final"
    }:
        raise ValueError("Expected a combat snapshot")

    # Initialize the result dictionary, owner tracking for the snapshot
    # and extract the list of monsters from the event data.
    result: dict[str, SnapshotMember] = {}
    owners: dict[str, bool] = {}
    monsters = event.data.get("monsters")

    if not isinstance(monsters, list):
        raise ValueError("Missing or invalid monster list")

    # Iterate over each monster in the snapshot and validate its data.
    for member in monsters:
        if not isinstance(member, dict):
            raise ValueError("Invalid monster data")
        key = member.get("instance_id")
        if not isinstance(key, str) or not key or key in result:
            raise ValueError("Missing or duplicate monster ID")
        team = member.get("is_player")
        if type(team) is not bool:
            raise ValueError("Unknown team")
        owner_id = member.get("owner_instance_id")
        if not isinstance(owner_id, str) or not owner_id:
            raise ValueError("Unknown monster owner")
        if owner_id in owners and owners[owner_id] != team:
            raise ValueError("Monster owner belongs to multiple teams")
        owners[owner_id] = team

        hp, maximum = member.get("current_hp"), member.get("max_hp")

        # Validate the current and maximum health values for the monster.
        if (
            isinstance(hp, bool)
            or not isinstance(hp, (int, float))
            or not isfinite(hp)
            or isinstance(maximum, bool)
            or not isinstance(maximum, (int, float))
            or not isfinite(maximum)
        ):
            raise ValueError("Invalid numeric health")
        if maximum <= 0 or not 0 <= hp <= maximum:
            raise ValueError("Health outside valid bounds")

        # Validate the fainted state for the monster.
        fainted = member.get("fainted")
        if type(fainted) is not bool or fainted != (hp == 0):
            raise ValueError("Invalid fainted state")

        # Store the validated monster data in the result dictionary.
        result[key] = SnapshotMember(owner_id, team, hp, maximum, fainted)
    return result


def _summarize_team(
    baseline: dict[str, SnapshotMember],
    observed: dict[str, SnapshotMember],
    is_player: bool,
) -> tuple[float, float]:
    """Summarizes the health and availability of a team based on the observed snapshot."""

    members = [
        observed[key] for key, member in baseline.items()
        if member.is_player is is_player and not member.fainted
    ]
    if not members:
        raise ValueError("Team has no initially available monsters")
    health = sum(member.current_hp for member in members)
    maximum = sum(member.max_hp for member in members)
    available = sum(not member.fainted for member in members)
    return health / maximum, available / len(members)


def calculate_combat_indicators(
    initial: TelemetryEvent, current: TelemetryEvent
) -> CombatAssessment:
    """Calculates combat indicators based on the initial and current telemetry events.

    Captures the combat indicators for both the player and the opponent based on the
    initial and current snapshots.
    """

    if initial.battle_id != current.battle_id:
        raise ValueError("Snapshots belong to different battles")
    if initial.turn != 1 or current.turn < initial.turn:
        raise ValueError("Invalid baseline or snapshot order")
    if initial.data.get("snapshot_phase") != "decision":
        raise ValueError("Baseline must be in the first decision snapshot")

    baseline, observed = _index_snapshot(initial), _index_snapshot(current)
    if baseline.keys() != observed.keys():
        return CombatAssessment(
            indicators=None,
            unavailable_reason="Roster changes are not supported",
            roster_changed=True,
        )

    for key, initial_member in baseline.items():
        current_member = observed[key]
        captured = not initial_member.is_player and current_member.is_player
        if not captured and (
            initial_member.owner_id != current_member.owner_id
            or initial_member.is_player != current_member.is_player
        ):
            raise ValueError("Monster ownership changed")

    # Summarize the health and availability for both the player and the opponent.
    player_health, player_availability = _summarize_team(baseline, observed, True)
    opponent_health, opponent_availability = _summarize_team(baseline, observed, False)

    return CombatAssessment(
        indicators=CombatIndicators(
            player_health=player_health,
            player_availability=player_availability,
            opponent_health=opponent_health,
            opponent_availability=opponent_availability,
        )
    )
