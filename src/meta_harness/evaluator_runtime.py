from __future__ import annotations

import json
from pathlib import Path
from statistics import mean
from typing import Any


def iter_task_dirs(run_dir: Path) -> list[Path]:
    tasks_dir = run_dir / "tasks"
    if not tasks_dir.exists():
        return []
    return sorted(path for path in tasks_dir.iterdir() if path.is_dir())


def read_json_if_exists(path: Path) -> Any:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def read_text_if_exists(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def load_task_result(task_dir: Path) -> dict[str, Any]:
    payload = read_json_if_exists(task_dir / "task_result.json")
    return payload if isinstance(payload, dict) else {}


def load_benchmark_probe(task_dir: Path) -> dict[str, Any]:
    payload = read_json_if_exists(task_dir / "benchmark_probe.stdout.txt")
    return payload if isinstance(payload, dict) else {}


def load_step_events(task_dir: Path) -> list[dict[str, Any]]:
    steps_path = task_dir / "steps.jsonl"
    if not steps_path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in steps_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        payload = json.loads(line)
        if isinstance(payload, dict):
            events.append(payload)
    return events


def task_total_latency_ms(task_dir: Path) -> float:
    events = load_step_events(task_dir)
    return float(
        sum(float(event.get("latency_ms", 0.0) or 0.0) for event in events)
    )


def flatten_signal_payload(payload: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    flattened: dict[str, Any] = {}
    for key, value in payload.items():
        dotted = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            flattened.update(flatten_signal_payload(value, dotted))
        else:
            flattened[dotted] = value
    return flattened


def average_numeric(values: list[float]) -> float:
    if not values:
        return 0.0
    return round(mean(values), 4)
