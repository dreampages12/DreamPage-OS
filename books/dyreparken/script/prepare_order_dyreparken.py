import os
import sys
import shutil
from pathlib import Path
from PIL import Image

# === KONFIGURASJON ==========================
# Juster disse hvis du endrer struktur senere
BOOK_ROOT = Path(r"C:\ComfyUI\books\dyreparken")
BASE_DIR = BOOK_ROOT / "base"
ORDERS_DIR = BOOK_ROOT / "orders"
COMFY_OUTPUT_ROOT = Path(r"C:\ComfyUI\output") / "dyreparken" / "orders"
SHARED_SCRIPT_DIR = Path(r"C:\ComfyUI\script")
EXTRA_INPUT_FILES = [
    "dreampage-first.png",
    "blank-back.png",
]
# ===========================================

# Hvilke faceswappede sider som skal ersatte hvilke base-bilder
# key   = "pageXX"  (fra ComfyUI)
# value = filnavn-stem i base/input (UTEN filending)
PAGE_TO_BASE_STEM = {
    "page00": "forside(dyreparken)",
    "page01": "01(dyreparken)",
    "page02": "02(dyreparken)",
    "page03": "03(dyreparken)",
    "page04": "04(dyreparken)",
    "page05": "05(dyreparken)",
    "page06": "06(dyreparken)",
    "page07": "07(dyreparken)",
    "page08": "08(dyreparken)",
    "page09": "09(dyreparken)",
    "page10": "10(dyreparken)",
    "page11": "11(dyreparken)",
    "page12": "12(dyreparken)",
    "page13": "13(dyreparken)",
    "page14": "14(dyreparken)",
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


def verify_image(path: Path) -> None:
    with Image.open(path) as img:
        img.verify()


def copy_image_checked(src: Path, dst: Path) -> None:
    verify_image(src)
    tmp = dst.with_name(f"{dst.name}.tmp")
    shutil.copy2(src, tmp)
    verify_image(tmp)
    tmp.replace(dst)


def find_swapped_image(comfy_dir: Path, page_prefix: str) -> Path | None:
    matches = [
        comfy_dir / name
        for name in os.listdir(comfy_dir)
        if name.startswith(page_prefix + "_")
    ]
    for path in sorted(matches, key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            verify_image(path)
            return path
        except Exception as exc:
            print(f"[ADVARSEL] Hopper over ugyldig Comfy-bilde {path.name}: {exc}")
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
        swapped_src = find_swapped_image(comfy_dir, page_prefix)

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
        copy_image_checked(swapped_src, base_dst)

    print("\n[Ferdig] Input-mappa er klar:")
    print(f"  {input_dir}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Bruk: python prepare_order_dyreparken.py <order_id>")
        raise SystemExit(1)

    main(sys.argv[1])
