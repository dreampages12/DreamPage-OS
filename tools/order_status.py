# -*- coding: utf-8 -*-
"""Hvor staar hver ordre - fra payload til Gelato-utkast.

    python tools/order_status.py                 # de 20 nyeste
    python tools/order_status.py --all           # alle
    python tools/order_status.py --open          # BARE de som ikke er ferdige
    python tools/order_status.py --gelato        # bekreft mot Gelato (tregere)
    python tools/order_status.py --order 1517    # én ordre, alle detaljer
    python tools/order_status.py --json          # for et dashbord

HVORFOR DEN FINNES
Ordre 1517 laa i tre doegn uten at noen visste det: n8n skrev "success",
jobb-DB-en hadde ingen rad, og mappa var tom. Ingen enkelt kilde kunne
svare paa "hvilke ordre er ikke ferdige".

Fire kilder maa krysses, og de er uenige med vilje:

  state/orders/*.json        payloaden slik WooCommerce sendte den. ALLE ordre,
                             ogsaa de fra n8n-tiden. Fasiten for "finnes ordren".
  state/jobs.sqlite          bare ordre som har gaatt gjennom flow. En ordre
                             UTEN rad her er ikke feilet - den er fra foer
                             flow, eller aldri publisert.
  books/<bok>/orders/<n>/pdf de trykkeklare filene. 33 sider samlet og 30
                             innersider er kravet; feil tall er en trykkfeil.
  state/gelato_drafts/*.json vaart notat om utkastet. IKKE autoritativt -
                             utkastet kan vaere slettet hos Gelato uten at
                             denne filen vet det. Derfor --gelato.

Konklusjonen staar i kolonnen TILSTAND, og den er bevisst konservativ: er en
kilde uenig med en annen, sier den UKLAR i stedet for OK. En tracker som
sier "ferdig" om noe som ikke er det, er verre enn ingen tracker.

Leser bare. Ingenting her endrer, sletter eller sender noe.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sqlite3
import sys

ROOT = os.environ.get("DP_ROOT", r"C:\DreamPage-OS")
ORDERS = os.path.join(ROOT, "state", "orders")
DRAFTS = os.path.join(ROOT, "state", "gelato_drafts")
JOBS_DB = os.path.join(ROOT, "state", "jobs.sqlite")
BOOKS = os.path.join(ROOT, "books")

# Gelato-produktet er 33 sider. Avvik er en trykkfeil, ikke en detalj.
TOTAL_PAGES = 33
INNER_MIN, INNER_MAX = 30, 31

DONE_STATES = ("UTKAST OK", "BESTILT", "SAMLET", "LEVERT")
BUSY_STATES = ("KJOERER", "I KOE")


def _load(path):
    try:
        with open(path, encoding="utf-8-sig") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None


def payloads():
    """{job_key: payload}. Filnavnet er noekkelen - ogsaa "1495-b1"."""
    out = {}
    for path in glob.glob(os.path.join(ORDERS, "*.json")):
        key = os.path.splitext(os.path.basename(path))[0]
        if key.startswith("_"):
            continue
        data = _load(path)
        if not data:
            continue
        out[key] = data.get("payload") or data
    return out


def jobs():
    if not os.path.isfile(JOBS_DB):
        return {}
    con = sqlite3.connect("file:%s?mode=ro" % JOBS_DB, uri=True)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT job_key,status,step,progress_done,progress_total,"
            "error,permanent,attempt,finished_at FROM jobs").fetchall()
    except sqlite3.Error:
        return {}
    finally:
        con.close()
    return dict((r["job_key"], dict(r)) for r in rows)


def pdfs(book_slug, key):
    """Sidetall fra de faktiske filene. pypdf er valgfri - uten den
    rapporterer vi at filene finnes, men ikke sidetallet."""
    folder = os.path.join(BOOKS, book_slug or "", "orders", key, "pdf")
    found = sorted(glob.glob(os.path.join(folder, "*.pdf")))
    out = {"files": len(found), "total": None, "inner": None, "mb": 0.0}
    if not found:
        return out
    out["mb"] = round(sum(os.path.getsize(f) for f in found) / 1e6, 1)
    try:
        from pypdf import PdfReader
    except ImportError:
        return out
    for path in found:
        name = os.path.basename(path).lower()
        try:
            pages = len(PdfReader(path).pages)
        except Exception:                            # noqa: BLE001
            continue
        if "gelato" in name:
            out["total"] = pages
        elif "inner" in name:
            out["inner"] = pages
    return out


def draft(key):
    """Vaart notat om utkastet.

    `status: merged` er IKKE en manglende utkast: ordren er samlet i en annen
    ordres Gelato-utkast (to boeker til samme kunde blir én forsendelse), og
    da staar `draft_id` med vilje tomt mens `merged_into_draft` peker paa det
    som faktisk finnes. Foerste versjon av denne trackeren meldte 1508 og
    1510 som "MANGLER UTKAST" av noeyaktig den grunnen.
    """
    data = _load(os.path.join(DRAFTS, "%s.json" % key)) or {}
    status = data.get("status")
    return {"id": data.get("draft_id"), "status": status,
            "at": data.get("updated_at") or data.get("merged_at"),
            "merged_into": data.get("merged_into_draft"),
            "merged_order": data.get("merged_into_order")}


def resolve_book(payload, fallback=""):
    """Bokmappa slik FLOW ser den, ikke slik payloaden staar.

    "den-magiske-reisen" + gender=gutt -> "den-magiske-reisen-gutt". Uten
    denne leter vi i en mappe som ikke finnes og melder at PDF-ene er borte.
    Samme funksjon som runneren bruker, saa de ikke kan komme i utakt.
    """
    try:
        sys.path.insert(0, os.path.join(ROOT, "flow"))
        sys.path.insert(0, os.path.join(ROOT, "flow", "worker"))
        import books as books_mod
        slug = books_mod.resolve_slug(payload)
        if slug:
            return slug
    except Exception:                                # noqa: BLE001
        pass
    return payload.get("book_slug") or fallback


def gelato_check(draft_id):
    """Spoer Gelato. Cloudflare svarer 403 "1010" paa urllib sin standard UA,
    saa User-Agent maa settes - det er ikke valgfritt."""
    import urllib.error
    import urllib.request
    sys.path.insert(0, os.path.join(ROOT, "flow"))
    import dp_secrets
    ua = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/120 Safari/537.36")
    req = urllib.request.Request(
        "https://order.gelatoapis.com/v4/orders/" + draft_id,
        headers={"X-API-KEY": dp_secrets.gelato_api_key(),
                 "Content-Type": "application/json", "User-Agent": ua})
    try:
        data = json.load(urllib.request.urlopen(req, timeout=40))
    except urllib.error.HTTPError as exc:
        return {"ok": False, "http": exc.code,
                "note": "borte hos Gelato" if exc.code == 404 else "feil"}
    except OSError as exc:
        return {"ok": None, "note": "naadde ikke Gelato: %s" % exc}
    items = data.get("items") or []
    # files[0].id er null naar Gelato ikke fikk hentet PDF-en - det traff
    # ordre 1300, der Drive-lenka over 100 MB ga en HTML-varselside.
    file_ids = [f.get("id") for it in items for f in (it.get("files") or [])]
    return {"ok": True, "type": data.get("orderType"),
            "financial": data.get("financialStatus"),
            "fulfilment": data.get("fulfillmentStatus"),
            "files_fetched": bool(file_ids) and all(file_ids),
            "hardcover": any("hardcover" in str(it.get("productUid"))
                             for it in items)}


def gelato_by_reference(key):
    """Finnes det en Gelato-ordre med DENNE ordrereferansen?

    Dette er det eneste autoritative svaret paa "ble boka levert", og grunnen
    er at de lokale sporene forsvinner: ordre 1205-1237 fra august har verken
    PDF, utkastfil eller rad i jobs.sqlite - de ble bygget i n8n-tiden og
    ryddet etterpaa. Foerste versjon av denne trackeren meldte alle elleve som
    "IKKE BYGGET". De er betalt og levert.

    Fravaer av treff her betyr IKKE at ordren er ubetalt - det betyr bare at
    Gelato ikke har den. En ubetalt handlekurv ser likt ut som en ordre som
    falt mellom to stoler, og payloadens `order_status` skiller dem ikke:
    baade 1528 og 1530 stod som "pending" mens de ble bygget.
    """
    import urllib.error
    import urllib.request
    sys.path.insert(0, os.path.join(ROOT, "flow"))
    import dp_secrets
    ua = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/120 Safari/537.36")
    body = json.dumps({"orderReferenceIds": [key], "limit": 10}).encode()
    req = urllib.request.Request(
        "https://order.gelatoapis.com/v4/orders:search", data=body,
        method="POST",
        headers={"X-API-KEY": dp_secrets.gelato_api_key(),
                 "Content-Type": "application/json", "User-Agent": ua})
    try:
        found = json.load(urllib.request.urlopen(req, timeout=45)).get("orders") or []
    except (urllib.error.HTTPError, OSError):
        return None
    for order in found:
        if order.get("orderType") == "order":
            return {"type": "order", "financial": order.get("financialStatus"),
                    "created": str(order.get("createdAt"))[:10]}
    if found:
        return {"type": found[0].get("orderType"),
                "financial": found[0].get("financialStatus"),
                "created": str(found[0].get("createdAt"))[:10]}
    return {"type": None}


def verdict(row):
    """(tilstand, hvorfor). Uenige kilder gir UKLAR, aldri OK."""
    job, pdf, dr = row["job"], row["pdf"], row["draft"]
    gel = row.get("gelato")
    byref = row.get("byref")

    # Levert er levert, uansett hva som ligger lokalt.
    if byref and byref.get("type") == "order":
        return "LEVERT", "Gelato-ordre %s %s" % (byref.get("financial"),
                                                 byref.get("created"))

    if job and job["status"] == "running":
        step = job.get("step") or "?"
        done = job.get("progress_done") or 0
        total = job.get("progress_total") or 0
        return "KJOERER", ("%s %d/%d" % (step, done, total)) if total else step
    if job and job["status"] == "pending":
        return "I KOE", "venter paa runneren"
    if job and job["status"] == "failed":
        why = (job.get("error") or "")[:60]
        return "FEILET", ("permanent: " if job.get("permanent") else "") + why
    if job and job["status"] == "cancelled":
        return "AVBRUTT", "avbrutt av operatoer"

    if gel is not None:
        if gel.get("ok") is False:
            return "UTKAST BORTE", gel.get("note") or "HTTP %s" % gel.get("http")
        if gel.get("ok") and not gel.get("files_fetched"):
            return "UKLAR", "utkast uten fil - sjekk Drive-lenka"
        if gel.get("ok") and gel.get("type") != "draft":
            return "BESTILT", "orderType=%s, %s" % (gel.get("type"),
                                                    gel.get("financial"))

    if dr["status"] == "merged":
        return "SAMLET", "i ordre %s sitt utkast" % (dr["merged_order"] or "?")

    if not dr["id"]:
        if pdf["files"]:
            return "MANGLER UTKAST", "%d PDF-er, men ingen utkast" % pdf["files"]
        if byref is not None and byref.get("type") is None:
            # Ingen spor noe sted. Ubetalt handlekurv, eller en ordre som
            # falt mellom to stoler - det kan ikke avgjoeres herfra.
            return "INGEN SPOR", "ikke bygget, og ikke hos Gelato"
        return "IKKE BYGGET", "ingen PDF, ingen utkast"

    if pdf["total"] is not None and pdf["total"] != TOTAL_PAGES:
        return "UKLAR", "samlet PDF har %s sider, ikke %d" % (pdf["total"],
                                                              TOTAL_PAGES)
    if pdf["inner"] is not None and not (INNER_MIN <= pdf["inner"] <= INNER_MAX):
        return "UKLAR", "%s innersider" % pdf["inner"]
    if not pdf["files"]:
        return "UKLAR", "utkast finnes, men PDF-ene er borte fra disk"

    return "UTKAST OK", "venter paa at et menneske bekrefter"


def _sort_key(key):
    head = key.split("-")[0]
    return (int(head) if head.isdigit() else 0, key)


def collect(only=None):
    pays, jobrows = payloads(), jobs()
    keys = sorted(set(pays) | set(jobrows), key=_sort_key)
    rows = []
    for key in keys:
        if only and key != only:
            continue
        pay = pays.get(key) or {}
        job = jobrows.get(key)
        slug = resolve_book(pay, (job or {}).get("book_slug") or "")
        rows.append({
            "key": key,
            "book": slug,
            "child": pay.get("child_name") or (job or {}).get("child_name") or "",
            "cover": pay.get("cover_type") or "",
            "lang": pay.get("language") or "",
            "continue_code": (pay.get("continue_code") or "").strip(),
            "job": job,
            "pdf": pdfs(slug, key),
            "draft": draft(key),
        })
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true",
                    help="alle ordre, ikke bare de nyeste")
    ap.add_argument("--open", action="store_true",
                    help="bare de som ikke er ferdige")
    ap.add_argument("--gelato", action="store_true",
                    help="bekreft hvert utkast mot Gelato-API-et")
    ap.add_argument("--order", help="én ordre, med detaljer")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--limit", type=int, default=20)
    args = ap.parse_args()

    rows = collect(args.order)
    if not rows:
        print("fant ingen ordre" + (" med noekkel %s" % args.order
                                    if args.order else ""))
        return 1

    if not (args.all or args.open or args.order):
        rows = rows[-args.limit:]

    # Gelato spoerres bare for de som HAR et utkast - ellers er det bortkastede
    # kall, og API-et har rate limits.
    if args.gelato or args.order:
        for row in rows:
            row["gelato"] = (gelato_check(row["draft"]["id"])
                             if row["draft"]["id"] else None)
            # Referansesoek naar det lokale sporet ikke holder: uten utkast,
            # eller naar utkastet er borte hos Gelato. Da er spoersmaalet
            # "ble den levert?", og bare Gelato kan svare.
            need_ref = (not row["draft"]["id"]
                        or (row["gelato"] or {}).get("ok") is False)
            row["byref"] = (gelato_by_reference(row["key"])
                            if need_ref and row["draft"]["status"] != "merged"
                            else None)

    for row in rows:
        row["state"], row["why"] = verdict(row)

    if args.open:
        rows = [r for r in rows if r["state"] not in DONE_STATES]

    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2, default=str))
        return 0

    if args.order:
        row = rows[0]
        print("ordre %s   %s   (%s)" % (row["key"], row["state"], row["why"]))
        print("  bok        %s" % row["book"])
        print("  barn       %s" % row["child"])
        print("  omslag     %s   sprak %s" % (row["cover"] or "(IKKE SATT)",
                                              row["lang"]))
        print("  fortsett   %s" % (row["continue_code"] or "(ingen)"))
        job = row["job"]
        if job:
            print("  jobb       %s  steg=%s  forsok=%s  ferdig=%s" % (
                job["status"], job.get("step") or "-", job.get("attempt"),
                job.get("finished_at") or "-"))
            if job.get("error"):
                print("  feil       %s" % job["error"][:200])
        else:
            print("  jobb       ingen rad i jobs.sqlite (fra foer flow, "
                  "eller aldri publisert)")
        pdf = row["pdf"]
        print("  pdf        %d filer, %s MB, samlet=%s innersider=%s" % (
            pdf["files"], pdf["mb"], pdf["total"], pdf["inner"]))
        dr = row["draft"]
        print("  utkast     %s  %s %s" % (dr["id"] or "(ingen)",
                                          dr["status"] or "", dr["at"] or ""))
        if row.get("gelato"):
            print("  gelato     %s" % row["gelato"])
        return 0

    print("%-9s %-26s %-12s %-15s %s" % ("ordre", "bok", "barn",
                                         "tilstand", "hvorfor"))
    print("-" * 104)
    for row in rows:
        print("%-9s %-26s %-12s %-15s %s" % (
            row["key"], row["book"][:26], row["child"][:12],
            row["state"], row["why"][:38]))

    counts = {}
    for row in rows:
        counts[row["state"]] = counts.get(row["state"], 0) + 1
    print()
    print("  " + "   ".join("%s: %d" % (k, v) for k, v in sorted(counts.items())))

    trouble = [r for r in rows if r["state"] not in DONE_STATES
               and r["state"] not in BUSY_STATES]
    if trouble:
        print()
        print("  KREVER HANDLING:")
        for row in trouble:
            print("    %-9s %-15s %s" % (row["key"], row["state"],
                                          row["why"][:60]))
    if not (args.gelato or args.order):
        print()
        print("  (utkastene er lest fra disk. --gelato bekrefter mot Gelato.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
