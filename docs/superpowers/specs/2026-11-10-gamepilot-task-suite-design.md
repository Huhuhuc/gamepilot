# GamePilot Task Suite and Evaluation Design

Date: 2026-11-10
Status: Implemented and smoke-verified on 2026-11-10. The full test suite passes; one-seed real-Godot task matrix is recorded in `docs/task-suite-smoke.md` and is not a performance claim.

## Goal

Extend GamePilot from difficulty-based episode evaluation into a small, reusable suite of deterministic game tasks. The suite must give each task an explicit setup, objective, deadline, success/failure rule, and comparable results for random, rule-based, and PPO policies. This is the first milestone before building the separate LLM game-task Agent.

## Game Scope

The only game environment in this work is the user's Godot 2D survival shooter **《冥日芳粥：肿么滴 demo》**, repository `Huhuhuc/2dshootgame`, pinned source commit `1ce73ad946302e61e87060d4a9a3ef44d4af106a`. GamePilot's local copy and original game mechanics remain the environment. Do not substitute Kiana Combat, the side-scrolling game, or a synthetic Python game.

This milestone evaluates policies on task definitions; it does not introduce multi-task PPO training, change PPO reward weights, or add an LLM. Existing `easy` and `original` training/evaluation commands remain usable.

## Task Set

Store versioned task definitions as JSON under `tasks/`. Each definition includes a stable task ID and version, human-readable title, environment difficulty, episode time limit, objective parameters, success rule, failure rule, and the expected deterministic seed range. Reject unknown task types, missing fields, invalid thresholds, and unsupported difficulty values before launching Godot.

Initial tasks:

- `survive_60`: survive the original 60-second round.
- `kill_target`: reach a configured kill count before the 60-second deadline.
- `survive_damage_limit`: survive the round while staying at or below a configured damage limit.
- `collect_and_survive`: collect at least one configured pickup and survive the round.

The suite is intentionally small. Task definitions describe goals and evaluation criteria; they do not yet alter the observation vector or PPO reward. This makes the first results comparable with the existing policies and keeps reward shaping as a separate experiment.

## Evaluation Flow

The evaluator loads and validates a task file, freezes its content hash, and evaluates each requested policy on the same task and seed set. Policies remain random, rule-based, or a loaded PPO model. Evaluation records must include task ID/version/hash, code hash, policy/model hash, seed, environment difficulty, outcome, objective status, failure reason, elapsed game time, remaining health, damage, kills, pickup count, reward, wall-clock duration, and trace location.

Aggregate reports group results by task and policy. They report success count/rate, mean and median completion time, mean damage and kills, failure-reason counts, and runtime. Preserve per-episode rows and traces. Do not merge different task definitions or code hashes into one comparison, select test seeds based on results, or treat a training reward as a task score.

## Task Outcomes and Environment Semantics

Task success and failure are separate from Gymnasium episode termination:

- A task objective becoming true marks task success. If the objective is reached before the environment's natural end, the evaluator may stop that episode and record task completion; survival objectives requiring the full round only succeed at the configured duration.
- Player death, exceeding a damage limit, or reaching a task deadline without meeting the objective marks task failure with a specific reason.
- Godot natural termination remains `terminated`; an external step cap remains `truncated`; communication errors remain execution errors and are excluded from game success/failure denominators.
- For `collect_and_survive`, record collected-pickup events from the game session, not the number of pickups remaining on screen. A pickup event increments at most once per pickup.
- Threshold comparisons are inclusive where stated (`kills >= target`, `damage <= limit`, `elapsed >= duration`).

Task evaluation must not add reward shaping or grant strategies extra observations. Random, rule, and PPO policies retain the same action space, observation, world setup, and seed sequence for each comparison.

## Architecture

- `tasks/*.json`: versioned task declarations and stable IDs.
- Python task loader/validator: validates task definitions and provides a canonical task hash.
- Godot session: accepts task environment parameters when needed and reports authoritative episode events, including pickup collection count; continue to own the game simulation.
- Task evaluator: pure Python logic that maps episode info and task config to success/failure and a reason, independently testable without Godot.
- Experiment runner: runs selected policies against task/seed matrices and writes JSON/CSV plus a compact HTML report.
- Existing legacy difficulty evaluation remains available during migration.

Do not copy the combat simulation into Python. Do not add a visual frontend, multi-process execution, curriculum training, online leaderboards, or cloud services in this milestone.

## Failure Handling and Data Integrity

Invalid task configuration fails before process launch. Godot errors, protocol disconnects, and invalid observations remain execution errors, not task losses. Keep partially completed experiment output and mark interrupted runs; never silently overwrite output directories. Store canonical task configuration, software/code hash, and seed with each run so old results remain interpretable after task changes.

Task success is computed from game events and final episode state, not an LLM judge or the reward sum. If required task evidence is absent, mark the episode invalid/incomplete rather than infer success.

## Verification

Unit tests cover task schema validation, stable hashes, inclusive thresholds, each success/failure path, deadline and death precedence, damage-limit failure, pickup counting, and separation of task outcome from `terminated`/`truncated`/execution error.

Integration tests use the real Godot process to verify task reset parameters, pickup collection reporting, at least one successful and one failed task, fixed-seed repeatability, trace replay, and same-seed policy matrix integrity. Retain all current environment tests.

Before claiming policy performance, run every policy on the same frozen seeds for each task and publish all episodes. Existing one-task historical metrics remain historical and must not be relabeled as task-suite results.

## Delivery Order

1. Validate task schema and implement pure task outcome evaluation.
2. Add authoritative pickup event counting and task configuration to the Godot/Python episode contract.
3. Extend the experiment runner and reports while preserving existing difficulty-based commands.
4. Add unit and real-Godot integration tests, then run the frozen task/seed comparison.
5. Update README, task examples, interview notes, and resume claims using only verified results.
6. After GamePilot task-suite acceptance, create a separate design and implementation plan for the LLM game-task Agent and benchmark, reusing the task IDs and graders without mixing it into the PPO codebase.

## Acceptance Criteria

- Four versioned task definitions load and validate; invalid definitions fail before Godot starts.
- Each task has deterministic success/failure rules and an independently tested evaluator.
- Random, rule, and PPO can be evaluated on the same task/seed matrix with task-level metrics and episode traces.
- Pickup tasks use collected-item events and pass an integration test.
- Environment terminal, truncation, and execution-error semantics remain unchanged and are separately represented from task outcome.
- Existing training/evaluation commands and all existing tests continue to work.
- README accurately distinguishes this task-evaluation milestone from multi-task training and from the future LLM Agent project.
