import json

import pytest

from gamepilot.comparison import compare_task_runs, wilson_interval, write_comparison


def _write(path, policy, seeds, *, task_hash="task-v1", provider=None, model=None):
    path.write_text(json.dumps({"provider": provider, "model": model, "tasks": [{
        "task_id": "kill_target", "task_version": 1, "task_sha256": task_hash,
        "policy": policy, "rows": seeds,
    }]}), encoding="utf-8")


def _row(seed, status, reason=None):
    return {"seed": seed, "task_status": status, "task_reason": reason,
            "seconds": 20.0, "damage": 1, "kills": 10}


def test_wilson_interval_handles_empty_and_small_samples():
    assert wilson_interval(0, 0) is None
    low, high = wilson_interval(1, 1)
    assert low == pytest.approx(0.2065, abs=0.001)
    assert high == 1.0


def test_comparison_pairs_seeds_and_excludes_invalid_from_rates(tmp_path):
    baseline = tmp_path / "baseline.json"
    llm = tmp_path / "llm.json"
    _write(baseline, "rule", [
        _row(2000, "success", "objectives_met"),
        _row(2001, "failure", "player_death"),
        _row(2002, "invalid", "execution_error"),
    ])
    _write(llm, "llm", [
        _row(2000, "failure", "player_death"),
        _row(2001, "success", "objectives_met"),
        _row(2002, "invalid", "provider_transport_error"),
    ], provider="ollama", model="test-model")

    result = compare_task_runs(baseline, llm, task_id="kill_target")
    assert result["seed_count"] == 3
    assert result["baseline"]["success_rate"] == 0.5
    assert result["llm"]["success_rate"] == 0.5
    assert result["baseline"]["invalid_or_incomplete"] == 1
    assert result["paired"] == {"valid_pairs": 2, "llm_only_successes": 1,
        "baseline_only_successes": 1, "ties": 0, "success_rate_delta": 0.0}

    output = tmp_path / "comparison"
    write_comparison(result, output)
    assert {path.name for path in output.iterdir()} == {"comparison.json", "episodes.csv", "report.html"}
    assert "Wilson" in (output / "report.html").read_text(encoding="utf-8")


@pytest.mark.parametrize("left_hash,right_hash", [("v1", "v2"), ("v1", "v1")])
def test_comparison_rejects_task_or_seed_mismatch(tmp_path, left_hash, right_hash):
    baseline = tmp_path / "baseline.json"
    llm = tmp_path / "llm.json"
    _write(baseline, "rule", [_row(2000, "success")], task_hash=left_hash)
    llm_seed = 2001 if left_hash == right_hash else 2000
    _write(llm, "llm", [_row(llm_seed, "success")], task_hash=right_hash)
    expected = "episode seed sets differ" if left_hash == right_hash else "task definition hashes differ"
    with pytest.raises(ValueError, match=expected):
        compare_task_runs(baseline, llm, task_id="kill_target")


def test_comparison_rejects_duplicate_seed_rows(tmp_path):
    baseline = tmp_path / "baseline.json"
    llm = tmp_path / "llm.json"
    _write(baseline, "rule", [_row(2000, "success"), _row(2000, "failure")])
    _write(llm, "llm", [_row(2000, "success")])
    with pytest.raises(ValueError, match="duplicate seeds"):
        compare_task_runs(baseline, llm, task_id="kill_target")
