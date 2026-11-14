"""Bounded real-game training, evaluation and action replay."""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import html
import json
from pathlib import Path
import time

import numpy as np

from .env import PilotEnv, ROOT
from .policies import rule_action
from .tasks import TASK_DIR, TaskSpec, grade_task, load_tasks
from .llm_agent.controller import TaskAgent
from .llm_agent.evaluator import evaluate_task_agent
from .llm_agent.provider import ChatProvider, ProviderSettings
from .comparison import compare_task_runs, write_comparison


def fingerprint():
    digest = hashlib.sha256()
    for folder, extensions in [(ROOT / "game", {".gd", ".tscn", ".tres", ".godot"}), (ROOT / "gamepilot", {".py"})]:
        for path in sorted(folder.rglob("*")):
            if path.is_file() and ".godot" not in path.parts and path.suffix in extensions:
                digest.update(str(path.relative_to(ROOT)).replace("\\", "/").encode())
                digest.update(path.read_bytes())
    return digest.hexdigest()


def evaluate(policy, *, model=None, seeds=range(2000, 2030), difficulty="original", visible=False, trace_path=None):
    env = PilotEnv(difficulty=difficulty, visible=visible)
    rows = []
    started = time.monotonic()
    trace = open(trace_path, "w", encoding="utf-8") if trace_path else None
    try:
        for seed in seeds:
            obs, info = env.reset(seed=seed)
            rng = np.random.default_rng(seed + 100000)
            actions = []
            rewards = []
            states = []
            while True:
                action = model.predict(obs, deterministic=True)[0] if policy == "ppo" else rule_action(obs) if policy == "rule" else rng.integers(0, 9, size=2)
                obs, reward, terminated, truncated, info = env.step(action)
                actions.append(np.asarray(action).tolist())
                rewards.append(reward)
                states.append([info[k] for k in ("x", "y", "health", "kills", "seconds")])
                if terminated or truncated:
                    break
            rows.append(info)
            if trace:
                trace.write(json.dumps({"seed": seed, "difficulty": difficulty, "actions": actions, "rewards": rewards, "states": states,
                    "terminal": info["outcome"], "code_sha256": fingerprint()}) + "\n")
        return {"policy": policy, "difficulty": difficulty, "episodes": len(rows),
            "successes": sum(r["is_success"] for r in rows),
            "mean_seconds": float(np.mean([r["seconds"] for r in rows])),
            "mean_kills": float(np.mean([r["kills"] for r in rows])),
            "mean_damage": float(np.mean([r["damage"] for r in rows])),
            "mean_reward": float(np.mean([r["reward"] for r in rows])),
            "wall_seconds": round(time.monotonic()-started, 3), "rows": rows}
    finally:
        env.close()
        if trace:
            trace.close()


def train(args):
    import torch
    from stable_baselines3 import PPO
    from stable_baselines3.common.callbacks import BaseCallback
    from stable_baselines3.common.monitor import Monitor
    torch.set_num_threads(1)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    settings = {"seed": args.seed, "steps_requested": args.steps, "difficulty": args.difficulty,
        "resume": args.resume, "code_sha256": fingerprint(), "created_at": datetime.now(timezone.utc).isoformat(),
        "algorithm": "SB3 PPO", "n_steps": 1024, "batch_size": 64, "n_epochs": 4,
        "ent_coef": 0.01, "learning_rate": 0.0003, "device": "cpu", "action_repeat": 4}
    if args.resume:
        settings["resume_sha256"] = hashlib.sha256(Path(args.resume).read_bytes()).hexdigest()
    (output / "config.json").write_text(json.dumps(settings, indent=2), encoding="utf-8")
    class Validation(BaseCallback):
        def __init__(self):
            super().__init__()
            self.best = float("-inf")
            self.last = 0
        def _on_step(self):
            if self.n_calls - self.last < 10000:
                return True
            self.last = self.n_calls
            result = evaluate("ppo", model=self.model, seeds=range(1000, 1010), difficulty=args.difficulty)
            result["training_steps"] = self.num_timesteps
            with (output / "validation.jsonl").open("a", encoding="utf-8") as file:
                file.write(json.dumps(result) + "\n")
            # Predeclared criterion: survival, then kills. Never select on held-out test seeds.
            score = result["mean_seconds"] + 0.01 * result["mean_kills"]
            if score > self.best:
                self.best = score
                self.model.save(output / "best")
            self.model.save(output / "checkpoint")
            print(json.dumps({"training_steps": self.num_timesteps, "validation_seconds": result["mean_seconds"],
                "validation_successes": result["successes"]}), flush=True)
            return True
    env = Monitor(PilotEnv(difficulty=args.difficulty), str(output / "episodes"))
    started = time.monotonic()
    try:
        if args.resume:
            model = PPO.load(args.resume, env=env, device="cpu")
            model.set_random_seed(args.seed)
        else:
            model = PPO("MlpPolicy", env, seed=args.seed, device="cpu", n_steps=1024,
                batch_size=64, n_epochs=4, ent_coef=0.01, learning_rate=0.0003, verbose=0)
        model.learn(total_timesteps=args.steps, callback=Validation(), reset_num_timesteps=not bool(args.resume))
        model.save(output / "last")
        settings.update(actual_model_timesteps=model.num_timesteps, wall_seconds=round(time.monotonic()-started, 3), status="completed")
        (output / "config.json").write_text(json.dumps(settings, indent=2), encoding="utf-8")
        print(json.dumps(settings), flush=True)
    except BaseException as error:
        settings.update(status="failed", error=type(error).__name__, wall_seconds=round(time.monotonic()-started, 3))
        (output / "config.json").write_text(json.dumps(settings, indent=2), encoding="utf-8")
        if "model" in locals():
            model.save(output / "interrupted")
        raise
    finally:
        env.close()


def comparison(args):
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    model = None
    if args.model:
        import torch
        from stable_baselines3 import PPO
        torch.set_num_threads(1)
        model = PPO.load(args.model, device="cpu")
    result = {"code_sha256": fingerprint(), "seed_range": [args.start_seed, args.start_seed+args.episodes-1],
        "model": str(args.model), "model_sha256": hashlib.sha256(Path(args.model).read_bytes()).hexdigest() if args.model else None,
        "created_at": datetime.now(timezone.utc).isoformat(), "strategies": []}
    policies = [args.policy] if args.policy else ["random", "rule"] + (["ppo"] if model else [])
    if "ppo" in policies and model is None:
        raise ValueError("PPO evaluation requires --model")
    for policy in policies:
        record = evaluate(policy, model=model, seeds=range(args.start_seed,args.start_seed+args.episodes),
            difficulty=args.difficulty, visible=args.visible, trace_path=output / (policy+"-traces.jsonl"))
        result["strategies"].append(record)
        (output / "results.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps({k:v for k,v in record.items() if k != "rows"}), flush=True)
    cells = "".join(f'<tr><td>{html.escape(r["policy"])}</td><td>{r["successes"]}/{r["episodes"]}</td><td>{r["mean_seconds"]:.2f}s</td><td>{r["mean_kills"]:.2f}</td><td>{r["mean_damage"]:.2f}</td></tr>' for r in result["strategies"])
    page = '<!doctype html><html lang="zh"><meta charset="utf-8"><title>GamePilot 评测</title><style>body{background:#f5f0e8;color:#25221e;font:18px system-ui;margin:60px auto;max-width:1000px;padding:24px}h1{border-left:6px solid #c56b32;padding-left:20px}table{width:100%;border-collapse:collapse}td,th{text-align:left;padding:18px;border-bottom:1px solid #d5ccc0}small{color:#6d6256}</style><h1>GamePilot · 真实游戏策略对照</h1><p>基于自有 Godot 射击游戏，结构化观测与固定测试种子。</p><table><tr><th>策略</th><th>通关</th><th>平均存活</th><th>平均击杀</th><th>平均损失生命</th></tr>'+cells+'</table><p>结果只适用于本次模型、游戏配置与种子。PPO 不保证超过手写规则；保留每局失败及动作轨迹。</p><small>配置 / 逐局指标：results.json；动作重放：*-traces.jsonl</small></html>'
    (output / "report.html").write_text(page, encoding="utf-8")


def evaluate_task_policy(policy, task: TaskSpec, *, model=None, seeds, visible=False, trace_path=None):
    seeds = list(seeds)
    if not seeds:
        raise ValueError("at least one evaluation seed is required")
    max_steps = int(np.ceil(task.deadline_seconds * 60 / 4)) + 2
    env = PilotEnv(difficulty=task.difficulty, visible=visible, max_steps=max_steps)
    rows = []
    trace = open(trace_path, "w", encoding="utf-8") if trace_path else None
    started = time.monotonic()
    try:
        for seed in seeds:
            rng = np.random.default_rng(seed + 100000)
            actions, rewards, states = [], [], []
            terminated = truncated = False
            execution_error = None
            info = {"seed": seed, "difficulty": task.difficulty, "seconds": 0.0, "health": None,
                    "damage": None, "kills": 0, "pickups_collected": 0, "reward": 0.0,
                    "outcome": "execution_error"}
            try:
                obs, info = env.reset(seed=seed)
                while True:
                    if policy == "ppo":
                        action = model.predict(obs, deterministic=True)[0]
                    elif policy == "rule":
                        action = rule_action(obs)
                    else:
                        action = rng.integers(0, 9, size=2)
                    obs, reward, terminated, truncated, info = env.step(action)
                    actions.append(np.asarray(action).tolist())
                    rewards.append(float(reward))
                    states.append([info[k] for k in ("x", "y", "health", "kills", "pickups_collected", "seconds")])
                    grade = grade_task(task, info, terminated=terminated, truncated=truncated)
                    if grade["status"] != "running" or terminated or truncated:
                        break
            except Exception as error:
                execution_error = type(error).__name__
                grade = grade_task(task, {}, execution_error=True)
            row = {**info, "task_status": grade["status"], "task_reason": grade["reason"],
                   "task_completed_at": grade["completed_at"], "execution_error": execution_error, "seed": seed}
            rows.append(row)
            if trace:
                trace.write(json.dumps({"task_id": task.task_id, "task_sha256": task.sha256,
                    "policy": policy, "seed": seed, "actions": actions, "rewards": rewards,
                    "states": states, "task_status": grade["status"], "task_reason": grade["reason"],
                    "execution_error": execution_error, "game_outcome": info.get("outcome"),
                    "code_sha256": fingerprint()},
                    ensure_ascii=False) + "\n")
            if execution_error is not None and seed != seeds[-1]:
                env.close()
                env = PilotEnv(difficulty=task.difficulty, visible=visible, max_steps=max_steps)
        eligible = [r for r in rows if r["task_status"] in ("success", "failure")]
        completed = [r["task_completed_at"] for r in eligible if r["task_status"] == "success"]
        with_damage = [r["damage"] for r in rows if isinstance(r.get("damage"), (int, float))]
        with_kills = [r["kills"] for r in rows if isinstance(r.get("kills"), (int, float))]
        successes = sum(r["task_status"] == "success" for r in eligible)
        return {"task_config": task.to_dict(), "task_id": task.task_id,
            "task_version": task.version, "task_sha256": task.sha256,
            "title": task.title, "difficulty": task.difficulty, "policy": policy, "episodes": len(rows),
            "eligible_episodes": len(eligible), "successes": successes,
            "success_rate": successes / len(eligible) if eligible else None,
            "mean_completion_seconds": float(np.mean(completed)) if completed else None,
            "median_completion_seconds": float(np.median(completed)) if completed else None,
            "mean_damage": float(np.mean(with_damage)) if with_damage else None,
            "mean_kills": float(np.mean(with_kills)) if with_kills else None,
            "failure_reasons": {reason: sum(r["task_reason"] == reason for r in rows)
                                for reason in sorted({r["task_reason"] for r in rows if r["task_status"] == "failure"})},
            "invalid_or_incomplete": sum(r["task_status"] in ("invalid", "incomplete") for r in rows),
            "wall_seconds": round(time.monotonic() - started, 3), "rows": rows}
    finally:
        env.close()
        if trace:
            trace.close()


def task_matrix(args):
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    all_tasks = load_tasks(args.task_dir)
    tasks = [task for task in all_tasks if args.task_id is None or task.task_id == args.task_id]
    if not tasks:
        raise ValueError(f"unknown task_id: {args.task_id}")
    model = None
    model_sha256 = None
    if args.model:
        import torch
        from stable_baselines3 import PPO
        torch.set_num_threads(1)
        model = PPO.load(args.model, device="cpu")
        model_sha256 = hashlib.sha256(Path(args.model).read_bytes()).hexdigest()
    policies = [args.policy] if args.policy else ["random", "rule"] + (["ppo"] if model else [])
    if "ppo" in policies and model is None:
        raise ValueError("PPO task evaluation requires --model")
    result = {"created_at": datetime.now(timezone.utc).isoformat(), "code_sha256": fingerprint(),
        "model_sha256": model_sha256, "tasks": [], "policies": policies}
    for task in tasks:
        seeds = range(args.start_seed if args.start_seed is not None else task.start_seed,
                      (args.start_seed if args.start_seed is not None else task.start_seed) +
                      (args.episodes if args.episodes is not None else task.episodes))
        for policy in policies:
            record = evaluate_task_policy(policy, task, model=model, seeds=seeds,
                visible=args.visible, trace_path=output / f"{task.task_id}-{policy}-traces.jsonl")
            result["tasks"].append(record)
            (output / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps({k: v for k, v in record.items() if k != "rows"}, ensure_ascii=False), flush=True)
    with (output / "episodes.csv").open("w", newline="", encoding="utf-8-sig") as file:
        columns = ["task_id", "task_version", "task_sha256", "policy", "seed", "task_status", "task_reason", "execution_error",
                   "task_completed_at", "outcome", "seconds", "health", "damage", "kills", "pickups_collected", "reward"]
        writer = csv.DictWriter(file, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for record in result["tasks"]:
            for row in record["rows"]:
                writer.writerow({**record, **row})
    report_rows_list = []
    for record in result["tasks"]:
        completion = record["mean_completion_seconds"]
        completion_label = "-" if completion is None else f"{completion:.2f}s"
        rate = record["success_rate"]
        rate_label = "-" if rate is None else f"{rate:.1%}"
        damage = record["mean_damage"]
        damage_label = "-" if damage is None else f"{damage:.2f}"
        kills = record["mean_kills"]
        kills_label = "-" if kills is None else f"{kills:.2f}"
        report_rows_list.append(
            f'<tr><td>{html.escape(record["task_id"])}</td><td>{html.escape(record["policy"])}</td>'
            f'<td>{record["successes"]}/{record["eligible_episodes"]}</td>'
            f'<td>{rate_label}</td><td>{completion_label}</td><td>{damage_label}</td>'
            f'<td>{kills_label}</td></tr>')
    report_rows = "".join(report_rows_list)
    report = ('<!doctype html><html lang="zh"><meta charset="utf-8"><title>GamePilot 任务评测</title>'
        '<style>body{background:#f5f0e8;color:#25221e;font:16px system-ui;margin:48px auto;max-width:1050px;padding:20px}'
        'h1{border-left:5px solid #c56b32;padding-left:16px}table{width:100%;border-collapse:collapse}'
        'td,th{text-align:left;padding:12px;border-bottom:1px solid #d5ccc0}</style>'
        '<h1>GamePilot · 游戏任务对照评测</h1><table><tr><th>任务</th><th>策略</th><th>成功数</th>'
        '<th>成功率</th><th>平均完成时间</th><th>平均受伤</th><th>平均击杀</th></tr>' + report_rows +
        '</table><p>任务成绩独立于环境奖励；无效或截断局不计入任务成功率，逐局数据和轨迹见 JSON/CSV/JSONL。</p></html>')
    (output / "report.html").write_text(report, encoding="utf-8")


def replay(args):
    trace = json.loads(Path(args.trace).read_text(encoding="utf-8").splitlines()[args.episode])
    if trace["code_sha256"] != fingerprint():
        raise ValueError("Replay code hash differs; use the recorded code version")
    env = PilotEnv(difficulty=trace["difficulty"], visible=args.visible)
    try:
        env.reset(seed=trace["seed"])
        for index, action in enumerate(trace["actions"]):
            _, reward, done, truncated, info = env.step(np.array(action))
            np.testing.assert_allclose([info[k] for k in ("x","y","health","kills","seconds")], trace["states"][index], rtol=0, atol=1e-5)
            np.testing.assert_allclose(reward, trace["rewards"][index], rtol=0, atol=1e-8)
        assert done or truncated
        assert info["outcome"] == trace["terminal"]
        print(json.dumps({"replay": "passed", "steps": len(trace["actions"]), "seed": trace["seed"]}))
    finally:
        env.close()


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    training = commands.add_parser("train")
    training.add_argument("--steps", type=int, default=10000)
    training.add_argument("--seed", type=int, default=0)
    training.add_argument("--difficulty", choices=["easy","original"], default="easy")
    training.add_argument("--resume")
    training.add_argument("--output", required=True)
    evaluation = commands.add_parser("evaluate")
    evaluation.add_argument("--model")
    evaluation.add_argument("--policy", choices=["ppo","rule","random"])
    evaluation.add_argument("--episodes", type=int, default=30)
    evaluation.add_argument("--start-seed", type=int, default=2000)
    evaluation.add_argument("--difficulty", choices=["easy","original"], default="original")
    evaluation.add_argument("--visible", action="store_true")
    evaluation.add_argument("--output", required=True)
    playback = commands.add_parser("replay")
    playback.add_argument("--trace", required=True)
    playback.add_argument("--episode", type=int, default=0)
    playback.add_argument("--visible", action="store_true")
    tasks = commands.add_parser("evaluate-tasks")
    tasks.add_argument("--task-dir", default=str(TASK_DIR))
    tasks.add_argument("--task-id")
    tasks.add_argument("--model")
    tasks.add_argument("--policy", choices=["ppo", "rule", "random"])
    tasks.add_argument("--episodes", type=int)
    tasks.add_argument("--start-seed", type=int)
    tasks.add_argument("--visible", action="store_true")
    tasks.add_argument("--output", required=True)
    llm = commands.add_parser("evaluate-llm")
    llm.add_argument("--task-dir", default=str(TASK_DIR))
    llm.add_argument("--task-id")
    llm.add_argument("--episodes", type=int)
    llm.add_argument("--start-seed", type=int)
    llm.add_argument("--max-repeat", type=int, default=60)
    llm.add_argument("--max-requests-per-episode", type=int, default=60)
    llm.add_argument("--max-tokens-per-episode", type=int)
    llm.add_argument("--history-window", type=int, default=4)
    llm.add_argument("--visible", action="store_true")
    llm.add_argument("--output", required=True)
    paired = commands.add_parser("compare-task-runs")
    paired.add_argument("--baseline", required=True, help="evaluate-tasks results.json")
    paired.add_argument("--llm", required=True, help="evaluate-llm results.json")
    paired.add_argument("--task-id", required=True)
    paired.add_argument("--baseline-policy", choices=["random", "rule", "ppo"], default="rule")
    paired.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.command == "train":
        if not 1 <= args.steps <= 1_000_000: parser.error("steps must be 1..1000000")
        train(args)
    elif args.command == "evaluate":
        if args.episodes < 1: parser.error("episodes must be positive")
        comparison(args)
    elif args.command == "evaluate-tasks":
        if args.episodes is not None and args.episodes < 1: parser.error("episodes must be positive")
        if args.start_seed is not None and args.start_seed < 0: parser.error("start-seed must be non-negative")
        task_matrix(args)
    elif args.command == "evaluate-llm":
        if args.episodes is not None and args.episodes < 1: parser.error("episodes must be positive")
        if args.start_seed is not None and args.start_seed < 0: parser.error("start-seed must be non-negative")
        if not 1 <= args.max_repeat <= 120: parser.error("max-repeat must be 1..120")
        if args.max_requests_per_episode < 1: parser.error("max-requests-per-episode must be positive")
        if args.max_tokens_per_episode is not None and args.max_tokens_per_episode < 1:
            parser.error("max-tokens-per-episode must be positive")
        if not 0 <= args.history_window <= 16: parser.error("history-window must be 0..16")
        tasks_to_run = load_tasks(args.task_dir)
        tasks_to_run = [task for task in tasks_to_run if args.task_id is None or task.task_id == args.task_id]
        if not tasks_to_run: raise ValueError(f"unknown task_id: {args.task_id}")
        settings = ProviderSettings.from_env()
        output = Path(args.output)
        output.mkdir(parents=True, exist_ok=False)
        agent = TaskAgent(ChatProvider(settings), max_repeat=args.max_repeat,
            max_requests_per_episode=args.max_requests_per_episode,
            max_tokens_per_episode=args.max_tokens_per_episode,
            history_window=args.history_window)
        result = {"provider": settings.provider, "model": settings.model,
            "base_url": settings.safe_base_url, "code_sha256": fingerprint(),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "request_budget_per_episode": args.max_requests_per_episode,
            "token_budget_per_episode": args.max_tokens_per_episode,
            "max_repeat": args.max_repeat, "history_window": args.history_window,
            "request_timeout_seconds": settings.timeout_seconds,
            "max_completion_tokens_per_request": settings.max_completion_tokens,
            "tasks": []}
        for task in tasks_to_run:
            start = args.start_seed if args.start_seed is not None else task.start_seed
            count = args.episodes if args.episodes is not None else task.episodes
            if start + count - 1 > 2**31 - 1: raise ValueError("evaluation seed range exceeds 32-bit integer limit")
            record = evaluate_task_agent(agent, task, seeds=range(start, start + count),
                visible=args.visible, trace_directory=output / "traces")
            result["tasks"].append(record)
            (output / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps({k: v for k, v in record.items() if k != "rows"}, ensure_ascii=False), flush=True)
        with (output / "episodes.csv").open("w", newline="", encoding="utf-8-sig") as file:
            columns = ["task_id", "task_version", "task_sha256", "seed", "task_status", "task_reason",
                "execution_error", "task_completed_at", "outcome", "seconds", "health", "damage", "kills",
                "pickups_collected", "reward", "prompt_tokens", "completion_tokens", "model_requests",
                "repair_attempts", "model_latency_seconds", "wall_seconds"]
            writer = csv.DictWriter(file, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            for record in result["tasks"]:
                writer.writerows(record["rows"])
        rows = []
        for record in result["tasks"]:
            success_rate = "-" if record["success_rate"] is None else f'{record["success_rate"]:.1%}'
            invalid_reasons = "; ".join(f'{reason}: {count}'
                                         for reason, count in record["invalid_reasons"].items()) or "-"
            rows.append(f'<tr><td>{html.escape(record["task_id"])}</td>'
                f'<td>{record["successes"]}/{record["eligible_episodes"]} ({success_rate})</td>'
                f'<td>{record["invalid_episodes"]}</td><td>{html.escape(invalid_reasons)}</td>'
                f'<td>{record["mean_model_latency_seconds"]:.2f}s</td>'
                f'<td>{record["total_model_requests"]}</td><td>{record["total_prompt_tokens"] + record["total_completion_tokens"]}</td></tr>')
        report = ('<!doctype html><html lang="zh"><meta charset="utf-8"><title>GamePilot LLM Agent</title>'
            '<style>body{background:#f5f0e8;color:#25221e;font:16px system-ui;margin:48px auto;max-width:1050px;padding:20px}'
            'h1{border-left:5px solid #c56b32;padding-left:16px}table{width:100%;border-collapse:collapse}'
            'td,th{text-align:left;padding:12px;border-bottom:1px solid #d5ccc0}</style>'
            f'<h1>GamePilot · LLM 游戏任务 Agent</h1><p>Provider: {html.escape(settings.provider)} · Model: {html.escape(settings.model)}</p>'
            '<table><tr><th>任务</th><th>成功率</th><th>无效局</th><th>无效原因</th><th>模型延迟</th><th>请求数</th><th>Token 数</th></tr>'
            + ''.join(rows) + '</table><p>无效局不计入成功率；成绩由游戏事件和任务 grader 决定。逐局数据见 episodes.csv / results.json。</p></html>')
        (output / "report.html").write_text(report, encoding="utf-8")
    elif args.command == "compare-task-runs":
        result = compare_task_runs(args.baseline, args.llm, task_id=args.task_id,
                                   baseline_policy=args.baseline_policy)
        write_comparison(result, args.output)
        print(json.dumps({key: value for key, value in result.items() if key != "episodes"},
                         ensure_ascii=False), flush=True)
    else:
        replay(args)


if __name__ == "__main__":
    main()
