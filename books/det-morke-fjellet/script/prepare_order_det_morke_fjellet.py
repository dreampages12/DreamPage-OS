import os
import sys
import shutil
from pathlib import Path

# DreamPage-roten finnes ved aa gaa OPPOVER til mappa som har books/ og flow/
# i seg - ikke ved aa telle mapper med dirname(dirname(...)), som brekker
# neste gang noe flyttes, og ikke ved aa hardkode en diskbokstav, som ikke
# finnes paa en Linux-server. Samme moenster som _dp_find_root i
# tekstscriptene; se CLAUDE.md.
def _dp_find_root(start):
    cur = os.path.dirname(os.path.abspath(start))
    while True:
        if (os.path.isdir(os.path.join(cur, "books"))
                and os.path.isdir(os.path.join(cur, "flow"))):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            raise RuntimeError("fant ingen DreamPage-rot (mappe med books/ "
                               "og flow/) over " + str(start))
        cur = parent


DP_ROOT = _dp_find_root(__file__)


def under(*parts):
    """En sti under DreamPage-roten, med plattformens separator.

    "/" i argumentet deles opp, slik at under("state/reprint") gir
    noeyaktig samme streng som under("state", "reprint") - og samme
    streng som flow/paths.py sin under(). Uten oppdelingen ville
    Windows fatt en sti med begge separatorer i seg. Den virker, men
    den er ikke den samme strengen koden hadde foer.
    """
    bits = [b for part in parts for b in str(part).split("/") if b]
    return os.path.join(DP_ROOT, *bits)

# === KONFIGURASJON ==========================
BOOK_ROOT = Path(under("books/det-morke-fjellet"))
BASE_DIR = BOOK_ROOT / "base"
ORDERS_DIR = BOOK_ROOT / "orders"
COMFY_OUTPUT_ROOT = Path(under("output")) / "det-morke-fjellet" / "orders"
SHARED_SCRIPT_DIR = Path(under("flow"))
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
    "page00": "forside(fjellet)",
    "page01": "01(fjellet)",
    "page02": "02(fjellet)",
    "page03": "03(fjellet)",
    "page04": "04(fjellet)",
    "page05": "05(fjellet)",
    "page06": "06(fjellet)",
    "page07": "07(fjellet)",
    "page08": "08(fjellet)",
    "page09": "09(fjellet)",
    "page10": "10(fjellet)",
    "page11": "11(fjellet)",
    "page12": "12(fjellet)",
    "page13": "13(fjellet)",
    "page14": "14(fjellet)",
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
        print("Bruk: python prepare_order_det_morke_fjellet.py <order_id>")
        raise SystemExit(1)

    main(sys.argv[1])
