# -*- coding: utf-8 -*-
"""Render en enkelt bokside på nytt, utenfor n8n.

Speiler workerens Build Page Prompt / HTTP Request ComfyUI / Acquire Comfy Lock,
med to viktige forskjeller:

1. SEED RANDOMISERES. Workflowen har hardkodet seed (node 156), så en ny
   kjøring med samme input gir NØYAKTIG samme bilde. Uten dette ville
   "ny variant"-knappen i boten vært en no-op.
2. Resultatet havner i .../variants/, ikke i comfy/. Ingenting rører den
   ferdige ordren før et bilde er godkjent - prepare_order plukker nemlig
   FØRSTE fil som matcher page_key, så løse varianter i comfy/ ville
   kunne havne i boka ved neste bygg.

Patch-nodene i config.json er ikke til å stole på (enhjorning peker på
151/121 som ikke finnes i dens egen workflow_api), derfor auto-detekteres de
på samme måte som i workeren.

  python regen_page.py --order 1235 --page 03 --count 3
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
import urllib.error
import urllib.request

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

COMFY = "http://127.0.0.1:8188"


OUTPUT_ROOT = r"C:\DreamPage-OS\output"
LOCK_PATH = r"C:\DreamPage-OS\DreamPage-image\.dreampage-comfy.lock"
LOCK_TTL = 2 * 60 * 60          # samme som workeren
RENDER_TIMEOUT = 15 * 60


class Cancelled(Exception):
    """Brukeren stoppet jobben."""


# --------------------------------------------------------------------------
# ComfyUI-låsen: deles med n8n-workeren, så en betalt ordre og en reprint
# aldri sloss om GPU-en.
# --------------------------------------------------------------------------
def read_lock() -> dict | None:
    try:
        with open(LOCK_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None


def acquire_lock(order_id: str, page_key: str, wait_seconds: int = 3600) -> bool:
    payload = json.dumps({
        "token": f"reprint:{order_id}:{page_key}:{int(time.time() * 1000)}",
        "createdAt": int(time.time() * 1000),
        "executionId": "reprint",
        "order_id": order_id,
        "page_key": page_key,
        "owner": "regen_page.py",
    }, indent=2)

    deadline = time.time() + wait_seconds
    while True:
        try:
            fd = os.open(LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
            return True
        except FileExistsError:
            existing = read_lock()
            age = time.time() - (existing or {}).get("createdAt", 0) / 1000
            if existing is None or age > LOCK_TTL:
                # Foreldet lås - workeren bruker samme TTL.
                try:
                    os.unlink(LOCK_PATH)
                except OSError:
                    pass
                continue
            if time.time() >= deadline:
                return False
            time.sleep(5)


def release_lock() -> None:
    lock = read_lock()
    if lock and lock.get("owner") == "regen_page.py":
        try:
            os.unlink(LOCK_PATH)
        except OSError:
            pass


# --------------------------------------------------------------------------
# Auto-deteksjon av patch-noder (portert fra workerens Build Page Prompt)
# --------------------------------------------------------------------------
def _refs(prompt: dict, node_id: str, class_filter=None) -> int:
    score = 0
    for node in prompt.values():
        if not isinstance(node, dict) or not node.get("inputs"):
            continue
        if class_filter and not class_filter(str(node.get("class_type", ""))):
            continue
        for value in node["inputs"].values():
            if isinstance(value, list) and value and str(value[0]) == str(node_id):
                score += 1
    return score


def _has_input(prompt: dict, node_id, name: str) -> bool:
    node = prompt.get(str(node_id)) if node_id else None
    return bool(node and isinstance(node.get("inputs"), dict) and name in node["inputs"])


def _loaders(prompt: dict) -> list[str]:
    return [nid for nid, node in prompt.items()
            if isinstance(node, dict) and node.get("class_type") == "LoadImage"
            and _has_input(prompt, nid, "image")]


def detect_nodes(prompt: dict, configured: dict) -> dict:
    pn = dict(configured or {})

    # output
    if not _has_input(prompt, pn.get("output"), "filename_prefix"):
        cands = [nid for nid, n in prompt.items()
                 if isinstance(n, dict) and _has_input(prompt, nid, "filename_prefix")]
        save = [nid for nid in cands if prompt[nid].get("class_type") == "SaveImage"]
        pn["output"] = (save or cands or [""])[0]

    # template: den lasteren som mates inn i inpaint/segmentering
    if not _has_input(prompt, pn.get("template"), "image"):
        def is_template_consumer(t: str) -> bool:
            return (t in ("InpaintCropImproved", "ImpactSimpleDetectorSEGS", "SAMDetectorCombined")
                    or "GroundingDino" in t or "Segment" in t)
        cands = [n for n in _loaders(prompt) if str(n) != str(pn.get("face", ""))]
        cands.sort(key=lambda n: _refs(prompt, n, is_template_consumer) * 100 + _refs(prompt, n),
                   reverse=True)
        pn["template"] = cands[0] if cands else ""

    # face: den lasteren som IKKE er template
    if not _has_input(prompt, pn.get("face"), "image"):
        cands = [n for n in _loaders(prompt) if str(n) != str(pn.get("template", ""))]
        flux = [n for n in cands
                if _refs(prompt, n, lambda t: "FluxKontext" in t) > 0]
        if flux:
            pn["face"] = flux[0]
        else:
            cands.sort(key=lambda n: _refs(prompt, n))
            pn["face"] = cands[0] if cands else ""

    # mask
    if not _has_input(prompt, pn.get("mask"), "image"):
        pn["mask"] = ""
        for nid, node in prompt.items():
            if isinstance(node, dict) and node.get("class_type") == "LoadImageMask" \
                    and _has_input(prompt, nid, "image"):
                pn["mask"] = nid
                break

    for key, needed in (("template", "image"), ("face", "image"),
                        ("output", "filename_prefix")):
        if not _has_input(prompt, pn.get(key), needed):
            raise SystemExit(f"klarte ikke å finne {key}-node med input '{needed}' i workflowen")
    return pn


def randomize_seeds(prompt: dict, seed: int) -> list[str]:
    """Sett alle seed-felt. Uten dette blir hver 'ny variant' identisk."""
    touched = []
    rng = random.Random(seed)
    for nid, node in prompt.items():
        if not isinstance(node, dict) or not isinstance(node.get("inputs"), dict):
            continue
        for key in ("seed", "noise_seed"):
            if key in node["inputs"] and isinstance(node["inputs"][key], (int, float)):
                node["inputs"][key] = rng.randrange(1, 2**53)
                touched.append(f"{nid}.{key}")
    return touched


# --------------------------------------------------------------------------
# ComfyUI
# --------------------------------------------------------------------------
def comfy_post(path: str, body: dict) -> dict:
    data = json.dumps(body).encode()
    req = urllib.request.Request(COMFY + path, data=data, method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        raw = resp.read().decode()
    return json.loads(raw) if raw.strip() else {}


def comfy_get(path: str) -> dict:
    with urllib.request.urlopen(COMFY + path, timeout=60) as resp:
        raw = resp.read().decode()
    return json.loads(raw) if raw.strip() else {}


def interrupt() -> None:
    """Avbryt det ComfyUI holder på med, og tøm køen dens."""
    for path, body in (("/interrupt", {}), ("/queue", {"clear": True})):
        try:
            comfy_post(path, body)
        except Exception:
            pass


def wait_for(prompt_id: str, timeout: int = RENDER_TIMEOUT,
             should_cancel=None) -> list[dict]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if should_cancel and should_cancel():
            raise Cancelled("avbrutt mens ComfyUI jobbet")
        try:
            history = comfy_get(f"/history/{prompt_id}")
        except (urllib.error.URLError, TimeoutError):
            time.sleep(3)
            continue
        entry = history.get(prompt_id)
        if entry:
            status = entry.get("status") or {}
            if status.get("status_str") == "error" or status.get("completed") is False and status.get("messages") and any(
                    m[0] == "execution_error" for m in status.get("messages", []) if isinstance(m, list)):
                raise SystemExit(f"ComfyUI feilet: {json.dumps(status)[:800]}")
            images = []
            for out in (entry.get("outputs") or {}).values():
                images.extend(out.get("images") or [])
            if images:
                return images
            if status.get("completed"):
                raise SystemExit("ComfyUI ble ferdig uten å produsere bilder")
        time.sleep(3)
    raise SystemExit(f"tidsavbrudd etter {timeout}s - ComfyUI ble ikke ferdig")


# --------------------------------------------------------------------------
def existing_variants(info: dict, page_key: str) -> list[str]:
    """Varianter som alt ligger på disk for denne siden.

    Brukes til å plukke opp igjen etter en restart: ComfyUI gjør ferdig det
    den holder på med selv om den som bestilte jobben forsvinner.
    """
    import glob as _glob
    found = _glob.glob(os.path.join(info["variants_dir"], f"{page_key}-s*"))
    return sorted(found, key=os.path.getmtime)


def render_variants(info: dict, page_key: str, count: int = 3,
                    face_image: str | None = None,
                    wait_lock: int = 3600,
                    on_progress=None, should_cancel=None) -> list[str]:
    """Render `count` varianter av en side. Returnerer filstier."""
    config = info["config"]
    page = dp_order.page_entry(config, page_key)
    if not page:
        available = ", ".join(p["page_key"] for p in config.get("pages", []))
        raise SystemExit(f"boka {info['book_slug']} har ingen side {page_key}.\nSider: {available}")

    # Kropps-, haar- og hudvariant (f.eks. 2-4 aar / kort haar / moerk hud).
    # Bytter BARE malbildet som gaar inn i ComfyUI - resultatet lagres fortsatt
    # under page_key, saa prepare, tekst-scriptet og PDF-bygget merker ingenting.
    variant = dp_order.body_variant(info)
    hair = dp_order.hair_variant(info)
    skin = dp_order.skin_variant(info)
    swapped = dp_order.apply_variants(page, variant, hair, skin)
    if swapped is not page:
        print(f"    variant kropp={variant} haar={hair} hud={skin}: "
              f"{swapped['template_image']}")
    page = swapped

    workflow_file = (config.get("workflowApi")
                     or (config.get("workflowApis") or {}).get("innerpages")
                     or "workflow_api.json")
    workflow_path = os.path.join(r"C:\DreamPage-OS\books", info["book_slug"], workflow_file)
    with open(workflow_path, encoding="utf-8-sig") as fh:
        base_prompt = json.load(fh)

    face = face_image or info["face_image"]
    if not os.path.isfile(os.path.join(r"C:\DreamPage-OS\input", face)):
        raise SystemExit(f"fant ikke barnebildet C:/DreamPage-OS/input/{face}")

    prefix = config.get("comfyOutputPrefix", f"{info['book_slug']}/orders")
    out_rel = f"{prefix}/{info['order_id']}/variants"
    out_dir = os.path.join(OUTPUT_ROOT, out_rel.replace("/", os.sep))
    os.makedirs(out_dir, exist_ok=True)

    results = []
    if not acquire_lock(info["order_id"], page_key, wait_seconds=wait_lock):
        lock = read_lock() or {}
        raise SystemExit("ComfyUI er opptatt med ordre "
                         f"{lock.get('order_id', '?')} ({lock.get('page_key', '?')}). Prøv igjen senere.")
    try:
        for index in range(count):
            if should_cancel and should_cancel():
                raise Cancelled("avbrutt før variant %d" % (index + 1))
            if on_progress:
                try:
                    on_progress(index, count)
                except Exception:
                    pass          # framdriftsvisning skal aldri stoppe en render
            prompt = json.loads(json.dumps(base_prompt))
            pn = detect_nodes(prompt, config.get("patchNodes") or config.get("innerPatchNodes") or {})

            seed = random.randrange(1, 2**53)
            prompt[pn["template"]]["inputs"]["image"] = page["template_image"]
            prompt[pn["face"]]["inputs"]["image"] = face
            if pn.get("mask") and page.get("mask_image"):
                prompt[pn["mask"]]["inputs"]["image"] = page["mask_image"]
            prompt[pn["output"]]["inputs"]["filename_prefix"] = f"{out_rel}/{page_key}-s{seed}"
            randomize_seeds(prompt, seed)

            # Workeren gjør den samme erstatningen; bong_tangent finnes ikke
            # i alle ComfyUI-installasjoner.
            for node in prompt.values():
                if isinstance(node, dict) and isinstance(node.get("inputs"), dict) \
                        and node["inputs"].get("scheduler") == "bong_tangent":
                    node["inputs"]["scheduler"] = "ddim_uniform"

            response = comfy_post("/prompt", {"prompt": prompt})
            prompt_id = response.get("prompt_id") or response.get("promptId")
            if not prompt_id:
                raise SystemExit(f"ComfyUI ga ingen prompt_id: {json.dumps(response)[:500]}")
            print(f"[{index + 1}/{count}] {page_key} seed={seed} prompt_id={prompt_id}", flush=True)

            for image in wait_for(prompt_id, should_cancel=should_cancel):
                path = os.path.join(OUTPUT_ROOT,
                                    (image.get("subfolder") or "").replace("/", os.sep),
                                    image["filename"])
                if os.path.isfile(path):
                    results.append(path)
                    print(f"      -> {path}", flush=True)
    finally:
        release_lock()

    if not results:
        raise SystemExit("ingen bilder ble produsert")
    return results


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--order", required=True)
    ap.add_argument("--page", required=True, help="03, page03 eller forside")
    ap.add_argument("--count", type=int, default=3)
    ap.add_argument("--face", default="", help="annet barnebilde i C:/DreamPage-OS/input")
    args = ap.parse_args()

    info = dp_order.resolve(args.order)
    page_key = dp_order.normalize_page_key(args.page)
    print(f"ordre {info['order_id']}  bok {info['book_slug']}  side {page_key}")
    paths = render_variants(info, page_key, args.count, face_image=args.face or None)
    print("\n".join(paths))
    return 0


if __name__ == "__main__":
    sys.exit(main())
