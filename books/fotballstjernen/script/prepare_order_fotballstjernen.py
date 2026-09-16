import os
import sys
import shutil
from pathlib import Path

# === KONFIGURASJON ==========================
# Scriptet ligger i <DreamPage-rot>/books/fotballstjernen/script.
BOOK_ROOT = Path(__file__).resolve().parents[1]
COMFYUI_ROOT = BOOK_ROOT.parents[1]
BASE_DIR = BOOK_ROOT / "base"
ORDERS_DIR = BOOK_ROOT / "orders"
COMFY_OUTPUT_ROOT = COMFYUI_ROOT / "output" / "fotballstjernen" / "orders"
# De delte input-filene ligger i flow/, ikke i den gamle script/-mappa.
SHARED_SCRIPT_DIR = COMFYUI_ROOT / "flow"
EXTRA_INPUT_FILES = [
    "dreampage-first.png",
    "blank-back.png",
]
# ===========================================

# Hvilke faceswappede sider som skal ersatte hvilke base-bilder
# key   = "pageXX"  (fra ComfyUI)
# value = filnavn-stem i base/input (UTEN filending)
PAGE_TO_BASE_STEM = {
    "page00": "forside(fotballstjernen)",
    "page01": "01(fotballstjernen)",
    "page02": "02(fotballstjernen)",
    "page03": "03(fotballstjernen)",
    "page04": "04-right(fotballstjernen)",
    "page05": "05(fotballstjernen)",
    "page06": "06(fotballstjernen)",
    "page07": "07(fotballstjernen)",
    "page08": "08(fotballstjernen)",
    "page09": "09(fotballstjernen)",
    "page10": "10(fotballstjernen)",
    "page11": "11-right(fotballstjernen)",
    "page12": "12(fotballstjernen)",
    "page13": "13(fotballstjernen)",
    "page14": "14-right(fotballstjernen)",
    "page15": "15(fotballstjernen)",
}


def find_file_by_stem(folder: Path, stem: str) -> Path | None:
    """
    Finn en fil i 'folder' som starter med 'stem' (uavhengig av .png/.jpg osv).
    Returnerer Path eller None hvis ingenting matcher.
    """
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
    # --- Sett opp mapper for denne ordren ---
    order_root = ORDERS_DIR / order_id
    input_dir = order_root / "input"
    comfy_dir = COMFY_OUTPUT_ROOT / order_id / "comfy"

    if not order_root.exists():
        raise SystemExit(f"Fant ikke order-mappe: {order_root}")

    if not comfy_dir.exists():
        raise SystemExit(f"Fant ikke comfy-mappe for ordren: {comfy_dir}")

    input_dir.mkdir(parents=True, exist_ok=True)

    print(f"[INFO] Kopierer base-bilder fra {BASE_DIR} til {input_dir} ...")

    # 1) Kopier alle base-bilder først
    for filename in os.listdir(BASE_DIR):
        src = BASE_DIR / filename
        if not src.is_file():
            continue

        dst = input_dir / filename
        shutil.copy2(src, dst)

    for filename in EXTRA_INPUT_FILES:
        src = SHARED_SCRIPT_DIR / filename
        if not src.is_file():
            print(f"[ADVARSEL] Fant ikke delt input-fil: {src}")
            continue
        shutil.copy2(src, input_dir / filename)

    print("[INFO] Base-bilder kopiert. Overstyrer med faceswappede sider...")

    # 2) Erstatt utvalgte sider med faceswappede versjoner
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
        print("Bruk: python prepare_order_fotballstjernen.py <order_id>")
        raise SystemExit(1)

    main(sys.argv[1])
