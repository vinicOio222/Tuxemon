# DDA Telemetry Event Contract

This document describes the telemetry event contract for Dyanamic Difficuly Adjustment (DDA) battles in Tuxemon.

Each line of a battle's JSONL file is one `TelemetryEvent`, serialized by
`TelemetryEvent.to_dict()` in [`types.py`](../types.py).

Envelope (always present):

| Field | Type | Notes |
| --- | --- | --- |
| `schema_version` | string | `TELEMETRY_SCHEMA_VERSION` (`0.2.0`). |
| `event_type` | string | One of `battle_started`, `action`, `switch`, `monster_snapshot`, `dda_analysis`, `battle_ended`. |
| `battle_id` | string | Battle identifier; the recorder generates a UUID by default. |
| `turn` | int | Turn number, zero or greater. The combat producer emits events in non-decreasing turn order. |
| `data` | object | Payload, described below. |
| `timestamp` | string | ISO 8601, UTC. Informational only; ordering uses `turn` and emission order. |

Change rules: adding an optional field is a minor change (`1.x.0`) and readers
must ignore unknown fields. Removing or renaming a field, or changing its type or
meaning, is a major change (`2.0.0`).

## Payloads

The built-in recorder includes every key in the payload tables. Fields marked
nullable may be present with a JSON `null` value. Optional metadata is omitted
when it does not apply.

### `battle_started`
Required: `combat_type` (string), `battle_mode` (string).

### `action`
An attempt recorded when the action is dequeued, before execution. It does not
confirm a hit, damage, healing, or item consumption. For items, the acting
trainer supplies the user ID and team, even when the target is on the other team.

| Field | Nullable | Notes |
| --- | --- | --- |
| `execution` | no | Always `attempt`. |
| `user`, `user_instance_id` | yes | Slug and instance ID of the user. |
| `user_owner_instance_id` | yes | Trainer ID of the user, or the user's own ID when it has no owner. |
| `user_is_player` | yes | `null` when the team cannot be determined. |
| `method` | yes | Slug of the technique, item, or status. |
| `action_kind` | no | `technique`, `item`, `status`, or `unknown`. |
| `target`, `target_instance_id` | yes | Absent target gives `null`. |

### `switch`
A monster entering the field. `forced` is `true` when there is no outgoing
monster or the outgoing monster has fainted (replacement after a knock-out).

| Field | Nullable | Notes |
| --- | --- | --- |
| `incoming`, `incoming_instance_id` | no | Monster entering the field. |
| `incoming_owner_instance_id`, `incoming_is_player` | yes | `null` when the owner is unknown. |
| `outgoing`, `outgoing_instance_id` | yes | `null` if no outgoing monster is supplied; a forced switch can still identify it. |
| `forced` | no | Boolean. |

### `monster_snapshot`
| Field | Nullable | Notes |
| --- | --- | --- |
| `snapshot_phase` | no | `decision`, `before_rewards`, `after_rewards`, or `final`. |
| `monsters` | no | List of monster objects (below). May be empty. |

Monster object:

| Field | Nullable | Notes |
| --- | --- | --- |
| `instance_id`, `slug`, `level` | no | |
| `current_hp`, `max_hp`, `hp_ratio`, `fainted` | no | `hp_ratio` comes from `Monster.hp_ratio`. |
| `owner_slug`, `owner_instance_id`, `is_player` | yes | `null` when the monster has no owner. |
| `statuses` | no | List of slugs, possibly empty. |

### `battle_ended`
Required: `outcome`, one of `win`, `loss`, `draw`, `escaped`, `unknown`.
Written once per battle.

Optional fields added in `0.1.1`:

- `aborted` (boolean): `true` when the battle is interrupted by state removal
  or graceful game shutdown before an outcome is known. The outcome is
  `unknown`; the player model does not include that battle in its history.
  An interrupted battle does not emit a final snapshot.
- `dropped_events` (positive integer): number of observations not retained
  for JSONL export after reaching the in-memory limit. The export is incomplete
  and should not be used for full replay. Live observation still receives these
  events. The default limit is 4,096 buffered events per battle, reserving room
  for a final snapshot and `battle_ended`.

### `dda_analysis`

Added in `0.2.0`. In observation mode, at most one event is emitted per turn
for single trainer battles. It follows the decision snapshot and precedes
player menus and AI action selection. Status notifications and
`check_decisions` (including held-item use and `ON_DECISION` status effects)
occur before the snapshot; queued actions and post-action status processing
occur later.

| Field | Type | Notes |
| --- | --- | --- |
| `mode` | string | Always `observation`; no adjustment is applied. |
| `config_version` | integer | DDA schema version used for inference. |
| `indicators` | object or null | Four normalized combat indicators, or null if unavailable. |
| `memberships` | object | Fuzzy input and output degrees; empty when unavailable. |
| `activated_rules` | array | Names of activated rules. |
| `pressure` | number or null | Estimated relative pressure, or null when unavailable. |
| `unavailable_reason` | string or null | Reason when no pressure is available. |

`config_version` identifies the schema, not an immutable configuration
snapshot. Preserve the campaign YAML separately when reproducing experiments.

Export is off by default. Set `gameplay.dda_telemetry_export: true` in the
config to write each finalized battle to JSONL. Live observation runs either
way, since the player model depends on it.

DDA is enabled per campaign by `mods/<slug>/dda.yaml`:

```yaml
version: 1
enabled: true
mode: observation
# fuzzy: complete rules and centroid_steps are required
```

A missing or invalid file disables DDA. The value is read when a new game
starts and stored in the `dda_enabled` game variable, so saved games keep
their choice. When disabled, no battle is observed or exported.
New games also store `dda_campaign` in the existing game-variable map so
observation loads the correct campaign's current YAML at battle start. Old
saves without this variable retain telemetry but cannot run fuzzy observation;
a warning is logged rather than guessing a campaign. Existing enabled campaigns
without a `mode` retain telemetry and default to `disabled` observation.
Observation requires both the saved DDA switch and a currently enabled,
valid campaign configuration with `mode: observation`.

When enabled, the client exports finalized battles in the background. A failed disk write is
retried once; persistent failures and a full export queue are logged. A normal
shutdown waits for accepted exports. A forced termination cannot finalize an
active battle or guarantee that pending exports reach disk.
