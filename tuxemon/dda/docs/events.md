# DDA Telemetry Event Contract

Each line of a battle's JSONL file is one `TelemetryEvent`, serialized by
`TelemetryEvent.to_dict()` in [types.py](/c:/Users/dfyou/Tuxemon/tuxemon/dda/types.py).

Envelope (always present):

| Field | Type | Notes |
| --- | --- | --- |
| `event_type` | string | One of `battle_started`, `action`, `switch`, `monster_snapshot`, `battle_ended`. |
| `battle_id` | string | UUID of the battle. |
| `turn` | int | Turn number, zero or greater. Non-decreasing within a battle. |
| `data` | object | Payload, described below. |
| `timestamp` | string | ISO 8601, UTC. Informational only; ordering uses `turn` and emission order. |
| `schema_version` | string | `TELEMETRY_SCHEMA_VERSION` (`1.0.0`). |

Change rules: adding an optional field is a minor change (`1.x.0`) and readers
must ignore unknown fields. Removing or renaming a field, or changing its type or
meaning, is a major change (`2.0.0`).

## Payloads

### `battle_started`
Required: `combat_type` (string), `battle_mode` (string).

### `action`
An attempt to execute an action. It does not confirm a hit, damage, healing, or
item consumption.

| Field | Optional | Notes |
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

| Field | Optional | Notes |
| --- | --- | --- |
| `incoming`, `incoming_instance_id` | no | Monster entering the field. |
| `incoming_owner_instance_id`, `incoming_is_player` | yes | `null` when the owner is unknown. |
| `outgoing`, `outgoing_instance_id` | yes | `null` for forced replacements; the fainted monster is not identified. |
| `forced` | no | Boolean. |

### `monster_snapshot`
| Field | Optional | Notes |
| --- | --- | --- |
| `snapshot_phase` | no | `decision`, `before_rewards`, `after_rewards`, or `final`. |
| `monsters` | no | List of monster objects (below). May be empty. |

Monster object:

| Field | Optional | Notes |
| --- | --- | --- |
| `instance_id`, `slug`, `level` | no | |
| `current_hp`, `max_hp`, `hp_ratio`, `fainted` | no | `hp_ratio` comes from `Monster.hp_ratio`. |
| `owner_slug`, `owner_instance_id`, `is_player` | yes | `null` when the monster has no owner. |
| `statuses` | no | List of slugs, possibly empty. |

### `battle_ended`
Required: `outcome`, one of `win`, `loss`, `draw`, `escaped`, `unknown`.
Written once per battle.
