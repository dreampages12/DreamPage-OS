import os
import sys
import shutil
from pathlib import Path

# === KONFIGURASJON ==========================
# Juster disse hvis du endrer struktur senere
BOOK_ROOT = Path(r"C:\DreamPage-OS\books\den-skjulte-styrken")
BASE_DIR = BOOK_ROOT / "base"
ORDERS_DIR = BOOK_ROOT / "orders"
COMFY_OUTPUT_ROOT = Path(r"C:\DreamPage-OS\output") / "den-skjulte-styrken" / "orders"
SHARED_SCRIPT_DIR = Path(r"C:\DreamPage-OS\flow")
EXTRA_INPUT_FILES = [
    "dreampage-first.png",
    "blank-back.png",
]
# ===========================================

# Hvilke faceswappede sider som skal ersatte hvilke base-bilder
# key   = "pageXX"  (fra ComfyUI)
# value = filnavn-stem i base/input (UTEN filending)
PAGE_TO_BASE_STEM = {
    "page00": "forside(styrken)",
    "page01": "01(styrken)",
    "page02": "02(styrken)",
    "page03": "03(styrken)",
    "page04": "04(styrken)",
    "page05": "05(styrken)",
    "page06": "06(styrken)",
    "page07": "07(styrken)",
    "page08": "08(styrken)",
    "page09": "09(styrken)",
    "page10": "10(styrken)",
    "page11": "11(styrken)",
    "page12": "12(styrken)",
    "page13": "13(styrken)",
    "page14": "14(styrken)",
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
        # Finn faceswappet fil i comfy_dir (starter med pageXX_...)
        swapped_src = None
        for name in os.listdir(comfy_dir):
            if name.startswith(page_prefix + "_"):
                swapped_src = comfy_dir / name
                break

        if swapped_src is None:
            print(f"[ADVARSEL] Fant ikke faceswappet bilde for {page_prefix} i {comfy_dir}")
            continue

        # Finn hvilken base-fil i input vi skal overwrite (01(Nissen).png osv)
        base_dst = find_file_by_stem(input_dir, base_stem)
        if base_dst is None:
            # Hvis vi ikke finner eksisterende, lag et fornuftig navn med .png
            base_dst = input_dir / f"{base_stem}.png"
            print(f"[INFO] Fant ikke eksisterende fil for {base_stem}, lager ny: {base_dst.name}")

        print(f"[INFO] {page_prefix} -> {base_dst.name}")
        shutil.copy2(swapped_src, base_dst)

    print("\n[Ferdig] Input-mappa er klar:")
    print(f"  {input_dir}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Bruk: python prepare_order_styrken.py <order_id>")
        raise SystemExit(1)

    main(sys.argv[1])
