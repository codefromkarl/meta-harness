from __future__ import annotations

from pathlib import Path

from meta_harness.integration_schemas import (
    IntegrationActivationRecord,
    IntegrationReviewResult,
    IntegrationSpec,
    ReviewChecklist,
)

EXPLORATION_REVIEW_STATUSES = frozenset(
    {
        "needs_review",
        "approved",
        "proposed",
        "benchmarked",
        "selected",
        "rejected",
    }
)
PROMOTION_REVIEW_STATUSES = frozenset({"promoted"})
ACTIVATION_REVIEW_STATUSES = frozenset({"activated"})
REVIEW_TRACK_ALIASES = {
    "candidate": "exploration",
    "exploration": "exploration",
    "proposal": "exploration",
    "proposed": "exploration",
    "benchmark": "exploration",
    "benchmarked": "exploration",
    "selected": "exploration",
    "promotion": "promotion",
    "promoted": "promotion",
    "activation": "activation",
    "activated": "activation",
}


def build_review_checklist(spec: IntegrationSpec) -> ReviewChecklist:
    summary = (
        f"Review integration draft for primitive `{spec.primitive_id}` "
        f"against target `{spec.target_project_path}`."
    )
    return ReviewChecklist(
        spec_id=spec.spec_id,
        summary=summary,
        risk_points=spec.risk_points,
        manual_checks=spec.manual_checks,
    )


def render_review_checklist_markdown(checklist: ReviewChecklist) -> str:
    lines = [
        "# Integration Review Checklist",
        "",
        f"- Spec ID: `{checklist.spec_id}`",
        f"- Summary: {checklist.summary}",
        "",
        "## Manual Checks",
    ]
    if checklist.manual_checks:
        for item in checklist.manual_checks:
            lines.append(f"- [ ] {item}")
    else:
        lines.append("- [ ] No manual checks recorded")

    lines.extend(["", "## Risk Points"])
    if checklist.risk_points:
        for item in checklist.risk_points:
            lines.append(f"- {item}")
    else:
        lines.append("- None")
    lines.append("")
    return "\n".join(lines)


def build_review_result(
    *,
    spec: IntegrationSpec,
    reviewer: str,
    approved_checks: list[str],
    missing_checks: list[str],
    notes: str = "",
    reviewed_spec_path: Path | None = None,
    binding_path: Path | None = None,
    activation_path: Path | None = None,
) -> IntegrationReviewResult:
    status = "needs_review"
    if not missing_checks:
        status = "approved"
    if activation_path is not None and not missing_checks:
        status = "activated"
    return IntegrationReviewResult(
        spec_id=spec.spec_id,
        reviewer=reviewer,
        status=status,
        approved_checks=approved_checks,
        missing_checks=missing_checks,
        notes=notes,
        reviewed_spec_path=str(reviewed_spec_path) if reviewed_spec_path is not None else None,
        binding_path=str(binding_path) if binding_path is not None else None,
        activation_path=str(activation_path) if activation_path is not None else None,
    )


def build_activation_record(
    *,
    spec: IntegrationSpec,
    binding_id: str,
    binding_path: Path,
    reviewer: str,
    reviewed_spec_path: Path,
    review_result_path: Path,
) -> IntegrationActivationRecord:
    return IntegrationActivationRecord(
        spec_id=spec.spec_id,
        binding_id=binding_id,
        binding_path=str(binding_path),
        reviewer=reviewer,
        reviewed_spec_path=str(reviewed_spec_path),
        review_result_path=str(review_result_path),
    )


def is_generated_binding_id(binding_id: str | None) -> bool:
    return isinstance(binding_id, str) and binding_id.startswith("generated/")


def normalize_review_status(status: object) -> str | None:
    if not isinstance(status, str):
        return None
    normalized = status.strip().lower()
    return normalized or None


def normalize_review_track(track: object) -> str | None:
    if not isinstance(track, str):
        return None
    normalized = REVIEW_TRACK_ALIASES.get(track.strip().lower())
    return normalized or None


def is_exploration_review_status(status: object) -> bool:
    return normalize_review_status(status) in EXPLORATION_REVIEW_STATUSES


def is_promoted_review_status(status: object) -> bool:
    return normalize_review_status(status) in PROMOTION_REVIEW_STATUSES


def is_activated_review_status(status: object) -> bool:
    return normalize_review_status(status) in ACTIVATION_REVIEW_STATUSES


def review_track_for_status(status: object, *, track: object = None) -> str | None:
    normalized_track = normalize_review_track(track)
    if normalized_track is not None:
        return normalized_track

    normalized_status = normalize_review_status(status)
    if normalized_status is None:
        return None
    if normalized_status in ACTIVATION_REVIEW_STATUSES:
        return "activation"
    if normalized_status in PROMOTION_REVIEW_STATUSES:
        return "promotion"
    if normalized_status in EXPLORATION_REVIEW_STATUSES:
        return "exploration"
    return None


def _binding_review_payloads(binding: dict[str, object]) -> list[dict[str, object]]:
    payloads: list[dict[str, object]] = []
    review = binding.get("review")
    if isinstance(review, dict):
        payloads.append(review)

    binding_patch = binding.get("binding_patch")
    if isinstance(binding_patch, dict):
        runtime = binding_patch.get("runtime")
        if isinstance(runtime, dict):
            runtime_binding = runtime.get("binding")
            if isinstance(runtime_binding, dict):
                nested_review = runtime_binding.get("review")
                if isinstance(nested_review, dict):
                    payloads.append(nested_review)
    return payloads


def binding_review_status(binding: dict[str, object]) -> str | None:
    for review in _binding_review_payloads(binding):
        status = normalize_review_status(review.get("status"))
        if status is not None:
            return status
    return None


def binding_review_track(binding: dict[str, object]) -> str | None:
    for review in _binding_review_payloads(binding):
        track = review_track_for_status(
            review.get("status"),
            track=review.get("track")
            or review.get("lane")
            or review.get("scope")
            or review.get("lifecycle"),
        )
        if track is not None:
            return track
    return None


def generated_binding_requires_activation(binding: dict[str, object]) -> bool:
    binding_id = binding.get("binding_id")
    if not is_generated_binding_id(str(binding_id) if isinstance(binding_id, str) else None):
        return False
    for review in _binding_review_payloads(binding):
        explicit_track = normalize_review_track(
            review.get("track")
            or review.get("lane")
            or review.get("scope")
            or review.get("lifecycle")
        )
        if explicit_track == "exploration":
            return False
        status = normalize_review_status(review.get("status"))
        if status in {"proposed", "benchmarked", "selected", "rejected"}:
            return False
    return True


def require_activated_generated_binding(binding: dict[str, object]) -> None:
    binding_id = binding.get("binding_id")
    if not generated_binding_requires_activation(binding):
        return
    if is_activated_review_status(binding_review_status(binding)):
        return
    raise ValueError(
        f"generated binding '{binding_id}' requires activated review before execution"
    )
