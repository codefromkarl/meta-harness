from __future__ import annotations

import json
import re
from pathlib import Path


def _normalize_error(raw_error: str) -> str:
    normalized = raw_error.lower()
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return " ".join(normalized.split())


def extract_failure_signatures(run_dir: Path) -> list[dict]:
    records: list[dict] = []
    tasks_dir = run_dir / "tasks"
    if not tasks_dir.exists():
        return records

    for task_dir in sorted(path for path in tasks_dir.iterdir() if path.is_dir()):
        steps_path = task_dir / "steps.jsonl"
        if not steps_path.exists():
            continue

        for line in steps_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            raw_error = payload.get("error")
            if payload.get("status") != "failed" or not raw_error:
                continue
            records.append(
                {
                    "task_id": task_dir.name,
                    "step_id": payload.get("step_id"),
                    "phase": payload.get("phase"),
                    "raw_error": raw_error,
                    "signature": _normalize_error(raw_error),
                }
            )

    (run_dir / "error_signatures.json").write_text(
        json.dumps(records, indent=2),
        encoding="utf-8",
    )
    return records


def load_or_extract_failure_signatures(run_dir: Path) -> list[dict]:
    signature_path = run_dir / "error_signatures.json"
    if signature_path.exists():
        return json.loads(signature_path.read_text(encoding="utf-8"))
    return extract_failure_signatures(run_dir)


def search_failure_signatures(runs_root: Path, query: str) -> list[dict]:
    normalized_query = _normalize_error(query)
    matches: list[dict] = []
    if not runs_root.exists():
        return matches

    for run_dir in sorted(path for path in runs_root.iterdir() if path.is_dir()):
        for record in load_or_extract_failure_signatures(run_dir):
            if normalized_query in record["signature"]:
                matches.append(
                    {
                        "run_id": run_dir.name,
                        **record,
                    }
                )
    return matches
