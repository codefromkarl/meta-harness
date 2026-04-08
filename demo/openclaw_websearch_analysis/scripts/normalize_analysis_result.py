from __future__ import annotations

import json
import sys
from pathlib import Path


def _extract_reply_payload(binding_payload: dict) -> dict:
    reply = binding_payload.get("reply")
    if isinstance(reply, dict):
        return reply
    if isinstance(reply, str) and reply.strip():
        return json.loads(reply)
    raise ValueError("binding payload reply must be non-empty JSON")


def main() -> None:
    if len(sys.argv) < 4:
        raise SystemExit(
            "usage: normalize_analysis_result.py <binding_payload> <task_dir> <probe...>"
        )

    payload_path = Path(sys.argv[1])
    task_dir = Path(sys.argv[2])
    probe_items = sys.argv[3:]

    binding_payload = json.loads(payload_path.read_text(encoding="utf-8"))
    reply_payload = _extract_reply_payload(binding_payload)
    analysis_summary = reply_payload.get("analysis_summary") or {}
    analysis_report = str(reply_payload.get("analysis_report") or "")
    if not isinstance(analysis_summary, dict) or not analysis_summary:
        raise ValueError("reply payload missing analysis_summary")
    if not analysis_report.strip():
        raise ValueError("reply payload missing analysis_report")

    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "analysis_summary.json").write_text(
        json.dumps(analysis_summary, indent=2),
        encoding="utf-8",
    )
    (task_dir / "analysis_report.md").write_text(analysis_report, encoding="utf-8")

    fingerprints: dict[str, str] = {}
    probes: dict[str, float] = {}
    for item in probe_items:
        key, _, value = item.partition("=")
        if key.startswith("analysis."):
            if key == "analysis.mode":
                fingerprints[key] = value
            else:
                probes[key] = float(value)

    (task_dir / "benchmark_probe.stdout.txt").write_text(
        json.dumps(
            {
                "fingerprints": fingerprints,
                "probes": probes,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
