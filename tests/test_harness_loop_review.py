from __future__ import annotations

import pytest

from meta_harness.integration_review import (
    binding_review_track,
    generated_binding_requires_activation,
    is_activated_review_status,
    is_exploration_review_status,
    is_promoted_review_status,
    normalize_review_status,
    require_activated_generated_binding,
    review_track_for_status,
)


def test_review_status_helpers_distinguish_exploration_promotion_and_activation() -> None:
    assert normalize_review_status(" approved ") == "approved"
    assert review_track_for_status("needs_review") == "exploration"
    assert review_track_for_status("promoted") == "promotion"
    assert review_track_for_status("activated") == "activation"
    assert is_exploration_review_status("benchmarked") is True
    assert is_promoted_review_status("promoted") is True
    assert is_activated_review_status("activated") is True


def test_generated_binding_allows_exploration_candidate_without_activation() -> None:
    binding = {
        "binding_id": "generated/candidate-binding",
        "review": {
            "status": "approved",
            "track": "exploration",
        },
    }

    assert binding_review_track(binding) == "exploration"
    assert generated_binding_requires_activation(binding) is False
    require_activated_generated_binding(binding)


def test_generated_binding_without_exploration_metadata_still_requires_activation() -> None:
    binding = {
        "binding_id": "generated/promoted-binding",
        "review": {
            "status": "approved",
        },
    }

    assert binding_review_track(binding) == "exploration"
    assert generated_binding_requires_activation(binding) is True
    with pytest.raises(ValueError, match="requires activated review"):
        require_activated_generated_binding(binding)


def test_binding_review_track_reads_nested_runtime_review_metadata() -> None:
    binding = {
        "binding_id": "generated/nested-candidate",
        "binding_patch": {
            "runtime": {
                "binding": {
                    "review": {
                        "status": "selected",
                        "track": "exploration",
                    }
                }
            }
        },
    }

    assert binding_review_track(binding) == "exploration"
    assert generated_binding_requires_activation(binding) is False
    require_activated_generated_binding(binding)
