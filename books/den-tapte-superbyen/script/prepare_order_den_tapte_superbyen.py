import os
import sys
import shutil
from pathlib import Path

# === KONFIGURASJON ==========================
BOOK_ROOT = Path(r"C:\DreamPage-OS\books\den-tapte-superbyen")
BASE_DIR = BOOK_ROOT / "base"
ORDERS_DIR = BOOK_ROOT / "orders"
COMFY_OUTPUT_ROOT = Path(r"C:\DreamPage-OS\output") / "den-tapte-superbyen" / "orders"
SHARED_SCRIPT_DIR = Path(r"C:\DreamPage-OS\flow")
EXTRA_INPUT_FILES = [
    "dreampage-first.png",
    "blank-back.png",
]
# ===========================================

# Hvilke faceswappede sider som skal erstatte hvilke base-bilder.
# key   = "pageXX"  (fra ComfyUI)
# value = filnavn-stem i base/input (UTEN filending)
#
# Denne lista MAA staa likt med "pages" i config.json. Ordre 1528: kartet i
# prepare_order_styrken.py hadde sider config.json ikke kjente, saa tre
# [ADVARSEL]-linjer kom paa hver eneste bygging. Da tolv ekte advarsler kom,
# saa de ut som mer av det samme - og tolv raa maler gikk til Gelato.
PAGE_TO_BASE_STEM = {
    "page00": "forside(superbyen)",
    "page01": "01(superbyen)",
    "page02": "02(superbyen)",
    "page03": "03(superbyen)",
    "page04": "04(superbyen)",
    "page05": "05(superbyen)",
    "page06": "06(superbyen)",
    "page07": "07(superbyen)",
    "page08": "08(superbyen)",
    "page09": "09(superbyen)",
    "page10": "10(superbyen)",
    "page11": "11(superbyen)",
    "page12": "12(superbyen)",
    "page13": "13(superbyen)",
    "page14": "14(superbyen)",
}


def find_file_by_stem(folder: Path, stem: str) -> Path | None:
    """Finn en fil i 'folder' som starter med 'stem' (uavhengig av filending)."""
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

    # 1) Kopier alle base-bilder foerst
    for filename in os.listdir(BASE_DIR):
        src = BASE_DIR / filename
        if not src.is_file():
            continue
        shutil.copy2(src, input_dir / filename)

    for filename in EXTRA_INPUT_FILES:
        src = SHARED_SCRIPT_DIR / filename
        if not src.is_file():
            print(f"[ADVARSEL] Fant ikke delt input-fil: {src}")
            continue
        shutil.copy2(src, input_dir / filename)

    print("[INFO] Base-bilder kopiert. Overstyrer med faceswappede sider...")

    # 2) Erstatt utvalgte sider med faceswappede versjoner.
    #    Ordre 1528: mangler en faceswappet side her, er malen fortsatt raa.
    #    Derfor teller vi dem opp og stopper til slutt hvis noen mangler.
    missing = []
    for page_prefix, base_stem in PAGE_TO_BASE_STEM.items():
        swapped_src = None
        for name in sorted(os.listdir(comfy_dir)):
            if name.startswith(page_prefix + "_"):
                swapped_src = comfy_dir / name
                break

        if swapped_src is None:
            print(f"[ADVARSEL] Fant ikke faceswappet bilde for {page_prefix} i {comfy_dir}")
            missing.append(page_prefix)
            continue

        base_dst = find_file_by_stem(input_dir, base_stem)
        if base_dst is None:
            base_dst = input_dir / f"{base_stem}.png"

        print(f"[INFO] {page_prefix} -> {base_dst.name}")
        shutil.copy2(swapped_src, base_dst)

    if missing:
        raise SystemExit(
            "[FEIL] Mangler faceswappede sider: " + ", ".join(missing) + "\n"
            "[FEIL] Uten dem gaar RAA maler til trykk (ordre 1528). Stopper.")

    print("\n[Ferdig] Input-mappa er klar:")
    print(f"  {input_dir}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Bruk: python prepare_order_den_tapte_superbyen.py <order_id>")
        raise SystemExit(1)

    main(sys.argv[1])
