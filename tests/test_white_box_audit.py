from __future__ import annotations

import json
from pathlib import Path

from meta_harness.scoring import score_run
from meta_harness.white_box_audit import evaluate_white_box_run


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def test_evaluate_white_box_run_reports_matching_rules(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    run_dir = tmp_path / "runs" / "run-audit"
    repo_root.mkdir(parents=True)
    write_json(
        run_dir / "effective_config.json",
        {
            "runtime": {"workspace": {"source_repo": str(repo_root)}},
            "evaluation": {
                "white_box_audit": {
                    "rules": [
                        {
                            "id": "snapshot-copy",
                            "path_globs": ["src/**/*.ts"],
                            "pattern": "copyFileSync",
                            "severity": "blocker",
                            "message": "snapshot copy write amplification",
                        }
                    ]
                }
            },
        },
    )
    write_json(
        run_dir / "run_metadata.json",
        {"run_id": "run-audit", "profile": "base", "project": "demo"},
    )
    target = repo_root / "src" / "storage" / "layout.ts"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("copyFileSync('a', 'b')\n", encoding="utf-8")

    report = evaluate_white_box_run(run_dir)

    assert report["architecture"]["white_box_rule_violation_count"] == 1
    assert report["architecture"]["white_box_blocker_count"] == 1
    assert report["probes"]["white_box.snapshot-copy.matches"] == 1.0
    assert report["workflow_scores"]["white_box_findings"][0]["path"].endswith(
        "src/storage/layout.ts"
    )
    assert report["composite_adjustment"] < 0.0


def test_evaluate_white_box_run_loads_rule_files_and_emits_runtime_profile(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    run_dir = tmp_path / "runs" / "run-audit-profiled"
    task_a_dir = run_dir / "tasks" / "task-a"
    task_b_dir = run_dir / "tasks" / "task-b"
    repo_root.mkdir(parents=True)
    task_a_dir.mkdir(parents=True)
    task_b_dir.mkdir(parents=True)

    write_json(
        run_dir / "effective_config.json",
        {
            "runtime": {"workspace": {"source_repo": str(repo_root)}},
            "evaluation": {
                "white_box_audit": {
                    "rule_files": ["configs/white_box_rules/core.json"],
                    "runtime_profiling": {"enabled": True, "top_n": 2},
                }
            },
        },
    )
    write_json(
        run_dir / "run_metadata.json",
        {"run_id": "run-audit-profiled", "profile": "base", "project": "demo"},
    )
    target = repo_root / "src" / "storage" / "layout.ts"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("copyFileSync('a', 'b')\n", encoding="utf-8")

    (task_a_dir / "steps.jsonl").write_text(
        json.dumps(
            {
                "step_id": "step-1",
                "phase": "plan",
                "status": "completed",
                "latency_ms": 120,
            }
        )
        + "\n"
        + json.dumps(
            {
                "step_id": "step-2",
                "phase": "execute",
                "status": "completed",
                "latency_ms": 30,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (task_b_dir / "steps.jsonl").write_text(
        json.dumps(
            {
                "step_id": "step-1",
                "phase": "plan",
                "status": "completed",
                "latency_ms": 40,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (task_a_dir / "plan.stdout.txt").write_text("profile output\n", encoding="utf-8")
    (task_a_dir / "plan.stderr.txt").write_text("warning\n", encoding="utf-8")

    report = evaluate_white_box_run(run_dir)

    runtime_profile = report["workflow_scores"]["white_box_runtime_profile"]
    assert report["architecture"]["white_box_rule_violation_count"] == 1
    assert report["cost"]["white_box_runtime_total_latency_ms"] == 190.0
    assert report["cost"]["white_box_runtime_stdout_bytes"] > 0
    assert report["probes"]["white_box.runtime.task_count"] == 2.0
    assert runtime_profile["slow_tasks"][0]["task_id"] == "task-a"
    assert runtime_profile["slow_tasks"][0]["latency_ms"] == 150.0
    assert runtime_profile["slow_phases"][0]["phase"] == "plan"


def test_score_run_executes_relative_white_box_audit_script_from_source_repo(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    run_dir = tmp_path / "runs" / "run-audit-pack"
    task_dir = run_dir / "tasks" / "task-a"
    task_dir.mkdir(parents=True)
    repo_root.mkdir(parents=True)
    target = repo_root / "src" / "storage" / "layout.ts"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("copyFileSync('a', 'b')\n", encoding="utf-8")

    repo_project_root = Path(__file__).resolve().parents[1]
    script_path = repo_project_root / "scripts" / "eval_white_box_audit.py"
    write_json(
        run_dir / "effective_config.json",
        {
            "runtime": {"workspace": {"source_repo": str(repo_root)}},
            "evaluation": {
                "evaluators": ["command"],
                "white_box_audit": {
                    "rules": [
                        {
                            "id": "snapshot-copy",
                            "path_globs": ["src/**/*.ts"],
                            "pattern": "copyFileSync",
                            "severity": "blocker",
                        }
                    ]
                },
                "command_evaluators": [
                    {
                        "name": "white-box/audit",
                        "command": ["python", str(script_path)],
                    }
                ],
            },
        },
    )
    write_json(
        run_dir / "run_metadata.json",
        {"run_id": "run-audit-pack", "profile": "base", "project": "demo"},
    )
    (task_dir / "steps.jsonl").write_text(
        json.dumps(
            {
                "step_id": "step-1",
                "phase": "review",
                "status": "completed",
                "latency_ms": 10,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    report = score_run(run_dir)

    assert report["architecture"]["white_box_rule_violation_count"] == 1
    assert report["cost"]["command_evaluators_run"] == 1
