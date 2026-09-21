import os
import sys
import shutil
from pathlib import Path
from PIL import Image

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
BOOK_ROOT = Path(under("books/havfruen"))
BASE_DIR = BOOK_ROOT / "base"
ORDERS_DIR = BOOK_ROOT / "orders"
COMFY_OUTPUT_ROOT = Path(under("output")) / "havfruen" / "orders"
SHARED_SCRIPT_DIR = Path(under("flow"))
EXTRA_INPUT_FILES = [
    "dreampage-first.png",
    "blank-back.png",
]
# ===========================================

PAGE_TO_BASE_STEM = {
    "page00": "forside(havfrue)",
    "page01": "01(havfrue)",
    "page02": "02(havfrue)",
    "page03": "03(havfrue)",
    "page04": "04(havfrue)",
    "page05": "05(havfrue)",
    "page06": "06(havfrue)",
    "page07": "07(havfrue)",
    "page08": "08(havfrue)",
    "page09": "09(havfrue)",
    "page10": "10(havfrue)",
    "page11": "11(havfrue)",
    "page12": "12(havfrue)",
    "page13": "13(havfrue)",
    "page14": "14(havfrue)",
}


def find_file_by_stem(folder: Path, stem: str) -> Path | None:
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

    for page_prefix, base_stem in PAGE_TO_BASE_STEM.items():
        swapped_src = find_swapped_image(comfy_dir, page_prefix)

        if swapped_src is None:
            print(f"[ADVARSEL] Fant ikke faceswappet bilde for {page_prefix} i {comfy_dir}")
            continue

        base_dst = find_file_by_stem(input_dir, base_stem)
        if base_dst is None:
            base_dst = input_dir / f"{base_stem}.png"
            print(f"[INFO] Fant ikke eksisterende fil for {base_stem}, lager ny: {base_dst.name}")

        print(f"[INFO] {page_prefix} -> {base_dst.name}")
        copy_image_checked(swapped_src, base_dst)

    print("\n[Ferdig] Input-mappa er klar:")
    print(f"  {input_dir}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Bruk: python prepare_order_havfruen.py <order_id>")
        raise SystemExit(1)

    main(sys.argv[1])
