# -*- coding: utf-8 -*-
"""Ny historie til Havfruen - "Havets hjerte" (2026-09-06).

Tobias har laget hele boka pa nytt (nye 01-14, forside, bakside, ryggrad,
dreampage-first og logo) og levert en ny historie. Dette scriptet bytter ut
sidetekstene 1-14 og baksideteksten i alle fem locale-scriptene.

Teksten er kortet ned fra manuset - malet er ~55 ord per side, samme lengde som
den forrige boka, ellers renner blokka nedover halvsida og treffer barnet.

`side` er halvsida teksten skal sta i, og er valgt som halvsida der barnet IKKE
er (bildene er 2048x1024-oppslag som splittes i to A5-kvadrater):

    1 V | 2 H | 3 V | 4 H | 5 V | 6 V | 7 V
    8 H | 9 V | 10 V | 11 V | 12 V | 13 V | 14 H

Sprak: nb er kilden. nn/en-US/en-GB/sv har hittil hatt NORSK historietekst
(gjelder alle bokene), men engelsk forside-logo sier "A Mermaid" - altsa er
markedet ment a vaere der. Historien er derfor oversatt her, og forsidelinje 1
("[NAVN] blir") er rettet til "[NAVN] becomes" for engelsk.

Bruk:
  python rewrite_havfruen_story.py --dry-run
  python rewrite_havfruen_story.py --apply
  python rewrite_havfruen_story.py --revert
"""
from __future__ import annotations

import argparse
import ast
import glob
import io
import os
import shutil
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TAG = "havfrue-nystory"
LOCALES = ["nb", "nn", "en-US", "en-GB", "sv"]

START_ANCHOR = "        # Side 1 –"
END_ANCHOR = "     ]\n\n\n    return pages"

# Halvside teksten skal sta i, og finjustering per side. x/width-offsetene
# folger den gamle boka: hoyre spalte skyves litt inn, venstre star.
LAYOUT = [
    ("left",  30, 0,  -10,   0),   # 1
    ("right", 29, 10, -10, -10),   # 2
    ("left",  29, 0,  -10,   0),   # 3
    ("right", 29, 10, -10, -10),   # 4
    ("left",  30, 0,  -10,   0),   # 5
    ("left",  29, 0,  -10,   0),   # 6
    ("left",  29, 0,  -10,   0),   # 7
    ("right", 29, 10, -10, -10),   # 8
    ("left",  29, 0,  -10,   0),   # 9
    ("left",  29, 0,  -10,   0),   # 10
    ("left",  29, 0,  -10,   0),   # 11
    ("left",  30, 0,  200,   0),   # 12 - skyves ned forbi ansiktet hennes
    ("left",  30, 0,  -10,   0),   # 13
    ("right", 28, 10, -10, -10),   # 14
]

TITLES = [
    "det mystiske skjellet", "stemmen fra havet", "den skjulte lagunen",
    "den magiske perlen", "(Navn) blir havfrue", "den forste svommeturen",
    "havfruenes rike", "noe er galt", "den morke passasjen", "havskilpadden",
    "den hemmelige hulen", "havets hjerte", "lyset vender tilbake",
    "en ny hemmelighet",
]

STORY = {}
HIGHLIGHTS = {}
BACK = {}
COVER_LINE1 = {}

# ------------------------------------------------------------------ nb
COVER_LINE1["nb"] = "[NAVN] blir"
STORY["nb"] = [
    "En varm sommerdag lekte (Navn) ved stranden.\n"
    "Hun hoppet mellom steinene og lette etter fine skjell i sanden.\n\n"
    "Plutselig glitret noe mellom to våte steiner. Det var et skjell som skinte i blått og lilla.\n\n"
    "(Navn) hadde aldri sett noe lignende.",

    "(Navn) løftet skjellet opp til øret.\n"
    "Men i stedet for bølgesus hørte hun en svak stemme.\n\n"
    "«Hallo? Kan du høre meg?»\n\n"
    "Ute mellom bølgene dukket et ansikt opp. Det var en ekte havfrue, og hun vinket (Navn) nærmere.",

    "Havfruen viste vei mellom to høye klipper.\n"
    "Bak dem lå en lagune (Navn) aldri hadde sett før.\n\n"
    "Vannet var helt klart, og langt der nede lyste et sterkt blått lys.\n\n"
    "«Dette stedet er hemmelig,» sa havfruen. «Og jeg tror skjellet valgte akkurat deg.»",

    "Midt i lagunen løftet havfruen frem en lysende perle.\n\n"
    "«Magien våkner bare for noen som virkelig vil hjelpe havet,» forklarte hun.\n\n"
    "(Navn) strakte hånden forsiktig frem. Da fingertuppene traff perlen, begynte hele lagunen å glitre.",

    "Vann og lys virvlet rundt (Navn), og hun kjente en merkelig kribling helt ned i tærne.\n\n"
    "Så forsvant beina hennes — og i stedet fikk hun en lang, glitrende havfruehale!\n\n"
    "«Jeg er en havfrue!» ropte hun.",

    "Havfruen tok (Navn) med under vann.\n"
    "Først var halen vanskelig å styre, men snart suste hun av gårde.\n\n"
    "Hun svømte mellom fargerike fisker, store koraller og bobler som danset rundt henne.\n\n"
    "(Navn) hadde aldri følt seg så lett og fri.",

    "Bak en stor undervannsportal ventet et helt havfruerike.\n\n"
    "Tårn av koraller strakte seg opp fra havbunnen, og små hus av skjell glitret mellom lysende planter.\n\n"
    "(Navn) klarte nesten ikke å se på alt samtidig. Det var det vakreste hun visste.",

    "Men lenger inne i riket la (Navn) merke til noe.\n"
    "Flere av lysene hadde sluknet.\n\n"
    "Korallene hadde mistet fargene sine, og fiskene gjemte seg mellom steinene.\n\n"
    "«Havets magi forsvinner,» sa havfruen. «Finner vi ikke årsaken, blir hele riket mørkt.»",

    "På havbunnen oppdaget (Navn) små spor av blått lys.\n"
    "Hun og havfruen fulgte dem inn i en gammel tunnel.\n\n"
    "Jo lenger de svømte, desto mørkere ble det. Bare de blå lysene viste vei.\n\n"
    "Plutselig hørte (Navn) en svak lyd. Noen trengte hjelp.",

    "Bak noen store steiner satt en havskilpadde fast mellom ødelagte koraller.\n\n"
    "«Vi må hjelpe den!» sa (Navn).\n\n"
    "Sammen dyttet de steinene unna. Skilpadden svømte en takknemlig sirkel rundt (Navn) "
    "og vinket med hodet. Den ville at de skulle følge etter.",

    "Skilpadden ledet dem dypere ned i havet.\n"
    "Snart kom de til en enorm steinvegg dekket av gamle symboler.\n\n"
    "Da skilpadden svømte mot veggen, begynte symbolene å lyse.\n\n"
    "En skjult åpning kom til syne — inn til en hule ingen hadde besøkt på svært lenge.",

    "Innerst i hulen lyste en enorm krystall, men lyset var svakt.\n\n"
    "«Havets hjerte,» hvisket havfruen. «Det gir lys og liv til hele riket.»\n\n"
    "Da begynte skjellet i hånden til (Navn) å gløde. Hun holdt det nærmere, "
    "og de to lysene svarte hverandre.",

    "(Navn) la skjellet forsiktig mot Havets hjerte.\n\n"
    "BOOM! En bølge av blått og gyllent lys fór gjennom havet.\n\n"
    "Korallene fikk fargene tilbake, gatene begynte å lyse, og fiskene kom frem igjen. "
    "Havfruer jublet over hele riket. (Navn) hadde reddet dem alle.",

    "Havfruene samlet seg rundt (Navn).\n"
    "«Du vil alltid være velkommen her,» sa venninnen hennes.\n\n"
    "Da blinket Havets hjerte igjen. En lysstråle skjøt ut i det mørke havet, "
    "og langt borte tentes lys i et gammelt palass.\n\n"
    "«Det kan ikke være sant …» hvisket havfruen.\n\n"
    "(Navn) smilte. Eventyret var ikke over ennå.",
]
HIGHLIGHTS["nb"] = [
    ["skjell", "glitret"], ["stemme", "havfrue"], ["lagune", "hemmelig"],
    ["perle", "Magien"], ["havfruehale", "havfrue"], ["koraller", "fri"],
    ["havfruerike", "vakreste"], ["magi", "mørkt"], ["tunnel", "hjelp"],
    ["havskilpadde", "hjelpe"], ["symbolene", "hule"], ["krystall", "hjerte"],
    ["lys", "reddet"], ["palass", "Eventyret"],
]
BACK["nb"] = (
    "Et glitrende skjell. En stemme fra havet. Et helt rike under bølgene.\n\n"
    "Når (Navn) finner et skjell som lyser i blått og lilla, åpner det døren til havfruenes "
    "hemmelige verden. Men magien i riket holder på å slukne, og bare noen med et ekte "
    "hjerte for havet kan vekke den igjen.\n\n"
    "Sammen med en havfrue og en havskilpadde leter (Navn) etter Havets hjerte — dypt inne "
    "i en hule ingen har besøkt på svært lenge.\n\n"
    "En personlig fortelling om mot, vennskap og magien i å hjelpe andre."
)

# ------------------------------------------------------------------ nn
COVER_LINE1["nn"] = "[NAVN] blir"
STORY["nn"] = [
    "Ein varm sommardag leikte (Navn) ved stranda.\n"
    "Ho hoppa mellom steinane og leita etter fine skjel i sanden.\n\n"
    "Brått glitra noko mellom to våte steinar. Det var eit skjel som skein i blått og lilla.\n\n"
    "(Navn) hadde aldri sett noko liknande.",

    "(Navn) løfta skjelet opp til øyret.\n"
    "Men i staden for bølgjesus høyrde ho ei svak stemme.\n\n"
    "«Hallo? Kan du høyre meg?»\n\n"
    "Ute mellom bølgjene dukka eit andlet opp. Det var ei ekte havfrue, og ho vinka (Navn) nærare.",

    "Havfrua viste veg mellom to høge klipper.\n"
    "Bak dei låg ei lagune (Navn) aldri hadde sett før.\n\n"
    "Vatnet var heilt klart, og langt der nede lyste eit sterkt blått lys.\n\n"
    "«Denne staden er hemmeleg,» sa havfrua. «Og eg trur skjelet valde nettopp deg.»",

    "Midt i lagunen løfta havfrua fram ei lysande perle.\n\n"
    "«Magien vaknar berre for nokon som verkeleg vil hjelpe havet,» forklarte ho.\n\n"
    "(Navn) strekte handa forsiktig fram. Då fingertuppane trefte perla, byrja heile lagunen å glitre.",

    "Vatn og lys virvla rundt (Navn), og ho kjende ei merkeleg kribling heilt ned i tærne.\n\n"
    "Så forsvann beina hennar — og i staden fekk ho ein lang, glitrande havfruehale!\n\n"
    "«Eg er ei havfrue!» ropa ho.",

    "Havfrua tok (Navn) med under vatn.\n"
    "Først var halen vanskeleg å styre, men snart susa ho av garde.\n\n"
    "Ho symde mellom fargerike fiskar, store korallar og boblar som dansa rundt henne.\n\n"
    "(Navn) hadde aldri kjent seg så lett og fri.",

    "Bak ein stor undervassportal venta eit heilt havfruerike.\n\n"
    "Tårn av korallar strekte seg opp frå havbotnen, og små hus av skjel glitra mellom lysande planter.\n\n"
    "(Navn) klarte nesten ikkje å sjå på alt samtidig. Det var det vakraste ho visste.",

    "Men lenger inne i riket la (Navn) merke til noko.\n"
    "Fleire av lysa hadde slokna.\n\n"
    "Korallane hadde mist fargane sine, og fiskane gøymde seg mellom steinane.\n\n"
    "«Magien i havet forsvinn,» sa havfrua. «Finn vi ikkje årsaka, blir heile riket mørkt.»",

    "På havbotnen oppdaga (Navn) små spor av blått lys.\n"
    "Ho og havfrua følgde dei inn i ein gammal tunnel.\n\n"
    "Jo lenger dei symde, dess mørkare vart det. Berre dei blå lysa viste veg.\n\n"
    "Brått høyrde (Navn) ein svak lyd. Nokon trong hjelp.",

    "Bak nokre store steinar sat ei havskjelpadde fast mellom øydelagde korallar.\n\n"
    "«Vi må hjelpe henne!» sa (Navn).\n\n"
    "Saman dytta dei steinane unna. Skjelpadda symde ein takksam sirkel rundt (Navn) "
    "og vinka med hovudet. Ho ville at dei skulle følgje etter.",

    "Skjelpadda leidde dei djupare ned i havet.\n"
    "Snart kom dei til ein enorm steinvegg dekt av gamle symbol.\n\n"
    "Då skjelpadda symde mot veggen, byrja symbola å lyse.\n\n"
    "Ei løynd opning kom til syne — inn til ei hole ingen hadde vitja på svært lenge.",

    "Innarst i hola lyste ein enorm krystall, men lyset var svakt.\n\n"
    "«Hjartet i havet,» kviskra havfrua. «Det gjev lys og liv til heile riket.»\n\n"
    "Då byrja skjelet i handa til (Navn) å gløde. Ho heldt det nærare, "
    "og dei to lysa svara kvarandre.",

    "(Navn) la skjelet forsiktig mot Hjartet i havet.\n\n"
    "BOOM! Ei bølgje av blått og gyllent lys fór gjennom havet.\n\n"
    "Korallane fekk fargane tilbake, gatene byrja å lyse, og fiskane kom fram igjen. "
    "Havfruer jubla over heile riket. (Navn) hadde redda dei alle.",

    "Havfruene samla seg rundt (Navn).\n"
    "«Du er alltid velkomen her,» sa venninna hennar.\n\n"
    "Då blinka Hjartet i havet igjen. Ein lysstråle skaut ut i det mørke havet, "
    "og langt borte tende lys seg i eit gammalt palass.\n\n"
    "«Det kan ikkje vere sant …» kviskra havfrua.\n\n"
    "(Navn) smilte. Eventyret var ikkje over enno.",
]
HIGHLIGHTS["nn"] = [
    ["skjel", "glitra"], ["stemme", "havfrue"], ["lagune", "hemmeleg"],
    ["perle", "Magien"], ["havfruehale", "havfrue"], ["korallar", "fri"],
    ["havfruerike", "vakraste"], ["Magien", "mørkt"], ["tunnel", "hjelp"],
    ["havskjelpadde", "hjelpe"], ["symbola", "hole"], ["krystall", "Hjartet"],
    ["lys", "redda"], ["palass", "Eventyret"],
]
BACK["nn"] = (
    "Eit glitrande skjel. Ei stemme frå havet. Eit heilt rike under bølgjene.\n\n"
    "Når (Navn) finn eit skjel som lyser i blått og lilla, opnar det døra til den hemmelege "
    "verda til havfruene. Men magien i riket held på å slokne, og berre nokon med eit ekte "
    "hjarte for havet kan vekkje han igjen.\n\n"
    "Saman med ei havfrue og ei havskjelpadde leitar (Navn) etter Hjartet i havet — djupt "
    "inne i ei hole ingen har vitja på svært lenge.\n\n"
    "Ei personleg forteljing om mot, vennskap og magien i å hjelpe andre."
)

# ------------------------------------------------------------------ en-US
COVER_LINE1["en-US"] = "[NAVN] becomes"
STORY["en-US"] = [
    "One warm summer day, (Navn) was playing down by the beach.\n"
    "She hopped from rock to rock, hunting for pretty shells in the sand.\n\n"
    "Suddenly something glittered between two wet stones. It was a shell that shone in blue and purple.\n\n"
    "(Navn) had never seen anything like it.",

    "(Navn) lifted the shell up to her ear.\n"
    "But instead of the sound of waves, she heard a faint little voice.\n\n"
    "«Hello? Can you hear me?»\n\n"
    "Out among the waves a face appeared. It was a real mermaid, and she waved (Navn) closer.",

    "The mermaid led the way between two tall cliffs.\n"
    "Behind them lay a lagoon (Navn) had never seen before.\n\n"
    "The water was perfectly clear, and far below it a strong blue light was glowing.\n\n"
    "«This place is a secret,» said the mermaid. «And I think the shell chose you.»",

    "In the middle of the lagoon the mermaid lifted up a glowing pearl.\n\n"
    "«The magic only wakes for someone who truly wants to help the ocean,» she explained.\n\n"
    "(Navn) reached out carefully. The moment her fingertips touched the pearl, "
    "the whole lagoon began to sparkle.",

    "Water and light swirled around (Navn), and she felt a strange tingle all the way down to her toes.\n\n"
    "Then her legs disappeared — and instead she had a long, glittering mermaid tail!\n\n"
    "«I'm a mermaid!» she cried.",

    "The mermaid took (Navn) down beneath the waves.\n"
    "At first the tail was hard to steer, but soon she was racing through the water.\n\n"
    "She swam past colorful fish, tall corals and bubbles that danced around her.\n\n"
    "(Navn) had never felt so light and free.",

    "Behind a great underwater gateway waited an entire mermaid kingdom.\n\n"
    "Towers of coral rose from the sea floor, and little houses of shell glittered among the glowing plants.\n\n"
    "(Navn) could hardly take it all in. It was the most beautiful place she had ever seen.",

    "But further into the kingdom, (Navn) noticed something.\n"
    "Many of the lights had gone out.\n\n"
    "The corals had lost their colors, and the fish were hiding among the stones.\n\n"
    "«The magic of the sea is fading,» said the mermaid. «If we don't find the cause, "
    "the whole kingdom will go dark.»",

    "On the sea floor (Navn) spotted small traces of blue light.\n"
    "She and the mermaid followed them into an ancient tunnel.\n\n"
    "The further they swam, the darker it grew. Only the little blue lights showed the way.\n\n"
    "Suddenly (Navn) heard a faint sound. Someone needed help.",

    "Behind some large rocks a sea turtle was stuck between broken corals.\n\n"
    "«We have to help her!» said (Navn).\n\n"
    "Together they pushed the rocks aside. The turtle swam a grateful circle around (Navn) "
    "and nodded her head. She wanted them to follow.",

    "The turtle led them deeper into the sea.\n"
    "Soon they reached an enormous stone wall covered in ancient symbols.\n\n"
    "When the turtle swam toward it, the symbols began to glow.\n\n"
    "A hidden opening appeared — into a cave no one had visited for a very long time.",

    "Deep inside the cave an enormous crystal was shining, but its light was weak.\n\n"
    "«The Heart of the Sea,» whispered the mermaid. «It gives light and life to the whole kingdom.»\n\n"
    "Then the shell in (Navn)'s hand began to glow. She held it closer, "
    "and the two lights answered each other.",

    "(Navn) laid the shell gently against the Heart of the Sea.\n\n"
    "BOOM! A wave of blue and golden light rushed through the ocean.\n\n"
    "The corals got their colors back, the streets lit up, and the fish came out again. "
    "Mermaids cheered across the kingdom. (Navn) had saved them all.",

    "The mermaids gathered around (Navn).\n"
    "«You will always be welcome here,» said her friend.\n\n"
    "Just then the Heart of the Sea flashed again. A beam of light shot out into the dark water, "
    "and far away lights came on in an ancient palace.\n\n"
    "«That can't be true …» whispered the mermaid.\n\n"
    "(Navn) smiled. The adventure was not over yet.",
]
HIGHLIGHTS["en-US"] = [
    ["shell", "glittered"], ["voice", "mermaid"], ["lagoon", "secret"],
    ["pearl", "magic"], ["tail", "mermaid"], ["corals", "free"],
    ["kingdom", "beautiful"], ["magic", "dark"], ["tunnel", "help"],
    ["turtle", "help"], ["symbols", "cave"], ["crystal", "Heart"],
    ["light", "saved"], ["palace", "adventure"],
]
BACK["en-US"] = (
    "A glittering shell. A voice from the sea. A whole kingdom beneath the waves.\n\n"
    "When (Navn) finds a shell that glows in blue and purple, it opens the door to the secret "
    "world of the mermaids. But the magic of the kingdom is fading, and only someone with a "
    "true heart for the ocean can wake it again.\n\n"
    "Together with a mermaid and a sea turtle, (Navn) searches for the Heart of the Sea — "
    "deep inside a cave no one has visited for a very long time.\n\n"
    "A personal story about courage, friendship and the magic of helping others."
)

# ------------------------------------------------------------------ en-GB
COVER_LINE1["en-GB"] = "[NAVN] becomes"
STORY["en-GB"] = [
    t.replace("colorful", "colourful")
     .replace("their colors", "their colours")
     .replace("swam toward it", "swam towards it")
    for t in STORY["en-US"]
]
HIGHLIGHTS["en-GB"] = [list(h) for h in HIGHLIGHTS["en-US"]]
BACK["en-GB"] = BACK["en-US"]

# ------------------------------------------------------------------ sv
# Svensk: logoen sier bare "Sjojungfru", saa artikkelen maa henge paa linje 1
# ("Elsa blir en Sjojungfru"). Samme moenster som line1_suffix i
# next_book_titles.json - sjekk alltid linje 1 mot hva logoen faktisk sier.
COVER_LINE1["sv"] = "[NAVN] blir en"
STORY["sv"] = [
    "En varm sommardag lekte (Navn) nere vid stranden.\n"
    "Hon hoppade mellan stenarna och letade efter fina snäckor i sanden.\n\n"
    "Plötsligt glittrade något mellan två blöta stenar. Det var en snäcka som lyste i blått och lila.\n\n"
    "(Navn) hade aldrig sett något liknande.",

    "(Navn) lyfte snäckan upp till örat.\n"
    "Men i stället för vågornas brus hörde hon en svag liten röst.\n\n"
    "«Hallå? Kan du höra mig?»\n\n"
    "Ute bland vågorna dök ett ansikte upp. Det var en riktig sjöjungfru, och hon vinkade (Navn) närmare.",

    "Sjöjungfrun visade vägen mellan två höga klippor.\n"
    "Bakom dem låg en lagun som (Navn) aldrig hade sett förut.\n\n"
    "Vattnet var alldeles klart, och långt där nere lyste ett starkt blått ljus.\n\n"
    "«Den här platsen är hemlig,» sa sjöjungfrun. «Och jag tror att snäckan valde just dig.»",

    "Mitt i lagunen lyfte sjöjungfrun fram en lysande pärla.\n\n"
    "«Magin vaknar bara för någon som verkligen vill hjälpa havet,» förklarade hon.\n\n"
    "(Navn) sträckte försiktigt fram handen. När fingertopparna nuddade pärlan "
    "började hela lagunen glittra.",

    "Vatten och ljus virvlade runt (Navn), och hon kände ett underligt pirrande ända ner i tårna.\n\n"
    "Sedan försvann benen — och i stället fick hon en lång, glittrande sjöjungfrusvans!\n\n"
    "«Jag är en sjöjungfru!» ropade hon.",

    "Sjöjungfrun tog med (Navn) ner under vattnet.\n"
    "Först var svansen svår att styra, men snart susade hon fram.\n\n"
    "Hon simmade bland färgglada fiskar, stora koraller och bubblor som dansade omkring henne.\n\n"
    "(Navn) hade aldrig känt sig så lätt och fri.",

    "Bakom en stor undervattensport väntade ett helt sjöjungfrurike.\n\n"
    "Torn av koraller sträckte sig upp från havsbottnen, och små hus av snäckor glittrade "
    "bland lysande växter.\n\n"
    "(Navn) hann nästan inte titta på allt samtidigt. Det var det vackraste hon visste.",

    "Men längre in i riket lade (Navn) märke till något.\n"
    "Flera av ljusen hade slocknat.\n\n"
    "Korallerna hade tappat sina färger, och fiskarna gömde sig mellan stenarna.\n\n"
    "«Havets magi håller på att försvinna,» sa sjöjungfrun. «Hittar vi inte orsaken "
    "blir hela riket mörkt.»",

    "På havsbottnen upptäckte (Navn) små spår av blått ljus.\n"
    "Hon och sjöjungfrun följde dem in i en gammal tunnel.\n\n"
    "Ju längre de simmade, desto mörkare blev det. Bara de blå ljusen visade vägen.\n\n"
    "Plötsligt hörde (Navn) ett svagt ljud. Någon behövde hjälp.",

    "Bakom några stora stenar satt en havssköldpadda fast mellan trasiga koraller.\n\n"
    "«Vi måste hjälpa henne!» sa (Navn).\n\n"
    "Tillsammans knuffade de undan stenarna. Sköldpaddan simmade ett tacksamt varv runt (Navn) "
    "och nickade med huvudet. Hon ville att de skulle följa med.",

    "Sköldpaddan ledde dem djupare ner i havet.\n"
    "Snart kom de till en enorm stenvägg täckt av gamla symboler.\n\n"
    "När sköldpaddan simmade mot väggen började symbolerna lysa.\n\n"
    "En dold öppning kom fram — in till en grotta som ingen hade besökt på mycket länge.",

    "Längst in i grottan lyste en enorm kristall, men ljuset var svagt.\n\n"
    "«Havets hjärta,» viskade sjöjungfrun. «Det ger ljus och liv åt hela riket.»\n\n"
    "Då började snäckan i (Navn)s hand glöda. Hon höll den närmare, "
    "och de två ljusen svarade varandra.",

    "(Navn) lade snäckan försiktigt mot Havets hjärta.\n\n"
    "BOOM! En våg av blått och gyllene ljus for genom havet.\n\n"
    "Korallerna fick tillbaka sina färger, gatorna började lysa och fiskarna kom fram igen. "
    "Sjöjungfrur jublade i hela riket. (Navn) hade räddat dem alla.",

    "Sjöjungfrurna samlades runt (Navn).\n"
    "«Du är alltid välkommen hit,» sa hennes vän.\n\n"
    "Just då blinkade Havets hjärta igen. En ljusstråle sköt ut i det mörka havet, "
    "och långt borta tändes ljus i ett gammalt palats.\n\n"
    "«Det kan inte vara sant …» viskade sjöjungfrun.\n\n"
    "(Navn) log. Äventyret var inte slut än.",
]
HIGHLIGHTS["sv"] = [
    ["snäcka", "glittrade"], ["röst", "sjöjungfru"], ["lagun", "hemlig"],
    ["pärla", "Magin"], ["sjöjungfrusvans", "sjöjungfru"], ["koraller", "fri"],
    ["sjöjungfrurike", "vackraste"], ["magi", "mörkt"], ["tunnel", "hjälp"],
    ["havssköldpadda", "hjälpa"], ["symbolerna", "grotta"], ["kristall", "hjärta"],
    ["ljus", "räddat"], ["palats", "Äventyret"],
]
BACK["sv"] = (
    "En glittrande snäcka. En röst från havet. Ett helt rike under vågorna.\n\n"
    "När (Navn) hittar en snäcka som lyser i blått och lila öppnas dörren till sjöjungfrurnas "
    "hemliga värld. Men magin i riket håller på att slockna, och bara någon med ett äkta "
    "hjärta för havet kan väcka den igen.\n\n"
    "Tillsammans med en sjöjungfru och en havssköldpadda letar (Navn) efter Havets hjärta — "
    "djupt inne i en grotta som ingen har besökt på mycket länge.\n\n"
    "En personlig berättelse om mod, vänskap och magin i att hjälpa andra."
)

BACK_HIGHLIGHTS = {
    "nb": ["havfruenes", "Havets", "mot", "vennskap", "magien"],
    "nn": ["havfruene", "Hjartet", "mot", "vennskap", "magien"],
    "en-US": ["mermaids", "Heart", "courage", "friendship", "magic"],
    "en-GB": ["mermaids", "Heart", "courage", "friendship", "magic"],
    "sv": ["sjöjungfrurnas", "Havets", "mod", "vänskap", "magin"],
}


def _q(s):
    """Python-literal av en streng uten linjeskift."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def py_str(text):
    """En kildelinje per avsnittslinje, slik resten av fila er skrevet."""
    parts = text.split("\n")
    out = []
    for i, part in enumerate(parts):
        lit = _q(part)
        if i != len(parts) - 1:
            lit = lit[:-1] + '\\n"'
        out.append('                    %s\n' % lit)
    return "".join(out)


def build_pages_block(locale):
    lines = []
    for i in range(14):
        side, size, xo, yo, wo = LAYOUT[i]
        hl = ", ".join(_q(h) for h in HIGHLIGHTS[locale][i])
        lines.append(
            '        # Side %d – %s → tekst %s\n'
            '        {\n'
            '            "filename": "%02d(havfrue).png",\n'
            '            "type": "inner",\n'
            '            "side": "%s",\n'
            '            "blocks": [{\n'
            '                "text": p(\n'
            '%s'
            '                ),\n'
            '                "font_size": %d,\n'
            '                "color": "#FFFFFF",\n'
            '                "highlights": [child_name, %s],\n'
            '                "x_offset": %d,\n'
            '                "y_offset": %d,\n'
            % (i + 1, TITLES[i], "VENSTRE" if side == "left" else "HØYRE",
               i + 1, side, py_str(STORY[locale][i]), size, hl, xo, yo)
        )
        if wo:
            lines.append('                "width_offset": %d,\n' % wo)
        lines.append('            }],\n        },\n\n')

    lines.append(
        '        # EKSTRA BLANK SISTE INNERSIDE\n'
        '        {\n'
        '            "filename": "blank-back.png",\n'
        '            "type": "inner",\n'
        '            "side": "left",\n'
        '            "blank_only": True\n'
        '        },\n'
        '        # PER-BOK LASTPAGE — kommer ETTER blank-back, lastes fra base_dir\n'
        '        {\n'
        '            "filename": "lastpage(havfrue).png",\n'
        '            "type": "inner",\n'
        '            "side": "right",\n'
        '            "blank_only": True\n'
        '        },\n\n'
        '        # Bakside\n'
        '        {\n'
        '            "filename": "bakside(havfrue).png",\n'
        '            "type": "cover",\n'
        '            "side": "left",\n'
        '            "blocks": [{\n'
        '                "text": p(\n'
        '%s'
        '                ),\n'
        '                "font_size": 38,\n'
        '                "color": "#FFFFFF",\n'
        '                "highlights": [child_name, %s],\n'
        '            }],\n'
        '        },\n\n'
        '     ]\n\n\n    return pages'
        % (py_str(BACK[locale]),
           ", ".join(_q(h) for h in BACK_HIGHLIGHTS[locale]))
    )
    return "".join(lines)


def patch(locale, text):
    if START_ANCHOR not in text:
        return None, "fant ikke '# Side 1 –'"
    if END_ANCHOR not in text:
        return None, "fant ikke slutten av pages-lista"
    i = text.index(START_ANCHOR)
    j = text.index(END_ANCHOR) + len(END_ANCHOR)
    text = text[:i] + build_pages_block(locale) + text[j:]

    # Den universelle split-layouten (_dp_apply_universal_layout) overstyrer
    # y_offset per side, saa den vertikale plasseringen maa endres DER - ikke i
    # sidedikten. Side 12 delte verdier med side 13; paa den nye kunsten la den
    # oeverste blokka seg over haka til barnet, saa 12 far egne verdier.
    old_off = ("    if number in (12, 13):\n"
               "        top_y = 50\n"
               "        bottom_y = 365\n")
    new_off = ("    if number == 13:\n"
               "        top_y = 50\n"
               "        bottom_y = 365\n"
               "    if number == 12:\n"
               "        top_y = 140\n"
               "        bottom_y = 430\n")
    if old_off in text:
        text = text.replace(old_off, new_off, 1)

    old_cover = '"text": p("[NAVN] blir"),'
    new_cover = '"text": p("%s"),' % COVER_LINE1[locale]
    if old_cover in text and old_cover != new_cover:
        text = text.replace(old_cover, new_cover, 1)
    return text, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--revert", action="store_true")
    args = ap.parse_args()
    if not (args.apply or args.dry_run or args.revert):
        ap.error("velg --dry-run, --apply eller --revert")

    if args.revert:
        for bak in sorted(glob.glob(os.path.join(SCRIPT_DIR, "*", "*.backup-before-%s-*" % TAG))):
            orig = bak.split(".backup-before-")[0]
            shutil.copy2(bak, orig)
            print("  tilbakestilt", os.path.relpath(orig, SCRIPT_DIR))
        return 0

    stamp = time.strftime("%Y%m%d-%H%M%S")
    for locale in LOCALES:
        path = os.path.join(SCRIPT_DIR, locale, "havfruen-text-%s.py" % locale)
        rel = os.path.relpath(path, SCRIPT_DIR).replace(os.sep, "/")
        text = io.open(path, encoding="utf-8").read()
        new_text, err = patch(locale, text)
        if err:
            print("  HOPPER OVER %-32s %s" % (rel, err))
            continue
        ast.parse(new_text)
        print("  %-32s 14 sider + bakside, forside: %s" % (rel, COVER_LINE1[locale]))
        if args.apply:
            shutil.copy2(path, "%s.backup-before-%s-%s" % (path, TAG, stamp))
            io.open(path, "w", encoding="utf-8", newline="").write(new_text)
    print("APPLIED" if args.apply else "DRY-RUN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
