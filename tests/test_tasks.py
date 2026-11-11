import json

import pytest

from gamepilot.experiment import evaluate_task_policy
from gamepilot.tasks import TASK_DIR, grade_task, load_task, load_tasks


def test_builtin_task_suite_is_versioned_and_unique():
    tasks = load_tasks()
    assert {task.task_id for task in tasks} == {
        "survive_60", "kill_target", "survive_damage_limit", "collect_and_survive"
    }
    assert all(task.version == 1 and task.start_seed == 2000 and task.episodes == 30 for task in tasks)
    assert len({task.sha256 for task in tasks}) == 4


def test_task_loader_rejects_unknown_fields_and_invalid_thresholds(tmp_path):
    data = json.loads((TASK_DIR / "kill_target.json").read_text(encoding="utf-8"))
    data["surprise"] = True
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="fields"):
        load_task(path)

    data.pop("surprise")
    data["objectives"][0]["target"] = 0
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="finite"):
        load_task(path)


def test_kill_objective_completes_early_and_uses_inclusive_threshold():
    task = load_task(TASK_DIR / "kill_target.json")
    result = grade_task(task, {"seconds": 12.0, "kills": 20, "damage": 0,
                               "pickups_collected": 0, "outcome": "running"})
    assert result == {"status": "success", "reason": "objectives_met", "completed_at": 12.0}


def test_damage_limit_failure_and_survive_task_success():
    task = load_task(TASK_DIR / "survive_damage_limit.json")
    failed = grade_task(task, {"seconds": 20, "kills": 4, "damage": 3,
                               "pickups_collected": 0, "outcome": "running"})
    assert failed["status"] == "failure" and failed["reason"] == "damage_limit"
    passed = grade_task(task, {"seconds": 60, "kills": 4, "damage": 2,
                               "pickups_collected": 0, "outcome": "survived", "is_success": True}, terminated=True)
    assert passed["status"] == "success"


def test_collect_and_survive_requires_both_objectives():
    task = load_task(TASK_DIR / "collect_and_survive.json")
    partial = grade_task(task, {"seconds": 60, "kills": 3, "damage": 0,
                                "pickups_collected": 0, "outcome": "survived", "is_success": True}, terminated=True)
    assert partial["status"] == "failure" and partial["reason"] == "deadline"
    complete = grade_task(task, {"seconds": 60, "kills": 3, "damage": 0,
                                 "pickups_collected": 1, "outcome": "survived", "is_success": True}, terminated=True)
    assert complete["status"] == "success"


def test_death_precedes_objective_and_external_stop_is_not_a_task_loss():
    task = load_task(TASK_DIR / "kill_target.json")
    dead = grade_task(task, {"seconds": 60, "kills": 20, "damage": 5,
                             "pickups_collected": 0, "outcome": "death"}, terminated=True)
    assert dead["status"] == "failure" and dead["reason"] == "player_death"
    truncated = grade_task(task, {"seconds": 2, "kills": 0, "damage": 0,
                                  "pickups_collected": 0, "outcome": "truncated"}, truncated=True)
    assert truncated["status"] == "incomplete" and truncated["reason"] == "external_truncation"
    error = grade_task(task, {}, execution_error=True)
    assert error["status"] == "invalid" and error["reason"] == "execution_error"


def test_missing_pickup_evidence_is_invalid():
    task = load_task(TASK_DIR / "collect_and_survive.json")
    result = grade_task(task, {"seconds": 10, "kills": 0, "damage": 0, "outcome": "running"})
    assert result["status"] == "invalid" and result["reason"] == "missing_episode_evidence"


def test_execution_errors_are_preserved_but_excluded_from_success_rate(tmp_path, monkeypatch):
    class BrokenEnv:
        def __init__(self, **_kwargs):
            pass

        def reset(self, *, seed):
            raise ConnectionError(f"failed seed {seed}")

        def close(self):
            pass

    monkeypatch.setattr("gamepilot.experiment.PilotEnv", BrokenEnv)
    task = load_task(TASK_DIR / "kill_target.json")
    result = evaluate_task_policy("rule", task, seeds=range(2000, 2002),
                                  trace_path=tmp_path / "errors.jsonl")
    assert result["episodes"] == 2
    assert result["eligible_episodes"] == 0
    assert result["success_rate"] is None
    assert result["invalid_or_incomplete"] == 2
    assert all(row["execution_error"] == "ConnectionError" for row in result["rows"])
    assert result["task_config"]["sha256"] == task.sha256


def test_execution_errors_work_with_one_shot_seed_iterables(tmp_path, monkeypatch):
    class BrokenEnv:
        def __init__(self, **_kwargs):
            pass

        def reset(self, *, seed):
            raise ConnectionError(f"failed seed {seed}")

        def close(self):
            pass

    monkeypatch.setattr("gamepilot.experiment.PilotEnv", BrokenEnv)
    task = load_task(TASK_DIR / "kill_target.json")
    result = evaluate_task_policy("rule", task, seeds=iter([2000]),
                                  trace_path=tmp_path / "single-error.jsonl")
    assert result["episodes"] == 1
    assert result["rows"][0]["execution_error"] == "ConnectionError"


def test_task_evaluation_requires_at_least_one_seed():
    task = load_task(TASK_DIR / "kill_target.json")
    with pytest.raises(ValueError, match="at least one"):
        evaluate_task_policy("rule", task, seeds=[])
