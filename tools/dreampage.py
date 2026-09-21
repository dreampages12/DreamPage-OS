# -*- coding: utf-8 -*-
"""Supervisoren for Linux. Samme kommandoer som dreampage.ps1 paa Windows.

    ./dreampage.sh up        start ComfyUI, flow, mockup, bot, tunnel
    ./dreampage.sh down      stopp alt vi eier (ikke midt i en ordre)
    ./dreampage.sh status    hva lever, hva staar i koen, hvor er ordrene
    ./dreampage.sh restart
    ./dreampage.sh logs      foelg flow-loggen
    ./dreampage.sh test      alle testene + check_assets
    ./dreampage.sh ensure    vaktmesteren (systemd-timer, hvert 5. minutt)
    ./dreampage.sh mode      book eller preview

HVORFOR PYTHON OG IKKE BASH:

Windows-supervisoren er PowerShell fordi Windows ikke har noe bedre. Paa
Linux var valget mellom bash og Python, og bash ville betydd en TREDJE
utgave av den samme logikken - helsesjekker, ventetider, "nekter aa stoppe
midt i en ordre" - i et spraak uten tester. Denne fila kan importeres og
testes, og den leser den samme `config/flow.json` som resten.

HVA SOM IKKE ER HER:

Vaktmesteren er `ensure`, akkurat som paa Windows, men den kalles av en
systemd-timer i stedet for Task Scheduler. Unit-filene ligger i
`deploy/systemd/`. Se docs/SETUP-LINUX.md.

Tjenestelista MAA stemme med `$SERVICES` i dreampage.ps1. To supervisorer
som er uenige om hvilke tjenester som finnes, er verre enn én som er feil:
da avhenger svaret paa "lever alt?" av hvilken maskin du spoer.
`test_supervisorene_er_enige` i flow/worker/tests/test_flow.py holder dem
sammen.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "flow"))
sys.path.insert(0, str(ROOT / "flow" / "worker"))

import dp_platform  # noqa: E402
from paths import CONFIG, IMAGE, STATE  # noqa: E402

LOGDIR = STATE / "log"


# ---------------------------------------------------------------------------
# Smaating
# ---------------------------------------------------------------------------
def say(msg: str = "") -> None:
    print(msg, flush=True)


def head(msg: str) -> None:
    print(f"\n{msg}", flush=True)


def flow_conf() -> dict:
    try:
        with open(CONFIG / "flow.json", encoding="utf-8-sig") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def comfy_url() -> str:
    """Adressen staar ETT sted: config/flow.json -> comfy.url.

    Samme regel som paa Windows. To steder med samme port betyr at
    supervisoren starter én instans og workeren snakker med en annen.
    """
    return str((flow_conf().get("comfy") or {}).get("url")
               or "http://127.0.0.1:8188")


def comfy_port() -> int:
    match = re.search(r":(\d+)", comfy_url())
    return int(match.group(1)) if match else 8188


def api_token() -> str | None:
    try:
        with open(CONFIG / "api.json", encoding="utf-8-sig") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    tokens = data.get("tokens")
    if isinstance(tokens, dict) and tokens:
        return next(iter(tokens))
    return data.get("token")


def get_json(url: str, token: str | None = None, timeout: float = 8):
    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return json.loads(res.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, OSError, ValueError):
        return None


def port_listening(port: int | None) -> bool:
    if not port:
        return False
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1.0)
        return sock.connect_ex(("127.0.0.1", int(port))) == 0


def pids_matching(pattern: str) -> list[int]:
    """PID-ene med en kommandolinje som matcher.

    Leser /proc direkte i stedet for aa kalle pgrep: da trenger en ny Linux-
    maskin ikke procps installert for at vaktmesteren skal virke, og vi
    slipper aa tolke exitkoder fra et eksternt verktoey.
    """
    found = []
    rx = re.compile(pattern)
    for entry in Path("/proc").iterdir() if Path("/proc").is_dir() else []:
        if not entry.name.isdigit():
            continue
        try:
            cmdline = (entry / "cmdline").read_bytes().replace(b"\0", b" ")
        except OSError:
            continue
        if rx.search(cmdline.decode("utf-8", "replace")):
            found.append(int(entry.name))
    return found


def spawn(argv: list[str], name: str, cwd: Path | None = None) -> None:
    """Start en tjeneste loesrevet fra dette skallet.

    `start_new_session` gjoer prosessen til sin egen prosessgruppeleder, saa
    den ikke faar SIGHUP naar terminalen lukkes. Uten det doer alt sammen med
    SSH-oekta som startet det - og en server som stopper naar noen logger av
    er ikke en server.

    Stderr tas VARE PAA, ikke toemmes: ble prosessen drept midt i en jobb, er
    tracebacken der det eneste som forklarer hvorfor. Windows-siden lærte det
    05.09.2026.
    """
    LOGDIR.mkdir(parents=True, exist_ok=True)
    out = LOGDIR / f"{name}.out.log"
    err = LOGDIR / f"{name}.err.log"
    if err.is_file() and err.stat().st_size > 0:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        err.rename(err.with_name(f"{err.name}.{stamp}"))
        old = sorted(LOGDIR.glob(f"{err.name}.*"),
                     key=lambda p: p.stat().st_mtime, reverse=True)
        for path in old[10:]:
            path.unlink(missing_ok=True)
    with open(out, "a", encoding="utf-8") as fo, open(err, "w", encoding="utf-8") as fe:
        subprocess.Popen(argv, cwd=str(cwd or ROOT), stdout=fo, stderr=fe,
                         stdin=subprocess.DEVNULL, start_new_session=True)


# ---------------------------------------------------------------------------
# Tjenestene, i oppstartsrekkefoelge
#
# ComfyUI foerst: flow sjekker den ved oppstart, og en worker som starter mot
# en doed ComfyUI logger bare feil i noen sekunder.
#
# `modes` er hvilke servermoduser tjenesten hoerer hjemme i. dp_bot og mockup
# er BOOK-bare: to Telegram-pollere paa samme token spiser hverandres
# oppdateringer, og en preview-PC har ingen ordre aa lage produktbilder av.
# Samme tabell som $SERVICES i dreampage.ps1 - se docstringen oeverst.
# ---------------------------------------------------------------------------
def comfy_argv() -> list[str]:
    """ComfyUI med VAARE mapper.

    --output/--input/--models utenfor DreamPage-image er selve grunnen til at
    mappa aldri maa redigeres: vi endrer ComfyUI ved aa gi den andre stier,
    ikke ved aa endre filene dens.
    """
    argv = [
        dp_platform.python_bin(), str(IMAGE / "main.py"),
        "--listen", "0.0.0.0", "--port", str(comfy_port()),
        "--disable-auto-launch",
        "--output-directory", str(ROOT / "output"),
        "--input-directory", str(ROOT / "input"),
        "--temp-directory", str(ROOT / "tmp" / "comfy"),
    ]
    extra = CONFIG / "extra_model_paths.yaml"
    if extra.is_file():
        argv += ["--extra-model-paths-config", str(extra)]
    frontend = ROOT / "frontend"
    if frontend.is_dir():
        # Nyeste versjonsmappe. Windows-siden pinner versjonen i scriptet;
        # her leses den av disk, slik at en ny maskin ikke trenger en
        # redigering for aa faa med seg frontenden den faktisk lastet ned.
        for candidate in sorted(frontend.iterdir(), reverse=True):
            static = candidate / "comfyui_frontend_package" / "static"
            if (static / "index.html").is_file():
                argv += ["--front-end-root", str(static)]
                break
    return argv


def comfy_is_ours() -> bool:
    """Svarer VAAR ComfyUI paa porten - fra DreamPage-image, med modeller?

    Ikke "svarer noe paa porten". 16.09.2026 svarte en ComfyUI fra en annen
    mappe, uten modeller, og en naiv helsesjekk sa OK mens ingen bokside
    kunne bygges.
    """
    stats = get_json(f"{comfy_url()}/system_stats", None, 15)
    if not stats:
        return False
    argv = " ".join(str(a) for a in (stats.get("system", {}).get("argv") or []))
    if not argv:
        return False
    if "DreamPage-image" not in argv:
        say(f"  ADVARSEL: ComfyUI paa {comfy_url()} kjoerer IKKE fra {IMAGE}")
        say(f"            argv: {argv}")
        say("            Den ser sannsynligvis ingen modeller. Stopp den.")
        return False
    return True


def flow_healthy() -> bool:
    """8766 er status-lytteren, og den kjoerer i en TRAAD inne i flow-
    prosessen. Doer traaden, lever prosessen videre og 8765 svarer fint - da
    er tunnelen utenfor nede uten at noe annet merker det. Derfor begge."""
    token = api_token()
    if not token:
        return port_listening(8765) and port_listening(8766)
    return (get_json("http://127.0.0.1:8765/api/health", token) is not None
            and port_listening(8766))


SERVICES = [
    {
        "name": "comfyui",
        "modes": ("book", "preview"),
        "port": None,                      # settes under (comfy_port())
        "match": r"DreamPage-image[/\\]main\.py",
        "start": lambda: spawn(comfy_argv(), "comfyui", cwd=IMAGE),
        "health": comfy_is_ours,
        "wait": 300,
    },
    {
        "name": "flow",
        "modes": ("book", "preview"),
        "port": 8765,
        "match": r"worker[/\\]main\.py",
        "start": lambda: spawn(
            [dp_platform.python_bin(), str(ROOT / "flow" / "worker" / "main.py")],
            "flow"),
        "health": flow_healthy,
        "wait": 60,
    },
    {
        "name": "mockup",
        "modes": ("book",),
        "port": 8790,
        "match": r"dp-mockup-server",
        "start": lambda: spawn(["node", "src/index.js"], "mockup",
                               cwd=ROOT / "server" / "dp-mockup-server"),
        "health": lambda: port_listening(8790),
        "wait": 30,
    },
    {
        "name": "dp_bot",
        "modes": ("book",),
        "port": None,
        "match": r"dp_bot\.py",
        # To pollere paa samme token spiser hverandres oppdateringer, saa vi
        # starter BARE naar ingen kjoerer. Det er hele vaktmesterlogikken.
        "start": lambda: (None if pids_matching(r"dp_bot\.py")
                          else spawn([dp_platform.python_bin(),
                                      str(ROOT / "flow" / "dp_bot.py")], "dp_bot")),
        "health": lambda: bool(pids_matching(r"dp_bot\.py")),
        "wait": 30,
    },
    {
        "name": "tunnel-status",
        "modes": ("book", "preview"),
        "port": None,
        "match": r"dp-01-status",
        "start": lambda: _start_tunnel(),
        "health": lambda: bool(pids_matching(r"dp-01-status")),
        "wait": 45,
    },
]


def _start_tunnel() -> None:
    """Vaar EGEN named tunnel: eksponerer BARE /api/status*.

    cloudflared finnes paa PATH paa en Linux-server (deb-pakken legger den i
    /usr/local/bin). Windows-siden peker paa en fil i Downloads fordi den ble
    lastet ned for haand.
    """
    binary = dp_platform.which("cloudflared")
    config = ROOT / "tunnel" / "config.yml"
    if not binary:
        say("  cloudflared finnes ikke paa PATH - se tunnel/README.md")
        return
    if not config.is_file():
        say(f"  {config} finnes ikke - hopper over tunnelen")
        return
    spawn([binary, "tunnel", "--config", str(config), "run", "dp-01-status"],
          "tunnel")


def services_for_mode() -> list[dict]:
    """Tjenestene som hoerer hjemme i DENNE modusen."""
    import config as flow_config
    try:
        mode = flow_config.mode()
    except ValueError:
        mode = "book"
    out = []
    for svc in SERVICES:
        if mode in svc["modes"]:
            item = dict(svc)
            if item["name"] == "comfyui":
                item["port"] = comfy_port()
            out.append(item)
    return out


# ---------------------------------------------------------------------------
# Kommandoene
# ---------------------------------------------------------------------------
def show_mode() -> dict | None:
    head("servermodus")
    try:
        import config as flow_config
        import pipeline as pipeline_mod
        info = {"mode": flow_config.mode(),
                "queue": flow_config.queue().get("name"),
                "pipeline": pipeline_mod.active_name(),
                "env": os.environ.get("DP_MODE")}
    except Exception as exc:                            # noqa: BLE001
        say(f"  kunne ikke lese modusen: {exc}")
        return None
    say(f"  {info['mode'].upper()}   koe={info['queue']}   "
        f"pipeline={info['pipeline']}")
    if info["env"]:
        say(f"  MERK: DP_MODE={info['env']} i miljoeet overstyrer fila")
    return info


def busy_reason() -> str | None:
    """Kjoerer det en ordre akkurat naa?"""
    health = get_json("http://127.0.0.1:8765/api/health", api_token())
    if health and (health.get("worker") or {}).get("running"):
        worker = health["worker"]
        return (f"flow jobber med {worker['running']} "
                f"(steg: {worker.get('running_step')})")
    queue = get_json(f"{comfy_url()}/queue")
    if queue:
        n = len(queue.get("queue_running") or []) + len(queue.get("queue_pending") or [])
        if n:
            return f"ComfyUI har {n} jobber i koeen"
    return None


def cmd_up(args) -> int:
    head("DreamPage OS: up")
    show_mode()
    if not IMAGE.is_dir():
        say(f"  ComfyUI mangler: {IMAGE}")
        return 1
    if not args.skip_models:
        models = ROOT / "tools" / "models.py"
        if (ROOT / "models" / "manifest.json").is_file() and models.is_file():
            subprocess.run([dp_platform.python_bin(), str(models), "check"])

    for svc in services_for_mode():
        head(f"start: {svc['name']}")
        if svc["health"]():
            say("  lever allerede")
            continue
        svc["start"]()
        deadline = time.monotonic() + svc["wait"]
        ok = False
        while time.monotonic() < deadline:
            time.sleep(3)
            if svc["health"]():
                ok = True
                break
        say("  OK" if ok else f"  svarte ikke innen {svc['wait']} s")

    head("RabbitMQ")
    health = get_json("http://127.0.0.1:8765/api/health", api_token(), 20)
    if not health:
        say("  flow-API-et svarer ikke - kan ikke sjekke koen")
    else:
        mq = health.get("rabbitmq") or {}
        if mq.get("connected"):
            say(f"  tilkoblet koen '{mq.get('queue')}', "
                f"prefetch={mq.get('prefetch')}, "
                f"{mq.get('broker_depth')} melding(er) venter")
        else:
            say(f"  IKKE tilkoblet: {mq.get('last_error')}")
    return cmd_status(args)


def cmd_down(args) -> int:
    head("DreamPage OS: down")
    busy = busy_reason()
    if busy and not args.force:
        say(f"  NEKTER: {busy}")
        say("  Vent til ordren er ferdig, eller bruk --force.")
        say("  En ordre som drepes midt i side-loekka maa kjoeres om - sidene")
        say("  som alt ligger paa disk gjenbrukes, saa det koster bare tid.")
        return 1
    if busy:
        say(f"  --force: stopper selv om {busy}")

    # Omvendt rekkefoelge av up: flow ned FOER ComfyUI, saa ingen ny jobb
    # starter mot en ComfyUI paa vei ned.
    order = ("dp_bot", "mockup", "flow", "comfyui")
    by_name = {s["name"]: s for s in SERVICES}
    for name in order:
        svc = by_name.get(name)
        if not svc:
            continue
        pids = pids_matching(svc["match"])
        if not pids:
            say(f"  {name} : kjoerer ikke")
            continue
        for pid in pids:
            say(f"  {name} : stopper pid {pid}")
            try:
                # SIGTERM, ikke SIGKILL: flow fanger den og lar jobben som
                # kjoerer bli ferdig med steget sitt foer den legger fra seg
                # RabbitMQ-meldingen. Se main.shutdown().
                os.kill(pid, signal.SIGTERM)
            except OSError as exc:
                say(f"    kunne ikke stoppe: {exc}")
    say("  tunnelen blir staaende (den eksponerer bare /api/status*)")
    return 0


def cmd_status(args) -> int:
    show_mode()
    head("tjenester")
    for svc in services_for_mode():
        pids = pids_matching(svc["match"])
        alive = False
        try:
            alive = bool(svc["health"]())
        except Exception:                               # noqa: BLE001
            alive = False
        extra = []
        if pids:
            extra.append(f"pid {pids[0]}")
        if svc["port"]:
            extra.append(f"port {svc['port']}")
        say(f"  {'OPP ' if alive else 'NED '} {svc['name']:<14} {'  '.join(extra)}")

    token = api_token()
    if not token:
        say("\n  config/api.json mangler - kan ikke spoerre flow om koen")
        return 0
    health = get_json("http://127.0.0.1:8765/api/health", token)
    if not health:
        say("\n  flow-API-et svarer ikke")
        return 0

    head("jobber")
    jobs = health.get("jobs") or {}
    say("  " + "   ".join(f"{k} {jobs.get(k, 0)}" for k in
                          ("pending", "running", "done", "failed", "cancelled")))
    worker = health.get("worker") or {}
    if worker.get("running"):
        say(f"  naa: {worker['running']}  steg={worker.get('running_step')}  "
            f"{worker.get('running_seconds')} s")
    if jobs.get("failed"):
        failed = get_json("http://127.0.0.1:8765/api/jobs?status=failed&limit=5",
                          token)
        head("feilede ordre")
        for job in (failed or {}).get("jobs", []):
            say(f"  {job['job_key']:<10} {str(job.get('book_slug')):<24} "
                f"{job.get('error')}")
    queue = get_json("http://127.0.0.1:8765/api/queue", token)
    if queue and queue.get("pending"):
        head("koe")
        for item in queue["pending"]:
            say(f"  {item['position']}. {item['job_key']:<10} {item.get('book_slug')}")
    return 0


def cmd_logs(args) -> int:
    path = LOGDIR / "flow.log"
    if not path.is_file():
        say(f"fant ingen {path}")
        return 1
    say(f"foelger {path}  (Ctrl+C for aa avslutte)")
    with open(path, encoding="utf-8", errors="replace") as fh:
        fh.seek(0, os.SEEK_END)
        try:
            while True:
                line = fh.readline()
                if line:
                    print(line, end="", flush=True)
                else:
                    time.sleep(0.5)
        except KeyboardInterrupt:
            return 0


def cmd_ensure(args) -> int:
    """Vaktmesteren: start det som er nede. Stille naar alt lever.

    Kjoeres av dreampage-ensure.timer hvert 5. minutt. Den er stille naar alt
    er oppe - ellers ville loggen vaert ubrukelig - og skriver bare naar den
    faktisk gjoer noe.

    Laasefila finnes fordi en kald ComfyUI kan bruke minutter paa aa svare.
    Uten den ville neste kjoering sett 'NED' og startet EN TIL.
    """
    log = STATE / "watchdog.log"
    lock = STATE / "watchdog.lock"
    STATE.mkdir(parents=True, exist_ok=True)

    def note(msg: str) -> None:
        line = f"{time.strftime('%Y-%m-%dT%H:%M:%S')}  {msg}"
        print(line, flush=True)
        try:
            with open(log, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError:
            pass

    if lock.is_file():
        age_min = (time.time() - lock.stat().st_mtime) / 60
        if age_min < 15:
            return 0
        note(f"tar over en laas som er {int(age_min)} min gammel")
    lock.write_text(str(os.getpid()), encoding="utf-8")

    started, failed = [], []
    try:
        for svc in services_for_mode():
            try:
                alive = bool(svc["health"]())
            except Exception:                           # noqa: BLE001
                alive = False
            if alive:
                continue
            note(f"{svc['name']}: NED - starter")
            try:
                svc["start"]()
            except Exception as exc:                    # noqa: BLE001
                note(f"{svc['name']}: start feilet: {exc}")
            deadline = time.monotonic() + svc["wait"]
            ok = False
            while time.monotonic() < deadline:
                time.sleep(3)
                try:
                    if svc["health"]():
                        ok = True
                        break
                except Exception:                       # noqa: BLE001
                    pass
            if ok:
                note(f"{svc['name']}: OPP igjen")
                started.append(svc["name"])
            else:
                note(f"{svc['name']}: SVARTE IKKE innen {svc['wait']} s")
                failed.append(svc["name"])
    finally:
        lock.unlink(missing_ok=True)

    if started or failed:
        note(f"ferdig: {len(started)} startet, {len(failed)} feilet")

    # SI FRA. En mislykket restart som bare blir en linje i en loggfil er en
    # ComfyUI som er usynlig nede til ordrene har hopet seg opp i RabbitMQ.
    notify = ROOT / "flow" / "worker" / "notify.py"
    if failed and notify.is_file():
        try:
            subprocess.run([dp_platform.python_bin(), str(notify), "watchdog",
                            ",".join(failed), ",".join(started)],
                           capture_output=True, timeout=60)
        except (OSError, subprocess.SubprocessError) as exc:
            note(f"kunne ikke varsle: {exc}")

    # Varsler som ikke kom fram (nattbruddet) ligger i utboksen.
    outbox = STATE / "notify_outbox"
    if outbox.is_dir() and any(outbox.glob("*.json")) and notify.is_file():
        try:
            res = subprocess.run([dp_platform.python_bin(), str(notify), "flush"],
                                 capture_output=True, text=True, timeout=120)
            note(f"utboksen: {res.stdout.strip()}")
        except (OSError, subprocess.SubprocessError) as exc:
            note(f"utboksen kunne ikke toemmes: {exc}")

    return 1 if failed else 0


def cmd_test(args) -> int:
    """ALLE testfilene, ikke en navngitt liste.

    Samme regel som paa Windows: en testkommando som maa oppdateres hver gang
    noen skriver en test, blir ikke oppdatert.
    """
    head("tester")
    failed = []
    test_dir = ROOT / "flow" / "worker" / "tests"
    for path in sorted(test_dir.glob("test_*.py")):
        say(f"\n--- {path.name}")
        if subprocess.run([dp_platform.python_bin(), str(path)]).returncode:
            failed.append(path.name)
    for extra, argv in (("check_assets", ["tools/check_assets.py"]),
                        ("comfy_workflows", ["tools/comfy_workflows.py", "--check"]),
                        ("check_portability", ["tools/check_portability.py"])):
        script = ROOT / argv[0]
        if not script.is_file():
            continue
        say(f"\n--- {extra}")
        cmd = [dp_platform.python_bin(), str(script)] + argv[1:]
        if subprocess.run(cmd).returncode:
            failed.append(extra)
    say("")
    if failed:
        say("FEILET: " + ", ".join(failed))
        return 1
    say("alle testene bestaatt")
    return 0


def cmd_mode(args) -> int:
    script = ROOT / "tools" / "server_mode.py"
    argv = [dp_platform.python_bin(), str(script)]
    if args.value:
        argv.append(args.value)
    return subprocess.run(argv).returncode


def main() -> int:
    ap = argparse.ArgumentParser(prog="dreampage.sh")
    ap.add_argument("command", nargs="?", default="status",
                    choices=["up", "down", "restart", "status", "logs",
                             "models", "test", "ensure", "mode"])
    ap.add_argument("value", nargs="?", default="",
                    help="for `mode`: book eller preview")
    ap.add_argument("--force", action="store_true",
                    help="down/restart: stopp selv midt i en ordre")
    ap.add_argument("--skip-models", action="store_true")
    args = ap.parse_args()

    if dp_platform.WINDOWS:
        # Windows har sin egen supervisor, og den er den som er kjoert i
        # produksjon. Denne ville ikke funnet prosesser uansett (/proc).
        say("Paa Windows: bruk .\\dreampage.ps1")
        return 2

    if args.command == "restart":
        code = cmd_down(args)
        if code and not args.force:
            return code
        time.sleep(5)
        return cmd_up(args)
    if args.command == "models":
        models = ROOT / "tools" / "models.py"
        return subprocess.run([dp_platform.python_bin(), str(models), "check"]).returncode
    return {
        "up": cmd_up, "down": cmd_down, "status": cmd_status,
        "logs": cmd_logs, "test": cmd_test, "ensure": cmd_ensure,
        "mode": cmd_mode,
    }[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
