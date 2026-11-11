"""Versioned game-task definitions and deterministic outcome grading."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any


TASK_DIR = Path(__file__).resolve().parents[1] / "tasks"
OBJECTIVE_TYPES = {"survive_seconds", "kills", "pickups"}


@dataclass(frozen=True)
class Objective:
    type: str
    target: float


@dataclass(frozen=True)
class TaskSpec:
    task_id: str
    version: int
    title: str
    difficulty: str
    deadline_seconds: float
    objectives: tuple[Objective, ...]
    max_damage: int | None
    start_seed: int
    episodes: int
    sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {"task_id": self.task_id, "version": self.version, "title": self.title,
                "difficulty": self.difficulty, "deadline_seconds": self.deadline_seconds,
                "objectives": [{"type": item.type, "target": item.target} for item in self.objectives],
                "constraints": {"max_damage": self.max_damage} if self.max_damage is not None else {},
                "evaluation": {"start_seed": self.start_seed, "episodes": self.episodes},
                "sha256": self.sha256}


def _number(value: Any, name: str, *, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")
    result = float(value)
    if not minimum <= result < float("inf"):
        raise ValueError(f"{name} must be finite and >= {minimum}")
    return result


def load_task(path: str | Path) -> TaskSpec:
    """Load one task JSON and reject unknown/ambiguous fields before Godot starts."""
    source = Path(path)
    raw_bytes = source.read_bytes()
    data = json.loads(raw_bytes.decode("utf-8"))
    required = {"task_id", "version", "title", "difficulty", "deadline_seconds",
                "objectives", "constraints", "evaluation"}
    if not isinstance(data, dict) or set(data) != required:
        raise ValueError(f"task fields must be exactly: {', '.join(sorted(required))}")
    task_id = data["task_id"]
    if not isinstance(task_id, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{1,63}", task_id):
        raise ValueError("task_id must be a stable lowercase identifier")
    if type(data["version"]) is not int or data["version"] < 1:
        raise ValueError("version must be a positive integer")
    if not isinstance(data["title"], str) or not data["title"].strip():
        raise ValueError("title is required")
    if data["difficulty"] not in ("original", "easy"):
        raise ValueError("difficulty must be original or easy")
    deadline = _number(data["deadline_seconds"], "deadline_seconds", minimum=0.001)
    if deadline > 600:
        raise ValueError("deadline_seconds must be <= 600")

    objectives_data = data["objectives"]
    if not isinstance(objectives_data, list) or not objectives_data:
        raise ValueError("at least one objective is required")
    objectives = []
    for item in objectives_data:
        if not isinstance(item, dict) or set(item) != {"type", "target"}:
            raise ValueError("each objective must contain only type and target")
        kind = item["type"]
        if kind not in OBJECTIVE_TYPES:
            raise ValueError(f"unsupported objective type: {kind}")
        target = _number(item["target"], f"{kind}.target", minimum=0.001)
        if kind in ("kills", "pickups") and not target.is_integer():
            raise ValueError(f"{kind}.target must be an integer")
        if kind == "survive_seconds" and target > deadline:
            raise ValueError("survive_seconds target cannot exceed task deadline")
        objectives.append(Objective(kind, target))

    constraints = data["constraints"]
    if not isinstance(constraints, dict) or set(constraints) - {"max_damage"}:
        raise ValueError("constraints may contain only max_damage")
    max_damage = constraints.get("max_damage")
    if max_damage is not None and (type(max_damage) is not int or max_damage < 0):
        raise ValueError("max_damage must be a non-negative integer")

    evaluation = data["evaluation"]
    if not isinstance(evaluation, dict) or set(evaluation) != {"start_seed", "episodes"}:
        raise ValueError("evaluation must contain start_seed and episodes")
    start_seed = evaluation["start_seed"]
    episodes = evaluation["episodes"]
    if type(start_seed) is not int or not 0 <= start_seed <= 2**31 - 1:
        raise ValueError("start_seed must be a non-negative 32-bit integer")
    if type(episodes) is not int or not 1 <= episodes <= 1000:
        raise ValueError("episodes must be between 1 and 1000")
    if start_seed + episodes - 1 > 2**31 - 1:
        raise ValueError("evaluation seed range exceeds 32-bit integer limit")

    canonical = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return TaskSpec(task_id, data["version"], data["title"].strip(), data["difficulty"],
                    deadline, tuple(objectives), max_damage, start_seed, episodes,
                    hashlib.sha256(canonical).hexdigest())


def load_tasks(directory: str | Path = TASK_DIR) -> list[TaskSpec]:
    tasks = [load_task(path) for path in sorted(Path(directory).glob("*.json"))]
    if not tasks:
        raise ValueError(f"no task definitions found in {directory}")
    ids = [task.task_id for task in tasks]
    if len(ids) != len(set(ids)):
        raise ValueError("task IDs must be unique")
    return tasks


def grade_task(task: TaskSpec, info: dict[str, Any], *, terminated: bool = False,
               truncated: bool = False, execution_error: bool = False) -> dict[str, Any]:
    """Grade one episode without conflating task results with environment status."""
    if execution_error:
        return {"status": "invalid", "reason": "execution_error", "completed_at": None}
    if truncated:
        return {"status": "incomplete", "reason": "external_truncation", "completed_at": None}
    try:
        seconds = float(info["seconds"])
        kills = int(info["kills"])
        damage = int(info["damage"])
        pickups = int(info["pickups_collected"])
    except (KeyError, TypeError, ValueError):
        return {"status": "invalid", "reason": "missing_episode_evidence", "completed_at": None}
    if info.get("outcome") == "death" or (terminated and info.get("is_success") is not True):
        return {"status": "failure", "reason": "player_death", "completed_at": seconds}
    if task.max_damage is not None and damage > task.max_damage:
        return {"status": "failure", "reason": "damage_limit", "completed_at": seconds}

    values = {"survive_seconds": seconds, "kills": kills, "pickups": pickups}
    if all(values[objective.type] >= objective.target for objective in task.objectives):
        return {"status": "success", "reason": "objectives_met", "completed_at": seconds}
    if terminated or seconds >= task.deadline_seconds:
        return {"status": "failure", "reason": "deadline", "completed_at": seconds}
    return {"status": "running", "reason": None, "completed_at": None}
