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
        r.submit(runner_mod.QueuedJob(key, sb.payload(key)))

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
    first = r.run_job(runner_mod.QueuedJob("I1", sb.payload("I1")))
    assert first["status"] == "done", first
    assert len(fake.rendered) == 3, fake.rendered

    # Kjoer igjen. Ingen nye sider skal lages.
    store.retry("I1")
    second = r.run_job(runner_mod.QueuedJob("I1", sb.payload("I1")))
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
    res = r.run_job(runner_mod.QueuedJob("X2", sb.payload("X2")))
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
    res = r.run_job(runner_mod.QueuedJob("U1", payload))

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
    assert names[0] == "validate_job"
    assert "render_pages" in names
    by_name = {s["name"]: s for s in described["steps"]}
    # render_pages har 14 timers timeout, ikke step_defaults sin ene time.
    assert by_name["render_pages"]["timeout_s"] == 14 * 3600, by_name["render_pages"]
    assert by_name["render_pages"]["checkpoint"] is True
    assert by_name["face_variants"]["optional"] is True
    assert by_name["fetch_child_image"]["retries"] == 3
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
    res = r.run_job(runner_mod.QueuedJob("K1", sb.payload("K1")))
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

    # Standarden er uendret, og et ukjent navn er en feil - ikke et stille
    # fall tilbake til den aktive.
    assert pipeline_mod.ACTIVE == "pages", pipeline_mod.ACTIVE
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


def main() -> int:
    sandbox = Sandbox()
    # Importene maa skje ETTER at DP_ROOT er satt.
    sys.path.insert(0, str(FLOW))
    sys.path.insert(0, str(WORKER))

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
