# -*- coding: utf-8 -*-
"""Rydd bort midlertidige sidevarianter som operatoerboten har laget.

Problemet: hver gang du trykker "lag 3 nye varianter" i Telegram, rendrer
`regen_page.render_variants` tre 4096x4096-PNG-er inn i
`output/<bok>/orders/<job_key>/variants/`. Du velger EN. De to andre blir
liggende for alltid. Paa denne maskinen var det 485 filer og 19 GiB.

Hvorfor det er trygt aa slette dem NAAR ordren er ferdig: den varianten du
godkjente blir KOPIERT ut av variants/ og inn i ordrens `input/` av
`reprint_order.commit_variant_to_input()` - det er den kopien som trykkes.
Filene i variants/ leses aldri av bokbyggingen. De ligger bevisst i en egen
mappe nettopp fordi `prepare_order` plukker foerste fil som matcher
sidenoekkelen, og loese varianter i comfy/ ville blitt trykt ved et uhell.

=== HVA SOM ALDRI ROERES ===

Kun `output/*/orders/*/variants/`, og bare filer som matcher det moensteret
regen_page selv skriver: `page<N>-s<seed>_<N>_.png`. Alt annet i mappa blir
liggende. Verktoeyet ser ikke paa - og kan ikke slette fra:

    books/            comfy/            input/            models/
    state/orders/     nodes/            local_data/       DreamPage-image/

=== FIRE SPERRER, ALLE MAA AAPNE ===

1. GELATO BETALT. Ordren maa ha minst en Gelato-ordre med orderType "order"
   OG financialStatus "paid". Et UTKAST er ikke nok: et utkast betyr at boka
   ikke er bestilt enda, og da kan du fortsatt trenge aa bytte en side.
   Dette er den viktigste sperren, og den som ble bedt om eksplisitt.

2. INGEN AAPEN OEKT. Finnes state/reprint/<ordre>.json,
   state/next_cover/<ordre>.json eller en inflight-markoer, sitter noen midt
   i et sidebytte. Da peker oekta paa filene vi er i ferd med aa slette.

3. IKKE I KOEEN. Er ordren pending eller running i jobb-DB-en, bygges den naa.

4. ALDER. Ingenting nyere enn --min-age-days (7 som standard), maalt paa den
   NYESTE fila i mappa. Ett friskt bytte beskytter hele settet - en operatoer
   som holder paa har ikke godt av at halve utvalget forsvinner.

   Sier Gelato at boka er sendt, levert eller underveis, er arbeidet ikke
   "sannsynligvis" ferdig - det ER ferdig, og da holder --min-age-days-shipped
   (1 som standard). Aldersgrensa er en stedfortreder for "kanskje noen holder
   paa"; naar vi har det direkte svaret, trenger vi ikke gjetningen.

5. GODKJENT KOPI FINNES. For hver side som har varianter maa den godkjente
   kopien ligge i ordrens input/. Det er dette som gjoer slettingen trygg, og
   derfor sjekkes det i stedet for aa antas. Oppslaget er det samme boten
   bruker (reprint_order.input_file_for).

Toerrkjoering er standard. `--apply` kreves for aa slette.

    python tools/cleanup_variants.py                    # vis hva som ville skjedd
    python tools/cleanup_variants.py --apply
    python tools/cleanup_variants.py --order 1482 --apply
    python tools/cleanup_variants.py --min-age-days 30 --apply
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "flow"))
# Ogsaa worker/, ellers finner ikke `import jobs` noe - og da rapporterte
# in_queue() "kunne ikke lese jobbkoeen" og holdt ALT tilbake.
sys.path.insert(0, str(ROOT / "flow" / "worker"))

from paths import OUTPUT, STATE  # noqa: E402

# Nøyaktig det regen_page.py skriver:
#     prompt[...]["filename_prefix"] = f"{out_rel}/{page_key}-s{seed}"
# ComfyUI legger paa "_00001_" og ".png". Alt annet i mappa er ikke vaart.
VARIANT_RE = re.compile(r"^page\d+-s\d+_\d+_\.png$", re.IGNORECASE)

# Forhaandsvisningene boten sender til Telegram. Rent avledet: de lages av en
# side som fortsatt finnes, sendes en gang og leses aldri igjen.
PREVIEW_DIR = ROOT / "tmp" / "dp_bot_previews"
PREVIEW_RE = re.compile(r"^(?P<order>[0-9]+(?:-b[0-9]+)?)-.*\.(?:jpg|jpeg|png)$",
                        re.IGNORECASE)


# Statuser der boka fysisk har forlatt trykkeriet. Da er arbeidet ikke
# "sannsynligvis" ferdig - det ER ferdig, og ingen kommer til aa bytte en side
# i den boka. Aldersgrensa er en STEDFORTREDER for "kanskje noen holder paa";
# naar Gelato sier levert, har vi det direkte svaret i stedet for gjetningen.
SHIPPED = {"shipped", "delivered", "in_transit"}


def human(n: float) -> str:
    for unit in ("B", "KiB", "MiB", "GiB"):
        if abs(n) < 1024 or unit == "GiB":
            return f"{n:,.1f} {unit}".replace(",", " ")
        n /= 1024
    return f"{n:.1f} GiB"


# ---------------------------------------------------------------------------
# Sperre 1: er ordren betalt hos Gelato?
# ---------------------------------------------------------------------------
def gelato_paid(order_ids: list[str]) -> dict:
    """{order_id: (betalt, forklaring, fulfillment_status)}.

    Ett kall per bunt paa 40. Et utkast, en kansellert ordre eller ingen
    Gelato-ordre i det hele tatt gir False - da er boka ikke bestilt, og
    variantene kan fortsatt vaere i bruk.
    """
    from finish_order import gelato

    out = {oid: (False, "ingen Gelato-ordre funnet", "") for oid in order_ids}
    # WooCommerce-ordrenummeret er referansen. job_key "1495-b1" er bok 2 i
    # ordre 1495, og Gelato kjenner bare "1495".
    refs = sorted({oid.split("-b")[0] for oid in order_ids})
    found: dict[str, list[dict]] = {}
    # limit har tak paa 100 hos Gelato - 200 gir HTTP 400. Og en ordre kan ha
    # FLERE Gelato-ordre (1482 har en betalt og en kansellert), saa 25
    # referanser per kall holder svaret godt under taket. Treffer vi likevel
    # taket, er svaret kanskje avkuttet, og da vet vi ikke nok til aa slette.
    BATCH, LIMIT = 25, 100
    for start in range(0, len(refs), BATCH):
        chunk = refs[start:start + BATCH]
        try:
            code, body = gelato(
                "POST", "https://order.gelatoapis.com/v4/orders:search",
                {"orderReferenceIds": chunk, "limit": LIMIT})
        except Exception as exc:                        # noqa: BLE001
            for oid in order_ids:
                out[oid] = (False, f"Gelato svarte ikke ({type(exc).__name__})", "")
            return out
        if code != 200:
            for oid in order_ids:
                out[oid] = (False, f"Gelato svarte HTTP {code}", "")
            return out
        orders = body.get("orders") or []
        if len(orders) >= LIMIT:
            for oid in order_ids:
                out[oid] = (False, "Gelato-svaret kan vaere avkuttet "
                                   f"({len(orders)} >= limit {LIMIT})", "")
            return out
        for order in orders:
            found.setdefault(str(order.get("orderReferenceId")), []).append(order)

    for oid in order_ids:
        ref = oid.split("-b")[0]
        orders = found.get(ref) or []
        if not orders:
            continue
        paid = [o for o in orders
                if str(o.get("orderType")) == "order"
                and str(o.get("financialStatus")) == "paid"
                and str(o.get("fulfillmentStatus")) != "canceled"]
        if paid:
            o = paid[0]
            out[oid] = (True, f"betalt, {o.get('fulfillmentStatus')}",
                        str(o.get("fulfillmentStatus") or ""))
        else:
            kinds = sorted({f"{o.get('orderType')}/{o.get('financialStatus')}"
                            for o in orders})
            out[oid] = (False, "ikke betalt: " + ", ".join(kinds), "")
    return out


# ---------------------------------------------------------------------------
# Sperre 2 og 3
# ---------------------------------------------------------------------------
def open_session(order_id: str) -> str | None:
    """Sitter noen midt i et sidebytte paa denne ordren?"""
    for path, what in (
        (STATE / "reprint" / f"{order_id}.json", "aapen sidebytte-oekt"),
        (STATE / "next_cover" / f"{order_id}.json", "aapen fortsett-side-oekt"),
    ):
        if path.is_file():
            return what
    inflight = STATE / "reprint" / "inflight"
    if inflight.is_dir():
        for entry in inflight.iterdir():
            if entry.name.startswith(order_id):
                return "et bygg er markert som paagaaende (inflight)"
    return None


def has_authoritative_copy(order_id: str, files: list) -> str | None:
    """Finnes den godkjente kopien i ordrens input/ for HVER side?

    Dette er hele sikkerhetsargumentet, gjort om til en sjekk i stedet for en
    antakelse: `commit_variant_to_input()` kopierer den varianten du godkjente
    ut av variants/ og inn i input/, og det er DEN som trykkes. Mangler kopien
    for en side, er varianten kanskje den eneste filen som finnes - og da
    slettes ingenting for den ordren.

    Bruker samme oppslag som boten (`reprint_order.input_file_for`), saa den
    kan ikke svare noe annet enn boten ville gjort.
    """
    try:
        import dp_order
        import reprint_order
        info = dp_order.resolve(order_id)
    except BaseException as exc:                        # noqa: BLE001
        # dp_order.resolve kaster SystemExit for ukjente ordre.
        return f"fant ikke ordren ({type(exc).__name__})"
    keys = sorted({m.group(1) for m in
                   (re.match(r"(page\d+)-s", f.name) for f in files) if m})
    if not keys:
        return "kunne ikke lese sidenoekler fra filnavnene"
    missing = [k for k in keys if not reprint_order.input_file_for(info, k)]
    if missing:
        return (f"{len(missing)} av {len(keys)} sider mangler godkjent kopi i "
                f"input/ ({', '.join(missing[:4])})")
    return None


def in_queue() -> set[str]:
    """job_key-ene som er pending eller running i jobb-DB-en."""
    try:
        import jobs as jobs_mod
        store = jobs_mod.store()
        keys = set()
        row = store.running()
        if row:
            keys.add(str(row["job_key"]))
        for row in store.pending():
            keys.add(str(row["job_key"]))
        return keys
    except Exception:                                   # noqa: BLE001
        # Kan vi ikke lese koeen, later vi som ALT staar i den. En opprydding
        # som ikke vet, skal ikke slette.
        return {"*"}


# ---------------------------------------------------------------------------
# Innsamling
# ---------------------------------------------------------------------------
def collect_variants(only: str | None) -> dict:
    groups: dict[str, dict] = {}
    for vdir in sorted(OUTPUT.glob("*/orders/*/variants")):
        if not vdir.is_dir():
            continue
        order_id = vdir.parent.name
        if only and order_id != only:
            continue
        files, other = [], 0
        for entry in vdir.iterdir():
            if not entry.is_file():
                continue
            if VARIANT_RE.match(entry.name):
                files.append(entry)
            else:
                other += 1
        if not files:
            continue
        groups[order_id] = {
            "kind": "variants", "dir": vdir, "files": files,
            "bytes": sum(f.stat().st_size for f in files),
            "newest": max(f.stat().st_mtime for f in files),
            "left_alone": other,
        }
    return groups


def collect_previews(only: str | None) -> dict:
    groups: dict[str, dict] = {}
    if not PREVIEW_DIR.is_dir():
        return groups
    for entry in PREVIEW_DIR.iterdir():
        if not entry.is_file():
            continue
        m = PREVIEW_RE.match(entry.name)
        if not m:
            continue
        order_id = m.group("order")
        if only and order_id != only:
            continue
        g = groups.setdefault(order_id, {"kind": "previews", "dir": PREVIEW_DIR,
                                         "files": [], "bytes": 0, "newest": 0.0,
                                         "left_alone": 0})
        st = entry.stat()
        g["files"].append(entry)
        g["bytes"] += st.st_size
        g["newest"] = max(g["newest"], st.st_mtime)
    return groups


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true",
                    help="slett. Uten denne vises bare hva som ville skjedd.")
    ap.add_argument("--order", help="bare denne ordren (job_key)")
    ap.add_argument("--min-age-days", type=float, default=7.0,
                    help="alder som kreves naar boka IKKE er sendt enda "
                         "(standard 7)")
    ap.add_argument("--min-age-days-shipped", type=float, default=1.0,
                    help="alder som kreves naar Gelato sier sendt/levert "
                         "(standard 1)")
    ap.add_argument("--skip-previews", action="store_true",
                    help="ikke rydd tmp/dp_bot_previews")
    ap.add_argument("--skip-gelato", action="store_true",
                    help=argparse.SUPPRESS)   # bare for testing; sperre 1 av
    args = ap.parse_args()

    groups = collect_variants(args.order)
    if not args.skip_previews:
        for order_id, g in collect_previews(args.order).items():
            groups[f"{order_id}::previews"] = g

    if not groups:
        print("Ingen midlertidige filer funnet.")
        return 0

    order_ids = sorted({key.split("::")[0] for key in groups})
    print(f"{len(groups)} gruppe(r) fordelt paa {len(order_ids)} ordre\n")

    paid = ({oid: (True, "-- sperre 1 av --", "") for oid in order_ids}
            if args.skip_gelato else gelato_paid(order_ids))
    queued = in_queue()
    now = time.time()

    to_delete, held = [], []
    for key in sorted(groups):
        g = groups[key]
        order_id = key.split("::")[0]
        reasons = []

        ok, why, fulfillment = paid.get(order_id, (False, "ukjent", ""))
        shipped = fulfillment in SHIPPED
        limit_days = args.min_age_days_shipped if shipped else args.min_age_days
        cutoff = limit_days * 86400
        if not ok:
            reasons.append(f"Gelato: {why}")
        session = open_session(order_id)
        if session:
            reasons.append(session)
        if "*" in queued or order_id in queued:
            reasons.append("staar i jobbkoeen" if order_id in queued
                           else "kunne ikke lese jobbkoeen")
        # Sperre 5 sjekkes bare naar de andre aapner - den slaar opp ordren,
        # og det er det dyreste vi gjoer.
        if not reasons and g["kind"] == "variants":
            problem = has_authoritative_copy(order_id, g["files"])
            if problem:
                reasons.append(problem)

        age = now - g["newest"]
        if age < cutoff:
            reasons.append(f"nyeste fil er {age / 86400:.1f} dogn gammel "
                           f"(grense {limit_days:g}"
                           + (", sendt" if shipped else "") + ")")

        row = {"key": key, "order": order_id, "kind": g["kind"],
               "files": g["files"], "bytes": g["bytes"],
               "age_days": age / 86400, "why": why,
               "left_alone": g["left_alone"]}
        (held if reasons else to_delete).append(
            {**row, "reasons": reasons})

    if to_delete:
        total = sum(r["bytes"] for r in to_delete)
        n = sum(len(r["files"]) for r in to_delete)
        print(f"KAN RYDDES: {n} filer, {human(total)}")
        for r in sorted(to_delete, key=lambda r: -r["bytes"]):
            print(f"  {r['order']:12} {r['kind']:9} {len(r['files']):4} filer "
                  f"{human(r['bytes']):>11}  {r['age_days']:5.0f} dogn  ({r['why']})")
        print()

    if held:
        total = sum(r["bytes"] for r in held)
        print(f"HOLDT TILBAKE: {sum(len(r['files']) for r in held)} filer, "
              f"{human(total)}")
        for r in sorted(held, key=lambda r: -r["bytes"]):
            print(f"  {r['order']:12} {r['kind']:9} {len(r['files']):4} filer "
                  f"{human(r['bytes']):>11}  -> {'; '.join(r['reasons'])}")
        print()

    extra = sum(r["left_alone"] for r in to_delete + held)
    if extra:
        print(f"{extra} fil(er) i variants/ matcher ikke moensteret og roeres "
              f"ikke i det hele tatt.\n")

    if not to_delete:
        print("Ingenting aa gjoere.")
        return 0
    if not args.apply:
        print("TOERRKJOERING - ingenting slettet. Kjoer med --apply.")
        return 0

    freed = failed = 0
    for r in to_delete:
        for f in r["files"]:
            try:
                size = f.stat().st_size
                f.unlink()
                freed += size
            except OSError as exc:
                failed += 1
                print(f"  KUNNE IKKE slette {f.name}: {exc}")
        # Tom variants/-mappe ryddes bort; previews-mappa beholdes.
        if r["kind"] == "variants":
            try:
                d = r["files"][0].parent
                if not any(d.iterdir()):
                    d.rmdir()
            except OSError:
                pass
    print(f"\nFrigjort {human(freed)}" + (f", {failed} feilet" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
