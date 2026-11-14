"""Run the bounded LLM policy against real tasks and preserve auditable traces."""
from __future__ import annotations

import json
from pathlib import Path
import time

import numpy as np

from ..env import PilotEnv
from ..tasks import TaskSpec, grade_task
from .controller import AgentDecisionError, TaskAgent
from .provider import ProviderError


def evaluate_episode(agent: TaskAgent, task: TaskSpec, *, seed: int, visible: bool = False,
                     trace_path: str | Path | None = None) -> dict:
    max_steps = int(np.ceil(task.deadline_seconds * 60 / 4)) + 2
    env = None
    started = time.monotonic()
    decisions = []
    actions = []
    rewards = []
    states = []
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "model_requests": 0,
             "repair_attempts": 0, "model_latency_seconds": 0.0}
    agent.reset_episode()
    error_category = None
    terminated = truncated = False
    info = {"seed": seed, "difficulty": task.difficulty, "seconds": 0.0,
            "health": None, "damage": None, "kills": 0, "pickups_collected": 0,
            "reward": 0.0, "outcome": "execution_error"}
    grade = {"status": "invalid", "reason": "execution_error", "completed_at": None}
    try:
        env = PilotEnv(difficulty=task.difficulty, visible=visible, max_steps=max_steps)
        obs, info = env.reset(seed=seed)
        previous_action = previous_grade = None
        decision_index = 0
        while True:
            before_obs = obs.copy()
            before_info = dict(info)
            action, call_usage = agent.decide(task, obs, info, decision_index=decision_index,
                                              previous_action=previous_action,
                                              previous_grade=previous_grade)
            decision_record = {"decision_index": decision_index,
                "move": action.move, "shoot": action.shoot, "requested_repeat": action.repeat,
                **call_usage}
            decision_started = time.monotonic()
            for repeat_index in range(action.repeat):
                obs, reward, terminated, truncated, info = env.step(
                    np.asarray([action.move, action.shoot], dtype=np.int64))
                actions.append([action.move, action.shoot])
                rewards.append(float(reward))
                states.append([info.get(key) for key in
                               ("x", "y", "health", "kills", "pickups_collected", "seconds")])
                grade = grade_task(task, info, terminated=terminated, truncated=truncated)
                if grade["status"] != "running" or terminated or truncated:
                    break
            decision_record["executed_repeat"] = repeat_index + 1
            decision_record["execution_seconds"] = time.monotonic() - decision_started
            decisions.append(decision_record)
            agent.record_transition(before_obs=before_obs, before_info=before_info,
                action=action, after_obs=obs, after_info=info, grade=grade,
                executed_repeat=repeat_index + 1)
            previous_action = {"move": action.move, "shoot": action.shoot,
                               "requested_repeat": action.repeat,
                               "executed_repeat": repeat_index + 1}
            previous_grade = grade
            decision_index += 1
            if grade["status"] != "running" or terminated or truncated:
                break
    except ProviderError as error:
        error_category = "provider_" + error.category
    except AgentDecisionError as error:
        error_category = "agent_" + error.category
    except Exception as error:
        error_category = "execution_" + type(error).__name__
    finally:
        if env is not None:
            env.close()
        usage = dict(agent.usage)

    if error_category is not None:
        grade = {"status": "invalid", "reason": error_category, "completed_at": None}
    row = {"task_id": task.task_id, "task_version": task.version,
           "task_sha256": task.sha256, "seed": seed, "difficulty": task.difficulty,
           "task_status": grade["status"], "task_reason": grade["reason"],
           "task_completed_at": grade["completed_at"], "execution_error": error_category,
           "outcome": info.get("outcome"), "seconds": info.get("seconds"),
           "health": info.get("health"), "damage": info.get("damage"),
           "kills": info.get("kills"), "pickups_collected": info.get("pickups_collected"),
           "reward": info.get("reward"), **usage,
           "wall_seconds": round(time.monotonic() - started, 3)}
    if trace_path:
        trace = {**row, "decisions": decisions, "actions": actions,
                 "rewards": rewards, "states": states,
                 "recent_action_outcomes": agent.history}
        Path(trace_path).write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")
    return row


def evaluate_task_agent(agent: TaskAgent, task: TaskSpec, *, seeds, visible: bool = False,
                        trace_directory: str | Path | None = None) -> dict:
    seeds = list(seeds)
    if not seeds:
        raise ValueError("at least one evaluation seed is required")
    trace_dir = Path(trace_directory) if trace_directory else None
    if trace_dir:
        trace_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for seed in seeds:
        trace_path = trace_dir / f"{task.task_id}-seed-{seed}.json" if trace_dir else None
        rows.append(evaluate_episode(agent, task, seed=seed, visible=visible, trace_path=trace_path))
    eligible = [row for row in rows if row["task_status"] in {"success", "failure"}]
    success = sum(row["task_status"] == "success" for row in eligible)
    return {"task_id": task.task_id, "task_version": task.version, "task_sha256": task.sha256,
            "policy": "llm",
            "episodes": len(rows), "eligible_episodes": len(eligible), "successes": success,
            "success_rate": success / len(eligible) if eligible else None,
            "invalid_episodes": len(rows) - len(eligible),
            "mean_damage": float(np.mean([r["damage"] for r in rows if r["damage"] is not None])) if any(r["damage"] is not None for r in rows) else None,
            "mean_kills": float(np.mean([r["kills"] for r in rows if r["kills"] is not None])) if any(r["kills"] is not None for r in rows) else None,
            "mean_model_latency_seconds": float(np.mean([r["model_latency_seconds"] for r in rows])),
            "total_model_requests": sum(r["model_requests"] for r in rows),
            "total_prompt_tokens": sum(r["prompt_tokens"] for r in rows),
            "total_completion_tokens": sum(r["completion_tokens"] for r in rows),
            "failure_reasons": {reason: sum(r["task_reason"] == reason for r in rows)
                                for reason in sorted({r["task_reason"] for r in rows if r["task_status"] == "failure"})},
            "invalid_reasons": {reason: sum(r["task_reason"] == reason for r in rows)
                                for reason in sorted({r["task_reason"] for r in rows if r["task_status"] == "invalid"})},
            "rows": rows}
