# -*- coding: utf-8 -*-
"""Lag en komplett testbok fra et bilde og et navn - uten n8n, Drive og Gelato.

Til aa prove ut hele flyten (faceswap -> sider -> tekst -> ferdig PDF) uten aa
sende en jobb gjennom RabbitMQ og uten aa rore en betalt ordre.

Trikset er at vi ikke trenger noen ny kodesti: dp_order.resolve() leser
payloaden fra state/orders/<id>.json, saa vi skriver rett og slett en
SYNTETISK payload dit. Da fungerer regen_page, prepare_order, tekst-scriptet
og build_gelato_pdf noeyaktig som for en ekte ordre - det er nettopp det vi
vil teste.

Isolasjon:
  * ingen RabbitMQ, ingen n8n-execution  - payloaden skrives lokalt
  * ingen Drive-opplasting                - dp_bot publiserer aldri en testordre
  * ingen Gelato-ORDRE eller -utkast      - vi kaller aldri /v4/orders
  * continue_code er tomt                 - QR-siden og opplastingen til
                                            landingssiden hoppes over

Den ENE nettverkskallet som staar igjen er Gelatos product-API, som gir
maalene paa coveret (GET cover-dimensions). Uten det blir coveret feil
stoerrelse, og kallet oppretter ingenting - det leser bare produktmaal.

  python dp_testbook.py --book fotballstjernen --name Test --face C:/bilde.jpg
  python dp_testbook.py --list
  python dp_testbook.py --delete test-0818-2035
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass

import dp_order                                                    # noqa: E402
import regen_page                                                  # noqa: E402
import reprint_order                                               # noqa: E402

# Stien til DreamPage-roten utledes, den hardkodes ikke: koden kjoerer paa
# Windows i dag og paa Linux paa nye maskiner. Se flow/paths.py.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import under  # noqa: E402

BOOKS_DIR = dp_order.BOOKS_DIR
COMFY_INPUT = under("input")
TEST_MARKER = "is_test"


def is_test(order_id: str) -> bool:
    """En testordre skal aldri kunne lastes opp eller sendes til trykk."""
    record = dp_order.read_cache(str(order_id).strip()) or {}
    return bool((record.get("payload") or {}).get(TEST_MARKER))


def testable_books() -> list[tuple[str, str]]:
    """(slug, visningsnavn) for boeker som faktisk kan bygges."""
    out = []
    for slug in sorted(os.listdir(BOOKS_DIR)):
        path = os.path.join(BOOKS_DIR, slug, "config.json")
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8-sig") as fh:
                config = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        # Uten prepareScript og tekst-script finnes det ingen bok aa bygge -
        # tre av mappene under books/ er paabegynte og har ingen av delene.
        if not config.get("prepareScript"):
            continue
        if not (config.get("textScripts") or config.get("textScript")):
            continue
        if not config.get("pages"):
            continue
        out.append((slug, config.get("displayName") or slug))
    return out


def new_order_id() -> str:
    return "test-" + dt.datetime.now().strftime("%m%d-%H%M%S")


def create(slug: str, child_name: str, face_source: str,
           cover_type: str = "hardcover", language: str = "nb",
           order_id: str | None = None) -> dict:
    """Legg opp mapper, ansiktsbilde og syntetisk payload. Returnerer info."""
    config_path = os.path.join(BOOKS_DIR, slug, "config.json")
    if not os.path.isfile(config_path):
        raise SystemExit("fant ingen config.json for bok " + slug)
    if not os.path.isfile(face_source):
        raise SystemExit("fant ikke bildet " + face_source)

    order_id = order_id or new_order_id()
    order_path = os.path.join(BOOKS_DIR, slug, "orders", order_id)
    os.makedirs(os.path.join(order_path, "input"), exist_ok=True)
    os.makedirs(os.path.join(order_path, "pdf"), exist_ok=True)

    # regen_page leter etter C:/DreamPage-OS/input/<order_id>.jpg, samme som for
    # en ekte ordre. JPEG fordi workflowen alltid har faatt JPEG derfra.
    face_dest = os.path.join(COMFY_INPUT, order_id + ".jpg")
    from PIL import Image
    with Image.open(face_source) as img:
        img.convert("RGB").save(face_dest, "JPEG", quality=95)

    payload = {
        "order_id": order_id,
        "child_name": child_name,
        "book_slug": slug,
        "cover_type": cover_type,
        "language": language,
        "script_language": language,
        # Tomt med vilje: da hopper rebuild_pdfs over hele QR-siste-siden,
        # inkludert opplastingen til landingssiden. En testbok skal ikke
        # lage en ekte fortsett-kode.
        "continue_code": "",
        "continue_url": "",
        "continue_coupon": "",
        "continue_callback": "",
        "next_book_slug": "",
        "next_book_title": "",
        "customer": {"email": "test@dreampage.store"},
        "shipping": {"first_name": "Test", "last_name": "Testesen",
                     "address_1": "Testveien 1", "postcode": "0000",
                     "city": "Testby", "country": "NO"},
        TEST_MARKER: True,
        "created_at": dt.datetime.now().isoformat(timespec="seconds"),
    }
    dp_order.write_cache(order_id, {"order_id": order_id,
                                    "execution_id": None,
                                    "payload": payload,
                                    "overrides": {}})
    return dp_order.resolve(order_id)


def render_all(info: dict, on_page=None, should_cancel=None) -> list[str]:
    """En variant per side, rett inn i comfy/ - ingen valg underveis."""
    pages = [page["page_key"] for page in info["config"].get("pages", [])]
    done = []
    for index, page_key in enumerate(pages):
        if should_cancel and should_cancel():
            raise regen_page.Cancelled("avbrutt av bruker")
        if on_page:
            on_page(index, len(pages), page_key)
        paths = regen_page.render_variants(info, page_key, 1,
                                           should_cancel=should_cancel)
        reprint_order.commit_variant(info, page_key, paths[0])
        done.append(page_key)
    return done


def build(info: dict) -> dict:
    """Prepare -> tekst-script -> gelato-PDF. Ingen Drive, ingen utkast."""
    return reprint_order.rebuild_pdfs(info)


def list_tests() -> list[dict]:
    out = []
    for slug, _name in testable_books():
        orders = os.path.join(BOOKS_DIR, slug, "orders")
        if not os.path.isdir(orders):
            continue
        for order_id in sorted(os.listdir(orders)):
            if not order_id.startswith("test-"):
                continue
            path = os.path.join(orders, order_id)
            if not os.path.isdir(path):
                continue
            pdfs = [n for n in os.listdir(os.path.join(path, "pdf"))
                    if n.lower().endswith(".pdf")] if os.path.isdir(
                        os.path.join(path, "pdf")) else []
            out.append({"order_id": order_id, "book_slug": slug,
                        "path": path, "pdfs": pdfs,
                        "modified": os.path.getmtime(path)})
    out.sort(key=lambda item: item["modified"], reverse=True)
    return out


def delete(order_id: str) -> list[str]:
    """Rydd bort en testbok helt. Nekter aa roere en ekte ordre."""
    order_id = str(order_id).strip()
    if not order_id.startswith("test-"):
        raise SystemExit("dette er ikke en testordre: " + order_id)
    removed = []
    for slug, _name in testable_books():
        path = os.path.join(BOOKS_DIR, slug, "orders", order_id)
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
            removed.append(path)
        try:
            with open(os.path.join(BOOKS_DIR, slug, "config.json"),
                      encoding="utf-8-sig") as fh:
                prefix = json.load(fh).get("comfyOutputPrefix", slug + "/orders")
        except (OSError, json.JSONDecodeError):
            continue
        out = os.path.join(under("output"), prefix.replace("/", os.sep), order_id)
        if os.path.isdir(out):
            shutil.rmtree(out, ignore_errors=True)
            removed.append(out)
    for path in (dp_order.cache_path(order_id),
                 os.path.join(COMFY_INPUT, order_id + ".jpg")):
        if os.path.isfile(path):
            os.unlink(path)
            removed.append(path)
    return removed


# --------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--book")
    ap.add_argument("--name")
    ap.add_argument("--face")
    ap.add_argument("--cover-type", default="hardcover")
    ap.add_argument("--lang", default="nb")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--books", action="store_true")
    ap.add_argument("--delete")
    ap.add_argument("--no-build", action="store_true",
                    help="bare render sidene, ikke bygg PDF")
    args = ap.parse_args()

    if args.books:
        for slug, name in testable_books():
            print("  " + slug.ljust(30) + name)
        return 0
    if args.list:
        for item in list_tests():
            print("  " + item["order_id"].ljust(20) + item["book_slug"].ljust(28)
                  + str(len(item["pdfs"])) + " pdf")
        return 0
    if args.delete:
        for path in delete(args.delete):
            print("  slettet " + path)
        return 0

    if not (args.book and args.name and args.face):
        ap.error("--book, --name og --face maa oppgis")

    info = create(args.book, args.name, args.face,
                  cover_type=args.cover_type, language=args.lang)
    print("testordre " + info["order_id"] + "  bok " + info["book_slug"]
          + "  barn " + info["child_name"])

    def on_page(index, total, page_key):
        print("  [" + str(index + 1) + "/" + str(total) + "] " + page_key, flush=True)

    render_all(info, on_page=on_page)
    if args.no_build:
        print("sidene er rendret - PDF hoppet over (--no-build)")
        return 0
    files = build(info)
    print("\nFERDIG")
    for key in ("cover", "inner", "gelato"):
        print("  " + os.path.basename(files[key]).ljust(34)
              + format(os.path.getsize(files[key]) / 1e6, "7.2f") + " MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
