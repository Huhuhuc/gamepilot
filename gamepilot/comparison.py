"""Validate seed-paired task runs and produce a compact comparison report."""
from __future__ import annotations

import csv
import html
import json
import math
from pathlib import Path


def _load(path: str | Path) -> dict:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read results JSON: {path}") from error
    if not isinstance(value, dict) or not isinstance(value.get("tasks"), list):
        raise ValueError(f"invalid task results file: {path}")
    return value


def _select(data: dict, task_id: str, policy: str) -> dict:
    matches = [record for record in data["tasks"]
               if record.get("task_id") == task_id and record.get("policy") == policy]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one {policy} record for task {task_id}")
    record = matches[0]
    rows = record.get("rows")
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"{policy} record has no episode rows")
    if not record.get("task_sha256"):
        raise ValueError(f"{policy} record is missing task hash")
    seeds = [row.get("seed") for row in rows]
    if any(type(seed) is not int for seed in seeds) or len(set(seeds)) != len(seeds):
        raise ValueError(f"{policy} record contains invalid or duplicate seeds")
    return record


def wilson_interval(successes: int, total: int, z: float = 1.959963984540054):
    if total <= 0:
        return None
    p = successes / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return [max(0.0, center - margin), min(1.0, center + margin)]


def compare_task_runs(baseline_path: str | Path, llm_path: str | Path, *,
                      task_id: str, baseline_policy: str = "rule") -> dict:
    baseline_data = _load(baseline_path)
    llm_data = _load(llm_path)
    baseline = _select(baseline_data, task_id, baseline_policy)
    llm = _select(llm_data, task_id, "llm")
    if baseline["task_sha256"] != llm["task_sha256"]:
        raise ValueError("task definition hashes differ")
    baseline_rows = {row["seed"]: row for row in baseline["rows"]}
    llm_rows = {row["seed"]: row for row in llm["rows"]}
    if set(baseline_rows) != set(llm_rows):
        raise ValueError("episode seed sets differ")

    pairs = []
    for seed in sorted(baseline_rows):
        b_row, l_row = baseline_rows[seed], llm_rows[seed]
        b_status = b_row.get("task_status")
        l_status = l_row.get("task_status")
        if b_status not in {"success", "failure", "invalid", "incomplete"}:
            raise ValueError(f"invalid baseline task status for seed {seed}")
        if l_status not in {"success", "failure", "invalid", "incomplete"}:
            raise ValueError(f"invalid LLM task status for seed {seed}")
        pairs.append({"seed": seed, "baseline_status": b_status,
                      "llm_status": l_status,
                      "baseline_reason": b_row.get("task_reason"),
                      "llm_reason": l_row.get("task_reason"),
                      "baseline_seconds": b_row.get("seconds"),
                      "llm_seconds": l_row.get("seconds"),
                      "baseline_damage": b_row.get("damage"),
                      "llm_damage": l_row.get("damage"),
                      "baseline_kills": b_row.get("kills"),
                      "llm_kills": l_row.get("kills")})

    b_valid = [row for row in baseline_rows.values() if row.get("task_status") in {"success", "failure"}]
    l_valid = [row for row in llm_rows.values() if row.get("task_status") in {"success", "failure"}]
    b_successes = sum(row.get("task_status") == "success" for row in b_valid)
    l_successes = sum(row.get("task_status") == "success" for row in l_valid)
    paired = [pair for pair in pairs if pair["baseline_status"] in {"success", "failure"}
              and pair["llm_status"] in {"success", "failure"}]
    llm_only = sum(pair["llm_status"] == "success" and pair["baseline_status"] == "failure" for pair in paired)
    baseline_only = sum(pair["baseline_status"] == "success" and pair["llm_status"] == "failure" for pair in paired)
    b_rate = b_successes / len(b_valid) if b_valid else None
    l_rate = l_successes / len(l_valid) if l_valid else None
    paired_delta = (sum(pair["llm_status"] == "success" for pair in paired) / len(paired)
                    - sum(pair["baseline_status"] == "success" for pair in paired) / len(paired)) if paired else None
    return {"task_id": task_id, "task_sha256": baseline["task_sha256"],
            "baseline_policy": baseline_policy, "llm_provider": llm_data.get("provider"),
            "llm_model": llm_data.get("model"), "seed_count": len(pairs),
            "baseline": {"episodes": len(baseline_rows), "valid_episodes": len(b_valid),
                "invalid_or_incomplete": len(baseline_rows) - len(b_valid),
                "successes": b_successes, "success_rate": b_rate,
                "wilson_95": wilson_interval(b_successes, len(b_valid))},
            "llm": {"episodes": len(llm_rows), "valid_episodes": len(l_valid),
                "invalid_or_incomplete": len(llm_rows) - len(l_valid),
                "successes": l_successes, "success_rate": l_rate,
                "wilson_95": wilson_interval(l_successes, len(l_valid))},
            "paired": {"valid_pairs": len(paired), "llm_only_successes": llm_only,
                "baseline_only_successes": baseline_only,
                "ties": len(paired) - llm_only - baseline_only,
                "success_rate_delta": paired_delta},
            "episodes": pairs}


def write_comparison(result: dict, output: str | Path) -> None:
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    (output / "comparison.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    with (output / "episodes.csv").open("w", newline="", encoding="utf-8-sig") as file:
        columns = list(result["episodes"][0]) if result["episodes"] else []
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows(result["episodes"])
    def rate_text(value):
        return "n/a" if value is None else f"{value:.1%}"
    def ci_text(value):
        return "n/a" if value is None else f"[{value[0]:.1%}, {value[1]:.1%}]"
    b, l, p = result["baseline"], result["llm"], result["paired"]
    report = ('<!doctype html><html lang="zh"><meta charset="utf-8"><title>GamePilot 配对任务对照</title>'
        '<style>body{background:#f5f0e8;color:#25221e;font:16px system-ui;margin:48px auto;max-width:1050px;padding:20px}'
        'h1{border-left:5px solid #c56b32;padding-left:16px}table{width:100%;border-collapse:collapse}'
        'td,th{text-align:left;padding:12px;border-bottom:1px solid #d5ccc0}</style>'
        f'<h1>GamePilot · 配对任务对照</h1><p>{html.escape(result["task_id"])} · '
        f'{html.escape(str(result.get("llm_model") or "LLM"))} · {result["seed_count"]} 个共同种子</p>'
        '<table><tr><th>策略</th><th>有效局</th><th>成功</th><th>成功率</th><th>Wilson 95% 区间</th><th>无效/截断</th></tr>'
        f'<tr><td>{html.escape(result["baseline_policy"])}</td><td>{b["valid_episodes"]}/{b["episodes"]}</td>'
        f'<td>{b["successes"]}</td><td>{rate_text(b["success_rate"])}</td><td>{ci_text(b["wilson_95"])}</td><td>{b["invalid_or_incomplete"]}</td></tr>'
        f'<tr><td>LLM</td><td>{l["valid_episodes"]}/{l["episodes"]}</td><td>{l["successes"]}</td>'
        f'<td>{rate_text(l["success_rate"])}</td><td>{ci_text(l["wilson_95"])}</td><td>{l["invalid_or_incomplete"]}</td></tr></table>'
        f'<p>仅双方均有效的配对局：{p["valid_pairs"]}；LLM 单独成功 {p["llm_only_successes"]} 局，基线单独成功 {p["baseline_only_successes"]} 局；配对成功率差 {rate_text(p["success_rate_delta"])}。</p>'
        '<p>置信区间为各策略成功率的 Wilson 区间；配对差值为描述性统计，不代表显著性检验。逐局数据见 episodes.csv。</p></html>')
    (output / "report.html").write_text(report, encoding="utf-8")
