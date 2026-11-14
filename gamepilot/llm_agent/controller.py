"""Task-aware prompting and strict validation for game-control tool calls."""
from __future__ import annotations

from dataclasses import dataclass
import json
import time

from ..tasks import TaskSpec


SYSTEM_PROMPT = """You control a real 2D survival shooter. You MUST call step_game exactly once and return no prose. The environment verifies task success. Direction indices: 0=stay/no shot, 1=right, 2=down-right, 3=down, 4=down-left, 5=left, 6=up-left, 7=up, 8=up-right; screen y increases downward. move and shoot are direction indices, not counts. repeat is the number of identical game actions and must stay within the supplied limit. Use the current structured observation and bounded recent measured outcomes to complete the objective and preserve health. Missing entities are omitted from the nearest-enemy/pickup lists. Enemy and pickup types use names decoded from game enums."""
ENEMY_TYPES = {0: "basic", 1: "shelled", 2: "fast_small", 3: "bomber"}
PICKUP_TYPES = {0: "speed", 1: "rapid_fire", 2: "spiral_shot"}


@dataclass(frozen=True)
class GameAction:
    move: int
    shoot: int
    repeat: int


class AgentDecisionError(RuntimeError):
    def __init__(self, category: str):
        super().__init__(category)
        self.category = category


def observation_summary(obs, info: dict) -> dict:
    values = [float(value) for value in obs]
    if len(values) != 76:
        raise ValueError("GamePilot observation must contain 76 values")
    enemies = []
    for index in range(6):
        row = values[12 + 8 * index:20 + 8 * index]
        if row[6] > 0.5:
            enemies.append({"relative_xy": row[0:2], "relative_velocity": row[2:4],
                            "health_fraction": row[4],
                            "type": ENEMY_TYPES.get(round(row[5] * 3), "unknown"),
                            "collision_radius": row[7]})
    pickups = []
    for index in range(2):
        row = values[60 + 4 * index:64 + 4 * index]
        if row[3] > 0.5:
            pickups.append({"relative_xy": row[0:2],
                            "type": PICKUP_TYPES.get(round(row[2] * 2), "unknown")})
    return {"episode": {key: info.get(key) for key in
                ("seconds", "health", "damage", "kills", "pickups_collected", "reward")},
            "player": {"normalized_xy": values[0:2], "normalized_velocity": values[2:4],
                       "health_fraction": values[4], "invulnerability_fraction": values[5],
                       "shoot_cooldown_fraction": values[6], "remaining_time_fraction": values[7],
                       "speed_buff_fraction": values[8], "rapid_buff_fraction": values[9],
                       "form_buff_fraction": values[10], "shot_pattern_code": values[11]},
            "nearest_enemies": enemies, "nearest_pickups": pickups,
            "wall_distances": values[68:76]}


class TaskAgent:
    def __init__(self, provider, *, max_repeat: int = 60, repair_attempts: int = 1,
                 max_requests_per_episode: int = 60, max_tokens_per_episode: int | None = None,
                 history_window: int = 4):
        if not 1 <= max_repeat <= 120:
            raise ValueError("max_repeat must be between 1 and 120")
        if repair_attempts not in (0, 1):
            raise ValueError("repair_attempts must be 0 or 1")
        if max_requests_per_episode < 1:
            raise ValueError("max_requests_per_episode must be positive")
        if max_tokens_per_episode is not None and max_tokens_per_episode < 1:
            raise ValueError("max_tokens_per_episode must be positive when set")
        if not 0 <= history_window <= 16:
            raise ValueError("history_window must be between 0 and 16")
        self.provider = provider
        self.max_repeat = max_repeat
        self.repair_attempts = repair_attempts
        self.max_requests_per_episode = max_requests_per_episode
        self.max_tokens_per_episode = max_tokens_per_episode
        self.history_window = history_window
        self.reset_episode()

    def reset_episode(self):
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0, "model_requests": 0,
                      "repair_attempts": 0, "model_latency_seconds": 0.0}
        self.history = []

    @staticmethod
    def _memory_snapshot(obs, info):
        state = observation_summary(obs, info)
        return {"seconds": info.get("seconds"), "health": info.get("health"),
                "damage": info.get("damage"), "kills": info.get("kills"),
                "pickups_collected": info.get("pickups_collected"),
                "nearest_enemy_types": [enemy["type"] for enemy in state["nearest_enemies"]],
                "nearest_pickup_types": [pickup["type"] for pickup in state["nearest_pickups"]]}

    def record_transition(self, *, before_obs, before_info, action, after_obs, after_info,
                          grade, executed_repeat):
        if self.history_window == 0:
            return
        before = self._memory_snapshot(before_obs, before_info)
        after = self._memory_snapshot(after_obs, after_info)
        deltas = {}
        for key in ("seconds", "health", "damage", "kills", "pickups_collected"):
            if isinstance(before[key], (int, float)) and isinstance(after[key], (int, float)):
                deltas[key] = after[key] - before[key]
        self.history.append({"action": {"move": action.move, "shoot": action.shoot,
                                         "requested_repeat": action.repeat,
                                         "executed_repeat": executed_repeat},
                             "before": before, "after": after, "delta": deltas,
                             "task_status": grade["status"], "task_reason": grade["reason"]})
        self.history = self.history[-self.history_window:]

    def decide(self, task: TaskSpec, obs, info: dict, *, decision_index: int,
               previous_action: dict | None = None, previous_grade: dict | None = None):
        objectives = [{"type": item.type, "target": item.target} for item in task.objectives]
        request_data = {"task": {"id": task.task_id, "title": task.title,
                                 "deadline_seconds": task.deadline_seconds,
                                 "objectives": objectives, "max_damage": task.max_damage},
                        "decision_index": decision_index,
                        "previous_action": previous_action,
                        "previous_task_status": previous_grade,
                        "recent_history": self.history,
                        "state": observation_summary(obs, info),
                        "tool_limits": {"max_repeat": self.max_repeat}}
        messages = [{"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": json.dumps(request_data, ensure_ascii=False)}]
        total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "latency_seconds": 0.0}
        for attempt in range(self.repair_attempts + 1):
            token_total = self.usage["prompt_tokens"] + self.usage["completion_tokens"]
            if self.usage["model_requests"] >= self.max_requests_per_episode:
                raise AgentDecisionError("request_budget_exhausted")
            if self.max_tokens_per_episode is not None and token_total >= self.max_tokens_per_episode:
                raise AgentDecisionError("token_budget_exhausted")
            started = time.monotonic()
            self.usage["model_requests"] += 1
            if attempt:
                self.usage["repair_attempts"] += 1
            try:
                response = self.provider.call_tool(messages, max_repeat=self.max_repeat)
            finally:
                latency = time.monotonic() - started
                self.usage["model_latency_seconds"] += latency
                total_usage["latency_seconds"] += latency
            total_usage["prompt_tokens"] += response.usage.get("prompt_tokens", 0)
            total_usage["completion_tokens"] += response.usage.get("completion_tokens", 0)
            self.usage["prompt_tokens"] += response.usage.get("prompt_tokens", 0)
            self.usage["completion_tokens"] += response.usage.get("completion_tokens", 0)
            token_total = self.usage["prompt_tokens"] + self.usage["completion_tokens"]
            if self.max_tokens_per_episode is not None and token_total > self.max_tokens_per_episode:
                raise AgentDecisionError("token_budget_exhausted")
            action, error = self._validate(response.tool_name, response.arguments)
            if error is None:
                return action, {**total_usage, "latency_seconds": total_usage["latency_seconds"],
                                "repair_attempts": attempt}
            if attempt == self.repair_attempts:
                raise AgentDecisionError(error)
            messages.extend([{"role": "assistant", "content": response.assistant_message.get("content", "")},
                             {"role": "user", "content": f"Tool call rejected: {error}. Call step_game once using only integer arguments within the declared limits."}])
        raise AgentDecisionError("invalid_tool_call")

    def _validate(self, name: str | None, arguments: object):
        if name != "step_game":
            return None, "missing_or_unknown_tool"
        if not isinstance(arguments, dict) or set(arguments) != {"move", "shoot", "repeat"}:
            return None, "invalid_tool_arguments"
        move, shoot, repeat = arguments["move"], arguments["shoot"], arguments["repeat"]
        if any(type(value) is not int for value in (move, shoot, repeat)):
            return None, "tool_arguments_must_be_integers"
        if not (0 <= move <= 8 and 0 <= shoot <= 8 and 1 <= repeat <= self.max_repeat):
            return None, "tool_argument_out_of_range"
        return GameAction(move, shoot, repeat), None
