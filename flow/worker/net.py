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
