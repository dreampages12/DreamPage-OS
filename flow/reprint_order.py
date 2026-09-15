# -*- coding: utf-8 -*-
"""Bygg en ordre på nytt etter at sider er byttet - PDF, Drive og Gelato-utkast.

Speiler halen av workeren (Prepare Pages -> ... -> Create Gelato Draft), men:

* Gelato-utkastet lages ALDRI automatisk. Det krever --gelato, som boten bare
  sender når du har trykket på godkjenn-knappen.
* Drive-duplikater ryddes bort (drive_upload --replace).
* QR-siste-siden bygges på nytt i riktig rekkefølge. Gjør man ikke det,
  tommer tekst-scriptet pdf/ og boka trykkes uten QR - continue_code hentes
  fra den opprinnelige payloaden og skal aldri gjettes.
* WP-progress røres ikke. En reprint skal ikke flytte kundens ordrestatus.

  python reprint_order.py --order 1235 --dry-run
  python reprint_order.py --order 1235 --apply
  python reprint_order.py --order 1235 --apply --gelato
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import shutil
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

import dp_order

# Windows-konsollen her er cp1252 og kan ikke skrive æøå. Uten dette krasjer
# et hvilket som helst print med norsk tekst i en UnicodeEncodeError.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
from finish_order import GELATO_KEY, PRODUCT_UID, gelato  # noqa: E402

LAST_PAGE = os.path.join(SCRIPT_DIR, "build_last_page.py")
GELATO_PDF = os.path.join(SCRIPT_DIR, "build_gelato_pdf.py")
DRIVE_UPLOAD = os.path.join(SCRIPT_DIR, "drive_upload.py")
MOCKUP_TEMPLATE = "psd_1c8e5a0dfdc188d1_layer-1"
CONTINUE_SECRET = "<CONTINUE_CALLBACK_SECRET>"
DRAFT_STATE_DIR = r"C:\ComfyUI\state\gelato_drafts"
PREPARED_DIR = r"C:\ComfyUI\state\reprint\prepared"

# Disse lages på nytt av hvert bygg og er aldri "en manuell endring":
# blank-back skrives av build_last_page ETTER prepare, page99 er QR-siden,
# og .bak-filer er våre egne kopier.
GENERATED_INPUT = {"blank-back.png", "dreampage-first.png"}


def say(text: str) -> None:
    """Konsollen her er cp1252; underscriptene skriver bokstaver den ikke har."""
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    sys.stdout.write(text.encode(encoding, "replace").decode(encoding, "replace") + "\n")
    sys.stdout.flush()


def run(args: list[str], label: str, check: bool = True) -> subprocess.CompletedProcess:
    say(f"\n--- {label}\n    {' '.join(args)}")
    proc = subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                          errors="replace")
    tail = (proc.stdout or "").strip().splitlines()
    for line in tail[-12:]:
        say("    " + line)
    if proc.returncode and check:
        raise SystemExit(f"{label} feilet (exit {proc.returncode}):\n{proc.stderr[-3000:]}")
    if proc.returncode:
        print(f"    (exit {proc.returncode} - fortsetter, dette steget er valgfritt)", flush=True)
    return proc


# --------------------------------------------------------------------------
# Manuelle endringer i input/
#
# prepare_order kopierer HELE base/ over input/ og legger deretter comfy-
# sidene oppå. Alt du har redigert for hånd - retusjert, upscalet, byttet ut -
# blir borte uten et ord. Derfor må vi vite om input/ er rørt FØR vi bygger.
# --------------------------------------------------------------------------
def manifest_path(order_id: str) -> str:
    return os.path.join(PREPARED_DIR, f"{order_id}.json")


def _fingerprint(path: str) -> list:
    st = os.stat(path)
    return [st.st_size, st.st_mtime_ns]


def _input_files(info: dict) -> list[tuple[str, str]]:
    folder = info["input_dir"]
    if not os.path.isdir(folder):
        return []
    out = []
    for name in sorted(os.listdir(folder)):
        if name in GENERATED_INPUT or name.startswith("page99"):
            continue
        if ".bak" in name.lower():
            continue
        path = os.path.join(folder, name)
        if os.path.isfile(path):
            out.append((name, path))
    return out


def write_prepared_manifest(info: dict) -> None:
    """Fotografer input/ rett etter en prepare, så vi senere ser hva som er rørt."""
    os.makedirs(PREPARED_DIR, exist_ok=True)
    data = {name: _fingerprint(path) for name, path in _input_files(info)}
    path = manifest_path(info["order_id"])
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"order_id": info["order_id"], "book_slug": info["book_slug"],
                   "written_at": dt.datetime.now().isoformat(timespec="seconds"),
                   "files": data}, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def read_prepared_manifest(info: dict) -> dict | None:
    try:
        with open(manifest_path(info["order_id"]), encoding="utf-8") as fh:
            return json.load(fh).get("files") or {}
    except (OSError, json.JSONDecodeError):
        return None


def manual_edits(info: dict) -> list[str]:
    """Filnavn i input/ som IKKE stammer fra siste prepare_order."""
    files = _input_files(info)
    manifest = read_prepared_manifest(info)
    if manifest is not None:
        return [name for name, path in files
                if manifest.get(name) != _fingerprint(path)]

    # Ingen manifest: ordren er eldre enn denne mekanismen. prepare_order
    # bruker shutil.copy2, som beholder mtime - en fil som fortsatt ligger
    # slik prepare la den, har derfor nøyaktig samme størrelse OG mtime som
    # kilden i base/, comfy/ eller script/. Alt annet er rørt for hånd.
    known = set()
    for folder in (os.path.join(dp_order.BOOKS_DIR, info["book_slug"], "base"),
                   info["comfy_dir"], SCRIPT_DIR):
        if not os.path.isdir(folder):
            continue
        for name in os.listdir(folder):
            path = os.path.join(folder, name)
            if os.path.isfile(path):
                known.add(tuple(_fingerprint(path)))
    return [name for name, path in files
            if tuple(_fingerprint(path)) not in known]


_PAGE_MAP_CACHE: dict[str, dict] = {}


def page_input_map(info: dict) -> dict:
    """page_key -> filnavn-stem i input/ ("page03" -> "03(Prinsessen)").

    Mappingen finnes BARE i bokas prepare-script; config.json kjenner den
    ikke. Vi trenger den når prepare hoppes over: da må en godkjent variant
    inn i input/ på egen hånd, ellers bygges boka med den gamle siden.
    """
    prepare = info["config"].get("prepareScript")
    if not prepare or not os.path.isfile(prepare):
        return {}
    if prepare in _PAGE_MAP_CACHE:
        return _PAGE_MAP_CACHE[prepare]
    import importlib.util
    name = "dp_prepare_" + info["book_slug"].replace("-", "_")
    spec = importlib.util.spec_from_file_location(name, prepare)
    if not spec or not spec.loader:
        return {}
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)          # main() er __main__-beskyttet
    mapping = dict(getattr(module, "PAGE_TO_BASE_STEM", {}) or {})
    _PAGE_MAP_CACHE[prepare] = mapping
    return mapping


def input_file_for(info: dict, page_key: str) -> str | None:
    """Fila i input/ som denne siden faktisk trykkes fra."""
    stem = page_input_map(info).get(page_key)
    folder = info["input_dir"]
    if not stem or not os.path.isdir(folder):
        return None
    for name in sorted(os.listdir(folder)):
        path = os.path.join(folder, name)
        if name.startswith(stem) and os.path.isfile(path):
            return path
    return None


def commit_variant_to_input(info: dict, page_key: str, source: str) -> str | None:
    """Legg en godkjent variant rett inn i input/, slik prepare ville gjort."""
    stem = page_input_map(info).get(page_key)
    if not stem:
        return None
    folder = info["input_dir"]
    os.makedirs(folder, exist_ok=True)
    dest = None
    for name in sorted(os.listdir(folder)):
        if name.startswith(stem) and os.path.isfile(os.path.join(folder, name)):
            dest = os.path.join(folder, name)
            break
    if dest is None:
        dest = os.path.join(folder, f"{stem}.png")
    shutil.copy2(source, dest)
    say(f"    input/{os.path.basename(dest)} <- {os.path.basename(source)}")
    return dest


# --------------------------------------------------------------------------
def commit_variant(info: dict, page_key: str, source: str) -> str:
    """Sett en godkjent variant inn som sidas comfy-resultat.

    prepare_order plukker FØRSTE fil som starter med page_key + "_", ikke den
    nyeste. Derfor må alle gamle treff bort først, ellers er det tilfeldig
    hvilken variant som havner i boka.
    """
    if not os.path.isfile(source):
        raise SystemExit(f"fant ikke {source}")
    comfy_dir = info["comfy_dir"]
    os.makedirs(comfy_dir, exist_ok=True)

    retired = os.path.join(comfy_dir, "_erstattet")
    for old in glob.glob(os.path.join(comfy_dir, f"{page_key}_*")):
        os.makedirs(retired, exist_ok=True)
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        shutil.move(old, os.path.join(retired, f"{stamp}-{os.path.basename(old)}"))
        say(f"    arkiverte {os.path.basename(old)}")

    dest = os.path.join(comfy_dir, f"{page_key}_00001_.png")
    shutil.copy2(source, dest)
    say(f"    {page_key} <- {os.path.basename(source)}")
    return dest


def adopt_legacy_next_cover(pdf_dir: str, next_dir: str) -> None:
    """Berg neste-forsiden fra pdf/ for ordre bygget foer next/ fantes.

    Bare aktuelt for en ordre som ligger urort mellom siste bygg og foerste
    reprint etter denne endringen - tekst-scriptet rmtree-er pdf/, saa vinduet
    er kort. Men er fila der, er den gratis aa redde.
    """
    for name in ("page99_next.png", "page99_next_mockup.png"):
        old, new = os.path.join(pdf_dir, name), os.path.join(next_dir, name)
        if os.path.isfile(old) and not os.path.isfile(new):
            shutil.copy2(old, new)
            say(f"    berget fra pdf/: {name}")


def backup(info: dict, what: tuple[str, ...] = ("input", "pdf")) -> str | None:
    """Kopier input/ og pdf/ UTENFOR pdf/ - tekst-scriptet rmtree-er pdf/."""
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    dest_root = os.path.join(info["order_path"], f"backup-reprint-{stamp}")
    made = False
    for name in what:
        src = os.path.join(info["order_path"], name)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(dest_root, name))
            made = True
    if made:
        say(f"    backup: {dest_root}")
        return dest_root
    return None


# --------------------------------------------------------------------------
def next_cover_paths(info: dict) -> tuple[str, str]:
    """(flat forside, 3D-mockup) for neste bok - i next/, ikke pdf/.

    pdf/ er ikke et sted noe kan ligge: tekst-scriptet rmtree-er den ved hvert
    bygg. next/ overlever baade den og Cleanup Comfy Folder.
    """
    next_dir = os.path.join(info["order_path"], "next")
    return (os.path.join(next_dir, "page99_next.png"),
            os.path.join(next_dir, "page99_next_mockup.png"))


def build_continue_page(info: dict, callback: bool = True) -> dict:
    """Bygg «Fortsett eventyret»-siden: forside -> mockup -> siste innerside.

    Skrevet ut av rebuild_pdfs fordi boten trenger noeyaktig samme kjede naar
    du bytter forsiden derfra. Ett sted aa endre, ellers driver de fra
    hverandre og boten bygger en side som reprint bygger annerledes.

    Skriver input/blank-back.png. PDF-ene er IKKE oppdatert etterpaa - det
    krever at tekst-scriptet kjoerer (rebuild_pdfs, eller «Bygg PDF» i boten).
    """
    payload = info["payload"]
    order_path = info["order_path"].replace("\\", "/")
    child = info["child_name"]
    next_png, mockup = (p.replace("\\", "/") for p in next_cover_paths(info))
    comfy = info["comfy_dir"].replace("\\", "/")

    os.makedirs(os.path.dirname(next_png), exist_ok=True)
    adopt_legacy_next_cover(f"{order_path}/pdf", os.path.dirname(next_png))

    if glob.glob(os.path.join(comfy, "page99_next*.png")):
        run([sys.executable, LAST_PAGE, "cover", "--raw", comfy,
             "--next-slug", str(info.get("next_book_slug") or ""),
             "--child-name", child, "--lang", script_lang(payload),
             "--mockup-template", MOCKUP_TEMPLATE,
             "--out", next_png, "--mockup-out", mockup],
            "Build Next Cover Title", check=False)
    elif os.path.isfile(next_png):
        say(f"\n--- Build Next Cover Title hoppet over"
            f"\n    raafila er ryddet bort - gjenbruker {next_png}")
    else:
        # Fail-soft videre (en betalt ordre skal ikke stoppe her), men ikke
        # stille: dette er noeyaktig feilen som ga trykte boeker med tittel og
        # QR, men uten bildet av neste bok.
        say("\n!!! ADVARSEL: neste-forsiden mangler og kan ikke bygges."
            f"\n    Verken {comfy}/page99_next*.png eller {next_png} finnes."
            f"\n    QR-siden blir uten bilde. Render den foerst med:"
            f"\n      python render_next_cover.py --order {info['order_id']} --commit")

    callback_url = str(payload.get("continue_callback") or "") if callback else ""
    if callback_url:
        # Landingssiden skal vise noeyaktig det som staar trykt, altsaa
        # mockupen. Den flate forsiden er fallback naar mockup-serveren tier.
        src = mockup if os.path.isfile(mockup) else next_png
        run([sys.executable, LAST_PAGE, "upload", "--file", src,
             "--callback", callback_url, "--secret", CONTINUE_SECRET],
            "Upload Continue Cover", check=False)

    blank_back = f"{order_path}/input/blank-back.png"
    run([sys.executable, LAST_PAGE, "image", "--next-cover", next_png,
         "--child-name", child,
         "--next-title", str(info.get("next_book_title") or ""),
         "--qr-url", str(payload.get("continue_url") or ""),
         "--coupon", str(payload.get("continue_coupon") or ""),
         "--lang", script_lang(payload), "--book-slug", info["book_slug"],
         "--mockup-template", MOCKUP_TEMPLATE,
         "--out", blank_back],
        "Build Last Page", check=False)

    return {"cover": next_png, "mockup": mockup, "last_page": blank_back,
            "has_cover": os.path.isfile(next_png)}


# --------------------------------------------------------------------------
def rebuild_pdfs(info: dict, skip_prepare: bool = False,
                 callback: bool = True) -> dict:
    payload = info["payload"]
    order_path = info["order_path"].replace("\\", "/")
    child = info["child_name"]
    pdf_dir = f"{order_path}/pdf"
    code = info["continue_code"]

    if not skip_prepare:
        prepare = info["config"].get("prepareScript")
        if not prepare:
            raise SystemExit(f"config for {info['book_slug']} mangler prepareScript")
        run([sys.executable, prepare, info["order_id"]], "Prepare Pages")
        # Fasit for hva input/ inneholdt rett etter prepare. Uten den kan vi
        # ikke skille en manuell endring fra en fil prepare selv la der.
        write_prepared_manifest(info)
    else:
        # Brukt når du har redigert input/ for hånd (f.eks. upscalet sider).
        # prepare_order ville kopiert base/ + comfy/ over dem igjen.
        print("\n--- Prepare Pages hoppet over (input/ brukes som den er)")

    if code:
        build_continue_page(info, callback=callback)
    else:
        print("\n--- QR-siste-side hoppet over (ordren har ingen continue_code)")

    text_script = info["text_script"]
    if not text_script:
        raise SystemExit(f"fant ingen tekst-script for {info['book_slug']}")

    # Windows-filsystemet er case-insensitivt: skriver tekst-scriptet
    # "Mateo_cover.pdf" over en eksisterende "MATEO_cover.pdf", beholder
    # katalogen det GAMLE navnet - og scriptets egen opprydding (keep-settet
    # bruker det nye navnet) sletter da PDF-en den nettopp lagde. Tom pdf/
    # foerst; scriptet toemmer den uansett, og backup() har tatt kopi.
    if os.path.isdir(pdf_dir):
        for fname in os.listdir(pdf_dir):
            stale = os.path.join(pdf_dir, fname)
            shutil.rmtree(stale) if os.path.isdir(stale) else os.remove(stale)

    run([sys.executable, text_script, "--base", f"{order_path}/input",
         "--out", pdf_dir, "--name", child,
         "--cover-type", info["cover_type"], "--gelato-api-key", GELATO_KEY],
        "Run Text Script")

    inner = f"{pdf_dir}/{child}_innersider.pdf"
    cover = f"{pdf_dir}/{child}_cover.pdf"
    combined = f"{pdf_dir}/{child}_gelato.pdf"

    if code:
        run([sys.executable, LAST_PAGE, "stamp", "--pdf", inner,
             "--qr-url", str(payload.get("continue_url") or "")],
            "Stamp QR On Innersider", check=False)

    run([sys.executable, GELATO_PDF, "--cover", cover, "--inner", inner,
         "--out", combined,
         "--expected-inner", str(info["config"].get("expectedInnerPages", 31)),
         "--book-slug", info["book_slug"], "--order-id", info["order_id"]],
        "Build Gelato PDF")

    from pypdf import PdfReader
    inner_pages = len(PdfReader(inner).pages)
    total_pages = len(PdfReader(combined).pages)
    print(f"\n    innersider {inner_pages}   samlet PDF {total_pages}")
    if total_pages != 33:
        raise SystemExit(f"samlet PDF har {total_pages} sider, Gelato-produktet krever 33")
    if inner_pages not in (30, 31):
        raise SystemExit(f"innersider har {inner_pages} sider, forventet 30 eller 31")

    return {"cover": cover, "inner": inner, "gelato": combined,
            "inner_pages": inner_pages, "total_pages": total_pages}


def script_lang(payload: dict) -> str:
    return str(payload.get("script_language") or payload.get("language") or "nb")


# --------------------------------------------------------------------------
def merged_state(order_id: str) -> dict | None:
    """Kvitteringen hvis ordren ligger INNE I et sammenslaatt utkast.

    Bare den sekundaere ordren far `status: "merged"`; den primaere beholder
    utkastet under sin egen referanse. Se dp_merge.merged_group() for hele
    gruppa uansett hvilken side du spor fra.
    """
    path = os.path.join(DRAFT_STATE_DIR, f"{order_id}.json")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            state = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    return state if state.get("status") == "merged" else None


def merge_guard(order_id: str, force: bool = False) -> None:
    """En sammenslått ordre ligger under en ANNEN orderReferenceId.

    Uten denne sperren ville reprint laget et duplikat ved siden av det
    sammenslåtte utkastet - to trykte bøker for en betalt.
    """
    state = None if force else merged_state(order_id)
    if state:
        raise SystemExit(
            f"ordre {order_id} ligger i det sammenslåtte utkastet "
            f"{state.get('merged_into_draft')} (sammen med ordre "
            f"{state.get('merged_into_order')}).\n"
            "Slett det utkastet i Gelato først, eller kjør med --force.")


def known_draft_ids(order_id: str) -> list[str]:
    """Utkast-id fra vår egen kvittering + Gelato-søk.

    orders:search har returnert tomt for et utkast laget 40 min tidligere, så
    den kan ikke stå alene når vi skal unngå duplikater.
    """
    ids = []
    path = os.path.join(DRAFT_STATE_DIR, f"{order_id}.json")
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as fh:
                state = json.load(fh)
            for key in ("draft_id", "gelato_draft_id", "orderId", "id"):
                if state.get(key):
                    ids.append(str(state[key]))
        except (OSError, json.JSONDecodeError):
            pass
    try:
        _, res = gelato("POST", "https://order.gelatoapis.com/v4/orders:search",
                        {"orderReferenceIds": [str(order_id)]})
        ids.extend(str(o["id"]) for o in res.get("orders", []))
    except Exception as error:
        print(f"    (Gelato-søk feilet: {error})")
    return list(dict.fromkeys(ids))


def upload_and_draft(info: dict, files: dict, make_draft: bool) -> dict:
    payload = info["payload"]
    order_id = info["order_id"]
    parent = info["config"]["driveFolderId"]

    uploaded = {}
    for key in ("cover", "inner", "gelato"):
        proc = run([sys.executable, DRIVE_UPLOAD, "--file", files[key],
                    "--parent", parent, "--folder", order_id, "--public", "--replace"],
                   f"Drive: {os.path.basename(files[key])}")
        start = proc.stdout.rfind("{")
        uploaded[key] = json.loads(proc.stdout[start:]) if start != -1 else {}

    result = {"drive": uploaded}
    if not make_draft:
        print("\n--- Gelato-utkast IKKE opprettet (krever --gelato)")
        return result

    old = known_draft_ids(order_id)
    print(f"\n--- Gelato: eksisterende utkast {old or 'ingen'}")

    file_url = (uploaded["gelato"].get("downloadUrl")
                or f"https://drive.usercontent.google.com/download"
                   f"?id={uploaded['gelato']['id']}&export=download&confirm=t")
    ship = payload["shipping"]
    cust = payload["customer"]
    body = {
        "orderType": "draft",
        "orderReferenceId": str(order_id),
        "customerReferenceId": cust.get("email") or f"customer-{order_id}",
        "currency": "NOK",
        "shippingAddress": {
            "firstName": ship["first_name"], "lastName": ship["last_name"],
            "addressLine1": ship["address_1"], "addressLine2": ship.get("address_2") or "",
            "city": ship["city"], "postCode": ship["postcode"], "country": ship["country"],
            "email": cust.get("email"),
            "phone": ship.get("phone") or cust.get("phone") or "",
        },
        "items": [{
            "itemReferenceId": f"item-{order_id}",
            "productUid": PRODUCT_UID[info["cover_type"]],
            "pageCount": 30,          # produkt-variant-ID, ikke faktisk sidetall
            "files": [{"type": "default", "url": file_url}],
            "quantity": 1,
        }],
    }

    # Nytt utkast FØRST, deretter rydding - vi skal aldri stå uten utkast.
    status, res = gelato("POST", "https://order.gelatoapis.com/v4/orders", body)
    draft_id = res.get("id")
    print(f"    nytt utkast (HTTP {status}): {draft_id}")
    result["draft_id"] = draft_id

    for old_id in old:
        if str(old_id) == str(draft_id):
            continue
        try:
            code, _ = gelato("DELETE", f"https://order.gelatoapis.com/v4/orders/{old_id}")
            print(f"    slettet gammelt utkast {old_id} (HTTP {code})")
        except Exception as error:
            print(f"    kunne ikke slette {old_id}: {error}")

    os.makedirs(DRAFT_STATE_DIR, exist_ok=True)
    with open(os.path.join(DRAFT_STATE_DIR, f"{order_id}.json"), "w", encoding="utf-8") as fh:
        json.dump({"order_id": order_id, "draft_id": draft_id,
                   "status": "draft", "source": "reprint_order.py",
                   "drive_url": file_url,
                   "updated_at": dt.datetime.now().isoformat(timespec="seconds")},
                  fh, ensure_ascii=False, indent=2)
    return result


# --------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--order", required=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--gelato", action="store_true",
                    help="opprett Gelato-utkast (ellers bare PDF + Drive)")
    ap.add_argument("--skip-prepare", action="store_true",
                    help="ikke kjør prepare_order - bruk input/ som den er")
    ap.add_argument("--no-drive", action="store_true")
    ap.add_argument("--no-backup", action="store_true")
    ap.add_argument("--no-callback", action="store_true",
                    help="ikke last opp forsidebildet til landingssiden på nytt")
    ap.add_argument("--force", action="store_true", help="overstyr merge-sperren")
    ap.add_argument("--name", help="overstyr barnets navn fra payloaden "
                                   "(f.eks. når kunden skrev NAVNET I VERSALER)")
    args = ap.parse_args()
    if not (args.apply or args.dry_run):
        ap.error("velg --dry-run eller --apply")

    info = dp_order.resolve(args.order)
    merge_guard(info["order_id"], args.force)

    payload_name = info["child_name"]
    if args.name and args.name != payload_name:
        info["child_name"] = args.name

    print(f"ordre      {info['order_id']}")
    print(f"bok        {info['book_slug']}")
    print(f"barn       {info['child_name']}"
          + (f"   (payload: {payload_name})" if info["child_name"] != payload_name else ""))
    print(f"cover_type {info['cover_type']}")
    print(f"continue   {info['continue_code'] or '(ingen)'}")
    print(f"gelato     {'JA' if args.gelato else 'nei - bare PDF + Drive'}")

    edits = manual_edits(info)
    if edits:
        print(f"\nADVARSEL: {len(edits)} fil(er) i input/ er endret for hand:")
        for name in edits[:12]:
            print(f"    {name}")
        if len(edits) > 12:
            print(f"    ... (+{len(edits) - 12})")
        if not args.skip_prepare and not args.force:
            raise SystemExit(
                "prepare_order ville overskrevet disse med base/ + comfy/.\n"
                "Kjor med --skip-prepare for a beholde dem, eller --force for "
                "a bygge alt pa nytt fra comfy.")

    if not args.apply:
        print("\nTORRKJORING - ingenting bygget, lastet opp eller opprettet")
        return 0

    if not args.no_backup:
        backup(info)
    files = rebuild_pdfs(info, skip_prepare=args.skip_prepare,
                         callback=not args.no_callback)
    for key in ("cover", "inner", "gelato"):
        say(f"    {os.path.basename(files[key]):32s} {os.path.getsize(files[key]) / 1e6:7.2f} MB")

    if args.no_drive:
        print("\n--- Drive og Gelato hoppet over (--no-drive)")
        return 0

    upload_and_draft(info, files, make_draft=args.gelato)
    print("\nFERDIG")
    return 0


if __name__ == "__main__":
    sys.exit(main())
