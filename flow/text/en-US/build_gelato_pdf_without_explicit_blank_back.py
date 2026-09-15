"""
Build a Gelato draft PDF that omits DreamPage's explicit blank-back page.

Gelato is adding an empty final page in the preview for this product. Sending
the 29 real inner pages (opening page + all story/image pages) avoids a second
empty end page while preserving every real content page.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from pypdf import PdfReader, PdfWriter


def build(
    cover_path: str,
    inner_path: str,
    out_path: str,
    expected_inner: int,
    expected_total: int,
) -> dict:
    if not os.path.isfile(cover_path):
        raise FileNotFoundError(f"Cover PDF missing: {cover_path}")
    if not os.path.isfile(inner_path):
        raise FileNotFoundError(f"Inner PDF missing: {inner_path}")

    cover = PdfReader(cover_path)
    inner = PdfReader(inner_path)
    cover_pages = list(cover.pages)
    inner_pages = list(inner.pages)

    if len(cover_pages) != 1:
        raise ValueError(f"Cover PDF must be exactly 1 page. Got {len(cover_pages)}.")
    if len(inner_pages) != expected_inner:
        raise ValueError(
            f"Inner PDF has {len(inner_pages)} pages, expected {expected_inner}."
        )

    submitted_inner = inner_pages[:-1]
    dropped = [len(inner_pages)]

    writer = PdfWriter()
    writer.add_page(cover_pages[0])
    for page in submitted_inner:
        writer.add_page(page)

    total = len(writer.pages)
    if total != expected_total:
        raise RuntimeError(f"Built PDF has {total} pages, expected {expected_total}.")

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "wb") as f:
        writer.write(f)

    print("[GELATO AUTO BACK] Page 1: cover spread")
    for out_index, source_index in enumerate(range(1, len(submitted_inner) + 1), start=2):
        role = "first inner page / opening page" if source_index == 1 else "story/image page"
        print(
            f"[GELATO AUTO BACK] PDF page {out_index}: "
            f"{role} (source inner page {source_index})"
        )
    print(
        "[GELATO AUTO BACK] Dropped explicit blank-back source inner page: "
        f"{dropped[0]}"
    )

    return {
        "gelato_pdf": out_path,
        "pageCount": total,
        "innerPageCount": len(inner_pages),
        "submittedInnerPageCount": len(submitted_inner),
        "innerPaddedTo": len(submitted_inner),
        "frontPad": 0,
        "backPad": 0,
        "endpapersAdded": False,
        "explicitBlankBackSubmitted": False,
        "gelatoAutoBackExpected": True,
        "droppedInnerPages": dropped,
        "keptInnerPages": list(range(1, len(submitted_inner) + 1)),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cover", required=True)
    ap.add_argument("--inner", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--expected-inner", type=int, default=30)
    ap.add_argument("--expected-total", type=int, default=30)
    args = ap.parse_args()

    info = build(
        cover_path=args.cover,
        inner_path=args.inner,
        out_path=args.out,
        expected_inner=args.expected_inner,
        expected_total=args.expected_total,
    )
    print(json.dumps(info))
    return 0


if __name__ == "__main__":
    sys.exit(main())
