"""
Build the Gelato print-ready PDF for the DreamPage 30-page photobook product.

Reads the existing cover.pdf and innersider.pdf produced by the per-book
*-text.py scripts and assembles a combined PDF with blank Gelato endpaper
pages wrapped around the already-finished inner PDF:

    Page 1     : cover spread (back + spine + front in one page)
    Page 2     : blank FRONT endpaper (Gelato glues this to the inside front
                 cover; it is NOT printed as a visible page)
    Pages 3..M : inner printable pages exactly as produced by the text script
    Remaining pages: blank BACK endpaper(s) until the PDF has 33 pages

The front blank is critical. Gelato consumes the first PDF page after the
cover as the inside-front-cover endpaper. Without it, the real opening page
(page0) is glued away and every following page shifts by one, which tears
each split L/R illustration across two different physical spreads.

Accepted inner-page counts:
    * 31  -> NEW layout (opening + 28 story + blank-back + Lastpage).
             Page indexes 0-30 are all filled. Silent OK.
    * 30  -> LEGACY layout (opening + 28 story + blank-back).
             The automation's `page_30` slot ends up blank. Allowed for
             backwards compatibility, but logs a loud warning so the book
             can be updated.

Anything outside {30, 31} (including gaps or unreadable pages) is a loud
error; we refuse to build a Gelato draft from it.

The Gelato API `pageCount` parameter is the product-variant identifier and
stays 30 regardless of how many physical inner pages the PDF carries.

Usage:
    python build_gelato_pdf.py --cover <cover.pdf> --inner <innersider.pdf>
                               --out <combined.pdf>
                               [--book-slug <slug>] [--order-id <id>]
                               [--expected-inner 31]

Stdout (last line) is a single JSON object — see build() docstring for
the full schema.
"""
import argparse
import json
import os
import sys

from pypdf import PdfReader, PdfWriter


ACCEPTED_INNER_COUNTS = (30, 31)
LEGACY_INNER_COUNT = 30
CURRENT_INNER_COUNT = 31
REQUIRED_GELATO_TOTAL_PAGES = 33


def _log(prefix: str, message: str) -> None:
    print(f"[GELATO PDF {prefix}] {message}", file=sys.stderr)


def build(
    cover_path: str,
    inner_path: str,
    out_path: str,
    expected_inner: int = CURRENT_INNER_COUNT,
    book_slug: str = "",
    order_id: str = "",
) -> dict:
    if not os.path.isfile(cover_path):
        raise FileNotFoundError(f"Cover PDF missing: {cover_path}")
    if not os.path.isfile(inner_path):
        raise FileNotFoundError(f"Inner PDF missing: {inner_path}")
    if os.path.getsize(cover_path) <= 0:
        raise ValueError(f"Cover PDF is empty (0 bytes): {cover_path}")
    if os.path.getsize(inner_path) <= 0:
        raise ValueError(f"Inner PDF is empty (0 bytes): {inner_path}")

    cover = PdfReader(cover_path)
    inner = PdfReader(inner_path)

    cover_pages = list(cover.pages)
    inner_pages = list(inner.pages)

    if len(cover_pages) != 1:
        raise ValueError(
            f"Cover PDF must be exactly 1 page (the spread). "
            f"Got {len(cover_pages)} pages in {cover_path}."
        )

    inner_count = len(inner_pages)
    if inner_count not in ACCEPTED_INNER_COUNTS:
        raise ValueError(
            f"Inner PDF has {inner_count} pages, expected one of "
            f"{list(ACCEPTED_INNER_COUNTS)} for the 30-page Gelato photobook. "
            "Refusing to pad or trim; fix the inner generator before "
            "creating the Gelato PDF."
        )

    compat_mode_31 = inner_count == CURRENT_INNER_COUNT
    legacy_warning = None
    if inner_count == LEGACY_INNER_COUNT:
        _log(
            "INFO",
            "30-inner-page layout (opening + 28 story + blank-back, no "
            "Lastpage). Builder adds 1 blank front + 1 blank back endpaper to "
            "reach the 33-page Gelato PDF; all 30 inner pages stay visible.",
        )
    else:
        legacy_warning = (
            f"31-inner-page layout for book='{book_slug or '?'}' "
            f"order='{order_id or '?'}'. The 31st inner page (e.g. "
            "Lastpage(*).png) lands on the back endpaper slot and is glued "
            "down / not printed as a visible page. Remove it for the clean "
            "30-inner-page layout."
        )
        _log("WARN", legacy_warning)

    if expected_inner not in ACCEPTED_INNER_COUNTS:
        _log(
            "INFO",
            f"--expected-inner={expected_inner} is outside accepted set "
            f"{list(ACCEPTED_INNER_COUNTS)}; treating as advisory.",
        )

    writer = PdfWriter()

    # 1) Cover spread.
    writer.add_page(cover_pages[0])

    # 2) Blank FRONT endpaper. Gelato glues the first PDF page after the cover
    # onto the inside front cover, so it is not printed as a visible page. This
    # blank absorbs that slot; without it the real opening page (page0) is
    # consumed there and every following page shifts by one, breaking every
    # split L/R illustration spread.
    front_box = inner_pages[0].mediabox
    writer.add_blank_page(
        width=float(front_box.width),
        height=float(front_box.height),
    )

    # 3) Inner pages exactly as produced by the text script. Order is preserved
    # — pypdf iterates the inner PDF page-by-page in numeric order (PDF page
    # objects are stored in document order, not by filename).
    for p in inner_pages:
        writer.add_page(p)

    last_inner_box = inner_pages[-1].mediabox
    final_blank_count = REQUIRED_GELATO_TOTAL_PAGES - len(writer.pages)
    if final_blank_count < 0:
        raise RuntimeError(
            f"Combined PDF already has {len(writer.pages)} pages before final "
            f"Gelato blanks; required total is {REQUIRED_GELATO_TOTAL_PAGES}. "
            "Inner page count is too high (cover + front endpaper + inner "
            "already exceeds 33)."
        )
    for _ in range(final_blank_count):
        writer.add_blank_page(
            width=float(last_inner_box.width),
            height=float(last_inner_box.height),
        )

    total = len(writer.pages)
    if total != REQUIRED_GELATO_TOTAL_PAGES:
        raise RuntimeError(
            f"Built combined PDF has {total} pages, expected "
            f"{REQUIRED_GELATO_TOTAL_PAGES}. Inner was {inner_count}, plus "
            f"1 cover and {final_blank_count} final blank endpaper page(s)."
        )

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "wb") as f:
        writer.write(f)

    gelato_page_index_first = 0
    gelato_page_index_last = inner_count - 1

    audit = {
        "gelato_pdf": out_path,
        "pageCount": total,
        "innerPageCount": inner_count,
        "innerPaddedTo": inner_count,
        "frontPad": 1,
        "frontEndpaperAdded": True,
        "backPad": final_blank_count,
        "endpapersAdded": True,
        "finalBlankPageAdded": final_blank_count > 0,
        "finalBlankPageCount": final_blank_count,
        "coverPageCount": 1,
        "expectedInnerPreferred": CURRENT_INNER_COUNT,
        "acceptedInnerCounts": list(ACCEPTED_INNER_COUNTS),
        "compatMode31": compat_mode_31,
        "layoutWarning": legacy_warning,
        "gelatoPageIndexFirst": gelato_page_index_first,
        "gelatoPageIndexLast": gelato_page_index_last,
        "gelatoPageIndexRange": f"{gelato_page_index_first}-{gelato_page_index_last}",
        "gelatoProductPageCount": 30,
        "bookSlug": book_slug,
        "orderId": order_id,
        "coverPdf": cover_path,
        "innerPdf": inner_path,
    }

    _log(
        "AUDIT",
        f"book={book_slug or '?'} order={order_id or '?'} "
        f"inner={inner_count} combined={total} "
        f"gelatoIndexes={audit['gelatoPageIndexRange']} "
        f"compatMode31={compat_mode_31}",
    )

    return audit


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cover", required=True)
    ap.add_argument("--inner", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument(
        "--expected-inner",
        type=int,
        default=CURRENT_INNER_COUNT,
        help="Preferred inner page count (advisory; accepted set is 30 or 31).",
    )
    ap.add_argument(
        "--expected-total",
        type=int,
        default=None,
        help="Deprecated/advisory; Gelato total is fixed at 33 pages.",
    )
    ap.add_argument("--book-slug", default="")
    ap.add_argument("--order-id", default="")
    args = ap.parse_args()

    info = build(
        cover_path=args.cover,
        inner_path=args.inner,
        out_path=args.out,
        expected_inner=args.expected_inner,
        book_slug=args.book_slug,
        order_id=args.order_id,
    )
    print(json.dumps(info))
    return 0


if __name__ == "__main__":
    sys.exit(main())
