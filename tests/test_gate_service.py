from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from typer.testing import CliRunner

from meta_harness.cli import app
from meta_harness.services.gate_service import (
    evaluate_gate_policy,
    list_gate_history,
    list_gate_results,
    load_gate_result,
)


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


class _CaptureHandler(BaseHTTPRequestHandler):
    requests: list[dict] = []

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        self.__class__.requests.append(
            {
                "path": self.path,
                "headers": dict(self.headers.items()),
                "body": json.loads(body) if body else None,
            }
        )
        encoded = json.dumps({"accepted": True}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


class CaptureServer:
    def __init__(self) -> None:
        _CaptureHandler.requests = []
        self.server = HTTPServer(("127.0.0.1", 0), _CaptureHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        host, port = self.server.server_address
        return f"http://{host}:{port}"

    @property
    def requests(self) -> list[dict]:
        return list(_CaptureHandler.requests)

    def __enter__(self) -> "CaptureServer":
        self.thread.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


def test_evaluate_gate_policy_passes_benchmark_target() -> None:
    policy = {
        "policy_id": "default-benchmark",
        "policy_type": "benchmark",
        "conditions": [
            {
                "kind": "benchmark_has_valid_variant",
                "path": "variants",
                "value": True,
            },
            {
                "kind": "ranking_score_gte",
                "path": "best_variant.ranking_score",
                "value": 13.0,
            },
            {
                "kind": "stability_flag_is",
                "path": "best_variant.stability_assessment.is_stable",
                "value": True,
            },
        ],
    }
    target = {
        "best_variant": {
            "name": "baseline",
            "ranking_score": 13.75,
            "stability_assessment": {"is_stable": True},
        },
        "variants": [
            {"name": "baseline", "ranking_score": 13.75},
        ],
    }

    payload = evaluate_gate_policy(
        policy=policy,
        target_payload=target,
        target_type="benchmark_experiment",
        target_ref="reports/benchmarks/demo.json",
    )

    assert payload["status"] == "passed"
    assert len(payload["passed_conditions"]) == 3
    assert payload["failed_conditions"] == []


def test_evaluate_gate_policy_fails_promotion_without_enough_evidence() -> None:
    policy = {
        "policy_id": "default-promotion",
        "policy_type": "promotion",
        "conditions": [
            {
                "kind": "evidence_run_count_gte",
                "path": "evidence_refs",
                "value": 2,
            }
        ],
    }

    payload = evaluate_gate_policy(
        policy=policy,
        target_payload={"candidate_id": "cand-123"},
        target_type="candidate_promotion",
        target_ref="candidates/cand-123/candidate.json",
        evidence_refs=["runs/run-1/score_report.json"],
    )

    assert payload["status"] == "failed"
    assert payload["passed_conditions"] == []
    assert payload["failed_conditions"][0]["kind"] == "evidence_run_count_gte"


def test_evaluate_gate_policy_supports_thresholds_resolved_from_target_payload() -> None:
    policy = {
        "policy_id": "default-benchmark-delta",
        "policy_type": "benchmark",
        "conditions": [
            {
                "kind": "ranking_score_gte",
                "path": "best_variant.ranking_score",
                "value": {"path": "baseline.ranking_score"},
            },
            {
                "kind": "score_metric_lte",
                "path": "score_report.architecture.white_box_blocker_count",
                "value": {"path": "baseline.architecture_budget.max_blockers"},
            },
        ],
    }
    target = {
        "baseline": {
            "ranking_score": 13.0,
            "architecture_budget": {"max_blockers": 0},
        },
        "best_variant": {
            "name": "candidate-a",
            "ranking_score": 13.6,
        },
        "score_report": {
            "architecture": {
                "white_box_blocker_count": 0,
            }
        },
    }

    payload = evaluate_gate_policy(
        policy=policy,
        target_payload=target,
        target_type="benchmark_experiment",
        target_ref="reports/benchmarks/demo.json",
    )

    assert payload["status"] == "passed"
    assert len(payload["passed_conditions"]) == 2
    assert payload["failed_conditions"] == []


def test_gate_evaluate_cli_reads_policy_and_target_files(tmp_path: Path) -> None:
    policy_path = tmp_path / "policy.json"
    target_path = tmp_path / "target.json"
    write_json(
        policy_path,
        {
            "policy_id": "default-benchmark",
            "policy_type": "benchmark",
            "conditions": [
                {
                    "kind": "benchmark_has_valid_variant",
                    "path": "variants",
                    "value": True,
                }
            ],
        },
    )
    write_json(
        target_path,
        {
            "variants": [
                {"name": "baseline", "ranking_score": 13.75},
            ]
        },
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "gate",
            "evaluate",
            "--policy",
            str(policy_path),
            "--target",
            str(target_path),
            "--target-type",
            "benchmark_experiment",
            "--target-ref",
            "reports/benchmarks/demo.json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "passed"
    assert payload["policy_id"] == "default-benchmark"


def test_gate_evaluate_cli_can_persist_result_artifact(tmp_path: Path) -> None:
    policy_path = tmp_path / "policy.json"
    target_path = tmp_path / "target.json"
    reports_root = tmp_path / "reports"
    write_json(
        policy_path,
        {
            "policy_id": "default-benchmark",
            "policy_type": "benchmark",
            "conditions": [],
        },
    )
    write_json(target_path, {"variants": []})

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "gate",
            "evaluate",
            "--policy",
            str(policy_path),
            "--target",
            str(target_path),
            "--target-type",
            "benchmark_experiment",
            "--target-ref",
            "reports/benchmarks/demo.json",
            "--reports-root",
            str(reports_root),
            "--persist-result",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["artifact_path"].startswith("reports/gates/")
    assert (tmp_path / payload["artifact_path"]).exists()


def test_evaluate_gate_policy_persists_result_artifact_and_history(tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    policy = {
        "policy_id": "default-benchmark",
        "policy_type": "benchmark",
        "conditions": [
            {
                "kind": "benchmark_has_valid_variant",
                "path": "variants",
                "value": True,
            }
        ],
    }
    target = {"variants": [{"name": "baseline"}]}

    payload = evaluate_gate_policy(
        policy=policy,
        target_payload=target,
        target_type="benchmark_experiment",
        target_ref="reports/benchmarks/demo.json",
        reports_root=reports_root,
        persist_result=True,
    )

    artifact_path = tmp_path / str(payload["artifact_path"])
    history_path = reports_root / "gates" / "history.jsonl"
    assert payload["status"] == "passed"
    assert artifact_path.exists()
    assert history_path.exists()
    assert json.loads(artifact_path.read_text(encoding="utf-8"))["policy_id"] == "default-benchmark"
    assert len(history_path.read_text(encoding="utf-8").splitlines()) == 1


def test_evaluate_gate_policy_can_apply_waiver_rule() -> None:
    policy = {
        "policy_id": "default-promotion",
        "policy_type": "promotion",
        "conditions": [
            {
                "kind": "evidence_run_count_gte",
                "path": "evidence_refs",
                "value": 2,
            }
        ],
        "waiver_rules": [
            {
                "match_kind": "evidence_run_count_gte",
                "reason": "manual override for demo candidate",
                "waived_by": "release-manager",
                "expires_at": "2099-01-01T00:00:00+00:00",
            }
        ],
    }

    payload = evaluate_gate_policy(
        policy=policy,
        target_payload={"candidate_id": "cand-123"},
        target_type="candidate_promotion",
        target_ref="candidates/cand-123/promotion_target.json",
        evidence_refs=["runs/run-1/score_report.json"],
    )

    assert payload["status"] == "waived"
    assert payload["failed_conditions"] == []
    assert payload["waived_conditions"][0]["kind"] == "evidence_run_count_gte"
    assert payload["waived_conditions"][0]["waived_by"] == "release-manager"


def test_evaluate_gate_policy_records_notifications_for_failed_gate() -> None:
    policy = {
        "policy_id": "default-benchmark",
        "policy_type": "benchmark",
        "conditions": [
            {
                "kind": "benchmark_has_valid_variant",
                "path": "variants",
                "value": True,
            }
        ],
        "notification_rules": [
            {
                "channel": "slack",
                "trigger_statuses": ["failed"],
                "target": "#eval-alerts",
                "template": "gate failed for {target_ref}",
            }
        ],
    }

    payload = evaluate_gate_policy(
        policy=policy,
        target_payload={"variants": []},
        target_type="benchmark_experiment",
        target_ref="reports/benchmarks/demo.json",
    )

    assert payload["status"] == "failed"
    assert payload["notifications"][0]["channel"] == "slack"
    assert payload["notifications"][0]["target"] == "#eval-alerts"
    assert "reports/benchmarks/demo.json" in payload["notifications"][0]["message"]


def test_evaluate_gate_policy_can_deliver_webhook_notifications() -> None:
    with CaptureServer() as server:
        policy = {
            "policy_id": "default-benchmark",
            "policy_type": "benchmark",
            "conditions": [
                {
                    "kind": "benchmark_has_valid_variant",
                    "path": "variants",
                    "value": True,
                }
            ],
            "notification_rules": [
                {
                    "channel": "webhook",
                    "trigger_statuses": ["failed"],
                    "target": f"{server.base_url}/gate-webhook",
                    "template": "gate failed for {target_ref}",
                    "headers": {"Authorization": "Bearer gate-token"},
                }
            ],
        }

        payload = evaluate_gate_policy(
            policy=policy,
            target_payload={"variants": []},
            target_type="benchmark_experiment",
            target_ref="reports/benchmarks/demo.json",
            execute_notifications=True,
        )

        assert payload["notifications"][0]["delivery"]["ok"] is True
        assert payload["notifications"][0]["delivery"]["status_code"] == 200
        assert len(server.requests) == 1
        assert server.requests[0]["path"] == "/gate-webhook"
        assert server.requests[0]["headers"]["Authorization"] == "Bearer gate-token"
        assert server.requests[0]["body"]["message"] == "gate failed for reports/benchmarks/demo.json"


def test_evaluate_gate_policy_can_deliver_slack_webhook_notifications() -> None:
    with CaptureServer() as server:
        policy = {
            "policy_id": "default-benchmark",
            "policy_type": "benchmark",
            "conditions": [
                {
                    "kind": "benchmark_has_valid_variant",
                    "path": "variants",
                    "value": True,
                }
            ],
            "notification_rules": [
                {
                    "channel": "slack_webhook",
                    "target": f"{server.base_url}/slack",
                    "trigger_statuses": ["failed"],
                    "template": "gate failed for {target_ref}",
                }
            ],
        }

        payload = evaluate_gate_policy(
            policy=policy,
            target_payload={"variants": []},
            target_type="benchmark_experiment",
            target_ref="reports/benchmarks/demo.json",
            execute_notifications=True,
        )

        assert payload["notifications"][0]["delivery"]["ok"] is True
        assert len(server.requests) == 1
        assert server.requests[0]["path"] == "/slack"
        assert server.requests[0]["body"]["text"] == "gate failed for reports/benchmarks/demo.json"


def test_gate_service_lists_and_loads_gate_results(tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    evaluate_gate_policy(
        policy={"policy_id": "benchmark-a", "policy_type": "benchmark", "conditions": []},
        target_payload={"variants": []},
        target_type="benchmark_experiment",
        target_ref="reports/benchmarks/a.json",
        reports_root=reports_root,
        persist_result=True,
    )
    second = evaluate_gate_policy(
        policy={"policy_id": "promotion-a", "policy_type": "promotion", "conditions": []},
        target_payload={"candidate_id": "cand-1"},
        target_type="candidate_promotion",
        target_ref="candidates/cand-1/promotion_target.json",
        reports_root=reports_root,
        persist_result=True,
    )

    listed = list_gate_results(reports_root=reports_root, policy_id="promotion-a")
    detail = load_gate_result(reports_root=reports_root, gate_id=second["gate_id"])
    history = list_gate_history(reports_root=reports_root, policy_id="promotion-a")

    assert [item["gate_id"] for item in listed] == [second["gate_id"]]
    assert detail["policy_id"] == "promotion-a"
    assert detail["target_ref"] == "candidates/cand-1/promotion_target.json"
    assert detail["artifact_path"] == second["artifact_path"]
    assert history[0]["gate_id"] == second["gate_id"]


def test_gate_cli_can_list_and_show_gate_results(tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    payload = evaluate_gate_policy(
        policy={"policy_id": "benchmark-a", "policy_type": "benchmark", "conditions": []},
        target_payload={"variants": []},
        target_type="benchmark_experiment",
        target_ref="reports/benchmarks/a.json",
        reports_root=reports_root,
        persist_result=True,
    )

    runner = CliRunner()
    listed = runner.invoke(
        app,
        [
            "gate",
            "list-results",
            "--reports-root",
            str(reports_root),
            "--policy-id",
            "benchmark-a",
        ],
    )
    shown = runner.invoke(
        app,
        [
            "gate",
            "show-result",
            "--reports-root",
            str(reports_root),
            "--gate-id",
            payload["gate_id"],
        ],
    )

    assert listed.exit_code == 0
    assert shown.exit_code == 0
    listed_payload = json.loads(listed.stdout)
    shown_payload = json.loads(shown.stdout)
    assert listed_payload[0]["gate_id"] == payload["gate_id"]
    assert shown_payload["policy_id"] == "benchmark-a"
