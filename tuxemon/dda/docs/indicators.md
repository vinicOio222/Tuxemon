# Battle indicators

The extractor in [`indicators.py`](../indicators.py) and the model in
[`player_model.py`](../player_model.py) describe observed battle resources; they
do not estimate player skill or decide difficulty. The initial prototype
targets single trainer battles. No fuzzy inference or AI adjustment is
performed by these components.

## Baseline and formulas

The baseline is the snapshot at the first decision of turn 1. Each team's
baseline members are the monsters on that team that were not fainted in that
snapshot. Monsters are identified by instance ID, not species or list position.
For each baseline member, a later snapshot supplies the current HP, current
maximum HP and fainted state:

- **Health reserve** = sum of current HP / sum of current maximum HP.
- **Availability** = number currently not fainted / number of baseline members.

Both values are in `[0, 1]`. Members that faint during battle remain in both
denominators; members already fainted at baseline are excluded even if revived.
An empty initially available team is unavailable rather than a zero-valued
indicator. The two teams' values are kept separately.

These are current resources, not damage or healing totals. In particular,
level-up and other reward effects are included: when maximum HP changes, the
new maximum is used. A change in the ratio can therefore reflect a reward
instead of combat. Snapshot phases (`decision`, `before_rewards`,
`after_rewards` and `final`) distinguish when each measurement was made;
`before_rewards` can occur multiple times. Comparing snapshots does not
isolate reward effects or establish damage per action.

## Battle records and availability

The player model retains the most recent successfully processed snapshot,
including its turn and phase. A consumer must check those fields before using
it for a decision: it is not automatically refreshed after every action.
`player_fainted` and `opponents_fainted` count distinct initially available
monsters observed fainted in snapshots, even if later revived. If a monster
faints and revives between snapshots, this count can miss that event.

The model rejects missing or invalid HP, IDs, team or owner data, duplicate
IDs, and inconsistent fainted states. A changed roster invalidates indicators
for the rest of that battle, even if the original roster returns. A capture
is treated as the existing special case: the captured monster remains assigned
to its baseline team for these calculations.

On an invalid snapshot the current record is cleared, the reason is logged
and exposed as `PlayerIndicators.unavailable_reason`. A later valid snapshot
can recover, except after a roster change. An aborted battle or a battle
without a valid final snapshot is not added to the recent battle history;
an earlier snapshot is not silently relabeled as the final result. Outcomes
and average turns in that history therefore cover **only battles with valid
final indicators**, not every battle played.

The recorder may omit events after its buffer limit. Its `dropped_events`
metadata identifies an incomplete JSONL, which must not be used as a complete
replay. A test replays a complete JSONL through the same player model and
compares the result at each event. No general offline replay tool is provided.

## Scope and next steps

The available values are resource measurements. Turn count and observed
faint counts remain on `BattleRecord`; victory/loss history remains in
`PlayerIndicators`, rather than being duplicated in `CombatIndicators`.
Level advantage is deliberately deferred: level alone is not overall monster
strength, and no normalization has yet been justified. Separate experiments
are needed before choosing additional inputs or calibrating fuzzy rules.
