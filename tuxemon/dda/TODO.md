# DDA: Implementation Roadmap

## Objective and Scope

Implement adaptive difficulty using MAPE-K and fuzzy logic in Tuxemon.
Start with single battles against trainers; expand only after validating the
prototype. Inference estimates combat pressure/challenge, not player skill
directly.

Planned modes: disabled (original AI), observation (analysis without adaptation),
and active (bounded adjustments). Do not change the player's monsters,
inventory, rewards, or damage rules as part of the first prototype.

## Planned Structure

```text
tuxemon/dda/
		__init__.py
		telemetry.py
		indicators.py
		fuzzy.py
		policy.py
		adapters.py
		controller.py
		knowledge.py
		TODO.md

mods/
		dda.yaml

tests/tuxemon/
		test_telemetry.py
		test_dda_indicators.py
		test_dda_fuzzy.py
		test_dda_policy.py
		test_dda_adapters.py
		test_dda_controller.py
```

Create files as needed, reusing existing helpers and tests. This tree is the
planned structure, not a list of files already implemented.

| Module | Responsibility | MAPE-K |
| --- | --- | --- |
| telemetry.py | Observations and JSONL export | Monitor |
| indicators.py | Initial baseline and normalized signals | Monitor/Analyze |
| fuzzy.py | Membership degrees, rules, inference, and defuzzification | Analyze |
| policy.py | Adjustment selection, bounds, and stability | Plan |
| adapters.py | Applying adjustments to the game's AI | Execute |
| controller.py | Coordination and per-battle lifecycle | Orchestration |
| knowledge.py | Validated configuration and bounded history | Knowledge |
| mods/dda.yaml | Versioned rules, bounds, and parameters | Knowledge |

Flow: observation -> indicators -> fuzzy inference -> policy -> adapter.
The controller coordinates the flow; knowledge provides configuration and
history. Indicators, fuzzy inference, and policy must not depend on graphical
interfaces.

## 1. Monitor: Consolidate Telemetry

- [x] Record battle start, actions, snapshots, and outcome with a battle ID.
- [x] Identify monsters and owners by ID, distinguishing player and opponent.
- [x] Distinguish techniques, items, and statuses in actions.
- [x] Separate decision, before_rewards, after_rewards, and final snapshots.
- [x] Test JSONL, real health properties, decisions, single finalization,
	and preservation of the state before rewards.
- [x] Inspect a real victory log with the corrected phases.
- [ ] Validate real defeat, escape, item-use, and switching logs.
- [ ] Define a versioned event contract and document optional fields.
- [ ] Define actions as execution attempts; do not confuse them with hits,
	damage dealt, effective healing, or confirmed item consumption.
- [ ] Identify the item user's team by trainer ID; do not rely only on the
	target's owner, who may receive an opponent's action.
- [ ] Provide in-memory observations to the controller during battle,
	without waiting for the JSONL file written at the end.
- [ ] Ensure recorded data is isolated: later payload mutations must not
	change earlier observations.
- [ ] Harden writing: prevent truncation on repeated writes, partial files,
	silent data loss on failure, and unsafe use of IDs as paths.
- [ ] Bound memory/history and handle aborted battles or game shutdown
	without blocking combat or duplicating final events.

Completion: a stable contract, coverage of in-scope scenarios, and telemetry
failures that do not change combat logic or prevent the battle from continuing.

## 2. Indicators: Next Step

- [ ] Create CombatIndicators and an extractor with typed inputs and outputs.
- [ ] Fix the initial baseline per battle and separate teams by identity,
	never by list order or species slug alone.
- [ ] Define baseline membership; monsters already fainted at the start
	do not count as new defeats or available resources.
- [ ] Calculate each team's health reserve: total current HP / total maximum
	HP of baseline members, retaining newly fainted members in the denominator.
- [ ] Calculate availability: initially fit members still fit /
	initially fit members.
- [ ] Calculate level advantage from the initially fit teams and define
	a justified normalization; level does not represent overall strength.
- [ ] Handle empty teams, zero maximum HP, missing data, unknown owners,
	duplicate IDs, and inconsistent values without NaN or misleading inference.
- [ ] Distinguish decision, reward, and final phases; before_rewards occurs
	per reward application, not necessarily only at the end of the battle.
- [ ] Separate reward-induced HP/level changes from combat changes.
	Net HP change is not equivalent to damage per action.
- [ ] Define how to handle added/removed members and maximum HP changes
	during battle while preserving an interpretable baseline.
- [ ] Reuse the extractor for live processing and offline JSONL replay.
- [ ] Test known calculations, asymmetric teams, repeated species,
	initially fainted members, rewards, and incomplete inputs.

Completion: identical events produce identical live/offline indicators,
with documented units, denominators, and bounds.

## 3. Analyze: Fuzzy Inference

- [ ] Choose a few initial inputs: health reserves and availability;
	justify additional inputs before expanding the rule base.
- [ ] Select and document the inference and defuzzification models.
- [ ] Evaluate an existing library (for example, scikit-fuzzy) with a small
	compatibility check; declare dependencies only when adopted.
- [ ] Define versioned universes and overlapping membership functions.
- [ ] Define a numeric output and low, moderate, and high pressure terms.
- [ ] Cover combinations such as both sides healthy, both weakened, player
	advantage, and player disadvantage, without classifying by HP alone.
- [ ] Handle no activated rules and insufficient data with an explicit,
	safe result rather than an arbitrary adjustment.
- [ ] Return membership degrees and activated rules to explain each result.
- [ ] Calibrate parameters across multiple battles, not a single victory.
- [ ] Test boundaries, overlaps, rule coverage, finite values, determinism,
	and expected trends in controlled scenarios.

Completion: reproducible, explainable inference validated without changing
the game.

## 4. Knowledge: Configuration and History

- [ ] Create a validated dda.yaml schema: version, modes, inputs, rules,
	bounds, intervals, and eligible trainers.
- [ ] Separate immutable configuration from battle state and recent history.
- [ ] Bound the history window and define resets between battles/sessions.
- [ ] Record the configuration version used in each experiment.
- [ ] Reject invalid rules/references and use disabled or observation mode
	on failure, with clear diagnostics.
- [ ] Test incomplete YAML, inverted bounds, unknown versions, and isolation
	between two battles.
- [ ] Decide whether cross-session persistence is needed; do not change the
	save format without a requirement and compatibility tests for old saves.

## 5. Controller: Observation Mode

- [ ] Create one controller per battle, shared by the monsters' AI instances.
- [ ] Run at the selected decision point, once per turn, before trainer
	decisions; document execution order relative to effects and menus.
- [ ] Emit dda_analysis with indicators, membership degrees, rules, output,
	mode, and configuration version, without applying adjustments.
- [ ] Reset state at the end and prevent duplicate analyses.
- [ ] Define local failure behavior: log the error and retain the original AI,
	without hiding combat errors unrelated to DDA.
- [ ] Test observation without mutations, repeated turns, resets, missing
	data, and indicator equivalence during replay.

## 6. Plan: Stable Policy

- [ ] Define DifficultyProfile and plans to maintain, increase, or reduce
	challenge.
- [ ] Relate estimated pressure to a justified target range, without treating
	every victory as a reason to increase difficulty.
- [ ] Apply hysteresis, a minimum interval, per-adjustment limits, and absolute
	bounds.
- [ ] Smooth signals/history only when necessary and justified.
- [ ] Do not adapt with insufficient evidence, outside the scope, or for
	excluded trainers; respect already committed/scheduled actions.
- [ ] Emit dda_plan with justification and previous/proposed profiles.
- [ ] Test oscillation, saturation, cooldown, and no-adjustment cases.

## 7. Execute: AI Adapters

- [ ] Choose an initial trainer behavior parameter and verify that changing
	it actually changes challenge before adding others.
- [ ] Connect DifficultyProfile to technique/target selection or item use,
	preserving valid actions and actual resource availability.
- [ ] Account for trainer-specific rules and random decision paths:
	not all trainers use the same weights or evaluators.
- [ ] Do not modify shared cached YAML objects; use battle-local parameters
	and restore them at the end.
- [ ] Do not change player attributes or rewrite actions in progress.
- [ ] Emit dda_applied with effective parameters, not just the proposed plan.
- [ ] Test disabled-mode equivalence to the original AI, bounds, unavailable
	techniques, exhausted items, and absence of state leakage between battles.

## 8. Integration, Fixes, and Evaluation

- [ ] Validate the complete cycle in disabled, observation, and active modes.
- [ ] Cover victory, defeat, escape, items, switches, statuses, pending actions,
	intermediate rewards, and loading a save followed by a battle.
- [ ] Check for battle-environment regressions when loading saves; map events
	must define the correct environment without an arbitrary generic fallback.
- [ ] Keep reproductions and tests for each discovered bug; distinguish unit
	tests from manual validation of the complete workflow.
- [ ] Measure per-turn overhead, log sizes, and controller stability.
- [ ] Create offline replay/reporting tools, reusing existing scripts where
	possible, without mixing research tools with combat runtime code.
- [ ] Define an evaluation protocol: fixed difficulty as the baseline and DDA
	with frozen parameters during evaluation data collection.
- [ ] Separate calibration battles from those used to evaluate results.
- [ ] Control teams, encounters, progression, randomness, and test order;
	consider a simple threshold baseline to justify fuzzy logic.
- [ ] Compare outcomes, duration in turns, resources, and adjustments;
	collect perceived challenge and fairness when participants are involved.
- [ ] Do not use timestamps containing animations/menus as pure decision time,
	or win rate alone as evidence of an improved experience.
- [ ] Define consent, privacy, and institutional ethics requirements before
	collecting participant data; do not commit personal gameplay data.
- [ ] Document architecture, formulas, rules, adopted dependencies, protocol,
	results, limitations, and reproduction instructions in the thesis.

## Delivery Order and Completion

1. Consolidate Monitor and implement tested indicators.
2. Implement fuzzy inference and configuration; validate through offline replay.
3. Integrate the controller in observation mode without changing decisions.
4. Implement the policy and one adapter; validate controlled active mode.
5. Fix regressions, calibrate, and freeze the experimental configuration.
6. Evaluate against the baseline and complete documentation and reproduction.

The project is complete when the full cycle works within the agreed scope,
known failures have handling/tests, adjustments are explainable and bounded,
and evaluation answers the research question. Improving the experience is a
hypothesis to test, not a guaranteed outcome of using fuzzy logic/MAPE-K.

## Local Validation

With the project environment and test dependencies installed:

```powershell
& .\.venv\Scripts\python.exe -m pytest -o addopts='' -q tests/tuxemon/test_telemetry.py
```

Also run focused tests for each new module and the checks required by the
repository. Restart the game after changes and inspect a new JSONL file;
old files do not change retroactively.
