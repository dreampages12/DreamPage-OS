# -*- coding: utf-8 -*-
"""Luft opp dedikasjonsteksten paa dreampage-first (introsida) for
den-magiske-reisen-jente.

Introsida tegnes av `render_page`-grenen `type == "blank"`, som kaller
`draw_text(...)` UTEN `line_spacing`. Defaulten i signaturen er 10 px - en
absolutt verdi som stammer fra en 1024 px-mal. Paa den ferdige 4096 px-sida er
fonten ~168 px, saa 10 px linjeavstand klistrer linjene sammen.

Bursdagen-/juleprinsessen-familien (`render_dreampage_first`) bruker
`line_gap = font_body_size * 0.55` paa den samme teksten. Denne patchen gir
Family-B-grenen det samme forholdet, saa introsida ser lik ut paa tvers av boker.

Idempotent - kjor den paa nytt naar som helst.

  python patch_dpfirst_linespacing.py --dry-run
  python patch_dpfirst_linespacing.py --apply
"""
from __future__ import annotations

import argparse
import io
import os
import sys

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

SCRIPT_ROOT = under("flow")
NAME = "den-magiske-reisen-jente-text-%s.py"
LOCALES = ["nb", "nn", "en-US", "en-GB", "sv"]
BACKUP_SUFFIX = ".backup-before-dpfirst-linespacing-20260914"

OLD = """                color=block.get("color", "#111111"),
                highlights=block.get("highlights", []),
                gradient=None,
                img=img,
                align="center"
            )"""

NEW = """                color=block.get("color", "#111111"),
                highlights=block.get("highlights", []),
                gradient=None,
                img=img,
                align="center",
                # Defaulten er 10 px absolutt (arvet fra en 1024 px-mal) og
                # klistret linjene sammen paa 4096 px-sida. 0.55 * fontstorrelsen
                # er samme forhold som render_dreampage_first bruker i
                # bursdagen-familien.
                line_spacing=max(10, int(font_size * 0.55)),
            )"""


def transform(src: str) -> tuple[str, str]:
    if NEW in src:
        return src, "allerede patchet"
    if src.count(OLD) != 1:
        raise SystemExit("fant %d treff paa draw_text-kallet (ventet 1)" % src.count(OLD))
    return src.replace(OLD, NEW), "linje_spacing lagt inn"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not (args.apply or args.dry_run):
        ap.error("velg --dry-run eller --apply")

    for locale in LOCALES:
        path = os.path.join(SCRIPT_ROOT, locale, NAME % locale)
        src = io.open(path, encoding="utf-8").read()
        out, note = transform(src)
        print("%-6s %s" % (locale, note))
        if out == src:
            continue
        compile(out, NAME % locale, "exec")
        if args.apply:
            bak = path + BACKUP_SUFFIX
            if not os.path.exists(bak):
                io.open(bak, "w", encoding="utf-8", newline="\n").write(src)
                print("       backup:", bak)
            io.open(path, "w", encoding="utf-8", newline="\n").write(out)
            print("       -> skrev", path)

    if not args.apply:
        print("(dry-run - ingenting skrevet)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
