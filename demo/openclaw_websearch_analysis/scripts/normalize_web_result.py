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
    if len(sys.argv) < 5:
        raise SystemExit(
            "usage: normalize_web_result.py <binding_payload> <task_dir> <collected_output> <probe...>"
        )

    payload_path = Path(sys.argv[1])
    task_dir = Path(sys.argv[2])
    collected_output = Path(sys.argv[3])
    probe_items = sys.argv[4:]

    binding_payload = json.loads(payload_path.read_text(encoding="utf-8"))
    reply_payload = _extract_reply_payload(binding_payload)
    page_html = str(reply_payload.get("page_html") or "")
    extracted = reply_payload.get("extracted") or {}
    if not page_html.strip():
        raise ValueError("reply payload missing page_html")
    if not isinstance(extracted, dict) or not extracted:
        raise ValueError("reply payload missing extracted object")

    task_dir.mkdir(parents=True, exist_ok=True)
    collected_output.parent.mkdir(parents=True, exist_ok=True)
    (task_dir / "page.html").write_text(page_html, encoding="utf-8")
    (task_dir / "extracted.json").write_text(
        json.dumps(extracted, indent=2),
        encoding="utf-8",
    )
    collected_output.write_text(json.dumps(extracted, indent=2), encoding="utf-8")

    fingerprints: dict[str, str] = {}
    probes: dict[str, float] = {}
    for item in probe_items:
        key, _, value = item.partition("=")
        if key.startswith("scrape."):
            if key == "scrape.mode":
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
