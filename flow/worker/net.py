# -*- coding: utf-8 -*-
"""Hvilke adresser denne maskinen har - og hvilke av dem som er tailnettet.

Finnes fordi kontrollpanelet kjoerer paa en ANNEN maskin. Det trenger POST
(retry, cancel, patch av steg) og det trenger koeen med barnenavn og
ordrenummer, altsaa det fulle API-et paa 8765. Det kan ikke gaa gjennom
tunnelen: statusporten har bare GET, og 8765 skal aldri vaere offentlig.

Men maskinene ligger allerede paa samme tailnet, og da finnes det en tredje
vei som verken er localhost eller internett.

Hvorfor ikke 0.0.0.0: da ville API-et ogsaa svart paa 192.168.86.x, altsaa
hele hjemmenettet - hver gjest paa wifi, hver IoT-dings. Vi binder til
tailnett-adressen SPESIFIKT, saa kjernen selv avviser alt annet. Det er
ingen brannmurregel aa huske paa.

Tailscale bruker CGNAT-blokka 100.64.0.0/10 (RFC 6598). Vi leter etter en
adresse i den i stedet for aa kalle `tailscale.exe`: CLI-en ligger ikke
alltid i PATH for en tjeneste, og svaret er det samme.
"""
from __future__ import annotations

import ipaddress
import socket

# RFC 6598. Tailscale deler ut 100.64.x.x - 100.127.x.x herfra.
TAILNET = ipaddress.ip_network("100.64.0.0/10")


def local_ipv4() -> list[str]:
    """Alle IPv4-adresser maskinen har, uten duplikater."""
    out: list[str] = []
    try:
        infos = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
    except socket.gaierror:
        return out
    for _fam, _type, _proto, _canon, sockaddr in infos:
        ip = sockaddr[0]
        if ip not in out:
            out.append(ip)
    return out


def tailscale_ips() -> list[str]:
    """Bare adressene som ligger i tailnettet.

    Tom liste betyr at Tailscale er nede eller ikke installert. Det er IKKE
    en feil som skal stoppe workeren - ordreflyten gaar over RabbitMQ og
    bryr seg ikke om dette. Kalleren logger og gaar videre.
    """
    found = []
    for ip in local_ipv4():
        try:
            if ipaddress.ip_address(ip) in TAILNET:
                found.append(ip)
        except ValueError:
            continue
    return found


def is_tailnet(host: str) -> bool:
    """Er denne verten en tailnett-adresse. Brukes av CORS-filteret."""
    try:
        return ipaddress.ip_address(host) in TAILNET
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Er internett her i det hele tatt
# ---------------------------------------------------------------------------
# Hver natt fra ca. 04:30 til 05:05 er utgaaende HTTPS nede paa denne maskinen.
# Det staar i state/dp_bot.log for hver eneste dag fra 12.08.2026 og framover:
# ~370 linjer "<urlopen error [Errno 2] No such file or directory>" mellom
# 04:30:4x og 05:05:0x. Aarsaken ligger utenfor maskinen (ingen proxy, ingen
# exit-node, ingenting i Windows-loggen) - men flyten maa taale den uansett.
#
# Ordre 1532 (tobok, betalt) kom inn 04:50 17.09.2026 og doede paa bildet.
# Retry-pausen ble da hevet til 5 minutter i troen paa at bruddet varte i to.
# Det varer i 35. Og fordi persist_payload er et sjekkpunkt, er meldingen alt
# acket naar bildet hentes: en ordre som feiler her, kommer aldri tilbake av
# seg selv.
#
# Derfor venter stegene som trenger internett paa at det er tilbake, i stedet
# for aa bruke opp forsoekene sine mot en vegg.
def internet_up(url: str, timeout: float = 10) -> bool:
    """Svarer verten i `url` i det hele tatt - med hva som helst.

    Et HTTP-svar, ogsaa 404 eller 405, betyr at nettet virker. Bare det at vi
    ikke kommer fram (DNS, TLS, tilkobling, timeout) teller som nede. Vi
    spoer bare om roten til verten, aldri om selve ressursen.
    """
    import urllib.error
    import urllib.parse
    import urllib.request

    parts = urllib.parse.urlsplit(url)
    root = f"{parts.scheme}://{parts.netloc}/"
    req = urllib.request.Request(root, method="HEAD", headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    try:
        with urllib.request.urlopen(req, timeout=timeout):
            return True
    except urllib.error.HTTPError:
        return True
    except (urllib.error.URLError, OSError):
        return False


def wait_for_internet(url: str, log=None, cancelled=lambda: False,
                      max_wait_s: float = 45 * 60, every_s: float = 30,
                      probe=internet_up, sleep=None) -> float:
    """Vent til verten i `url` svarer. Returnerer sekunder ventet.

    45 minutter dekker nattbruddet (35 min) med margin. Gir den opp, kaster
    den RuntimeError - en systemfeil, som steget selv kan proeve igjen.

    Mens vi venter, staar koeen. Det er med vilje: alt bak denne ordren
    trenger det samme nettet, og en ordre som venter er bedre enn en ordre
    som er doed og som ingen faar beskjed om.
    """
    import time

    sleep = sleep or time.sleep
    waited = 0.0
    warned = False
    while not probe(url):
        if cancelled():
            raise RuntimeError("avbrutt mens vi ventet paa nettet")
        if waited >= max_wait_s:
            raise RuntimeError(
                f"nettet har vaert nede i {int(waited // 60)} min "
                f"({url.split('?')[0]} svarer ikke) - gir opp")
        if log and not warned:
            log.warn(f"nettet er nede ({url.split('?')[0]} svarer ikke) - "
                     f"venter inntil {int(max_wait_s // 60)} min")
            warned = True
        sleep(every_s)
        waited += every_s
    if log and warned:
        log.info(f"nettet er tilbake etter {int(waited)} s")
    return waited
