from dataclasses import dataclass
from math import isfinite

from tuxemon.dda.telemetry import TelemetryEvent, TelemetryEventType


@dataclass(frozen=True)
class CombatIndicators:
    """Represents combat indicators for a battle."""
    
    player_health: float
    opponent_health: float
    player_availability: float
    opponent_availability: float


def calculate_combat_indicators(
    initial: TelemetryEvent, current: TelemetryEvent
) -> CombatIndicators:
    """Calculates combat indicators based on the initial and current telemetry events."""
    
    if initial.battle_id != current.battle_id:
        raise ValueError("Snapshots belong to different battles")
    if initial.turn != 1 or current.turn < initial.turn:
        raise ValueError("Invalid baseline or snapshot order")
    if initial.data.get("snapshot_phase") != "decision":
        raise ValueError("Baseline must be in the first decision snapshot")
    
    def index(event: TelemetryEvent) -> dict:
        """Indexes relevant combat data from a telemetry event."""
        
        if event.event_type != TelemetryEventType.MONSTER_SNAPSHOT:
            raise ValueError("Expected a monster snapshot")
        if event.data.get("snapshot_phase") not in {"decision", "before_rewards"}:
            raise ValueError("Expected a combat snapshot")
        
        result = {}
        
        # Index monsters by their instance ID for quick lookup and validation
        for member in event.data.get("monsters", []):
            key = member["instance_id"]
            if not isinstance(key, str) or not key or key in result:
                raise ValueError("Missing or duplicate monster ID")
            if type(member["is_player"]) is not bool:
                raise ValueError("Unknown team")
            
            hp, maximum = member["current_hp"], member["max_hp"]
            if not all(
                type(value) in (int, float) and isfinite(value)
                for value in (hp, maximum)
            ):
                raise ValueError("Invalid numeric health")
            if maximum <= 0 or not 0 <= hp <= maximum:
                raise ValueError("Health outside valid bounds")
            if type(member["fainted"]) is not bool or member["fainted"] != (hp == 0):
                raise ValueError("Invalid fainted state")
            result[key] = member
        return result
    
    baseline, observed = index(initial), index(current)
    if baseline.keys() != observed.keys():
        raise ValueError("Roster changes are not supported")
    if any(
        baseline[key]["owner_instance_id"] != observed[key]["owner_instance_id"]
        or baseline[key]["is_player"] != observed[key]["is_player"]
        for key in baseline
    ):
        raise ValueError("Monster ownership changed")
    
    def summarize(is_player: bool) -> tuple[float, float]:
        """Summarizes combat indicators for the specified team."""
        
        # Filter the observed monsters to include only those that
        # belong to the specified team and are not fainted
        members = [
            observed[key] for key, member in baseline.items()
            if member["is_player"] is is_player and not member["fainted"]
        ]
        if not members:
            raise ValueError("Team has no initially available monsters")

        # Calculate the total current health, maximum health,
        # and number of available monsters for the team
        health = sum(member["current_hp"] for member in members)
        maximum = sum(member["max_hp"] for member in members)
        available = sum(not member["fainted"] for member in members)
        
        # Returns the fraction of remaining health and available monsters for the team
        return health / maximum, available / len(members)
    
    player_health, player_availability = summarize(True)
    opponent_health, opponent_availability = summarize(False)
    
    return CombatIndicators(
        player_health=player_health,
        player_availability=player_availability,
        opponent_health=opponent_health,
        opponent_availability=opponent_availability
    )
