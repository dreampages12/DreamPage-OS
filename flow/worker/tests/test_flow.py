# -*- coding: utf-8 -*-
"""Testene som svarer paa akseptansekriteriene i oppdraget.

    python flow/worker/tests/test_flow.py

Ingen pytest-avhengighet: dette skal kunne kjoeres paa maskinen som faktisk
trykker boeker, uten aa installere noe. Alt gaar mot et midlertidig DP_ROOT,
saa testene kan ikke roere en kundeordre.

Kriteriene som daekkes:

  * To ordre paa koen samtidig kjoerer etter hverandre - aldri parallelt mot
    ComfyUI. (test_serialisering)
  * Samme ordre levert to ganger produserer én bok, ikke to.
    (test_idempotens, test_duplikat_ack)
  * ComfyUI kan restartes midt i en ordre uten at ordren doer permanent.
    (test_disk_slaar_history)
  * "Er siden ferdig?" ser KUN i ordrens egen mappe.
    (test_sidenoekler_lekker_ikke)
  * Du kan svare "hvor stoppet ordre X og hvorfor" fra jobb-DB-en.
    (test_ubyggbar_bok_feiler_hoeyt)
  * En poison message spiser ikke koeen. (test_permanent_feil_kjoeres_ikke_om)
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORKER = HERE.parent
FLOW = WORKER.parent

_results: list[tuple[str, bool, str]] = []


def test(fn):
    """Enkleste mulige testregister. Navnet er dokumentasjonen."""
    _results.append((fn.__name__, None, ""))
    return fn


# ---------------------------------------------------------------------------
# Sandkasse: et helt DP_ROOT i en midlertidig mappe
# ---------------------------------------------------------------------------
# Et PNG-hode uten omveier: testene trenger bare at fila SER ut som
# et bilde. Skrevet med bytes() og ikke escape-sekvenser, saa den
# taaler aa bli flyttet mellom verktoy som tolker backslash.
PNG_STUB = bytes([0x89]) + b"PNG" + bytes([13, 10, 26, 10]) + b"0" * 64


class Sandbox:
    """Et komplett, falskt DreamPage-rot med én bok og tre sider.

    Poenget er at ingen test kan naa en ekte ordre. `DP_ROOT` settes FOER
    modulene importeres, fordi paths.py leser den ved import.
    """

    def __init__(self):
        self.root = Path(tempfile.mkdtemp(prefix="dpflow-test-"))
        os.environ["DP_ROOT"] = str(self.root)
        for d in ("books", "output", "input", "state", "config", "flow"):
            (self.root / d).mkdir(parents=True, exist_ok=True)

        self.slug = "testbok"
        book = self.root / "books" / self.slug
        book.mkdir(parents=True, exist_ok=True)
        pages = [{"page_key": f"page{i:02d}",
                  "template_image": f"{i:02d}(test).png",
                  "mask_image": f"{i:02d}-headmask(test).png",
                  "face_expression": "noytral"} for i in range(3)]
        (book / "config.json").write_text(json.dumps({
            "slug": self.slug,
            "displayName": "Testbok",
            "textScript": str(self.root / "flow" / "text-test.py"),
            "orderBasePath": str(book / "orders"),
            "comfyOutputPrefix": f"{self.slug}/orders",
            "patchNodes": {"template": "1", "face": "2", "output": "3"},
            "pages": pages,
            "expectedInnerPages": 30,
            "workflowApi": "workflow_api.json",
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        # Minimal, men strukturelt ekte workflow: to LoadImage og en SaveImage.
        (book / "workflow_api.json").write_text(json.dumps({
            "1": {"class_type": "LoadImage", "inputs": {"image": "mal.png"}},
            "2": {"class_type": "LoadImage", "inputs": {"image": "ansikt.jpg"}},
            "3": {"class_type": "SaveImage",
                  "inputs": {"filename_prefix": "x", "images": ["1", 0]}},
        }), encoding="utf-8")
        (self.root / "flow" / "text-test.py").write_text("# test\n", encoding="utf-8")

    def payload(self, job_key: str) -> dict:
        return {"job_key": job_key, "order_id": job_key,
                "book_slug": self.slug, "book_title": "Testbok",
                "child_name": "Testbarn", "cover_type": "hardcover",
                "language": "nb"}

    def child_photo(self, job_key: str) -> None:
        (self.root / "input" / f"{job_key}.jpg").write_bytes(b"\xff\xd8\xff" + b"0" * 64)

    def comfy_dir(self, job_key: str) -> Path:
        return self.root / "output" / self.slug / "orders" / job_key / "comfy"

    def place_pages(self, job_key: str, keys) -> None:
        """Legg ferdige sidefiler paa disk, som om ComfyUI hadde laget dem."""
        d = self.comfy_dir(job_key)
        d.mkdir(parents=True, exist_ok=True)
        for key in keys:
            (d / f"{key}_00001_.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 128)

    def close(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)


class FakeComfy:
    """ComfyUI-erstatning som skriver sidefilen etter `render_seconds`.

    Teller ogsaa hvor mange som er inne i render_page samtidig - det er
    maalingen som gjoer serialiseringstesten til et bevis og ikke en paastand.
    """

    def __init__(self, sandbox: Sandbox, render_seconds: float = 0.25):
        self.sandbox = sandbox
        self.render_seconds = render_seconds
        self.inflight = 0
        self.max_inflight = 0
        self.rendered: list[str] = []
        self._lock = threading.Lock()
        self.conf = {"disk_settle_s": 0}

    def alive(self) -> bool:
        return True

    def system_stats(self) -> dict:
        return {"system": {"comfyui_version": "test"}}

    def queue_depth(self) -> int:
        return 0

    @staticmethod
    def existing_page(output_dir: Path, page_key: str):
        import comfy as comfy_mod
        return comfy_mod.Comfy.existing_page(output_dir, page_key)

    def render_page(self, prompt, output_dir: Path, page_key: str, on_progress=None):
        import comfy as comfy_mod
        existing = self.existing_page(output_dir, page_key)
        if existing:
            return comfy_mod.PageResult(page_key=page_key, path=existing,
                                        source="already-on-disk")
        with self._lock:
            self.inflight += 1
            self.max_inflight = max(self.max_inflight, self.inflight)
        try:
            time.sleep(self.render_seconds)
            output_dir.mkdir(parents=True, exist_ok=True)
            path = output_dir / f"{page_key}_00001_.png"
            path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 128)
            with self._lock:
                self.rendered.append(f"{output_dir.parent.parent.name}/{page_key}")
            return comfy_mod.PageResult(page_key=page_key, path=path,
                                        source="rendered", prompt_id="test")
        finally:
            with self._lock:
                self.inflight -= 1


def fresh_store(sandbox: Sandbox, name: str):
    import jobs as jobs_mod
    path = sandbox.root / "state" / f"{name}.sqlite"
    return jobs_mod.JobStore(path)


# ---------------------------------------------------------------------------
# Testene
# ---------------------------------------------------------------------------
@test
def test_serialisering(sb: Sandbox) -> None:
    """Tre ordre lagt paa koen samtidig kjoerer ETTER HVERANDRE.

    Dette er kriteriet som erstatter .dreampage-comfy.lock. Beviset er at
    FakeComfy aldri ser mer enn én side under arbeid samtidig, selv naar tre
    jobber ligger paa koen fra foer arbeidstraaden starter.
    """
    import runner as runner_mod
    store = fresh_store(sb, "ser")
    r = runner_mod.Runner(store)
    fake = FakeComfy(sb, render_seconds=0.15)
    r.comfy = fake

    keys = ["S1", "S2", "S3"]
    for key in keys:
        sb.child_photo(key)
        store.enqueue(key, sb.payload(key))
    r.start()
    for key in keys:
        r.submit(runner_mod.QueuedJob(key, sb.payload(key), pipeline="pages"))

    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        counts = store.count_by_status()
        if counts["done"] + counts["failed"] >= len(keys):
            break
        time.sleep(0.1)
    r.stop()

    counts = store.count_by_status()
    assert counts["done"] == 3, f"ventet 3 ferdige, fikk {counts}"
    assert fake.max_inflight == 1, (
        f"to sider var under arbeid samtidig (maks {fake.max_inflight}). "
        f"Serialiseringen er brutt - det er noeyaktig feilen fra 14.09.2026.")
    assert len(fake.rendered) == 9, f"ventet 9 sider, fikk {fake.rendered}"


@test
def test_idempotens(sb: Sandbox) -> None:
    """Samme ordre kjoert to ganger gir ÉN bok: sidene lages ikke om."""
    import runner as runner_mod
    store = fresh_store(sb, "idem")
    r = runner_mod.Runner(store)
    fake = FakeComfy(sb, render_seconds=0)
    r.comfy = fake
    sb.child_photo("I1")

    store.enqueue("I1", sb.payload("I1"))
    first = r.run_job(runner_mod.QueuedJob("I1", sb.payload("I1"),
                                       pipeline="pages"))
    assert first["status"] == "done", first
    assert len(fake.rendered) == 3, fake.rendered

    # Kjoer igjen. Ingen nye sider skal lages.
    store.retry("I1")
    second = r.run_job(runner_mod.QueuedJob("I1", sb.payload("I1"),
                                        pipeline="pages"))
    assert second["status"] == "done", second
    assert len(fake.rendered) == 3, (
        f"andre kjoering laget nye sider: {fake.rendered}. En ordre som kommer "
        f"to ganger paa koen ville blitt to boeker.")


@test
def test_duplikat_ack(sb: Sandbox) -> None:
    """En ferdig jobb som leveres paa nytt kjoeres IKKE om igjen.

    Ordre 1499 kom tre ganger paa én dag. `enqueue` er stedet det stoppes.
    """
    store = fresh_store(sb, "dup")
    assert store.enqueue("D1", sb.payload("D1")) is True
    store.start("D1")
    store.finish("D1", "done")
    assert store.enqueue("D1", sb.payload("D1")) is False, \
        "en ferdig jobb ble lagt paa koen igjen"


@test
def test_permanent_feil_kjoeres_ikke_om(sb: Sandbox) -> None:
    """En poison message spiser ikke koeen.

    En jobb som feilet paa sin EGEN feil - en bok uten config.json - legges
    ikke tilbake automatisk. Uten dette ville den blitt levert, feilet, lagt
    tilbake, levert... i evig loekke, og blokkert alle ordre bak seg.
    """
    store = fresh_store(sb, "poison")
    store.enqueue("P1", sb.payload("P1"))
    store.start("P1")
    store.finish("P1", "failed", "boka mangler config.json", permanent=True)
    assert store.enqueue("P1", sb.payload("P1")) is False, \
        "en permanent feilet jobb ble kjoert paa nytt automatisk"
    # Men operatoeren skal kunne be om det, naar aarsaken er rettet.
    assert store.retry("P1") is True
    assert store.job("P1")["status"] == "pending"
    assert store.job("P1")["permanent"] == 0


@test
def test_systemfeil_proeves_igjen_men_ikke_evig(sb: Sandbox) -> None:
    """En systemfeil retries, men bare tre ganger."""
    store = fresh_store(sb, "attempts")
    store.enqueue("A1", sb.payload("A1"))
    for expected in (True, True, False):
        store.start("A1")
        store.finish("A1", "failed", "ComfyUI svarte ikke")
        got = store.enqueue("A1", sb.payload("A1"))
        assert got is expected, f"forsoek {store.job('A1')['attempt']}: ventet {expected}, fikk {got}"


@test
def test_disk_slaar_history(sb: Sandbox) -> None:
    """Ligger siden paa disk, er den ferdig - uansett hva /history sier.

    Dette er det som gjoer at ComfyUI kan startes paa nytt midt i en ordre:
    history-en forsvinner med prosessen, filen gjoer ikke. Uten dette doer
    ordren, og i dag etterlater den i tillegg en laasefil som blokkerer neste.
    """
    import comfy as comfy_mod
    sb.place_pages("R1", ["page00", "page01"])
    d = sb.comfy_dir("R1")
    assert comfy_mod.Comfy.existing_page(d, "page00") is not None
    assert comfy_mod.Comfy.existing_page(d, "page02") is None

    class DeadComfy(comfy_mod.Comfy):
        """ComfyUI som nettopp startet paa nytt: /history er tom."""
        def history(self, prompt_id):
            return {}
        def submit(self, prompt):
            return "borte"

    client = DeadComfy({"url": "http://127.0.0.1:1", "prompt_timeout_s": 5,
                        "poll_interval_s": 0, "poll_max_tries": 3,
                        "history_timeout_s": 5, "history_error_tolerance": 5,
                        "disk_settle_s": 0})
    # page00 finnes: skal returnere uten aa roere nettverket i det hele tatt.
    result = client.render_page({}, d, "page00")
    assert result.source == "already-on-disk", result.source
    assert result.path is not None


@test
def test_sidenoekler_lekker_ikke(sb: Sandbox) -> None:
    """"Er siden ferdig?" ser KUN i ordrens EGEN mappe.

    14.09.2026 fikk ordre 1499 og 1500 se i hverandres output-mapper.
    Sidenoeklene er like i alle boeker, saa hver av dem konkluderte med at den
    andres sider var deres egne - og hoppet over dem. Bildene var ikke feil,
    de var borte.
    """
    import comfy as comfy_mod
    sb.place_pages("X1", ["page00", "page01", "page02"])
    other = sb.comfy_dir("X2")
    other.mkdir(parents=True, exist_ok=True)
    assert comfy_mod.Comfy.existing_page(other, "page00") is None, \
        "fant en side i en mappe der ingen side er laget"

    # Og en full kjoering for X2 maa lage alle tre paa nytt, selv om X1 har dem.
    import runner as runner_mod
    store = fresh_store(sb, "scope")
    r = runner_mod.Runner(store)
    fake = FakeComfy(sb, render_seconds=0)
    r.comfy = fake
    sb.child_photo("X2")
    store.enqueue("X2", sb.payload("X2"))
    res = r.run_job(runner_mod.QueuedJob("X2", sb.payload("X2"),
                                     pipeline="pages"))
    assert res["status"] == "done", res
    assert len(fake.rendered) == 3, (
        f"X2 laget bare {len(fake.rendered)} sider - den saa i X1 sin mappe")


@test
def test_ubyggbar_bok_feiler_hoeyt(sb: Sandbox) -> None:
    """En bok uten config.json gir en FEILET jobb med en lesbar aarsak.

    Ordre 1517 (Hestestjernen, 2026-09-15 19:00) doede i n8n sin
    "Read Config File" etter 1,3 sekunder, og n8n skrev `status = success`.
    Ingen ble varslet. Her skal status vaere `failed`, feilteksten si hva som
    mangler, og steget som feilet skal vaere navngitt.
    """
    import runner as runner_mod
    store = fresh_store(sb, "ubyggbar")
    r = runner_mod.Runner(store)
    r.comfy = FakeComfy(sb, render_seconds=0)

    payload = sb.payload("U1")
    payload["book_slug"] = "finnes-ikke"
    payload["book_title"] = "Finnes Ikke"
    store.enqueue("U1", payload)
    res = r.run_job(runner_mod.QueuedJob("U1", payload, pipeline="pages"))

    assert res["status"] == "failed", res
    assert res.get("permanent") is True, res
    job = store.job("U1")
    assert job["status"] == "failed"
    assert "config.json" in (job["error"] or ""), job["error"]
    failed = [s for s in job["steps"] if s["status"] == "failed"]
    assert failed and failed[0]["name"] == "validate_job", job["steps"]


@test
def test_continue_code_roeres_ikke(sb: Sandbox) -> None:
    """continue_code gaar uendret gjennom, og regenereres aldri."""
    import books
    payload = sb.payload("C1")
    payload["continue_code"] = "ABCD1234"
    job = books.build_job(payload)
    assert job["continue_code"] == "ABCD1234"

    # Uten kode i payloaden skal det bli tomt - ikke noe oppdiktet.
    payload2 = sb.payload("C2")
    assert books.build_job(payload2)["continue_code"] == ""


@test
def test_cover_type_alltid_eksplisitt(sb: Sandbox) -> None:
    """Softcover er default i koden, men selges ikke. Mangler feltet, skal
    det bli hardcover - ikke softcover."""
    import books
    payload = sb.payload("V1")
    payload.pop("cover_type")
    assert books.build_job(payload)["cover_type"] == "hardcover"


@test
def test_job_key_er_mappenoekkelen(sb: Sandbox) -> None:
    """To boeker i samme WooCommerce-ordre havner i ULIKE mapper.

    order_id er ikke unik: 1411-b1 og 1411-b2 har begge order_id 1411.
    """
    import books
    a = books.build_job({**sb.payload("1411-b1"), "order_id": "1411"})
    b = books.build_job({**sb.payload("1411-b2"), "order_id": "1411"})
    assert a["order_id"] == "1411-b1" and b["order_id"] == "1411-b2"
    assert a["woo_order_id"] == b["woo_order_id"] == "1411"
    assert a["output_dir"] != b["output_dir"], "de to boekene deler output-mappe"
    assert a["order_path"] != b["order_path"]


@test
def test_tittelnormalisering(sb: Sandbox) -> None:
    """De 16 oedelagte n8n-noeklene er naabare etter normalisering.

    Den kjoerende noden har literal `?` der ae/oe/aa skulle staatt, saa
    "Enhjoerningsdalen" traff aldri tabellen. Nesten: handle-veien redder
    ordren, og derfor ble det aldri oppdaget.
    """
    from book_titles import TITLE_TO_SLUG, normalize
    cases = {
        "enhjørningsdalen": "enhjorning",
        "ENHJØRNINGSDALEN": "enhjorning",
        "sjöjungfrun": "havfruen",
        "Påskejakten": "paskejakten",
        "modet i hjärtat": "motet-i-hjertet",
        "  The Mermaid  ": "havfruen",
    }
    for title, want in cases.items():
        got = TITLE_TO_SLUG.get(normalize(title))
        assert got == want, f"{title!r} -> {got}, ventet {want}"


@test
def test_pipeline_er_data(sb: Sandbox) -> None:
    """Pipelinen kan beskrives som JSON, og stegene erklaerer egne verdier."""
    import pipeline
    described = pipeline.describe()
    names = [s["name"] for s in described["steps"]]
    # check_assets FOERST, og foer alt som rendrer eller bygger. Kunsten er
    # fail-soft hele veien ned (ordre 1510 og 1506), saa en manglende fil
    # maa stoppe jobben FOER den blir et bilde ingen ser paa igjen.
    assert names[0] == "check_assets", names
    assert names[1] == "validate_job", names
    assert names.index("check_assets") < names.index("render_pages"), names
    assert "render_pages" in names
    by_name = {s["name"]: s for s in described["steps"]}
    # render_pages har 14 timers timeout, ikke step_defaults sin ene time.
    assert by_name["render_pages"]["timeout_s"] == 14 * 3600, by_name["render_pages"]
    assert by_name["render_pages"]["checkpoint"] is True
    assert by_name["face_variants"]["optional"] is True
    # fetch_child_image overstyrer standarden (0). Tallet selv er ikke
    # poenget - det ble hevet fra 3 til 4 da ordre 1532 doede paa et
    # to-minutters nettverksbrudd - men at steget erklaerer sitt eget er.
    # Ventetiden testes i test_bildehenting_taaler_kort_nettverksbrudd.
    assert by_name["fetch_child_image"]["retries"] >= 3, by_name["fetch_child_image"]
    json.dumps(described)          # maa vaere serialiserbart for API-et


@test
def test_avbrudd_stopper_mellom_sider(sb: Sandbox) -> None:
    """En cancel fra operatoeren stopper jobben mellom to sider."""
    import runner as runner_mod
    store = fresh_store(sb, "cancel")
    r = runner_mod.Runner(store)
    r.comfy = FakeComfy(sb, render_seconds=0)
    sb.child_photo("K1")
    store.enqueue("K1", sb.payload("K1"))
    store.start("K1")
    store.request_cancel("K1")
    res = r.run_job(runner_mod.QueuedJob("K1", sb.payload("K1"),
                                     pipeline="pages"))
    assert res["status"] == "failed", res
    assert "avbrutt" in (res.get("error") or "").lower(), res


@test
def test_status_lekker_ikke_kundedata(sb: Sandbox) -> None:
    """/api/status skal ikke inneholde navn, ordrenummer, job_key eller stier.

    Dette er det ENESTE endepunktet som er ment aa naa ut av maskinen. Vi
    legger en jobb med gjenkjennelige verdier i DB-en og krever at ingen av
    dem dukker opp i statusen. `/api/health` inneholder derimot hele argv,
    og `/api/queue` inneholder barnenavn - de skal aldri eksponeres.
    """
    import json as _json
    import status as status_mod

    store = fresh_store(sb, "status")
    payload = dict(sb.payload("9911"))
    payload["child_name"] = "Gjenkjennelig-Barnenavn"
    payload["order_id"] = "9911"
    store.enqueue("9911", payload)

    # Tving forbi cachen: den er delt paa modulnivaa mellom testene.
    status_mod._cache.update(at=0.0, value=None)
    snap = status_mod.snapshot(runner=None, consumer=None, store=store)
    blob = _json.dumps(snap, ensure_ascii=False)

    for needle in ("Gjenkjennelig-Barnenavn", "9911", str(sb.root),
                   sb.slug, "Testbok"):
        assert needle not in blob, (
            f"statusen inneholder {needle!r}. /api/status naar ut av maskinen; "
            f"kundedata og filstier skal aldri vaere med.")

    # ... men tallene MAA vaere der, ellers er endepunktet ubrukelig.
    assert snap["jobs"]["pending"] == 1, snap["jobs"]
    assert snap["server"]["id"], "serveren maa kunne identifisere seg"
    assert snap["schema"] == 1, snap


@test
def test_status_token_naar_ikke_kundedata(sb: Sandbox) -> None:
    """Et token med scope "status" skal avvises paa alt annet enn status.

    Poenget med scopet: laekker overvaakingstokenet, skal det ikke vaere en
    kundedatalekkasje. Testen gaar mot avhengighetene direkte, saa den
    trenger ingen kjoerende server.
    """
    import json as _json
    import api as api_mod
    from fastapi import HTTPException
    from fastapi.security import HTTPAuthorizationCredentials

    cfg = sb.root / "config" / "api.json"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(_json.dumps({"tokens": {
        "T-full": "dashbord",
        "T-status": {"name": "overvaaking", "scope": "status"},
        "T-rart": {"name": "ukjent scope", "scope": "tull"},
    }}), encoding="utf-8")
    api_mod.API_CONFIG_PATH = cfg

    def creds(token):
        return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    assert api_mod.caller(creds("T-full")) == "dashbord"
    assert api_mod.status_caller(creds("T-full")) == "dashbord"
    assert api_mod.status_caller(creds("T-status")) == "overvaaking"

    for token, why in (("T-status", "status-token"), ("T-rart", "ukjent scope")):
        try:
            api_mod.caller(creds(token))
        except HTTPException as exc:
            assert exc.status_code == 403, (why, exc.status_code)
        else:
            raise AssertionError(f"{why} slapp inn paa full tilgang")

    # Ukjent token og manglende token skal fortsatt avvises.
    for bad, code in ((creds("T-finnes-ikke"), 403), (None, 401)):
        try:
            api_mod.status_caller(bad)
        except HTTPException as exc:
            assert exc.status_code == code, (bad, exc.status_code)
        else:
            raise AssertionError("ugyldig legitimasjon slapp inn")


@test
def test_status_api_har_bare_statusruter(sb: Sandbox) -> None:
    """Porten som eksponeres utenfra skal ikke HA noe annet aa naa.

    Dette er loeftet som gjoer det trygt aa peke en fjernstyrt tunnel-ingress
    (uten sti-filter) mot status-porten: appen inneholder tre ruter, og
    /api/jobs, /api/queue, /api/health og /panel er ikke montert i den.
    Grensen er konstruksjonen, ikke et regex i tunnel/config.yml.

    Feiler denne, har noen montert en rute i status-appen, og da kan
    `tobias-pc.dreampage.store` naa mer enn status. Ikke "fiks" den ved aa
    utvide ALLOWED_PATHS - flytt ruten til api.py i stedet.
    """
    import status_api

    app = status_api.create_status_app(runner=None, consumer=None)
    got = sorted(r.path for r in app.routes)
    assert got == sorted(status_api.ALLOWED_PATHS), (
        f"status-appen har rutene {got}. Bare {sorted(status_api.ALLOWED_PATHS)} "
        f"er lov - alt annet blir naabart utenfra.")

    # Ingen skriving. En tunnel utenfra skal ikke kunne endre noe.
    for route in app.routes:
        methods = set(getattr(route, "methods", ()) or ())
        assert methods <= {"GET", "HEAD"}, (route.path, methods)

    # Hver rute MAA ha auth. Tunnelen er transport, ikke autentisering.
    import api as api_mod
    for route in app.routes:
        deps = getattr(getattr(route, "dependant", None), "dependencies", [])
        calls = [d.call for d in deps]
        assert api_mod.status_caller in calls, (
            f"{route.path} mangler status_caller. En rute uten auth paa den "
            f"eksponerte porten er aapen for hele internett.")


@test
def test_cors_slipper_bare_tailnettet(sb: Sandbox) -> None:
    """CORS-moensteret skal treffe tailnettet og INGENTING annet.

    Kontrollpanelet kjoerer paa en annen maskin og vi vet ikke hvilken port
    det bruker, saa origin matches med et moenster i stedet for en liste.
    Et moenster som er litt for loest slipper inn hjemmenettet eller en
    offentlig side, og da kan en fane brukeren har aapen snakke med API-et.

    Grensetilfellene er med fordi forfatteren traadde feil paa dem:
    100.63 og 100.128 ligger UTENFOR 100.64.0.0/10, og
    `.ts.net`-navn har flere ledd enn ett. Foerste versjon av regexet
    avviste dreampage-01.tail1234.ts.net.

    Merk at CORS ikke er grensen her - tokenet og bind-adressen er det
    (worker/net.py). Denne testen holder bekvemmeligheten aerlig.
    """
    import re
    import api as api_mod

    rx = re.compile(api_mod._TAILNET_ORIGIN)
    lov = [
        "http://100.64.0.1", "http://100.127.255.254",
        "http://100.78.242.12:3000", "http://dreampage-01:8080",
        "https://dreampage-01.tail1234.ts.net",
        "https://dreampage-01.tail1234.ts.net:8443",
    ]
    ulov = [
        "http://192.168.86.50:3000",      # hjemmenettet
        "http://10.0.0.5", "http://172.16.0.5",
        "http://100.63.255.255",          # rett UNDER blokka
        "http://100.128.0.1",             # rett OVER blokka
        "https://evil.example.com",
        "http://evil.com/100.78.242.12",  # IP-en i stien, ikke verten
        "https://not-ts.net.evil.com",
        "http://100.78.242.12.evil.com",
    ]
    for o in lov:
        assert rx.match(o), f"{o} burde vaert tillatt"
    for o in ulov:
        assert not rx.match(o), (
            f"{o} slapp gjennom CORS-moensteret. Det skal BARE treffe "
            f"tailnettet - ikke hjemmenettet og ikke noe offentlig.")

    # Av som standard: en ny server skal ikke arve dette.
    import config as cfg_mod
    assert cfg_mod.DEFAULTS["api"]["tailnet"] is False, (
        "tailnet maa vaere false i standardene. Skrus paa per maskin i "
        "config/flow.json, ellers blir neste server naabar uten at noen ba om det.")


@test
def test_pipeline_override_endrer_ikke_standarden(sb: Sandbox) -> None:
    """En kjoering kan velge pipeline uten aa endre den for alle andre.

    Dette finnes fordi alternativet - aa flippe pipeline.ACTIVE til "full"
    for aa proeve fase 5 paa én ordre - endrer hvordan HVER framtidige ordre
    behandles paa et system med betalende kunder. Overstyringen skal gjelde
    én kjoering og ingenting mer.
    """
    import pipeline as pipeline_mod
    from runner import QueuedJob

    # Den aktive pipelinen er en av de kjente - ikke et navn noen har skrevet
    # feil. (Her stod det en gang `== "pages"`. Det var en oyeblikksverdi, ikke
    # en invariant: fase 5 gjorde "full" aktiv 16.09.2026, og da feilet en test
    # som egentlig handler om noe annet - nemlig at OVERSTYRINGEN ikke lekker.)
    assert pipeline_mod.ACTIVE in pipeline_mod.PIPELINES, pipeline_mod.ACTIVE
    for navn in ("pages", "full"):
        assert pipeline_mod.by_name(navn), navn
    try:
        pipeline_mod.by_name("tull")
    except KeyError:
        pass
    else:
        raise AssertionError("ukjent pipelinenavn burde gitt KeyError")

    # QueuedJob baerer valget, og standarden er None = den aktive.
    assert QueuedJob("K", {}).pipeline is None
    assert QueuedJob("K", {}, pipeline="full").pipeline == "full"

    # "full" er "pages" pluss etter-stegene, i den rekkefoelgen. Hvis noen
    # bygger om pipelinen skal en full kjoering fortsatt gjoere sidene foerst.
    pages = [st.name for st in pipeline_mod.by_name("pages")]
    full = [st.name for st in pipeline_mod.by_name("full")]
    assert full[:len(pages)] == pages, (pages, full)
    assert "upload_and_draft" in full and "upload_and_draft" not in pages


# ---------------------------------------------------------------------------
# Varsling: en betalt ordre som stopper, skal si fra selv
# ---------------------------------------------------------------------------
@test
def test_feilet_jobb_varsler(sb: Sandbox) -> None:
    """En jobb som feiler sender ETT varsel, med ordre, steg og aarsak.

    Kriteriet dette daekker er ordre 1517: boka fantes ikke, jobben stoppet,
    og ingen fikk beskjed. Fram til 16.09.2026 fantes det to varsler i hele
    workeren og BEGGE fyrte bare naar det gikk bra - feilen var flyttet fra
    n8n sin `status = success` til en SQLite-rad ingen leser.
    """
    import notify
    import runner as runner_mod

    sent: list = []
    original = notify.send
    notify.send = lambda text, log=None, timeout=30: (
        sent.append(text) or {"sent": True})
    try:
        store = fresh_store(sb, "varsel")
        r = runner_mod.Runner(store)
        r.comfy = FakeComfy(sb, render_seconds=0)
        payload = sb.payload("V1")
        payload["book_slug"] = "finnes-ikke"
        store.enqueue("V1", payload)
        res = r.run_job(runner_mod.QueuedJob("V1", payload, pipeline="pages"))
    finally:
        notify.send = original

    assert res["status"] == "failed", res
    assert len(sent) == 1, f"ventet ETT varsel, fikk {len(sent)}: {sent}"
    text = sent[0]
    assert "V1" in text, text
    # Permanent feil skal si at den ikke starter av seg selv - det er
    # forskjellen operatoeren maa handle ulikt paa.
    assert "starter ikke av seg selv" in text, text
    assert "retry" in text, text


@test
def test_varsling_som_feiler_stopper_ingenting(sb: Sandbox) -> None:
    """Telegram nede skal ikke gjoere en ferdig jobb til en feilet jobb."""
    import notify
    import runner as runner_mod

    original = notify.send

    def eksploder(text, log=None, timeout=30):
        raise OSError("Telegram er nede")

    notify.send = eksploder
    try:
        store = fresh_store(sb, "varsel2")
        r = runner_mod.Runner(store)
        r.comfy = FakeComfy(sb, render_seconds=0)
        payload = sb.payload("V2")
        payload["book_slug"] = "finnes-ikke"
        store.enqueue("V2", payload)
        # Skal ikke kaste videre: jobben er alt feilet, og varselet er et
        # sidespor. Kaster den her, mister vi finished-callbacken og dermed
        # ack-en til RabbitMQ.
        res = r.run_job(runner_mod.QueuedJob("V2", payload, pipeline="pages"))
    finally:
        notify.send = original

    assert res["status"] == "failed", res
    assert (store.job("V2") or {}).get("status") == "failed"


# ---------------------------------------------------------------------------
# check_assets som steg
# ---------------------------------------------------------------------------
@test
def test_manglende_kunst_stopper_foer_rendring(sb: Sandbox) -> None:
    """En manglende kunstfil stopper jobben FOER noe blir rendret.

    Ordre 1510 (line2-logoen) og 1506 (aapningssida) naadde begge et
    trykkeklart utkast fordi kunstkjeden er fail-soft: den advarer og gaar
    videre. Da maa mangelen fanges foer rendringen, ikke under.
    """
    import steps as steps_mod
    from books import JobError

    ctx = steps_mod.Context(job_key="A1", payload=sb.payload("A1"),
                            log=_NullLog())

    sys.path.insert(0, str(steps_mod.TOOLS_DIR))
    import check_assets as checker

    original = checker.audit
    checker.audit = lambda: ([("x", "a.png")], [("config/x.json", "flow/text/logo/borte.png")])
    try:
        raised = None
        try:
            steps_mod.check_assets(ctx)
        except JobError as exc:
            raised = exc
        assert raised is not None, "manglende kunst gikk rett gjennom"
        assert "borte.png" in str(raised), str(raised)
    finally:
        checker.audit = original

    # Og med alt paa plass skal steget si hvor mange stier det sjekket.
    checker.audit = lambda: ([("x", "a.png"), ("y", "b.png")], [])
    try:
        detail = steps_mod.check_assets(ctx)
        assert detail == {"paths": 2, "missing": 0}, detail
    finally:
        checker.audit = original


# ---------------------------------------------------------------------------
# Ufullstendig comfy/ -> raa maler i boka (ordre 1528)
# ---------------------------------------------------------------------------
@test
def test_ufullstendig_comfy_stopper_bygging(sb: Sandbox) -> None:
    """prepare far ikke kjore naar sider mangler BEGGE steder.

    Ordre 1528 (Lion, den-skjulte-styrken) fikk 12 raa maler i en bok som gikk
    til Gelato. cleanup_comfy_folder hadde slettet de rendrede sidene da det
    forste utkastet ble laget; operatoren rendret to nye fra Telegram, og
    /bygg kjorte prepare_order - som kopierer base-maler over input/ forst og
    henter faceswappede sider fra comfy/ etterpa. De 12 den ikke fant, ble
    staaende som raa maler. Scriptet advarte og avsluttet med 0.

    PDF-guarden fanget det ikke: den teller SIDER, ikke om de er
    personaliserte. 33 sider var riktig. Innholdet var det ikke.

    Guarden skal bare stoppe naar sidene mangler i input/ OGSAA - da hjelper
    ingen prepare, og de maa gjennom ComfyUI paa nytt.
    """
    # reprint_order henter Gelato-nokkelen ved IMPORT (finish_order gjor det
    # paa modulniva). Sandkassa har ingen secrets.json, saa vi bruker den
    # dokumenterte miljooverstyringen - ingen ekte nokkel, og ingenting her
    # snakker med Gelato.
    os.environ.setdefault("DP_GELATO_API_KEY", "test-ikke-en-ekte-nokkel")
    sys.path.insert(0, str(FLOW))
    import reprint_order

    comfy = sb.comfy_dir("C1")
    comfy.mkdir(parents=True, exist_ok=True)
    tom_input = sb.root / "books" / sb.slug / "orders" / "C1" / "input"
    tom_input.mkdir(parents=True, exist_ok=True)
    keys = ("page00", "page01", "page02")
    info = {
        "comfy_dir": str(comfy),
        "input_dir": str(tom_input),
        "book_slug": sb.slug,
        "config": {"pages": [{"page_key": k, "template_image": f"{k}(test).png"}
                             for k in keys]},
    }

    # Ingenting rendret, og input/ er tom -> maa rendres paa nytt.
    try:
        reprint_order.assert_comfy_complete(info)
    except SystemExit as exc:
        assert "3 av 3" in str(exc), str(exc)
        assert "ComfyUI" in str(exc), "maa si at sidene maa rendres paa nytt"
        # Den skal IKKE be operatoren bygge med --skip-prepare her: det
        # ville gitt en bok med tre manglende sider.
        assert "bygg med --skip-prepare" not in str(exc), str(exc)
    else:
        raise AssertionError("tom comfy/ og tom input/ slapp igjennom")

    # To av tre - noyaktig formen ordre 1528 hadde.
    for key in keys[:2]:
        (comfy / f"{key}_00001_.png").write_bytes(PNG_STUB)
    try:
        reprint_order.assert_comfy_complete(info)
    except SystemExit as exc:
        assert "3 av 3" in str(exc), "input/ er tom, saa alle tre er ubrukelige"
        assert "page02" in str(exc), str(exc)
    else:
        raise AssertionError("delvis rendret comfy/ slapp igjennom")

    # Alle tre i comfy/ -> prepare skal kjore som normalt.
    (comfy / "page02_00001_.png").write_bytes(PNG_STUB)
    decision = reprint_order.assert_comfy_complete(info)
    assert decision["total"] == 3, decision
    assert decision["skip_prepare"] is False, decision

    # En bok uten pages i config skal ikke stoppes av denne guarden.
    assert reprint_order.assert_comfy_complete(
        {"comfy_dir": str(comfy), "config": {}})["total"] == 0


@test
def test_ryddet_comfy_hopper_over_prepare(sb: Sandbox) -> None:
    """Ligger sidene ferdige i input/, velger guarden skip-prepare selv.

    Dette er normaltilstanden for enhver ordre som alt har fatt et
    Gelato-utkast: `cleanup_comfy_folder` har slettet comfy/, mens de
    ferdige sidene staar i input/. Skal vi bare rette en tittel eller en
    font, er det ingenting a rendre - og prepare er det ENESTE som kan gjore
    skade, fordi den kopierer raa maler over sidene.

    Forste utgave av guarden stoppet ogsa her og ba operatoren legge til
    --skip-prepare for hand. 1536, 1537 og 1538 sto samtidig og ventet pa det
    17.09.2026, og hele koeen stod stille sa lenge.
    """
    os.environ.setdefault("DP_GELATO_API_KEY", "test-ikke-en-ekte-nokkel")
    sys.path.insert(0, str(FLOW))
    import reprint_order

    comfy = sb.comfy_dir("C2")          # finnes ikke - ryddet bort
    order_input = sb.root / "books" / sb.slug / "orders" / "C2" / "input"
    order_input.mkdir(parents=True, exist_ok=True)

    keys = ("page00", "page01", "page02")
    pages = [{"page_key": k, "template_image": f"{k}(test).png"} for k in keys]
    info = {"comfy_dir": str(comfy), "input_dir": str(order_input),
            "book_slug": sb.slug, "config": {"pages": pages}}

    # Malene, slik de ligger i books/<slug>/base og rot-input.
    base = sb.root / "books" / sb.slug / "base"
    base.mkdir(parents=True, exist_ok=True)
    for k in keys:
        (base / f"{k}(test).png").write_bytes(b"MAL-" + k.encode())

    # Ferdige, personaliserte sider i input/ - forskjellige fra malene.
    for k in keys:
        (order_input / f"{k}(test).png").write_bytes(b"FACESWAPPET-" + k.encode())

    decision = reprint_order.assert_comfy_complete(info)
    assert decision["skip_prepare"] is True, decision
    assert "input/" in decision["reason"], decision

    # ... men en side som er byte-identisk med malen er IKKE personalisert,
    # og da skal den fortsatt stoppe. Det er hele 1528 i en enkelt fil.
    (order_input / "page01(test).png").write_bytes(b"MAL-page01")
    try:
        reprint_order.assert_comfy_complete(info)
    except SystemExit as exc:
        assert "page01" in str(exc), str(exc)
        assert "RAA MAL" in str(exc), str(exc)
        assert "page00" not in str(exc), "de to gode sidene skal ikke meldes"
    else:
        raise AssertionError("raa mal i input/ slapp igjennom")


@test
def test_raa_mal_stopper_pdf_bygget(sb: Sandbox) -> None:
    """Sluttsjekken paa input/ staar UANSETT hvilken vei bygget tok.

    `assert_comfy_complete` velger vei ut fra comfy/. Men et bygg kan ogsaa
    starte med `--skip-prepare` valgt for hand, eller prepare kan ha lagt
    igjen en raa mal. Ordre 1528 naadde Gelato med 12 raa maler fordi ingen
    stilte spoersmaalet til slutt - prepare advarer og fortsetter, og
    PDF-guarden teller sider og ikke innhold.

    Denne sjekken er derfor det siste som skjer foer teksten legges paa.
    """
    os.environ.setdefault("DP_GELATO_API_KEY", "test-ikke-en-ekte-nokkel")
    sys.path.insert(0, str(FLOW))
    import reprint_order

    keys = ("page00", "page01", "page02")
    order_input = sb.root / "books" / sb.slug / "orders" / "R1" / "input"
    order_input.mkdir(parents=True, exist_ok=True)
    base = sb.root / "books" / sb.slug / "base"
    base.mkdir(parents=True, exist_ok=True)
    for k in keys:
        (base / f"{k}(test).png").write_bytes(b"MAL-" + k.encode())
        (order_input / f"{k}(test).png").write_bytes(b"FACESWAPPET-" + k.encode())

    info = {"comfy_dir": str(sb.comfy_dir("R1")), "input_dir": str(order_input),
            "book_slug": sb.slug,
            "config": {"pages": [{"page_key": k, "template_image": f"{k}(test).png"}
                                 for k in keys]}}

    assert reprint_order.assert_input_personalized(info) == 3

    # En raa mal -> stopp, med sidenoekkelen og hvilken mal den er lik.
    (order_input / "page01(test).png").write_bytes(b"MAL-page01")
    try:
        reprint_order.assert_input_personalized(info)
    except SystemExit as exc:
        assert "page01" in str(exc), str(exc)
        assert "RAA MAL" in str(exc), str(exc)
    else:
        raise AssertionError("raa mal slapp gjennom sluttsjekken")

    # En side som mangler helt er like alvorlig.
    (order_input / "page01(test).png").write_bytes(b"FACESWAPPET-page01")
    (order_input / "page02(test).png").unlink()
    try:
        reprint_order.assert_input_personalized(info)
    except SystemExit as exc:
        assert "page02" in str(exc), str(exc)
    else:
        raise AssertionError("manglende side slapp gjennom sluttsjekken")


@test
def test_valgte_sider_verifiseres_paa_fila(sb: Sandbox) -> None:
    """Sidene operatoren godkjenner i Telegram maa ligge i input/.

    17.09.2026 ble 12 godkjente sider bygget bort i stillhet paa tre ordre
    (1536, 1537, 1538): kopieringen til input/ var betinget av at
    `skip_prepare` var satt, og meldingen sa likevel «bygget». En \u2705 som
    ikke er kontrollert er verre enn ingen melding - da tror du boka er
    riktig.

    Sjekken maa gjoeres paa FILA. At kopieringen returnerte en sti beviser
    ingenting om hva som endte opp i boka.
    """
    os.environ.setdefault("DP_GELATO_API_KEY", "test-ikke-en-ekte-nokkel")
    sys.path.insert(0, str(FLOW))
    import dp_bot
    import reprint_order

    # Filnavnet en side har i input/ staar i bokas prepare-script, ikke i
    # config.json. Uten den tabellen vet ingen hvilken fil page01 ER.
    script_dir = sb.root / "books" / sb.slug / "script"
    script_dir.mkdir(parents=True, exist_ok=True)
    (script_dir / f"prepare_order_{sb.slug}.py").write_text(
        'PAGE_TO_BASE_STEM = {"page01": "01(test)"}\n', encoding="utf-8")

    order_input = sb.root / "books" / sb.slug / "orders" / "V1" / "input"
    order_input.mkdir(parents=True, exist_ok=True)
    (order_input / "01(test).png").write_bytes(b"GAMMEL-SIDE")

    variants = sb.root / "output" / sb.slug / "orders" / "V1" / "variants"
    variants.mkdir(parents=True, exist_ok=True)
    valgt = variants / "page01-s123_00001_.png"
    valgt.write_bytes(b"DEN-OPERATOREN-VALGTE")

    info = {"input_dir": str(order_input), "book_slug": sb.slug,
            "config": {"prepareScript": "",
                       "pages": [{"page_key": "page01",
                                  "template_image": "01(test).png"}]}}
    session = {"order_id": "V1",
               "pages": {"page01": {"status": "approved", "chosen": str(valgt)}}}

    # input/ har fortsatt den gamle sida -> feil skal meldes.
    assert dp_bot.verify_chosen_pages(info, session) == ["page01"], \
        "et valgt bilde som ikke ligger i input/ maa oppdages"

    # Legg den valgte sida inn, slik et riktig bygg gjoer.
    reprint_order.commit_variant_to_input(info, "page01", str(valgt))
    assert dp_bot.verify_chosen_pages(info, session) == [], \
        "riktig bygget ordre skal ikke gi falsk alarm"

    # En side uten valg skal ikke sjekkes i det hele tatt.
    assert dp_bot.verify_chosen_pages(
        info, {"pages": {"page02": {"status": "pending", "chosen": None}}}) == []
    assert dp_bot.verify_chosen_pages(info, None) == []


@test
def test_eget_bilde_fra_telegram(sb: Sandbox) -> None:
    """«Last inn eget bilde»: bare 4096x2048 og 8192x4096, og det skal i boka.

    Foer maatte Claude bytte sider med ChatGPT-bilder for haand. Knappen
    maa avvise feil stoerrelse (et 3000x1500-bilde ville blitt trykt
    uskarpt), og et godkjent bilde maa ende i BAADE input/ og comfy/ - ellers
    blir det borte ved neste «Bygg fra comfy».
    """
    os.environ.setdefault("DP_GELATO_API_KEY", "test-ikke-en-ekte-nokkel")
    sys.path.insert(0, str(FLOW))
    import dp_bot
    from PIL import Image

    tmp = sb.root / "opplasting"
    tmp.mkdir(parents=True, exist_ok=True)

    feil = tmp / "feil.png"
    Image.new("RGB", (3000, 1500), "red").save(feil)
    try:
        dp_bot.prepare_upload(str(feil), str(tmp / "ut-feil.png"))
        raise AssertionError("3000x1500 skulle vaert avvist")
    except ValueError as error:
        assert "3000x1500" in str(error)
    assert not (tmp / "ut-feil.png").exists(), "avvist bilde skal ikke lagres"

    liten = tmp / "liten.jpg"
    Image.new("RGBA", (4096, 2048), "blue").convert("RGB").save(liten, "JPEG")
    ut = tmp / "ut.png"
    assert dp_bot.prepare_upload(str(liten), str(ut)) == (4096, 2048)
    with Image.open(ut) as img:
        assert img.size == (8192, 4096), "4096x2048 skal skaleres opp"
        assert img.format == "PNG" and img.mode == "RGB"

    script_dir = sb.root / "books" / sb.slug / "script"
    script_dir.mkdir(parents=True, exist_ok=True)
    (script_dir / f"prepare_order_{sb.slug}.py").write_text(
        'PAGE_TO_BASE_STEM = {"page01": "01(test)"}\n', encoding="utf-8")
    order_input = sb.root / "books" / sb.slug / "orders" / "U1" / "input"
    order_input.mkdir(parents=True, exist_ok=True)
    (order_input / "01(test).png").write_bytes(b"GAMMEL-SIDE")
    comfy = sb.comfy_dir("U1")
    comfy.mkdir(parents=True, exist_ok=True)
    (comfy / "page01_00001_.png").write_bytes(b"GAMMEL-COMFY")

    info = {"input_dir": str(order_input), "comfy_dir": str(comfy),
            "book_slug": sb.slug,
            "config": {"prepareScript": "",
                       "pages": [{"page_key": "page01",
                                  "template_image": "01(test).png"}]}}
    result = dp_bot.install_upload(info, "page01", str(ut))
    assert (order_input / "01(test).png").read_bytes() == ut.read_bytes()
    assert (comfy / "page01_00001_.png").read_bytes() == ut.read_bytes()
    assert open(result["backup"], "rb").read() == b"GAMMEL-SIDE", \
        "den gamle sida skal tas vare paa"

    # En side boka ikke kjenner skal rope, ikke late som den ble byttet.
    try:
        dp_bot.install_upload(info, "page07", str(ut))
        raise AssertionError("ukjent side skulle feilet")
    except RuntimeError as error:
        assert "IKKE" in str(error)
    assert not list(comfy.glob("page07_*")), "ingenting skal skrives foer sjekken"


@test
def test_prepare_scriptets_navn_gjettes_ikke(sb: Sandbox) -> None:
    """Stien til prepare-scriptet kommer fra config, aldri fra sluggen.

    Ti av boekene har et scriptnavn som ikke foelger sluggen:
    `dinosaurenes-dal` bruker `prepare_order_dinosaur.py`,
    `den-skjulte-styrken` bruker `prepare_order_styrken.py`. Gjettet vi
    navnet, ble tabellen tom - og da fant `commit_variant_to_input` ingen
    fil aa skrive til, saa sidene operatoeren hadde valgt ble ikke med.

    Det traff ordre 1534 (Oliver) 18.09.2026: aatte godkjente sider falt ut.
    Guarden fanget det foer opplasting, men aarsaken laa her.

    AST maa ogsaa taale at tabellen bygges i en LOEKKE - det gjoer
    `den-magiske-bursdagen-jente`, som skriver page00 som literal og de
    fjorten andre i en for-loekke. AST ser bare literalen.
    """
    sys.path.insert(0, str(FLOW))
    import page_files

    script_dir = sb.root / "books" / sb.slug / "script"
    script_dir.mkdir(parents=True, exist_ok=True)

    # Navnet har INGENTING med sluggen aa gjoere, og tabellen bygges delvis
    # i en loekke - noeyaktig de to formene som finnes i produksjon.
    odd = script_dir / "prepare_order_noe_helt_annet.py"
    odd.write_text(
        'PAGE_TO_BASE_STEM = {"page00": "forside(test)"}\n'
        'for _n in range(1, 3):\n'
        '    PAGE_TO_BASE_STEM[f"page{_n:02d}"] = f"{_n:02d}-right(test)"\n',
        encoding="utf-8")

    pages = [{"page_key": f"page{i:02d}", "template_image": f"{i:02d}(test).png"}
             for i in range(3)]
    info = {"book_slug": sb.slug, "input_dir": str(sb.root / "tom"),
            "config": {"prepareScript": str(odd), "pages": pages}}

    assert page_files.prepare_script(info) == str(odd), \
        "stien maa komme fra config"

    mapping = page_files.stem_map_for(info)
    for page in pages:
        assert page["page_key"] in mapping, \
            f"{page['page_key']} mangler - loekken ble ikke lest"
    assert mapping["page01"] == "01-right(test)", mapping

    # page_stem skal bruke tabellen, ikke template_image: for en delt side
    # er de to ULIKE, og template_image er da det gale svaret.
    assert page_files.page_stem(info, pages[1]) == "01-right(test)"

    # Uten prepareScript i config faller vi tilbake paa det sluggen tilsier -
    # men da SKAL page_stem bruke template_image, ikke finne opp noe.
    uten = {"book_slug": sb.slug, "input_dir": str(sb.root / "tom"),
            "config": {"pages": pages}}
    assert page_files.prepare_script(uten).endswith(
        f"prepare_order_{sb.slug}.py")
    assert page_files.page_stem(uten, pages[1]) == "01(test)"


class _NullLog:
    def info(self, *a, **k): pass
    def warn(self, *a, **k): pass
    def error(self, *a, **k): pass
    def bind(self, *a, **k): pass


@test
def test_workflow_per_side(sb: Sandbox) -> None:
    """En side kan ha sin egen workflow, og standarden er bokens.

    Hestestjernens forside trenger en variant som oppskalerer malen foer
    inpaint-croppen. Den varianten er MAALT daarligere paa sider der hodet er
    lite, saa den maa kunne gjelde én side - ikke hele boka.

    build_prompt leste alt workflow_api_file, men build_pages hardkodet
    bokens fil for hver side, saa noekkelen var doed. Testen holder den i
    live, og krever at en side UTEN noekkelen er uendret.
    """
    import books as B

    job = B.build_job(sb.payload("W1"))
    cfg = job["config"]
    cfg["pages"][0]["workflow_api_file"] = "spesial.json"
    pages = B.build_pages(job)

    assert pages[0]["workflow_api_file"] == "spesial.json", pages[0]
    for page in pages[1:]:
        assert page["workflow_api_file"] != "spesial.json", (
            f"{page['page_key']} arvet forsidens workflow. Overstyringen skal "
            f"gjelde ÉN side.")

    # Uten noekkelen: bokens egen fil, som foer endringen.
    del cfg["pages"][0]["workflow_api_file"]
    plain = B.build_pages(job)
    assert len({p["workflow_api_file"] for p in plain}) == 1, plain


@test
def test_bildehenting_taaler_kort_nettverksbrudd(sb: Sandbox) -> None:
    """fetch_child_image maa vente lenger enn et forbigaaende nettverksbrudd.

    17.09.2026 kl. 04:51 var TLS nede paa maskinen i ca. to minutter. Steget
    hadde 4 forsoek med 5 s grunnpause - 30 sekunder totalt - og drepte BEGGE
    boekene i ordre 1532, en betalt tobok-ordre. Feilen var over lenge foer
    noen saa den, og Telegram-varselet kom heller ikke fram, fordi det gikk
    over samme nedlagte HTTPS.

    Testen regner ut den faktiske ventetiden, ikke bare at feltene finnes.
    Kravet er minst 4 minutter: et vindu som daekker et nettverksbrudd av den
    typen som faktisk traff oss, med margin.
    """
    import pipeline as pipeline_mod

    steg = [s for s in pipeline_mod.by_name("full")
            if s.name == "fetch_child_image"]
    assert steg, "fetch_child_image finnes ikke i pipelinen"
    step = steg[0]
    cfg = step.settings()

    base = cfg["retry_delay_s"]
    attempts = cfg["retries"] + 1
    # Samme formel som runner._run_step bruker.
    total = sum(min(base * n, base * 6) for n in range(1, attempts))
    assert total >= 240, (
        f"fetch_child_image gir opp etter {total} s ({attempts} forsoek, "
        f"grunnpause {base} s). Et forbigaaende nettverksbrudd varte i to "
        f"minutter og drepte to betalte boeker - vinduet maa vaere minst 4 min.")

    # ComfyUI-stegene skal IKKE ha blitt tregere av dette: de snakker med en
    # tjeneste paa samme maskin, og en ordre skal ikke staa unoedig.
    for other in pipeline_mod.by_name("full"):
        if other.name in ("render_pages", "face_variants"):
            assert other.settings()["retry_delay_s"] <= 10, (
                f"{other.name} har grunnpause "
                f"{other.settings()['retry_delay_s']} s - den snakker med "
                f"ComfyUI lokalt og skal vente kort.")


@test
def test_systemexit_dreper_ikke_koeen(sb: Sandbox) -> None:
    """Et steg som kaster SystemExit skal feile JOBBEN, ikke traaden.

    17.09.2026 kastet gelato_api.verify_draft SystemExit for ordre 1532-b1.
    SystemExit arver BaseException, saa den gikk rett gjennom `except
    Exception` i _run_step, run_job OG _loop. Arbeidstraaden doede stille:
    jobben stod som "running" for alltid, ordre 1537 og 1532-b2 laa fast i
    koeen, og /api/status meldte worker_alive: false i 47 minutter uten at
    noe varslet.

    Testen kjoerer en pipeline med ETT steg som kaster SystemExit, og krever
    at runneren lever og at en jobb etterpaa fortsatt kjoerer.
    """
    import pipeline as pipeline_mod
    import runner as runner_mod

    store = fresh_store(sb, "sysexit")
    r = runner_mod.Runner(store)
    r.comfy = FakeComfy(sb, render_seconds=0)

    def sprenger(ctx):
        raise SystemExit("gelato_api gjorde dette")

    boom = (pipeline_mod.Step("sprenger", sprenger, "kaster SystemExit"),)

    sb.child_photo("S1")
    store.enqueue("S1", sb.payload("S1"))
    store.start("S1")
    try:
        res = r.run_job(runner_mod.QueuedJob("S1", sb.payload("S1")), pipeline=boom)
    except BaseException as exc:                     # noqa: BLE001
        raise AssertionError(
            f"run_job slapp {type(exc).__name__} ut til kalleren. I _loop "
            f"betyr det at arbeidstraaden doer og koeen stopper for godt.")

    assert res["status"] == "failed", res
    row = store.job("S1") or {}
    assert row.get("status") == "failed", (
        f"jobben staar som {row.get('status')!r}. En jobb som staar 'running' "
        f"for alltid blokkerer koeen og ser ut som en hengende ordre.")

    # Og det viktigste: runneren tar neste jobb.
    sb.child_photo("S2")
    store.enqueue("S2", sb.payload("S2"))
    store.start("S2")
    res2 = r.run_job(runner_mod.QueuedJob("S2", sb.payload("S2")),
                     pipeline=pipeline_mod.by_name("pages"))
    assert res2["status"] in ("done", "failed"), res2
    assert (store.job("S2") or {}).get("status") != "running", store.job("S2")


class _NoteLog:
    """Samler warn/info/error, saa en test kan se hva som ble sagt."""

    def __init__(self):
        self.lines: list = []

    def warn(self, m, **_k):
        self.lines.append(("warn", m))

    def info(self, m, **_k):
        self.lines.append(("info", m))

    def error(self, m, **_k):
        self.lines.append(("error", m))


@test
def test_nattbruddet_ventes_ut(sb: Sandbox) -> None:
    """Et nettbrudd paa 35 minutter skal ventes ut, ikke gis opp.

    Hver natt 04:30-05:05 er utgaaende HTTPS nede paa maskinen - i dp_bot.log
    hver dag siden 12.08.2026. Forrige fiks (5 min retry) bygde paa at bruddet
    varte i to minutter. Det varer i 35, og ordre 1532 doede i det.
    """
    import net

    calls = {"probe": 0}
    slept: list = []

    def probe(_url):
        calls["probe"] += 1
        return calls["probe"] > 70            # 70 x 30 s = 35 min nede

    log = _NoteLog()
    waited = net.wait_for_internet("https://x.invalid/a?b=c", log,
                                   probe=probe, sleep=slept.append)
    assert waited == 35 * 60, waited
    assert len(slept) == 70, len(slept)
    # Én advarsel naar det starter, ikke én hvert 30. sekund.
    assert sum(1 for k, _ in log.lines if k == "warn") == 1, log.lines

    # Gir opp etter 45 min, med en feil som sier det.
    try:
        net.wait_for_internet("https://x.invalid/", probe=lambda _u: False,
                              sleep=lambda _s: None)
    except RuntimeError as exc:
        assert "nede" in str(exc), exc
    else:
        raise AssertionError("wait_for_internet ga aldri opp")

    # En operatoer som avbryter, skal ikke maatte vente 45 minutter.
    try:
        net.wait_for_internet("https://x.invalid/", probe=lambda _u: False,
                              cancelled=lambda: True, sleep=lambda _s: None)
    except RuntimeError as exc:
        assert "avbrutt" in str(exc), exc
    else:
        raise AssertionError("avbrudd ble ikke respektert")

    # Et HTTP-svar - ogsaa en feil - betyr at nettet virker.
    import http.server
    import threading as _t

    class _H(http.server.BaseHTTPRequestHandler):
        def do_HEAD(self):
            self.send_response(405)
            self.end_headers()

        def log_message(self, *_a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), _H)
    _t.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        assert net.internet_up(f"http://127.0.0.1:{srv.server_port}/x.jpg")
    finally:
        srv.shutdown()
    assert not net.internet_up("http://127.0.0.1:9/", timeout=2)


@test
def test_barnebilde_404_stopper_med_en_gang(sb: Sandbox) -> None:
    """Serveren sier nei -> JobError med en gang, ikke 45 min venting.

    Ordre 1546 (18.09.2026): WordPress svarte 404 paa barnebildet, og gjorde
    det fortsatt sju timer senere. Med ventingen paa nettet ville et nytt
    forsoek holdt hele koeen - uten aa kunne hjelpe.
    """
    import http.server
    import threading as _t
    import steps
    from books import JobError

    class _H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(404)
            self.end_headers()

        do_HEAD = do_GET

        def log_message(self, *_a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), _H)
    _t.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        ctx = steps.Context(job_key="B404", payload={}, log=_NoteLog())
        ctx.job = {"image_url": f"http://127.0.0.1:{srv.server_port}/b.jpg"}
        try:
            steps.fetch_child_image(ctx)
        except JobError as exc:
            assert "404" in str(exc) and "input/B404.jpg" in str(exc), exc
        else:
            raise AssertionError("404 ga ikke JobError")
    finally:
        srv.shutdown()
    assert not (sb.root / "input" / "B404.jpg").exists()
    assert not (sb.root / "input" / "B404.jpg.part").exists()


@test
def test_varsel_som_ikke_kom_fram_sendes_senere(sb: Sandbox) -> None:
    """Et Telegram-varsel under nattbruddet skal fram, merket som forsinket.

    Ordre 1532 doede 04:51 - og varselet om det gikk over det samme nedlagte
    nettet. Operatoeren fikk vite det fem timer senere, fra panelet.
    """
    import urllib.error
    import notify
    import dp_secrets

    posted: list = []
    down = {"now": True}

    def fake_post(_token, _chat, text, _timeout):
        if down["now"]:
            raise urllib.error.URLError("[Errno 2] No such file or directory")
        posted.append(text)
        return {"sent": True, "http": 200}

    orig = (notify._post, notify.OUTBOX, dp_secrets.get)
    notify._post = fake_post
    notify.OUTBOX = sb.root / "state" / "notify_outbox"
    dp_secrets.get = lambda k, *a, **kw: {"worker_bot_token": "t",
                                         "worker_chat_id": 1}.get(k)
    try:
        r = notify.send("ORDRE X FEILET")
        assert r["sent"] is False and r["queued"] is True, r
        assert len(list(notify.OUTBOX.glob("*.json"))) == 1

        # Fortsatt nede: vaktmesteren proever, ingenting forsvinner.
        assert notify.flush() == {"sent": 0, "waiting": 1}

        down["now"] = False
        r = notify.send("neste varsel")
        assert r["sent"] is True, r
        assert posted[0] == "neste varsel", posted
        assert "Forsinket" in posted[1] and "ORDRE X FEILET" in posted[1], posted
        assert not list(notify.OUTBOX.glob("*.json")), "utboksen ble ikke toemt"
    finally:
        notify._post, notify.OUTBOX, dp_secrets.get = orig


@test
def test_duplikat_etterlater_ingen_tagg(sb: Sandbox) -> None:
    """Et duplikat ackes og glemmes - taggen skal ikke bli liggende.

    Duplikatet av 1536 (17.09.2026 11:38) ble acket, men taggen ble liggende i
    Consumer._tags. /api/status viste `unacked: 1` med tom koe i et doegn, og
    en senere ack paa samme job_key ville truffet en tagg som ikke lenger
    gjaldt.
    """
    import threading as _t
    import types
    import mq as mq_mod

    store = fresh_store(sb, "duptag")
    store.enqueue("T1", sb.payload("T1"))
    store.start("T1")
    store.finish("T1", "done")

    submitted: list = []
    c = mq_mod.Consumer.__new__(mq_mod.Consumer)
    c.store = store
    c.runner = types.SimpleNamespace(submit=submitted.append, depth=lambda: 0)
    c.log = _NoteLog()
    c._tags = {}
    c._tags_lock = _t.Lock()
    c._connection = c._channel = None          # _ack blir en no-op

    method = types.SimpleNamespace(delivery_tag=7, redelivered=True)
    c._handle(method, json.dumps(sb.payload("T1")).encode())
    assert not submitted, "en ferdig jobb ble kjoert paa nytt"
    assert c._tags == {}, f"duplikatet etterlot en tagg: {c._tags}"

    # En ny jobb skal fortsatt huskes, ellers blir den aldri acket.
    c._handle(types.SimpleNamespace(delivery_tag=8, redelivered=False),
              json.dumps(sb.payload("T2")).encode())
    assert c._tags == {"T2": 8}, c._tags
    assert len(submitted) == 1


@test
def test_glad_variant_brukes_bare_der_config_sier_det(sb: Sandbox) -> None:
    """Glad-varianten brukes paa siden som ber om den - og ingen andre.

    18.09.2026: fotballstjernen fikk en glad variant til side 14, i tillegg
    til den triste paa side 04. Uttrykket kommer fra config, og en side som
    sier `smil` uten at noen fil finnes, faar originalbildet som foer.
    """
    import books as B

    job = B.build_job(sb.payload("G1"))
    face = job["face_filename"]
    stem = face.rsplit(".", 1)[0]
    cfg = job["config"]
    cfg["pages"][0]["face_expression"] = "glad"
    cfg["pages"][1]["face_expression"] = "smil"
    (sb.root / "input" / f"{stem}-glad.jpg").write_bytes(b"\xff\xd8\xff" + b"0" * 32)
    try:
        pages = {p["page_key"]: p for p in B.build_pages(job)}
    finally:
        (sb.root / "input" / f"{stem}-glad.jpg").unlink()

    assert pages["page00"]["face_image"] == f"{stem}-glad.jpg", pages["page00"]
    assert pages["page01"]["face_image"] == face, pages["page01"]
    assert pages["page02"]["face_image"] == face, pages["page02"]


@test
def test_variantfeil_roper(sb: Sandbox) -> None:
    """En variant som feiler, skal gi en ADVARSEL-linje - ikke stillhet.

    Scriptet skrev "FEILET (...)", og face_variants-steget leter bare etter
    "ADVARSEL" og "MERK:". Feilen var usynlig i jobbloggen og panelet, og
    side 04 i fotballstjernen fikk originalbildet uten at noen fikk vite det.
    """
    import contextlib
    import io as _io
    fv = str(FLOW / "face_variants")
    if fv not in sys.path:
        sys.path.insert(0, fv)
    import build_variants as BV

    book = sb.root / "books" / sb.slug / "config.json"
    orig_cfg = book.read_text(encoding="utf-8")
    cfg = json.loads(orig_cfg)
    cfg["pages"][0]["face_expression"] = "trist"
    cfg["pages"][1]["face_expression"] = "finnes-ikke"
    book.write_text(json.dumps(cfg), encoding="utf-8")
    sb.child_photo("V9")

    def boom(_graph):
        raise RuntimeError("ComfyUI svarte ikke")

    saved = (BV.BOOKS, BV.BFV.submit, BV.BFV.INPUT_DIR, BV.BOOKS_DIR,
             BV.BFV.normalize_orientation, sys.argv)
    BV.BOOKS = {sb.slug}
    BV.BFV.submit = boom
    BV.BFV.INPUT_DIR = str(sb.root / "input")
    BV.BOOKS_DIR = sb.root / "books"
    BV.BFV.normalize_orientation = lambda _p: None
    sys.argv = ["build_variants.py", "V9", "--book", sb.slug]
    out = _io.StringIO()
    try:
        from PIL import Image
        Image.new("RGB", (8, 8)).save(sb.root / "input" / "V9.jpg")
        with contextlib.redirect_stdout(out):
            code = BV.main()
    finally:
        (BV.BOOKS, BV.BFV.submit, BV.BFV.INPUT_DIR, BV.BOOKS_DIR,
         BV.BFV.normalize_orientation, sys.argv) = saved
        book.write_text(orig_cfg, encoding="utf-8")

    text = out.getvalue()
    assert code == 0, "scriptet skal aldri stoppe en ordre"
    warns = [l for l in text.splitlines() if "ADVARSEL" in l]
    assert any("trist" in l and "ComfyUI svarte ikke" in l for l in warns), text
    assert any("finnes-ikke" in l for l in warns), text

    # En bok som ikke er med, skal ikke advare om noe - det er forventet.
    saved_argv = sys.argv
    sys.argv = ["build_variants.py", "V9", "--book", "dyreparken"]
    out = _io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            BV.main()
    finally:
        sys.argv = saved_argv
    assert "ADVARSEL" not in out.getvalue(), out.getvalue()


@test
def test_bare_fotballstjernen_har_varianter(sb: Sandbox) -> None:
    """Ingen andre boeker skal bruke variantsystemet ennaa (18.09.2026).

    Og fotballstjernen skal be om noeyaktig trist paa side 04 og glad paa
    side 14 - ellers vil scriptet lage noe ingen side bruker, eller en side
    vente paa noe som aldri lages.
    """
    fv = str(FLOW / "face_variants")
    if fv not in sys.path:
        sys.path.insert(0, fv)
    import build_variants as BV

    assert BV.BOOKS == {"fotballstjernen"}, BV.BOOKS
    real = FLOW.parent / "books" / "fotballstjernen" / "config.json"
    cfg = json.loads(real.read_text(encoding="utf-8"))
    got = {p["page_key"]: p.get("face_expression", "noytral")
           for p in cfg["pages"] if p.get("face_expression", "noytral") != "noytral"}
    assert got == {"page04": "trist", "page14": "glad"}, got
    for expr in set(got.values()):
        assert (FLOW / "face_variants" / "workflows" / f"{expr}.json").is_file(), expr


@test
def test_ombygging_fra_telegram_beholder_uttrykket(sb: Sandbox) -> None:
    """regen_page og rerun_order_comfy skal velge samme ansikt som workeren.

    Foer 18.09.2026 brukte begge alltid originalbildet. En side 04 i
    fotballstjernen som ble bygget om fra Telegram, mistet det triste ansiktet
    uten et ord.
    """
    import contextlib
    import importlib.util
    import io as _io

    spec = importlib.util.spec_from_file_location(
        "regen_page_test", str(FLOW / "regen_page.py"))
    regen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(regen)

    (sb.root / "input" / "R1-trist.jpg").write_bytes(b"\xff\xd8\xff")
    info = {"face_image": "R1.jpg", "book_slug": "fotballstjernen"}
    try:
        assert regen.page_face(info, {"face_expression": "trist"}) == "R1-trist.jpg"
        assert regen.page_face(info, {"face_expression": "noytral"}) == "R1.jpg"
        # Operatoerens eget valg vinner.
        assert regen.page_face(info, {"face_expression": "trist"}, "ny.jpg") == "ny.jpg"
        # Mangler glad i en bok som skal ha den: originalen, men det SIES.
        out = _io.StringIO()
        with contextlib.redirect_stdout(out):
            got = regen.page_face(info, {"page_key": "page14",
                                         "face_expression": "glad"})
        assert got == "R1.jpg", got
        assert "ADVARSEL" in out.getvalue(), out.getvalue()
        # I en bok uten varianter er det forventet - ingen advarsel.
        out = _io.StringIO()
        with contextlib.redirect_stdout(out):
            regen.page_face({"face_image": "R1.jpg", "book_slug": "dyreparken"},
                            {"face_expression": "smil"})
        assert "ADVARSEL" not in out.getvalue(), out.getvalue()
    finally:
        (sb.root / "input" / "R1-trist.jpg").unlink()


@test
def test_fotballstjernen_har_ingen_side_15(sb: Sandbox) -> None:
    """Side 15 (gutten med pokalen) er borte - fra ALLE tre stedene.

    Fortsett-eventyret-siden erstattet den paa hver ordre, saa den ble rendret
    og aldri trykt. Staar den igjen i prepare- eller tekstscriptet uten aa
    staa i config, blir det en ADVARSEL paa hver bygging - og en advarsel som
    alltid staar paa, skjulte de tolv ekte i ordre 1528.
    """
    real = FLOW.parent / "books" / "fotballstjernen"
    cfg = json.loads((real / "config.json").read_text(encoding="utf-8"))
    keys = [p["page_key"] for p in cfg["pages"]]
    assert "page15" not in keys and keys[-1] == "page14", keys
    prep = (real / "script" / "prepare_order_fotballstjernen.py").read_text(encoding="utf-8")
    assert '"page15"' not in prep, "prepare-scriptet har fortsatt page15"
    for lang in ("nb", "nn", "sv", "en-US", "en-GB"):
        text = (FLOW / "text" / lang / f"fotballstjernen-text-{lang}.py").read_text(encoding="utf-8")
        assert "15(fotballstjernen)" not in text, f"{lang}: tekstscriptet har fortsatt side 15"


def main() -> int:
    sandbox = Sandbox()
    # Importene maa skje ETTER at DP_ROOT er satt.
    sys.path.insert(0, str(FLOW))
    sys.path.insert(0, str(WORKER))

    # Sandkassa kjorer "pages", uansett hva som er aktivt i produksjon.
    #
    # Disse testene handler om SIDE-LOEKKA - serialisering, idempotens,
    # avbrudd, varsling. Etter at fase 5 gjorde "full" aktiv (16.09.2026)
    # ville Runner.start() ogsaa dratt gjenopptatte jobber gjennom Drive- og
    # Gelato-stegene, som krever ekte infrastruktur og ekte penger. Da tester
    # de noe annet enn det de heter.
    #
    # De enkelte kallene sier `pipeline="pages"` selv; dette daekker veien
    # gjennom Runner.start(), der jobber legges paa koen uten et valg.
    import pipeline as pipeline_mod
    pipeline_mod.ACTIVE = "pages"

    names = [name for name, _, _ in _results]
    _results.clear()
    module = sys.modules[__name__]
    failed = 0
    try:
        for name in names:
            fn = getattr(module, name)
            try:
                fn(sandbox)
                print(f"  OK    {name}")
            except AssertionError as exc:
                failed += 1
                print(f"  FEIL  {name}\n        {exc}")
            except Exception:                        # noqa: BLE001
                failed += 1
                print(f"  KRASJ {name}")
                print("        " + traceback.format_exc().replace("\n", "\n        "))
    finally:
        sandbox.close()
    print(f"\n{len(names) - failed}/{len(names)} tester gikk gjennom")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
