from __future__ import annotations

from typing import Any


def paginate_items(
    items: list[dict[str, Any]] | list[str],
    *,
    limit: int | None = None,
    offset: int = 0,
) -> dict[str, Any]:
    normalized_offset = max(0, offset)
    total = len(items)

    if limit is None:
        paged = items[normalized_offset:]
        effective_limit = len(paged)
    else:
        effective_limit = max(0, limit)
        paged = items[normalized_offset : normalized_offset + effective_limit]

    return {
        "items": paged,
        "page": {
            "limit": effective_limit,
            "offset": normalized_offset,
            "total": total,
            "has_more": normalized_offset + len(paged) < total,
        },
    }
