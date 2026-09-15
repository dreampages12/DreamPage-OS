# -*- coding: utf-8 -*-
"""Render page99_next - neste bok sin forside med DENNE ordrens barnebilde.

Workeren lager den som et ekstra element i Pages Config, sa den finnes ikke
nar en ordre har kommet inn uten continue-felt. Da ma den lages i etterkant.

Malen og masken hentes fra neste bok sin config, barnebildet og utmappa fra
ordren. Rendringen gar gjennom samme las som workeren, sa en betalt ordre og
denne aldri sloss om GPU-en.

  python render_next_cover.py --order 1295 --next det-forsvunne-dinosauregget
  python render_next_cover.py --order 1295 --next ... --commit   # inn i comfy/
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

import dp_order
import regen_page

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass


def next_slug_for(info: dict, override: str = "") -> str:
    slug = override or str(info.get("next_book_slug") or "")
    if not slug:
        raise ValueError("ingen next_book_slug paa ordren eller i bokas config"
                         " - oppgi neste bok")
    return slug


def next_shim(info: dict, next_slug: str) -> dict:
    """En kopi av ordren som later som den ER neste bok.

    Rendringen skal bruke neste bok sin mal/maske/workflow, men ordrens
    barnebilde og ordrens egen utmappe - ikke neste bok sin.
    """
    next_config_path = os.path.join(r"C:\ComfyUI\books", next_slug, "config.json")
    if not os.path.isfile(next_config_path):
        raise FileNotFoundError(f"fant ikke {next_config_path}")
    with open(next_config_path, encoding="utf-8-sig") as fh:
        next_config = json.load(fh)

    next_config["comfyOutputPrefix"] = info["config"].get(
        "comfyOutputPrefix", f"{info['book_slug']}/orders")

    shim = dict(info)
    shim["config"] = next_config
    shim["book_slug"] = next_slug          # styrer hvilken workflow_api som lastes
    return shim


def render(info: dict, next_slug: str = "", count: int = 1, **kwargs) -> list[str]:
    """Render neste bok sin forside med DENNE ordrens barnebilde.

    kwargs gaar rett videre til regen_page.render_variants (face_image,
    on_progress, should_cancel), slik at boten kan vise framdrift og avbryte.
    """
    shim = next_shim(info, next_slug_for(info, next_slug))
    return regen_page.render_variants(shim, "page00", count=count, **kwargs)


def commit(info: dict, path: str) -> str:
    """Gjoer en variant til DEN raa neste-forsiden ordren bygger siden fra."""
    dst = os.path.join(info["comfy_dir"], "page99_next_00001_.png")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(path, dst)
    return dst


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--order", required=True)
    ap.add_argument("--next", dest="next_slug", default="",
                    help="slug for neste bok (default: fra payloaden)")
    ap.add_argument("--count", type=int, default=1)
    ap.add_argument("--commit", action="store_true",
                    help="kopier valgt variant til comfy/page99_next_00001_.png")
    args = ap.parse_args()

    info = dp_order.resolve(args.order)
    try:
        next_slug = next_slug_for(info, args.next_slug)
    except ValueError as error:
        raise SystemExit(f"{error} med --next")

    print(f"ordre {info['order_id']}  barn {info['child_name']}  "
          f"ansikt {info['face_image']}")
    print(f"neste bok {next_slug}")

    paths = render(info, next_slug, count=args.count)

    for path in paths:
        print(f"    {path}")

    if args.commit:
        print(f"\ncommit -> {commit(info, paths[-1])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
