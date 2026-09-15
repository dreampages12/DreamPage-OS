# -*- coding: utf-8 -*-
"""Skriv inn den nye Dinosaurenes dal-historien (portal + T-rex) i alle 5 locale-script.

Bruk:
  python script/rewrite_dinosaur_story.py --dry-run
  python script/rewrite_dinosaur_story.py --apply
  python script/rewrite_dinosaur_story.py --revert
"""
import argparse
import glob
import os
import re
import shutil
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
LOCALES = ["nb", "nn", "en-US", "en-GB", "sv"]
STAMP = time.strftime("%Y%m%d-%H%M%S")
SUFFIX = ".backup-before-dino-nystory-"

# side = motsatt halvdel av der barnet står i den nye kunsten
# (oddetall: barnet til venstre -> tekst høyre, partall: omvendt)
STORY = [
    (1, "right",
     "(Navn) gikk den samme stien som alltid, den bak trærne der skogen er tettest.\n"
     "Han kjente hver stein og hver rot på veien.\n"
     "Men i dag var noe annerledes. Langt inne mellom stammene lyste det.\n"
     "Et mykt lys som han aldri hadde sett før.",
     ["annerledes", "lys"]),
    (2, "left",
     "(Navn) stoppet og lyttet. Skogen var helt stille – ikke en fugl, ikke et vindpust.\n"
     "Så gikk han nærmere, steg for steg.\n"
     "Mellom trærne fant han en liten åpning, og der glitret og dirret luften.\n"
     "Det var nesten som om skogen ville vise ham en hemmelig vei.",
     ["stille", "hemmelig"]),
    (3, "right",
     "Plutselig vokste lyset seg større, helt til det sto som en ring foran ham.\n"
     "En lysende portal!\n"
     "Gjennom den kunne (Navn) skimte noe helt annet enn skogen sin:\n"
     "enorme planter, høye fjell – og noe veldig stort som beveget seg.",
     ["lysende", "portal"]),
    (4, "left",
     "(Navn) kjente det kile i magen, og hjertet slo fort.\n"
     "Hvor førte portalen? Og kom han seg tilbake igjen?\n"
     "Han trakk pusten dypt, samlet motet og tok ett forsiktig skritt frem.\n"
     "Så gikk han rett gjennom det dansende lyset.",
     ["motet", "portalen"]),
    (5, "right",
     "På den andre siden stoppet (Navn) helt opp.\n"
     "Foran ham lå en enorm, grønn dal – større enn noe han hadde sett.\n"
     "Langhalser vandret rolig mellom trærne, og fossefall raste nedover fjellsidene.\n"
     "Han var ikke i skogen sin lenger. Han var i Dinosaurenes dal.",
     ["dal", "Langhalser"]),
    (6, "left",
     "Plutselig raslet det i bregnene rett ved siden av ham.\n"
     "(Navn) snudde seg – og ut kom en liten dinosaur!\n"
     "Den stanset, la hodet på skakke og så nysgjerrig på ham.\n"
     "«Jeg heter Lumi,» sa den. «Hvem er du?»",
     ["Lumi", "dinosaur"]),
    (7, "right",
     "«(Navn),» svarte han. Da smilte Lumi med hele munnen.\n"
     "«Bli med, da! Jeg skal vise deg dalen.»\n"
     "Sammen fulgte de en smal sti gjennom det høye gresset.\n"
     "Rundt dem trampet dinosaurer mellom trærne, og nye lyder kom fra alle kanter.",
     ["Lumi", "Sammen"]),
    (8, "left",
     "Brått stoppet Lumi midt i steget.\n"
     "Foran dem, rett i gjørma, lå et fotspor.\n"
     "Det var så stort at (Navn) kunne stått oppi det med begge føttene.\n"
     "«Den som lagde dette,» hvisket Lumi, «er mye større enn oss.»",
     ["fotspor", "Lumi"]),
    (9, "right",
     "Sporene fortsatte inn mellom trærne, og (Navn) og Lumi fulgte etter.\n"
     "De endte i en liten lysning – og der lå en dinosaurunge fast under tunge greiner.\n"
     "Den pep svakt og fikk ikke reist seg.\n"
     "«Vi må hjelpe den!» sa (Navn), og løp bort.",
     ["dinosaurunge", "hjelpe"]),
    (10, "left",
     "Da ristet bakken under føttene deres. DUNK. DUNK. DUNK.\n"
     "Et brøl fylte hele skogen, så høyt at bladene skalv.\n"
     "Lumi krøp sammen bak en stein.\n"
     "Og mellom trærne kom den: en enorm T-rex.",
     ["brøl", "T-rex"]),
    (11, "right",
     "(Navn) var redd. Han hadde aldri vært så redd før.\n"
     "Men han ble stående – for dinosaurungen lå der fortsatt.\n"
     "Og da oppdaget han noe: T-rexen brølte ikke mot ham.\n"
     "Den så på ungen under greinene, og øynene var ikke sinte. De var bekymrede.",
     ["redd", "bekymrede"]),
    (12, "left",
     "«Den vil hjelpe den også,» sa (Navn). «Kom igjen, Lumi!»\n"
     "(Navn) tok tak i en grein og dro alt han orket.\n"
     "Lumi dyttet med skulderen, og T-rexen løftet den tyngste stokken med munnen.\n"
     "Én etter én ga greinene etter – helt til ungen endelig kom seg løs.",
     ["hjelpe", "Lumi"]),
    (13, "right",
     "Dinosaurungen reiste seg og løp rett bort til T-rexen.\n"
     "Så senket det store hodet seg rolig ned mot (Navn), helt nært.\n"
     "Nå forsto han det: det største brølet betyr ikke alltid fare.\n"
     "Han hadde vært redd – og likevel modig. Det var det som telte.",
     ["modig", "brølet"]),
    (14, "left",
     "Da solen sank bak fjellene, lyste portalen opp igjen mellom trærne.\n"
     "«Kommer du tilbake?» spurte Lumi.\n"
     "«Jeg lover,» sa (Navn), og vinket farvel før han gikk hjem gjennom lyset.\n"
     "Bak ham lå Dinosaurenes dal og ventet. Dette eventyret var bare begynnelsen.",
     ["Lumi", "eventyret"]),
]


def build_block() -> str:
    out = []
    for num, side, text, hl in STORY:
        lines = text.split("\n")
        body = "".join(
            '                    "%s%s"\n' % (ln.replace('"', '\\"'),
                                              "\\n" if i < len(lines) - 1 else "")
            for i, ln in enumerate(lines)
        )
        hl_src = ", ".join(["child_name"] + ['"%s"' % h for h in hl])
        out.append(
            "        # Side %d\n"
            "        {\n"
            '            "filename": "%02d(dinosaur).png",\n'
            '            "type": "inner",\n'
            '            "side": "%s",\n'
            '            "blocks": [{\n'
            '                "text": p(\n'
            "%s"
            "                ),\n"
            '                "font_size": 34,\n'
            '                "color": "#FFFFFF",\n'
            '                "highlights": [%s],\n'
            "            }],\n"
            "        },\n" % (num, num, side, body, hl_src)
        )
    return "\n".join(out) + "\n"


INTRO_NEW = (
    '                    "Takk for at du kjøpte denne personlige historien!\\n"\n'
    '                    "I denne boken følger vi (Navn) gjennom en lysende portal og inn i Dinosaurenes dal."\n'
    '                    " (Navn) lærer at ekte mot er å hjelpe andre – selv når noe virker skummelt.\\n"\n'
    '                    "Vi håper historien bringer glede, trygghet og fantasifulle øyeblikk."\n'
)

BAKSIDE_NEW = (
    '                    "Denne boken handler om mot. Om å våge å gå inn i det ukjente – og om å hjelpe andre når de trenger det.\\n"\n'
    '                    "Gjennom et magisk møte i Dinosaurenes dal lærer (Navn) at det som virker skummelt ikke alltid er farlig, og at selv det største brølet kan komme fra noen som bare vil hjelpe.\\n"\n'
    '                    "En varm og personlig historie om vennskap, nysgjerrighet og om å være modig selv når hjertet banker fort.\\n"\n'
    '                    "En bok som gir trygghet, selvtillit – og minner barnet på at også de kan være en helt."\n'
)

BAKSIDE_HL = ('                "highlights": [child_name, "mot", "Dinosaurenes dal", '
              '"vennskap", "modig", "helt"],\n')


def patch(src: str) -> str:
    # 1) historiesidene 1-14
    start = src.index("        # Side 1\n")
    end = src.index("        # EKSTRA BLANK")
    src = src[:start] + build_block() + src[end:]

    # 2) intro-teksten på dreampage-first ("blank"-siden)
    m = re.search(r'( *"Takk for at du kjøpte.*?\n)( *"Vi håper historien.*?\n)',
                  src, re.S)
    if not m:
        raise SystemExit("fant ikke intro-teksten")
    src = src[:m.start()] + INTRO_NEW + src[m.end():]

    # 3) baksideteksten + highlights
    m = re.search(r'( *"Denne boken handler om mot\..*?\n)( *"En bok som gir trygghet.*?\n)',
                  src, re.S)
    if not m:
        raise SystemExit("fant ikke baksideteksten")
    src = src[:m.start()] + BAKSIDE_NEW + src[m.end():]
    src = re.sub(r' *"highlights": \[child_name, "Påskedalen".*?\],\n', BAKSIDE_HL, src)
    return src


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--revert", action="store_true")
    args = ap.parse_args()

    for loc in LOCALES:
        path = os.path.join(ROOT, loc, "dinosaur-text-%s.py" % loc)
        if args.revert:
            backups = sorted(glob.glob(path + SUFFIX + "*"))
            if not backups:
                print("ingen backup for", loc)
                continue
            shutil.copyfile(backups[-1], path)
            print("gjenopprettet", loc, "fra", os.path.basename(backups[-1]))
            continue

        src = open(path, encoding="utf-8").read()
        new = patch(src)
        compile(new, path, "exec")
        if args.apply:
            shutil.copyfile(path, path + SUFFIX + STAMP)
            with open(path, "w", encoding="utf-8", newline="") as fh:
                fh.write(new)
            print("oppdatert", path)
        else:
            print("%-6s OK - %d -> %d tegn" % (loc, len(src), len(new)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
