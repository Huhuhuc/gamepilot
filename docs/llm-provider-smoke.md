# Ollama JSON Schema Smoke

Run date: 2026-11-14 (Asia/Hong_Kong)  
Provider/model: Ollama `qwen3:4b`  
Task/seed: `kill_target` v1 / 2000  
Code fingerprint: `5982c791763b9750cce97401bdea6378d1a118f7d0fcb945dde41f9f263ca668`

## Result

The model returned four JSON actions that passed the runner's strict action validation. The runner executed all four actions in the real Godot game, advancing game time to 0.267 seconds. The fifth model response brought reported per-episode usage above the configured 6,000-token budget, so the runner stopped before executing that response and marked the episode `invalid` with `agent_token_budget_exhausted`.

| Metric | Value |
|---|---:|
| Valid executed actions | 4 |
| Model requests | 5 |
| Prompt tokens | 6,708 |
| Completion tokens | 111 |
| Model latency | 4.45 s total |
| Game time advanced | 0.267 s |
| Kills | 0 |
| Episode status | Invalid: token budget exhausted |

Raw outputs are in `runs/qwen3-4b-jsonschema-smoke-20261114-v2/`. The first response was slower while the local model loaded; subsequent responses were faster. Usage counters include the rejected fifth response, because the provider reports its token use only after generation.

## What This Verifies

- The Ollama `/api/chat` JSON Schema request is accepted by the installed model.
- Model JSON is parsed and checked by the runner before it becomes a game action.
- Valid actions reach the real Godot environment.
- A budget overrun stops the episode and is surfaced as an invalid reason in JSON and HTML reports.

This is a protocol and runner integration smoke only. The episode did not complete `kill_target`, is not an eligible game outcome, and provides no evidence that the model can complete the task or outperform a baseline. Do not quote it as a success rate or capability result.
