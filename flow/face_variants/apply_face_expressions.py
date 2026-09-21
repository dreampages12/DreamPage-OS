# -*- coding: utf-8 -*-
"""
Legger `face_expression` pa hver side i books/<slug>/config.json.

Default er "noytral" - lukket munn, rolig, kan smile bittelitt. Den skal sta pa
nesten alle sider. "smil" brukes bare der scenen er utvetydig glede OG malbarnet
har et bredt, apent smil. Bare to uttrykk finnes - de tidligere "trist"-sidene
(fotballstjernen 03/04, motet-i-hjertet 08) staar naa som noytral, som er
riktigere enn et smil paa en nedtur.

Valgene under er tatt ved a se pa hver enkelt malside (hodet klippet ut via
headmasken) 2026-08-20. Alt som ikke star oppfort her far "noytral".

Bruk:  python apply_face_expressions.py [--apply]
"""
import sys
import argparse, io, json, os, shutil, time

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

BOOKS = under("books")
DEFAULT = "noytral"

# slug -> {page_key: uttrykk}. Kun avvik fra default.
OVERRIDES = {
    "dragejakten": {
        "page06": "smil",   # ler ved bålet i hulen
        "page10": "smil",   # bredt smil, flyr over skyene
        "page11": "smil",   # ler mens han rir på dragen
        "page13": "smil",   # vinker farvel til dragene
    },
    "fotballstjernen": {
        "page03": "noytral",  # blikket ned foran målet, nedtur
        "page04": "noytral",  # sitter alene på gresset etter tapet
        "page11": "smil",   # armen i været, jubel på stadion
        "page14": "smil",   # ler med armene ut, triumfen
        "page15": "smil",   # sluttsiden, ler
    },
    "havfruen": {
        "page04": "smil",   # det lysende skjellet, magisk oppdagelse
        "page06": "smil",   # vinker og ler under vann
        "page11": "smil",   # svømmer fritt, størst smil
    },
    "enhjorning": {
        "page02": "smil",   # løper gjennom skogen
        "page12": "smil",   # rører manken i det magiske lyset
        "page13": "smil",   # klemmer enhjørningen
    },
    "dyreparken": {
        "page04": "smil",   # ivrig, åpent smil
        "page06": "smil",   # ler av dyrene
        "page07": "smil",   # bred latter
        "page12": "smil",   # ler med lekeelefanten
    },
    "det-forsvunne-dinosauregget": {
        "page04": "smil",   # åpent smil i jungelen
        "page07": "smil",   # ler mens han løper
        "page09": "smil",   # ler ved vannet
        "page13": "smil",   # løper med åpent smil
    },
    "den-skjulte-styrken": {
        "page06": "smil",   # ler i kappen over byen
    },
    "motet-i-hjertet": {
        "page00": "smil",   # forsiden: kroningen
        "page08": "noytral",  # hånden på brystet, fortvilet i skogen
        "page10": "smil",   # løper og ler
        "page12": "smil",   # holder reveungen
        "page13": "smil",   # blir kronet
    },
    "den-magiske-bursdagen-jente": {
        "page02": "smil",   # bred latter
        "page05": "smil",   # danser med åpent smil
        "page07": "smil",   # ler i gnistene
        "page11": "smil",   # snurrer med ballongene
    },
    # Gjennomgaende rolige/undrende boker - alt noytralt:
    #   dinosaurenes-dal, den-magiske-reisen-gutt, den-magiske-reisen-jente,
    #   den-skjulte-verdenen, den-tapte-superbyen, fotball-vm,
    #   kongerikets-hemmelighet
}

VALID = {"noytral", "smil"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    stamp = time.strftime("%Y%m%d-%H%M%S")

    for key, mapping in OVERRIDES.items():
        for expr in mapping.values():
            if expr not in VALID:
                raise SystemExit("ugyldig uttrykk %r i %s" % (expr, key))

    totals = {"noytral": 0, "smil": 0}
    for slug in sorted(os.listdir(BOOKS)):
        path = os.path.join(BOOKS, slug, "config.json")
        if not os.path.isfile(path):
            continue
        cfg = json.load(io.open(path, encoding="utf-8"))
        pages = cfg.get("pages")
        if not pages:
            continue
        over = OVERRIDES.get(slug, {})
        unknown = set(over) - {p["page_key"] for p in pages}
        if unknown:
            raise SystemExit("%s: ukjente page_keys %s" % (slug, sorted(unknown)))
        changed = 0
        for p in pages:
            expr = over.get(p["page_key"], DEFAULT)
            totals[expr] += 1
            if p.get("face_expression") != expr:
                p["face_expression"] = expr
                changed += 1
        marks = ",".join("%s=%s" % (k, v) for k, v in sorted(over.items()))
        print("%-32s %2d sider  %2d endret  %s" % (slug, len(pages), changed, marks))
        if args.apply and changed:
            shutil.copyfile(path, path + ".backup-before-faceexpr-" + stamp)
            with io.open(path, "w", encoding="utf-8") as fh:
                fh.write(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n")

    print("\nTOTALT  noytral=%(noytral)d  smil=%(smil)d" % totals)
    if not args.apply:
        print("(torrkjoring - kjor med --apply for a skrive)")


if __name__ == "__main__":
    main()
