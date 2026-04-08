from __future__ import annotations

import json
import subprocess
from pathlib import Path


def test_public_demo_flow_script_materializes_expected_artifacts(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    script_path = repo_root / "scripts" / "demo_public_flow.sh"
    output_root = tmp_path / "demo-output"

    completed = subprocess.run(
        ["bash", str(script_path), str(output_root)],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    stdout_lines = {
        key: value
        for key, _, value in (
            line.partition("=") for line in completed.stdout.splitlines() if "=" in line
        )
    }
    promotions = json.loads(
        (output_root / "datasets" / "promotions.json").read_text(encoding="utf-8")
    )
    proposal_dirs = [
        path for path in (output_root / "proposals").iterdir() if path.is_dir()
    ]
    candidate_dirs = [
        path for path in (output_root / "candidates").iterdir() if path.is_dir()
    ]
    validation_report = json.loads(
        (output_root / "reports" / "demo_public_validation.json").read_text(encoding="utf-8")
    )
    benchmark_report = json.loads(
        (output_root / "reports" / "benchmarks" / "demo_public_budget_headroom.json").read_text(
            encoding="utf-8"
        )
    )
    loop_id = stdout_lines["loop_id"]
    best_variant = next(
        item for item in benchmark_report["variants"] if item["name"] == "budget_plus_two"
    )

    assert (output_root / "runs").exists()
    assert (output_root / "exports").exists()
    assert len(proposal_dirs) == 2
    assert len(candidate_dirs) >= 1
    assert promotions["demo-public-cases-hard:hard_case"] == "v1"
    assert (output_root / "datasets" / "demo-public-cases" / "v2" / "manifest.json").exists()
    assert (output_root / "exports").glob("*.otel.json")
    assert stdout_lines["proposal_id"]
    assert stdout_lines["materialized_candidate_id"]
    assert stdout_lines["loop_id"]
    assert stdout_lines["validation_report"].endswith("demo_public_validation.json")
    assert stdout_lines["benchmark_report"].endswith(
        "reports/benchmarks/demo_public_budget_headroom.json"
    )
    assert (
        output_root / "reports" / "loops" / loop_id / "loop.json"
    ).exists()
    assert validation_report["ok"] is True
    assert benchmark_report["best_variant"] == "budget_plus_two"
    assert best_variant["delta_from_baseline"]["composite"] > 0


def test_public_benchmark_snapshot_is_checked_in() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    snapshot_path = (
        repo_root / "reports" / "benchmarks" / "demo_public_budget_headroom.json"
    )

    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    best_variant = next(
        item for item in payload["variants"] if item["name"] == "budget_plus_two"
    )

    assert payload["experiment"] == "demo_public_budget_headroom"
    assert payload["baseline"] == "baseline"
    assert payload["best_variant"] == "budget_plus_two"
    assert best_variant["delta_from_baseline"]["composite"] > 0


def test_generate_llm_proposal_script_returns_valid_proposal_payload(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    script_path = repo_root / "scripts" / "generate_llm_proposal.py"
    payload = {
        "profile": "base",
        "project": "demo",
        "model": "gpt-5.4",
        "system_prompt": "You are an offline harness optimizer.",
        "user_prompt": "Objective: improve retrieval robustness",
        "objective": {
            "goal": "improve retrieval robustness",
            "focus": "retrieval",
        },
        "experience": {
            "matching_runs": [{"run_id": "run-a"}, {"run_id": "run-b"}],
            "failure_records": [
                {"family": "timeout"},
                {"family": "timeout"},
                {"family": "grounding"},
            ],
            "best_candidate": {"candidate_id": "cand-best"},
        },
        "effective_config": {
            "retrieval": {"top_k": 8},
            "budget": {"max_turns": 12},
        },
    }

    completed = subprocess.run(
        ["python", str(script_path)],
        cwd=repo_root,
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["proposal"]["strategy"] == "llm_harness_patch"
    assert result["proposal"]["model"] == "gpt-5.4"
    assert result["proposal"]["source_runs"] == ["run-a", "run-b"]
    assert result["config_patch"]["retrieval"]["top_k"] > 8
    assert "llm harness" in result["notes"]
