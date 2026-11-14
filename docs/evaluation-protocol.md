# Evaluation Protocol

## Task Policy Comparison

Use the task JSON as the frozen objective source. A comparison must use identical task ID/version/hash and seed list for random, rule, PPO (when a trained model is available), and LLM policies. Do not choose seeds after looking at model results.

For non-LLM policies:

```powershell
.\.venv\Scripts\python.exe -m gamepilot.experiment evaluate-tasks --task-id kill_target --episodes 30 --start-seed 2000 --output runs/rule-random-kill-v1
```

For the LLM policy, configure a provider/model and repeat the same task/seed arguments:

```powershell
.\.venv\Scripts\python.exe -m gamepilot.experiment evaluate-llm --task-id kill_target --episodes 30 --start-seed 2000 --output runs/llm-kill-v1
```

Then validate and report the paired comparison:

```powershell
.\.venv\Scripts\python.exe -m gamepilot.experiment compare-task-runs --baseline runs/rule-random-kill-v1/results.json --llm runs/llm-kill-v1/results.json --task-id kill_target --baseline-policy rule --output runs/paired-kill-v1
```

The comparison command refuses different task hashes, missing/duplicate seeds, and unequal seed sets. It reports Wilson intervals for per-policy success rates, plus the paired success-rate difference among seeds where both episodes have a valid game outcome. Invalid and incomplete episodes do not become losses; their counts remain visible. Paired wins/losses and the rate delta are descriptive only, with no p-value or claim of statistical significance.

Each command refuses to overwrite an existing output directory. Keep each policy's output with the task hash, code hash, model identity, and run date. Do not combine data across code or task hashes without an explicit migration.

For LLM runs, also keep `history_window`, `max_repeat`, per-call completion limit, request/token budgets, and provider timeout from `results.json` with the benchmark. These settings change the agent's context and interaction budget, so comparisons must hold them fixed when measuring model or prompt changes.

## Metrics

- Task success rate is `success / (success + failure)`. Invalid provider/engine runs and externally truncated episodes are excluded and reported separately.
- Include failure reasons, completion time, damage, kills, pickups, request count, latency, and provider-reported token counts.
- Report invalid-episode rate beside task success rate. A model that frequently times out must not look artificially strong because failed requests disappeared from the denominator.
- Preserve invalid reasons separately from game failure reasons; budget exhaustion, provider errors, and execution faults are not game losses.
- Model requests are counted before transport, so failed HTTP calls and repair attempts are included.
- Token budgets use provider-reported usage. Providers that omit token usage are still bounded by request and timeout limits; do not infer unreported tokens.
- A one-seed run is an integration smoke only. Use the task's default 30 episodes as a first comparison set, then add seeds for uncertainty analysis before making broad capability claims.

## Current Evidence

`docs/task-suite-smoke.md` records one real-Godot seed for each task and random/rule policy. A separate adapter smoke used rule logic behind the LLM tool interface. Those runs validate environment integration and grader behavior only; they do not measure an LLM model and do not establish general policy performance.
