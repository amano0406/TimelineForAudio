from __future__ import annotations

from typing import Any


def list_payload(
    *,
    key: str,
    count_key: str,
    total_key: str,
    returned_key: str,
    rows: list[dict[str, Any]],
    page: int | None,
    page_size: int | None,
    sort_fields: list[str],
) -> dict[str, Any]:
    if page is not None and page < 1:
        raise ValueError("--page must be 1 or greater.")
    if page_size is not None and page_size < 1:
        raise ValueError("--page-size must be 1 or greater.")

    total = len(rows)
    use_all = page is None and page_size is None
    if use_all:
        returned_rows = rows
        pagination = {
            "mode": "all",
            "page": None,
            "page_size": None,
            total_key: total,
            "total_pages": 1 if total else 0,
            returned_key: total,
            "offset": 0,
            "range_start": 1 if total else 0,
            "range_end": total,
            "has_previous": False,
            "has_next": False,
        }
    else:
        effective_page = page or 1
        effective_page_size = page_size or 100
        total_pages = (total + effective_page_size - 1) // effective_page_size if total else 0
        start = (effective_page - 1) * effective_page_size
        end = start + effective_page_size
        returned_rows = rows[start:end] if start < total else []
        returned_count = len(returned_rows)
        pagination = {
            "mode": "page",
            "page": effective_page,
            "page_size": effective_page_size,
            total_key: total,
            "total_pages": total_pages,
            returned_key: returned_count,
            "offset": start,
            "range_start": start + 1 if returned_count else 0,
            "range_end": start + returned_count if returned_count else 0,
            "has_previous": effective_page > 1 and total > 0,
            "has_next": effective_page < total_pages,
        }

    return {
        count_key: total,
        total_key: total,
        "pagination": pagination,
        "sort": {
            "order": "desc",
            "fields": sort_fields,
        },
        key: returned_rows,
    }
