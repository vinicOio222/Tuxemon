# Fuzzy inference

The first inference version estimates relative combat pressure for a single
trainer battle. It does not estimate player skill and does not change game
decisions. Its schema and fuzzy semantics are version 1, selected by
`DDASettings.version`.

## Inputs and universes

The extractor supplies four normalized resource indicators in `[0, 1]`:
player and opponent health reserve, and player and opponent availability.
For this first model, each side's two indicators are combined with equal
weight:

`team strength = (health reserve + availability) / 2`

This keeps the rule base to two inputs while still accounting for both
resource signals. Equal weighting is a provisional modeling assumption, not
an empirically established fact. Level, battle duration, outcomes, and other
signals are excluded until their value and normalization can be justified.

Both team strength and output pressure use the version-1 universe `[0, 1]`.
The overlapping membership functions are:

- `low`: `max(0, 1 - 2x)`
- `moderate`: `max(0, 1 - abs(2x - 1))`
- `high`: `max(0, 2x - 1)`

The middle term is triangular; low and high are shoulder functions. Adjacent
terms overlap on `[0.0, 0.5]` and `[0.5, 1.0]`, respectively, and their
degrees sum to 1 throughout the universe.

## Inference and output

`MamdaniFuzzyMachine` applies the configured rules with minimum for
antecedent conjunction and implication, and maximum to aggregate output
terms. It defuzzifies the aggregated low/moderate/high pressure memberships
using a sampled centroid, including both endpoints of the output universe.
The number of intervals is campaign-configurable as `fuzzy.centroid_steps`
(10–10,000); the game mod currently uses 100.

Low pressure means the player is relatively advantaged; high pressure means
the opponent is relatively advantaged. When both sides have similar resource
strength, the configured rule base produces moderate pressure. The active
campaign rule base must define each of the nine low/moderate/high team-strength
combinations exactly once. Configuration validation rejects missing or
duplicated combinations.

`FuzzyResult` includes input and team-strength membership degrees, output-term
activation degrees, activated rule names, and the crisp pressure. Missing,
invalid, or out-of-range indicators, and an evaluation with no activated
rules, produce `pressure=None` and an explicit `unavailable_reason`; callers
must not interpret that result as a difficulty adjustment.

## Dependency and calibration status

The project environment does not have `scikit-fuzzy` installed, and the
project does not declare it as a dependency. The current implementation keeps
the required min/max Mamdani operations and sampled centroid local, avoiding a
new runtime dependency. Unit tests cover the specified membership boundaries,
overlap, rule coverage, deterministic output, finite bounds, unavailable
inputs, and expected pressure trends. A direct compatibility comparison
against an external fuzzy library has not been run.

The equal weighting, membership breakpoints, and rule outputs remain initial
parameters. They require calibration across multiple battles and must not be
treated as validated by the controlled unit scenarios alone.
