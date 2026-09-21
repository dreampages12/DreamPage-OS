# -*- coding: utf-8 -*-
"""Det som faktisk er forskjellig mellom Windows og Linux. Ett sted.

DreamPage OS er skrevet paa Windows og trykker boeker fra Windows i dag. Nye
maskiner settes opp paa Linux. Begge skal virke, og den maskinen som staar i
produksjon akkurat naa skal ikke merke at den andre finnes.

Regelen er derfor: **en `if windows:` i produksjonskoden er en feil.** Er noe
forskjellig, hoerer det hjemme her, bak et navn som sier HVA det gjoer og
ikke hvilket OS det er. Da finnes forskjellene paa ett sted i stedet for
spredt over 80 filer, og en tredje plattform er en funksjon her - ikke en
skattejakt.

Det er bevisst lite her. Det meste av koden er allerede portabel fordi den
bruker `pathlib`, `os.path.join` og `flow/paths.py`; det som ikke er det, er
dette:

  * maskinens oppetid       (kernel32 vs /proc/uptime)
  * hvor n8n sin SQLite bor (%USERPROFILE%\\.n8n vs ~/.n8n)
  * hvordan tjenester passes paa (Task Scheduler vs systemd)
  * hva en kjoerbar fil heter (.exe eller ingenting)

`paths.py` haandterer stier og er uavhengig av dette; den eneste koblingen
er at begge utleder alt fra ROOT i stedet for aa hardkode en disk.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

WINDOWS = os.name == "nt"
LINUX = sys.platform.startswith("linux")
MACOS = sys.platform == "darwin"

# Navnet mennesker og statusvisningen leser.
NAME = "windows" if WINDOWS else ("linux" if LINUX else sys.platform)


# ---------------------------------------------------------------------------
# Oppetid
# ---------------------------------------------------------------------------
def machine_uptime_s() -> int | None:
    """Hvor lenge maskinen har vaert oppe, i sekunder. None hvis ukjent.

    Brukes bare av statusvisningen. Den skal ALDRI kaste: en flaatevisning
    som ikke kan vise oppetid er et savn, en statusrute som krasjer er en
    server som ser doed ut.
    """
    if WINDOWS:
        try:
            import ctypes
            return int(ctypes.windll.kernel32.GetTickCount64() // 1000)
        except (AttributeError, OSError, ValueError):
            return None
    try:
        # /proc/uptime: "12345.67 98765.43" - sekunder oppe, sekunder idle.
        with open("/proc/uptime", encoding="ascii") as fh:
            return int(float(fh.read().split()[0]))
    except (OSError, ValueError, IndexError):
        return None


# ---------------------------------------------------------------------------
# Kjoerbare filer
# ---------------------------------------------------------------------------
def exe(name: str) -> str:
    """Filnavnet en kjoerbar fil har paa denne plattformen."""
    return f"{name}.exe" if WINDOWS else name


def which(name: str, *fallbacks: str) -> str | None:
    """Finn en kjoerbar fil paa PATH, med eksplisitte alternativer.

    `fallbacks` er fulle stier som proeves hvis PATH ikke har den. Brukes til
    cloudflared, som paa denne maskinen ligger i Downloads og ikke paa PATH -
    men som paa en Linux-server ligger i /usr/local/bin der den skal.
    """
    found = shutil.which(name) or shutil.which(exe(name))
    if found:
        return found
    for candidate in fallbacks:
        if candidate and Path(candidate).is_file():
            return str(candidate)
    return None


def python_bin() -> str:
    """Python-tolken DreamPage skal kjoere med.

    `sys.executable` naar vi alt kjoerer i riktig tolk. DP_PYTHON i miljoeet
    vinner, slik at en supervisor kan peke paa et virtuelt miljoe uten aa
    aktivere det - det er formen systemd vil ha det paa.
    """
    return os.environ.get("DP_PYTHON") or sys.executable or exe("python3")


# ---------------------------------------------------------------------------
# n8n
#
# n8n er IKKE i ordreveien lenger (se docs/ordreveien.md), men to filer maa
# bevares fordi produksjonskode leser SQLite-fila direkte for aa hente gamle
# ordre-payloads og for aa dekryptere Google Drive-legitimasjonen.
# ---------------------------------------------------------------------------
def n8n_home() -> Path:
    """Mappa med database.sqlite og config (encryptionKey).

    DP_N8N_HOME i miljoeet vinner. Uten den: brukerens hjemmemappe, som er
    riktig baade paa Windows (C:\\Users\\<bruker>\\.n8n) og paa Linux
    (~/.n8n) - `Path.home()` kan begge.
    """
    override = os.environ.get("DP_N8N_HOME")
    if override:
        return Path(override)
    return Path.home() / ".n8n"


def n8n_db() -> Path:
    return n8n_home() / "database.sqlite"


def n8n_config() -> Path:
    return n8n_home() / "config"


# ---------------------------------------------------------------------------
# Tjenestestyring
# ---------------------------------------------------------------------------
def supervisor() -> str:
    """Hva som passer paa prosessene paa denne maskinen.

    "task-scheduler"  Windows: `dreampage.ps1 ensure` hvert 5. minutt.
    "systemd"         Linux: dreampage-ensure.timer gjoer det samme.
    "none"            ingen vaktmester funnet - da er det et MENNESKE som
                      maa starte ting igjen, og det skal staa i statusen.
    """
    if WINDOWS:
        return "task-scheduler"
    if LINUX and which("systemctl"):
        return "systemd"
    return "none"


def supervisor_command() -> str:
    """Kommandoen som starter alt paa nytt. Vises i feilmeldinger."""
    return (".\\dreampage.ps1 up" if WINDOWS else "./dreampage.sh up")


def describe() -> dict:
    """Plattformen som JSON, til /api/status og /api/health.

    Ingen stier og ingen brukernavn: dette gaar ut av maskinen. Bare navn og
    versjoner, slik at en flaatevisning kan se at halve flaaten kjoerer et
    annet OS enn den andre halvparten.
    """
    return {
        "os": NAME,
        "release": _release(),
        "python": ".".join(str(p) for p in sys.version_info[:3]),
        "supervisor": supervisor(),
    }


def _release() -> str | None:
    """Kort versjonsnavn. "11" paa Windows, "Ubuntu 24.04" paa Linux."""
    try:
        import platform as _stdlib_platform
        if WINDOWS:
            return _stdlib_platform.release() or None
        # /etc/os-release er standarden paa alt som er Linux i dag.
        data = {}
        with open("/etc/os-release", encoding="utf-8") as fh:
            for line in fh:
                if "=" in line:
                    key, _, value = line.partition("=")
                    data[key.strip()] = value.strip().strip('"')
        return data.get("PRETTY_NAME") or data.get("NAME") or None
    except (OSError, ValueError):
        return None
