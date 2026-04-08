from __future__ import annotations

from typing import Any


def probe_condition_matches(expected: Any, observed: Any) -> bool:
    if isinstance(expected, dict):
        if observed is None:
            return False
        if "equals" in expected:
            return observed == expected["equals"]
        if "min" in expected:
            if not isinstance(observed, (int, float)):
                return False
            if float(observed) < float(expected["min"]):
                return False
        if "max" in expected:
            if not isinstance(observed, (int, float)):
                return False
            if float(observed) > float(expected["max"]):
                return False
        return True
    return observed == expected


def validate_expected_signals(
    expected_signals: dict[str, Any] | None,
    mechanism: dict[str, Any],
) -> dict[str, Any]:
    if not expected_signals:
        return {
            "expected_signals_satisfied": True,
            "missing_signals": [],
            "mismatch_signals": [],
        }

    missing_signals: list[str] = []
    mismatch_signals: list[str] = []

    for section in ("fingerprints", "probes"):
        expected_section = expected_signals.get(section)
        observed_section = mechanism.get(section)
        if not isinstance(expected_section, dict):
            continue
        observed_section = observed_section if isinstance(observed_section, dict) else {}
        for key, expected in expected_section.items():
            if key not in observed_section:
                missing_signals.append(f"{section}.{key}")
                continue
            if not probe_condition_matches(expected, observed_section[key]):
                mismatch_signals.append(f"{section}.{key}")

    return {
        "expected_signals_satisfied": not missing_signals and not mismatch_signals,
        "missing_signals": missing_signals,
        "mismatch_signals": mismatch_signals,
    }
