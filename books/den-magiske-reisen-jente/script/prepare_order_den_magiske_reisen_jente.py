import os
import sys
import shutil
from pathlib import Path

BOOK_ROOT = Path(r"C:\ComfyUI\books\den-magiske-reisen-jente")
BASE_DIR = BOOK_ROOT / "base"
ORDERS_DIR = BOOK_ROOT / "orders"
COMFY_OUTPUT_ROOT = Path(r"C:\ComfyUI\output") / "den-magiske-reisen-jente" / "orders"
SHARED_SCRIPT_DIR = Path(r"C:\ComfyUI\script")
EXTRA_INPUT_FILES = [
    "dreampage-first.png",
    "blank-back.png",
]

PAGE_TO_BASE_STEM = {
    "page00": "forside(den-magiske-reisen-jente)",
    "page01": "01(den-magiske-reisen-jente)",
    "page02": "02(den-magiske-reisen-jente)",
    "page03": "03(den-magiske-reisen-jente)",
    "page04": "04(den-magiske-reisen-jente)",
    "page05": "05(den-magiske-reisen-jente)",
    "page06": "06(den-magiske-reisen-jente)",
    "page07": "07(den-magiske-reisen-jente)",
    "page08": "08(den-magiske-reisen-jente)",
    "page09": "09(den-magiske-reisen-jente)",
    "page10": "10(den-magiske-reisen-jente)",
    "page11": "11(den-magiske-reisen-jente)",
    "page12": "12(den-magiske-reisen-jente)",
    "page13": "13(den-magiske-reisen-jente)",
    "page14": "14(den-magiske-reisen-jente)",
}


def find_file_by_stem(folder: Path, stem: str) -> Path | None:
    for name in os.listdir(folder):
        if name.startswith(stem):
            return folder / name
    return None


def find_latest_page_file(folder: Path, page_prefix: str) -> Path | None:
    matches = [
        folder / name
        for name in os.listdir(folder)
        if name.startswith(page_prefix + "_")
    ]
    if not matches:
        return None
    return max(matches, key=lambda p: p.stat().st_mtime)


def main(order_id: str) -> None:
    order_root = ORDERS_DIR / order_id
    input_dir = order_root / "input"
    comfy_dir = COMFY_OUTPUT_ROOT / order_id / "comfy"

    if not order_root.exists():
        raise SystemExit(f"Fant ikke order-mappe: {order_root}")

    if not comfy_dir.exists():
        raise SystemExit(f"Fant ikke comfy-mappe for ordren: {comfy_dir}")

    input_dir.mkdir(parents=True, exist_ok=True)

    print(f"[INFO] Kopierer base-bilder fra {BASE_DIR} til {input_dir} ...")

    for filename in os.listdir(BASE_DIR):
        src = BASE_DIR / filename
        if src.is_file():
            shutil.copy2(src, input_dir / filename)

    for filename in EXTRA_INPUT_FILES:
        src = SHARED_SCRIPT_DIR / filename
        if not src.is_file():
            print(f"[ADVARSEL] Fant ikke delt input-fil: {src}")
            continue
        shutil.copy2(src, input_dir / filename)

    print("[INFO] Base-bilder kopiert. Overstyrer med faceswappede sider...")

    for page_prefix, base_stem in PAGE_TO_BASE_STEM.items():
        swapped_src = find_latest_page_file(comfy_dir, page_prefix)

        if swapped_src is None:
            print(f"[ADVARSEL] Fant ikke faceswappet bilde for {page_prefix} i {comfy_dir}")
            continue

        base_dst = find_file_by_stem(input_dir, base_stem)
        if base_dst is None:
            base_dst = input_dir / f"{base_stem}.png"
            print(f"[INFO] Fant ikke eksisterende fil for {base_stem}, lager ny: {base_dst.name}")

        print(f"[INFO] {page_prefix} -> {base_dst.name}")
        shutil.copy2(swapped_src, base_dst)

    print("\n[Ferdig] Input-mappa er klar:")
    print(f"  {input_dir}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Bruk: python prepare_order_den_magiske_reisen_jente.py <order_id>")
        raise SystemExit(1)

    main(sys.argv[1])
