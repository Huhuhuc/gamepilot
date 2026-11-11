# Task Suite Smoke Record

Date: 2026-11-10

This run verifies that each task can be graded in the real Godot game and that random and rule policies share the same task and seed. It is a one-seed integration smoke, not a statistically meaningful policy comparison.

Command:

```powershell
.\.venv\Scripts\python.exe -m gamepilot.experiment evaluate-tasks --episodes 1 --start-seed 2000 --output runs/audit-task-matrix-20261110
```

Results at seed `2000`:

| Task | Random | Rule | Rule episode facts |
|---|---:|---:|---|
| `collect_and_survive` | 0/1 | 1/1 | 1 pickup, 60.02 s, 0 damage, 50 kills |
| `kill_target` | 0/1 | 1/1 | 20 kills at 29.47 s, 0 damage |
| `survive_60` | 0/1 | 1/1 | 60.02 s, 0 damage, 50 kills |
| `survive_damage_limit` | 0/1 | 1/1 | 60.02 s, 0 damage, 50 kills |

The random policy died before the survival objectives; for the damage-limit task it also exceeded the limit. All eight runs had valid episode evidence and no execution errors. The separate rule-policy boundary smoke at seed `2010` completed `survive_damage_limit` with exactly 2 damage, confirming that the inclusive limit passes.

The run output is local under ignored `runs/`. Task configuration hashes, per-episode records, traces, CSV, and HTML report are retained there. Re-run with the recorded code revision if action-level replay is needed.

Keep any future performance statement based on larger, frozen seed sets (at least the task definitions' default 30 episodes), and report all episodes and invalid runs.
