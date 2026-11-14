# LLM Game Task Agent Design

Date: 2026-11-10
Status: Ollama JSON Schema and OpenAI-compatible function-calling paths are implemented; 43 automated tests pass. A live `qwen3:4b` smoke executed four valid actions before the 6,000-token episode budget stopped the run; this is protocol evidence, not a task capability result. See `docs/llm-provider-smoke.md`.

## Goal

Build a separate LLM-driven agent that reads the existing task contract, observes the real Godot survival shooter through structured state, and acts through a bounded game-control tool. Evaluate it on the exact same versioned task definitions and frozen seeds as the non-LLM baselines. The goal is to measure whether an LLM can plan and use tools in a game environment, not to train or fine-tune a foundation model.

## Boundaries

- Use only GamePilot's selected Godot survival shooter and its authoritative environment/task grader.
- Keep the LLM agent as a separate package and command path; do not alter PPO training, PPO rewards, or existing policies.
- Support a local Ollama endpoint and an OpenAI-compatible chat-completions endpoint through environment configuration. Never commit API keys or silently fall back to another model.
- First iteration uses the existing 76-dimensional structured observation. It is not a vision agent.
- Model decisions are bounded batches of the existing move/shoot actions. Maximum batch size is configurable and capped, so the evaluator can grade objectives and stop on death between decisions.
- Task outcome comes from the existing deterministic grader; model text and self-reported success are never evidence.

## Runtime Design

1. Load and validate a versioned task before launching Godot.
2. Start one `PilotEnv` for the episode and present the task objective, permitted action schema, and current structured observation to the model.
3. The model requests the `step_game` tool with movement direction, firing direction, and a bounded number of environment decisions to repeat. The runner validates every field and clamps no invalid value silently.
4. Execute the requested actions using the shared `MultiDiscrete([9, 9])` action space. After each environment step, run the deterministic grader and stop immediately on success, failure, truncation, or execution error.
5. Return the tool result as compact game state, objective progress, and the latest event deltas. Keep only a small bounded history; do not store private chain-of-thought.
6. If a tool call is malformed, return a structured validation error and allow one repair request. If the provider times out, returns an API error, or remains invalid, preserve the partial trace and mark the episode invalid rather than a game loss.

## Provider and Tool Contracts

- A provider interface owns HTTP transport, request timeouts, model identification, and response parsing. Ollama uses `/api/chat` with a JSON Schema action format and `options.num_predict`; the runner turns the parsed, validated JSON into the bounded `step_game` action. OpenAI-compatible providers use native function calling with the configured base URL and bearer key.
- Tool arguments are strict JSON with `move` and `shoot` integer indices in `[0, 8]` and `repeat` in `[1, max_repeat]`. No arbitrary Python, shell, filesystem, or network tool is available to the model.
- The runner, not the model, owns reset, seed, environment lifecycle, reward, terminal state, task grading, and output files.
- Logs include provider/model, task hash, code hash, seed, validated tool calls, observations, timing, token usage when provided, and failure category. Secrets and full hidden reasoning are excluded.

## Evaluation

- Run the LLM policy, random policy, rule policy, and optional PPO model against identical task IDs and seed lists. No test-seed selection by result.
- Report task success rate only over valid completed game episodes; report provider/tool failures separately. Also record completion time, damage, kills, pickups, model latency, request count, and token usage where available.
- Retain JSON/CSV/JSONL traces and model/provider configuration with secrets redacted. A live API benchmark requires an explicit run and captures model/version and date because provider behavior changes.
- Unit tests use a local fake HTTP server for tool-call parsing, timeout, HTTP failure, malformed arguments, one repair attempt, and secret redaction. Real Godot integration tests cover early task completion, death, and trace data. Live-provider smoke is documented separately and skipped when no endpoint is available.

## First Release Exclusions

No visual input, browser UI, multi-agent orchestration, model fine-tuning, vector memory, unrestricted tools, background cloud jobs, or claims that an LLM outperforms PPO. The initial deliverable is a bounded and auditable tool-using agent plus a reproducible benchmark.
