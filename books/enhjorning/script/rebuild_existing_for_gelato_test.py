from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


COMFY_ROOT = Path(r"C:\ComfyUI")
BOOK_ROOT = COMFY_ROOT / "books" / "enhjorning"
ORDER_ROOT = BOOK_ROOT / "orders"
PREPARE_SCRIPT = BOOK_ROOT / "script" / "prepare_order_enhjorning.py"
TEXT_SCRIPT = COMFY_ROOT / "script" / "Enhjorning-text.py"
GELATO_BUILDER = COMFY_ROOT / "script" / "build_gelato_pdf.py"


def run_step(command: list[str], env: dict[str, str] | None = None) -> str:
    print("[RUN]", " ".join(command))
    result = subprocess.run(
        command,
        cwd=str(COMFY_ROOT),
        env=env,
        text=True,
        capture_output=True,
    )
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    if result.returncode != 0:
        raise SystemExit(result.returncode)
    return result.stdout


def parse_last_json(stdout: str) -> dict:
    for line in reversed([line.strip() for line in stdout.splitlines() if line.strip()]):
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue
    raise ValueError("No JSON payload found in command output")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--order-id", default="459")
    parser.add_argument("--name", default="Helene")
    parser.add_argument("--cover-type", default="hardcover")
    parser.add_argument("--expected-inner", type=int, default=30)
    parser.add_argument("--expected-total", type=int, default=33)
    parser.add_argument("--gelato-api-key", default=os.environ.get("GELATO_API_KEY"))
    args = parser.parse_args()

    order_dir = ORDER_ROOT / args.order_id
    input_dir = order_dir / "input"
    pdf_dir = order_dir / "pdf"
    cover_pdf = pdf_dir / f"{args.name}_cover.pdf"
    inner_pdf = pdf_dir / f"{args.name}_innersider.pdf"
    gelato_pdf = pdf_dir / f"{args.name}_gelato.pdf"

    run_step([sys.executable, str(PREPARE_SCRIPT), args.order_id])

    env = os.environ.copy()
    if args.gelato_api_key:
        env["GELATO_API_KEY"] = args.gelato_api_key

    run_step(
        [
            sys.executable,
            str(TEXT_SCRIPT),
            "--name",
            args.name,
            "--base",
            str(input_dir),
            "--out",
            str(pdf_dir),
            "--cover-type",
            args.cover_type,
        ],
        env=env,
    )

    builder_out = run_step(
        [
            sys.executable,
            str(GELATO_BUILDER),
            "--cover",
            str(cover_pdf),
            "--inner",
            str(inner_pdf),
            "--out",
            str(gelato_pdf),
            "--expected-inner",
            str(args.expected_inner),
            "--expected-total",
            str(args.expected_total),
        ]
    )

    info = parse_last_json(builder_out)
    info.update(
        {
            "order_id": args.order_id,
            "child_name": args.name,
            "cover_pdf": str(cover_pdf),
            "inner_pdf": str(inner_pdf),
            "gelato_pdf": str(gelato_pdf),
            "gelatoPrintableInnerStartPdfPage": 2,
            "gelatoPrintableInnerEndPdfPage": 1 + info.get("innerPageCount", 0),
            "gelatoPrintablePages": "PDF starts with cover, then all generated inner pages, then final blank Gelato endpaper page(s) until 33 total pages.",
        }
    )
    print(json.dumps(info, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
