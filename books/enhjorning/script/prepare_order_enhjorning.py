from __future__ import annotations

import os
import shutil
import sys
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


BOOK_ROOT = Path(under("books/enhjorning"))
BASE_DIR = BOOK_ROOT / "base"
ORDERS_DIR = BOOK_ROOT / "orders"
COMFY_OUTPUT_ROOT = Path(under("output")) / "enhjorning" / "orders"
SHARED_SCRIPT_DIR = Path(under("flow"))
EXTRA_INPUT_FILES = [
    "dreampage-first.png",
    "blank-back.png",
]

PAGE_TO_BASE_STEM = {
    "page00": "forside(enhjorning)",
    "page01": "01(enhjorning)",
    "page02": "02(enhjorning)",
    "page03": "03(enhjorning-right)",
    "page04": "04(enhjorning)",
    "page05": "05(enhjorning)",
    "page06": "06(enhjorning)",
    "page07": "07(enhjorning)",
    "page08": "08(enhjorning)",
    "page09": "09(enhjorning)",
    "page10": "10(enhjorning)",
    "page11": "11(enhjorning)",
    "page12": "12(enhjorning)",
    "page13": "13(enhjorning)",
    "page14": "14(enhjorning)",
}


def find_file_by_stem(folder: Path, stem: str) -> Path | None:
    for name in os.listdir(folder):
        if name.startswith(stem):
            return folder / name
    return None


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
    missing = []
    for page_prefix, base_stem in PAGE_TO_BASE_STEM.items():
        swapped_src = None
        for name in os.listdir(comfy_dir):
            if name.startswith(page_prefix + "_"):
                swapped_src = comfy_dir / name
                break

        if swapped_src is None:
            missing.append(page_prefix)
            print(f"[ADVARSEL] Fant ikke faceswappet bilde for {page_prefix} i {comfy_dir}")
            continue

        base_dst = find_file_by_stem(input_dir, base_stem)
        if base_dst is None:
            base_dst = input_dir / f"{base_stem}.png"
            print(f"[INFO] Fant ikke eksisterende fil for {base_stem}, lager ny: {base_dst.name}")

        print(f"[INFO] {page_prefix} -> {base_dst.name}")
        shutil.copy2(swapped_src, base_dst)

    if missing:
        raise SystemExit("Mangler faceswappede sider: " + ", ".join(missing))

    print("\n[Ferdig] Input-mappa er klar:")
    print(f"  {input_dir}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Bruk: python prepare_order_enhjorning.py <order_id>")
        raise SystemExit(1)

    main(sys.argv[1])
