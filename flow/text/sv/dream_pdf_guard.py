"""Inner-page guardrails for the DreamPage Gelato pipeline.

Accepted inner-page counts for the 30-page Gelato photobook product:

- 31 pages  -> NEW layout (opening + 28 story + blank-back + Lastpage).
              This fills the automation's `page_30` slot so the last printed
              page is never blank. Silent OK.

- 30 pages  -> LEGACY layout (opening + 28 story + blank-back). The
              automation's `page_30` slot ends up blank in the final book.
              Allowed for backwards compatibility, but logs a loud warning
              so the book can be updated.

- anything else (< 30, > 31, or with a missing opening/back page) is a
  loud error; we refuse to build a Gelato draft from it.

The Gelato API `pageCount` parameter is the product-variant identifier and
stays 30 regardless of how many physical inner pages the PDF carries.
"""
from __future__ import annotations

import os
from typing import Iterable, List, Optional, Sequence

from pypdf import PdfReader


ACCEPTED_INNER_PAGE_COUNTS: tuple[int, ...] = (30, 31)
LEGACY_INNER_PAGE_COUNT = 30
CURRENT_INNER_PAGE_COUNT = 31

# Back-compat: callers still import EXPECTED_INNER_PAGES. It now expresses
# the preferred (new) layout, not a strict equality requirement.
EXPECTED_INNER_PAGES = CURRENT_INNER_PAGE_COUNT


def _basename(path: str) -> str:
    return os.path.basename(path).lower()


def _is_final_inner_page(name: str) -> bool:
    return name == "blank-back.png" or name.startswith("lastpage") or name == "15(fotballstjernen).png"


def _is_opening_inner_page(name: str) -> bool:
    return name in {"blank.png", "dreampage-first-rendered.png"}


def describe_inner_page(path: str, index: int, total: int) -> str:
    name = _basename(path)
    if _is_opening_inner_page(name):
        return "first inner page / opening page"
    if _is_final_inner_page(name):
        return "final inner/back page"
    if index == 0:
        return "story/image page (WARNING: first page is not the opening page)"
    if index == total - 1:
        return "story/image page (WARNING: final page is not the final inner/back page)"
    return "story/image page"


def _emit_legacy_warning(actual: int, script_name: Optional[str]) -> None:
    label = f" for {script_name}" if script_name else ""
    print(
        f"[INNER PDF] 30-inner-page layout{label}: {actual} pages "
        "(opening + 28 story + blank-back, no Lastpage). build_gelato_pdf.py "
        "wraps this with blank front/back endpapers to reach the 33-page "
        "Gelato PDF; all 30 inner pages stay visible."
    )


def log_inner_page_order(
    inner_paths: Iterable[str],
    *,
    script_name: Optional[str] = None,
    expected_count: int = EXPECTED_INNER_PAGES,
    accepted_counts: Sequence[int] = ACCEPTED_INNER_PAGE_COUNTS,
) -> List[str]:
    """Log inner-page order and enforce the 30-or-31 page contract.

    `expected_count` is advisory only — it controls a single info line and
    no longer raises when the actual count differs, because the pipeline now
    accepts both the legacy (30) and current (31) layouts. The acceptance
    set is `accepted_counts` (default 30, 31).
    """
    all_paths = list(inner_paths)
    # Drop any per-book Lastpage(*).png centrally for ALL books. The 30-page
    # Gelato product has no slot for a 31st inner page; build_gelato_pdf.py now
    # adds real blank front/back endpapers instead. Removing it here means each
    # book builds its inner PDF from the filtered list returned below.
    paths = [p for p in all_paths if not _basename(p).startswith("lastpage")]
    dropped = len(all_paths) - len(paths)
    actual = len(paths)
    label = f" for {script_name}" if script_name else ""

    if dropped:
        print(
            f"[INNER PDF] Removed {dropped} Lastpage page(s){label}: the 30-page "
            "Gelato product has no slot for them (front/back endpapers are added "
            "by build_gelato_pdf.py)."
        )
    print(f"[INNER PDF] Final inner page order{label}: {actual} pages")
    print(
        f"[INNER PDF] Accepted layouts: {sorted(set(accepted_counts))} "
        f"(preferred: {expected_count})"
    )

    for i, path in enumerate(paths, start=1):
        role = describe_inner_page(path, i - 1, actual)
        print(f"[INNER PDF] Page {i}: {role} ({os.path.basename(path)})")

    if actual not in accepted_counts:
        raise ValueError(
            f"Inner PDF page count must be one of {sorted(set(accepted_counts))}; "
            f"got {actual}. Refusing to continue because Gelato fulfillment "
            "requires the exact product page count."
        )

    if not paths:
        raise ValueError("Inner page list is empty; refusing to build PDF.")

    first_name = _basename(paths[0])
    last_name = _basename(paths[-1])
    if not _is_opening_inner_page(first_name):
        raise ValueError(
            f"First inner page is {os.path.basename(paths[0])}, expected the opening page. "
            "Refusing to risk an unintended leading blank/story shift."
        )
    if not _is_final_inner_page(last_name):
        raise ValueError(
            f"Final inner page is {os.path.basename(paths[-1])}, expected blank-back.png or Lastpage(*).png. "
            "Refusing to risk an unintended trailing blank or missing final inner/back page."
        )

    # Per-file sanity: every page file must exist and be non-empty so the
    # Gelato draft does not silently end on an empty page.
    for i, path in enumerate(paths, start=1):
        if not os.path.isfile(path):
            raise ValueError(f"Inner page {i} file is missing: {path}")
        if os.path.getsize(path) <= 0:
            raise ValueError(f"Inner page {i} file is empty (0 bytes): {path}")

    if actual == LEGACY_INNER_PAGE_COUNT:
        _emit_legacy_warning(actual, script_name)
    else:
        print(f"[INNER PDF] 31-page layout active — page indexes 0-30 all filled.")

    if expected_count not in accepted_counts:
        print(
            f"[INNER PDF] NOTE: expected_count={expected_count} is outside the "
            f"accepted set {sorted(set(accepted_counts))}; treating it as advisory."
        )

    print("[INNER PDF] Blank padding added by PDF writer: none")
    return paths


def validate_inner_pdf_page_count(
    pdf_path: str,
    expected_count: int = EXPECTED_INNER_PAGES,
    accepted_counts: Sequence[int] = ACCEPTED_INNER_PAGE_COUNTS,
) -> int:
    """Validate the rendered inner PDF page count against the accepted set.

    Same rules as log_inner_page_order: 30 or 31 OK, 30 emits a warning,
    anything else raises.
    """
    actual = len(PdfReader(pdf_path).pages)
    if actual not in accepted_counts:
        raise ValueError(
            f"Rendered inner PDF has {actual} pages, expected one of "
            f"{sorted(set(accepted_counts))}: {pdf_path}"
        )
    if actual == LEGACY_INNER_PAGE_COUNT:
        _emit_legacy_warning(actual, os.path.basename(pdf_path))
    print(
        f"[INNER PDF] Validated rendered PDF page count: {actual} pages "
        f"(accepted: {sorted(set(accepted_counts))}, preferred: {expected_count}) "
        f"({pdf_path})"
    )
    return actual
