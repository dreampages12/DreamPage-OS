# -*- coding: utf-8 -*-
"""Tittel- og handle-oppslag: det WooCommerce sender -> bokas MAPPENAVN.

GENERERT av tools/migrate/extract_title_map.py, hentet fra noden
"Load Book Config" i n8n-workflowen xy8qiRUzcBpH52CI den 2026-09-15.
Ikke rediger her - rediger kilden, eller gjoer tabellen selvstendig naar n8n
er borte.

Norsk, engelsk og svensk tittel peker paa SAMME bokmappe. Det er bare
textScript som varierer med spraaket.

De 16 oedelagte noeklene fra n8n (literal `?` der ae/oe/aa skulle staatt) er
bevisst IKKE tatt med. Hver av dem hadde allerede en ASCII-foldet tvilling
i tabellen, og normalize() under gjoer at begge stavemaatene treffer.
De var: den dolda v?rlden, enh?rning, enh?rningsdalen, enhj?rning, enhj?rningsdalen, fotbollsstj?rna, modet i hj?rtat, p?skejakten, sj?jungfru, sj?jungfrun
"""
from __future__ import annotations

import re
import unicodedata


# ---------------------------------------------------------------------------
# Normalisering
#
# Slugene folder ae/oe/aa til ASCII paa den maaten mappenavnene alt gjoer:
# "moetet i hjertet" -> motet-i-hjertet, "enhjoerning" -> enhjorning,
# "paaskejakten" -> paskejakten. Svensk ae/oe foelger samme regel.
#
# Baade tabellen og oppslaget normaliseres, saa "Enhjoerningsdalen",
# "enhjorningsdalen" og "ENHJOERNINGSDALEN" treffer samme bok. Det er ogsaa
# det som gjoer de 16 oedelagte n8n-noeklene unoedvendige.
# ---------------------------------------------------------------------------
_FOLD = {
    "\u00e6": "ae", "\u00f8": "o", "\u00e5": "a",     # ae oe aa
    "\u00e4": "a", "\u00f6": "o", "\u00fc": "u",      # ae oe ue (svensk/tysk)
    "\u00e9": "e", "\u00e8": "e", "\u00ea": "e",
}


def normalize(value: str) -> str:
    """Nedkoket form for oppslag: smaa bokstaver, ASCII-foldet, ett mellomrom."""
    text = unicodedata.normalize("NFC", str(value or "")).strip().lower()
    text = "".join(_FOLD.get(ch, ch) for ch in text)
    # Det som er igjen av aksenter strippes; "café" og "cafe" er samme bok.
    text = "".join(ch for ch in unicodedata.normalize("NFD", text)
                   if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text)


_TITLES_RAW = {
    "dinosaurenes dal": "dinosaurenes-dal",
    "fotball vm": "fotball-vm",
    "fotball-vm": "fotball-vm",
    "fotballvm": "fotball-vm",
    "vm i fotball": "fotball-vm",
    "the world cup": "fotball-vm",
    "world cup": "fotball-vm",
    "football world cup": "fotball-vm",
    "soccer world cup": "fotball-vm",
    "wins the world cup": "fotball-vm",
    "fotbolls vm": "fotball-vm",
    "fotbolls-vm": "fotball-vm",
    "fotbollsvm": "fotball-vm",
    "kongerikets hemmelighet": "kongerikets-hemmelighet",
    "kongerikets hemmlighet": "kongerikets-hemmelighet",
    "the secret of the kingdom": "kongerikets-hemmelighet",
    "the kingdom's secret": "kongerikets-hemmelighet",
    "kungarikets hemlighet": "kongerikets-hemmelighet",
    "den tapte superbyen": "den-tapte-superbyen",
    "tapte superbyen": "den-tapte-superbyen",
    "the lost super city": "den-tapte-superbyen",
    "lost super city": "den-tapte-superbyen",
    "den forlorade superstaden": "den-tapte-superbyen",
    "den forsvunna superstaden": "den-tapte-superbyen",
    "det forsvunne dinosauregget": "det-forsvunne-dinosauregget",
    "forsvunne dinosauregget": "det-forsvunne-dinosauregget",
    "det forsvunne dinosaur egget": "det-forsvunne-dinosauregget",
    "the lost dinosaur egg": "det-forsvunne-dinosauregget",
    "lost dinosaur egg": "det-forsvunne-dinosauregget",
    "det forsvunna dinosaurieagget": "det-forsvunne-dinosauregget",
    "den forsvunna dinosaurieagget": "det-forsvunne-dinosauregget",
    "det forlorade dinosaurieagget": "det-forsvunne-dinosauregget",
    "den skjulte styrken": "den-skjulte-styrken",
    "motet i hjertet": "motet-i-hjertet",
    "paskejakten": "paskejakten",
    "paaskejakten": "paskejakten",
    "dragejakten": "dragejakten",
    "enhjorning": "enhjorning",
    "enhjorningsdalen": "enhjorning",
    "den skjulte verdenen": "den-skjulte-verdenen",
    "dyreparken": "dyreparken",
    "fotballstjernen": "fotballstjernen",
    "hestestjernen": "hestestjernen",
    "havfruen": "havfruen",
    "the dragon quest": "dragejakten",
    "the brave heart": "motet-i-hjertet",
    "the dinosaur valley": "dinosaurenes-dal",
    "the unicorn valley": "enhjorning",
    "the hidden power": "den-skjulte-styrken",
    "the hidden world": "den-skjulte-verdenen",
    "soccer star": "fotballstjernen",
    "football star": "fotballstjernen",
    "animal park": "dyreparken",
    "riding star": "hestestjernen",
    "the mermaid": "havfruen",
    "mermaid": "havfruen",
    "the easter egg hunt": "paskejakten",
    "easter valley": "paskedalen",
    "den dolda varlden": "den-skjulte-verdenen",
    "drakjakten": "dragejakten",
    "den dolda kraften": "den-skjulte-styrken",
    "modet i hjartat": "motet-i-hjertet",
    "dinosauriernas dal": "dinosaurenes-dal",
    "enhorningsdalen": "enhjorning",
    "fotbollsstjarna": "fotballstjernen",
    "djurparken": "dyreparken",
    "sjojungfru": "havfruen",
    "sjojungfrun": "havfruen"
}

_HANDLES_RAW = {
    "enhjorningsdalen": "enhjorning",
    "fotball-vm": "fotball-vm",
    "fotballvm": "fotball-vm",
    "vm-i-fotball": "fotball-vm",
    "world-cup": "fotball-vm",
    "the-world-cup": "fotball-vm",
    "football-world-cup": "fotball-vm",
    "soccer-world-cup": "fotball-vm",
    "fotbolls-vm": "fotball-vm",
    "the-secret-of-the-kingdom": "kongerikets-hemmelighet",
    "kungarikets-hemlighet": "kongerikets-hemmelighet",
    "tapte-superbyen": "den-tapte-superbyen",
    "the-lost-super-city": "den-tapte-superbyen",
    "forsvunne-dinosauregget": "det-forsvunne-dinosauregget",
    "the-lost-dinosaur-egg": "det-forsvunne-dinosauregget",
    "den-magiske-reisen": "den-magiske-reisen-gutt",
    "den-magiske-reisen-jente": "den-magiske-reisen-jente"
}

# Titler der samme navn selges i to utgaver, og bare `gender` i
# payloaden skiller dem. Mangler gender skal ordren STOPPE, ikke gjette.
_GENDERED_RAW = [
    "den magiska resan",
    "den magiske reisen",
    "magic journey",
    "magiska resan",
    "the magic journey"
]


# Normaliserte oppslagstabeller. Bygges én gang ved import.
TITLE_TO_SLUG = {normalize(k): v for k, v in _TITLES_RAW.items()}
HANDLE_TO_SLUG = {normalize(k): v for k, v in _HANDLES_RAW.items()}
GENDERED_TITLES = {normalize(t) for t in _GENDERED_RAW}
