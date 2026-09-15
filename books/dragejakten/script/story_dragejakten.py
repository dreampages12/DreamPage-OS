# -*- coding: utf-8 -*-
"""Historien til Dragejakten - kilde for alle fem spraakfilene.

Kildeteksten er norsk (nb) og bruker "(navn)" som plassholder, akkurat som
build_pages i tekstscriptene. Oversettelsene bruker "{name}", fordi
_DREAMPAGE_TRANSLATIONS slaar opp paa den NORSKE teksten der barnets navn er
byttet ut med {name}.

Ny historie + 14 nye innersider tatt i bruk 2026-09-04.
"""

# side = hvilken halvdel av oppslaget teksten skal staa paa. Regnet ut fra
# tyngdepunktet i headmasken: cx < 0.5 -> "right", ellers "left".
# strong = tyngre bakgrunnsplate bak teksten (lyse/travle halvsider).

COVER_TITLE_NB = "[NAVN] og\nDragejakten"

INTRO_NB = (
    "Takk for at du kjøpte denne personlige historien!\n"
    "I denne boken følger vi (Navn) på et eventyr i en verden full av drager.\n"
    "(Navn) lærer at ekte mot er å hjelpe noen som trenger det.\n"
    "Vi håper historien bringer glede, spenning og fantasifulle øyeblikk."
)

INTRO_TR = {
    "nn": (
        "Takk for at du kjøpte denne personlege historia!\n"
        "I denne boka følgjer vi {name} på eit eventyr i ein verd full av drakar.\n"
        "{name} lærer at ekte mot er å hjelpe nokon som treng det.\n"
        "Vi håpar historia gjev glede, spaning og fantasifulle augneblinkar."
    ),
    "en": (
        "Thank you for purchasing this personal story!\n"
        "In this book we follow {name} on an adventure in a world full of dragons.\n"
        "{name} learns that real courage is helping someone who needs it.\n"
        "We hope the story brings joy, excitement and imaginative moments."
    ),
    "sv": (
        "Tack för att du köpte den här personliga berättelsen!\n"
        "I den här boken följer vi {name} på ett äventyr i en värld full av drakar.\n"
        "{name} lär sig att riktigt mod är att hjälpa någon som behöver det.\n"
        "Vi hoppas att berättelsen ger glädje, spänning och fantasifulla stunder."
    ),
}

BAKSIDE_NB = (
    "Dypt inne i skogen finner (navn) enorme fotspor – og en drage som er lenket fast i en mørk hule.\n"
    "Sammen flyr de over fjellene for å redde dragens lille sønn.\n"
    "Dragejakten er en spennende historie om mot, vennskap og det å hjelpe andre.\n"
    "En personlig barnebok hvor (navn) selv blir helten i sitt eget drageeventyr."
)

BAKSIDE_TR = {
    "nn": (
        "Djupt inne i skogen finn {name} enorme fotspor – og ein drake som er lenka fast i ei mørk hole.\n"
        "Saman flyg dei over fjella for å redde den vesle sonen til draken.\n"
        "Dragejakta er ei spennande historie om mot, venskap og det å hjelpe andre.\n"
        "Ei personleg barnebok der {name} sjølv blir helten i sitt eige drakeeventyr."
    ),
    "en": (
        "Deep in the forest {name} finds enormous footprints – and a dragon chained inside a dark cave.\n"
        "Together they fly over the mountains to rescue the dragon's little son.\n"
        "The Dragon Quest is an exciting story about courage, friendship and helping others.\n"
        "A personal children's book where {name} becomes the hero of his own dragon adventure."
    ),
    "sv": (
        "Djupt inne i skogen hittar {name} enorma fotspår – och en drake som sitter fastkedjad i en mörk grotta.\n"
        "Tillsammans flyger de över bergen för att rädda drakens lilla son.\n"
        "Drakjakten är en spännande berättelse om mod, vänskap och att hjälpa andra.\n"
        "En personlig barnbok där {name} själv blir hjälten i sitt eget drakäventyr."
    ),
}

PAGES = [
    dict(
        n=1, side="left", strong=False, expr="noytral",
        hl=["(navn)", "utforske", "skogen", "fotspor"],
        nb=(
            "(navn) likte å utforske skogen.\n"
            "Han kjente hver sti og hvert eneste tre.\n"
            "Men denne dagen fant han noe han aldri hadde sett før.\n"
            "Enorme fotspor i bakken – så store at begge føttene hans fikk plass i ett av dem."
        ),
        nn=(
            "{name} likte å utforske skogen.\n"
            "Han kjende kvar sti og kvart einaste tre.\n"
            "Men denne dagen fann han noko han aldri hadde sett før.\n"
            "Enorme fotspor i bakken – så store at begge føtene hans fekk plass i eitt av dei."
        ),
        en=(
            "{name} loved exploring the forest.\n"
            "He knew every path and every single tree.\n"
            "But on this day he found something he had never seen before.\n"
            "Enormous footprints in the ground – so big that both his feet fit inside one of them."
        ),
        sv=(
            "{name} tyckte om att utforska skogen.\n"
            "Han kände varje stig och varje enda träd.\n"
            "Men den här dagen hittade han något han aldrig hade sett förut.\n"
            "Enorma fotspår i marken – så stora att båda hans fötter fick plats i ett av dem."
        ),
    ),
    dict(
        n=2, side="right", strong=False, expr="noytral",
        hl=["(navn)", "Sporene", "dypere", "skogen"],
        nb=(
            "Sporene fortsatte mellom trærne.\n"
            "(navn) fulgte etter, dypere og dypere inn i skogen.\n"
            "Greinene lukket seg over ham, og lyden av fugler ble borte.\n"
            "Hvem hadde laget dem? Og hvor kunne de føre?"
        ),
        nn=(
            "Spora heldt fram mellom trea.\n"
            "{name} følgde etter, djupare og djupare inn i skogen.\n"
            "Greinene lukka seg over han, og lyden av fuglar vart borte.\n"
            "Kven hadde laga dei? Og kvar kunne dei føre?"
        ),
        en=(
            "The tracks continued between the trees.\n"
            "{name} followed them, deeper and deeper into the forest.\n"
            "The branches closed above him, and the sound of birds faded away.\n"
            "Who had made them? And where could they lead?"
        ),
        sv=(
            "Spåren fortsatte mellan träden.\n"
            "{name} följde efter, djupare och djupare in i skogen.\n"
            "Grenarna slöt sig ovanför honom, och ljudet av fåglar tystnade.\n"
            "Vem hade gjort dem? Och vart kunde de leda?"
        ),
    ),
    dict(
        n=3, side="left", strong=True, expr="noytral",
        hl=["(navn)", "hule", "blått", "mot"],
        nb=(
            "Plutselig stoppet sporene foran en mørk hule i fjellet.\n"
            "Fra innsiden kom et svakt blått lys som pustet, av og på.\n"
            "Langt der inne hørte han noe tungt puste i mørket.\n"
            "(navn) tok mot til seg og gikk inn."
        ),
        nn=(
            "Plutseleg stoppa spora framfor ei mørk hole i fjellet.\n"
            "Frå innsida kom eit svakt blått lys som pusta, av og på.\n"
            "Langt der inne høyrde han noko tungt puste i mørket.\n"
            "{name} tok mot til seg og gjekk inn."
        ),
        en=(
            "Suddenly the tracks stopped in front of a dark cave in the mountain.\n"
            "From inside came a faint blue light that breathed, on and off.\n"
            "Far in there he heard something heavy breathing in the dark.\n"
            "{name} gathered his courage and walked in."
        ),
        sv=(
            "Plötsligt stannade spåren framför en mörk grotta i berget.\n"
            "Inifrån kom ett svagt blått ljus som andades, av och på.\n"
            "Långt där inne hörde han något tungt andas i mörkret.\n"
            "{name} tog mod till sig och gick in."
        ),
    ),
    dict(
        n=4, side="left", strong=False, expr="noytral",
        hl=["(navn)", "drage", "lenket", "redd"],
        nb=(
            "Langt inne i hulen fikk (navn) øye på noe enormt.\n"
            "En stor blågrønn drage var lenket fast til fjellveggen!\n"
            "Tunge jernlenker lå rundt beina hans.\n"
            "Men dragen så ikke farlig ut.\n"
            "Den så redd ut."
        ),
        nn=(
            "Langt inne i hola fekk {name} auge på noko enormt.\n"
            "Ein stor blågrøn drake var lenka fast til fjellveggen!\n"
            "Tunge jernlenkjer låg rundt beina hans.\n"
            "Men draken såg ikkje farleg ut.\n"
            "Han såg redd ut."
        ),
        en=(
            "Far inside the cave {name} spotted something enormous.\n"
            "A great blue-green dragon was chained to the rock wall!\n"
            "Heavy iron chains lay around its legs.\n"
            "But the dragon did not look dangerous.\n"
            "It looked scared."
        ),
        sv=(
            "Långt inne i grottan fick {name} syn på något enormt.\n"
            "En stor blågrön drake satt fastkedjad vid bergväggen!\n"
            "Tunga järnkedjor låg runt hans ben.\n"
            "Men draken såg inte farlig ut.\n"
            "Den såg rädd ut."
        ),
    ),
    dict(
        n=5, side="right", strong=False, expr="smil",
        hl=["(navn)", "KLANK", "Lenken", "fri"],
        nb=(
            "(navn) løp bort til dragen.\n"
            "Låsen var gammel og rusten. Han dro og vred, og dro enda en gang, helt til den endelig ga etter.\n"
            "KLANK!\n"
            "Lenken falt i bakken.\n"
            "Dragen var fri!"
        ),
        nn=(
            "{name} sprang bort til draken.\n"
            "Låsen var gammal og rusten. Han drog og vreid, og drog endå ein gong, heilt til han endeleg gav etter.\n"
            "KLANK!\n"
            "Lenkja fall i bakken.\n"
            "Draken var fri!"
        ),
        en=(
            "{name} ran over to the dragon.\n"
            "The lock was old and rusty. He pulled and twisted, and pulled once more, until it finally gave way.\n"
            "CLANK!\n"
            "The chain fell to the ground.\n"
            "The dragon was free!"
        ),
        sv=(
            "{name} sprang fram till draken.\n"
            "Låset var gammalt och rostigt. Han drog och vred, och drog en gång till, tills det äntligen gav vika.\n"
            "KLANG!\n"
            "Kedjan föll till marken.\n"
            "Draken var fri!"
        ),
    ),
    dict(
        n=6, side="left", strong=True, expr="noytral",
        hl=["(navn)", "dragen", "Sønnen", "fanget"],
        nb=(
            "«Takk, (navn),» sa dragen. Stemmen var dyp og varm.\n"
            "Men så ble den alvorlig.\n"
            "«Sønnen min er også fanget – jeg klarer ikke å redde ham alene.»\n"
            "(navn) kjente hjertet slå fortere. Men han visste med én gang hva han måtte gjøre."
        ),
        nn=(
            "«Takk, {name},» sa draken. Stemma var djup og varm.\n"
            "Men så vart han alvorleg.\n"
            "«Sonen min er òg fanga – eg klarer ikkje å redde han åleine.»\n"
            "{name} kjende hjartet slå fortare. Men han visste med ein gong kva han måtte gjere."
        ),
        en=(
            "\"Thank you, {name},\" said the dragon. Its voice was deep and warm.\n"
            "Then it turned serious.\n"
            "\"My son is trapped too – I cannot rescue him alone.\"\n"
            "{name} felt his heart beat faster. But he knew at once what he had to do."
        ),
        sv=(
            "«Tack, {name},» sa draken. Rösten var djup och varm.\n"
            "Men så blev den allvarlig.\n"
            "«Min son är också fångad – jag klarar inte att rädda honom ensam.»\n"
            "{name} kände hjärtat slå fortare. Men han visste med en gång vad han måste göra."
        ),
    ),
    dict(
        n=7, side="left", strong=True, expr="smil",
        hl=["(navn)", "ryggen", "vingene", "dragen"],
        nb=(
            "Dragen bøyde seg helt ned til bakken.\n"
            "«Hopp opp!»\n"
            "(navn) klatret forsiktig opp på ryggen og holdt godt fast i de varme skjellene.\n"
            "Så spredte dragen de enorme vingene sine."
        ),
        nn=(
            "Draken bøygde seg heilt ned til bakken.\n"
            "«Hopp opp!»\n"
            "{name} klatra forsiktig opp på ryggen og heldt godt fast i dei varme skjela.\n"
            "Så spreidde draken dei enorme vengene sine."
        ),
        en=(
            "The dragon bowed all the way down to the ground.\n"
            "\"Climb on!\"\n"
            "{name} carefully climbed onto its back and held tight to the warm scales.\n"
            "Then the dragon spread its enormous wings."
        ),
        sv=(
            "Draken böjde sig ända ner till marken.\n"
            "«Hoppa upp!»\n"
            "{name} klättrade försiktigt upp på ryggen och höll hårt i de varma fjällen.\n"
            "Sedan spred draken ut sina enorma vingar."
        ),
    ),
    dict(
        n=8, side="right", strong=True, expr="smil",
        hl=["(navn)", "WHOOSH", "skogen", "fløyet"],
        nb=(
            "WHOOSH!\n"
            "De skjøt ut av hulen og høyt opp over skogen.\n"
            "Vinden suste i ørene hans, og under dem ble trærne små som fyrstikker.\n"
            "(navn) hadde aldri fløyet før. Han lo høyt."
        ),
        nn=(
            "WHOOSH!\n"
            "Dei skaut ut av hola og høgt opp over skogen.\n"
            "Vinden susa i øyra hans, og under dei vart trea små som fyrstikker.\n"
            "{name} hadde aldri flydd før. Han lo høgt."
        ),
        en=(
            "WHOOSH!\n"
            "They shot out of the cave and high up above the forest.\n"
            "The wind rushed past his ears, and below them the trees became as small as matchsticks.\n"
            "{name} had never flown before. He laughed out loud."
        ),
        sv=(
            "WHOOSH!\n"
            "De sköt ut ur grottan och högt upp över skogen.\n"
            "Vinden susade i hans öron, och under dem blev träden små som tändstickor.\n"
            "{name} hade aldrig flugit förut. Han skrattade högt."
        ),
    ),
    dict(
        n=9, side="left", strong=False, expr="noytral",
        hl=["(navn)", "fjell", "steinruiner", "drage"],
        nb=(
            "Snart dukket et mørkt fjell opp foran dem.\n"
            "Høyt oppe mellom gamle steinruiner satt en liten drage fanget bak et gitter.\n"
            "Han var ikke større enn (navn) selv.\n"
            "«Der er han!» ropte (navn)."
        ),
        nn=(
            "Snart dukka eit mørkt fjell opp framfor dei.\n"
            "Høgt oppe mellom gamle steinruinar sat ein liten drake fanga bak eit gitter.\n"
            "Han var ikkje større enn {name} sjølv.\n"
            "«Der er han!» ropte {name}."
        ),
        en=(
            "Soon a dark mountain appeared ahead of them.\n"
            "High up among old stone ruins sat a little dragon trapped behind bars.\n"
            "He was no bigger than {name} himself.\n"
            "\"There he is!\" shouted {name}."
        ),
        sv=(
            "Snart dök ett mörkt berg upp framför dem.\n"
            "Högt uppe bland gamla stenruiner satt en liten drake fångad bakom galler.\n"
            "Han var inte större än {name} själv.\n"
            "«Där är han!» ropade {name}."
        ),
    ),
    dict(
        n=10, side="right", strong=True, expr="noytral",
        hl=["(navn)", "murene", "gitteret", "redd"],
        nb=(
            "(navn) snek seg inn mellom de gamle murene. Steinene var kalde og glatte.\n"
            "Den lille dragen skalv bak gitteret og trakk seg bakover.\n"
            "«Ikke vær redd,» hvisket (navn).\n"
            "«Jeg skal få deg ut.»"
        ),
        nn=(
            "{name} sneik seg inn mellom dei gamle murane. Steinane var kalde og glatte.\n"
            "Den vesle draken skalv bak gitteret og trekte seg bakover.\n"
            "«Ikkje ver redd,» kviskra {name}.\n"
            "«Eg skal få deg ut.»"
        ),
        en=(
            "{name} crept in between the old walls. The stones were cold and slippery.\n"
            "The little dragon trembled behind the bars and backed away.\n"
            "\"Don't be afraid,\" whispered {name}.\n"
            "\"I will get you out.\""
        ),
        sv=(
            "{name} smög sig in mellan de gamla murarna. Stenarna var kalla och hala.\n"
            "Den lilla draken darrade bakom gallret och backade undan.\n"
            "«Var inte rädd,» viskade {name}.\n"
            "«Jag ska få ut dig.»"
        ),
    ),
    dict(
        n=11, side="left", strong=False, expr="smil",
        hl=["(navn)", "låsen", "KLIKK", "Porten"],
        nb=(
            "(navn) fant låsen og tok godt tak.\n"
            "Én gang.\n"
            "To ganger.\n"
            "KLIKK!\n"
            "Porten åpnet seg, og den lille dragen løp rett ut og gned hodet mot armen hans."
        ),
        nn=(
            "{name} fann låsen og tok godt tak.\n"
            "Éin gong.\n"
            "To gonger.\n"
            "KLIKK!\n"
            "Porten opna seg, og den vesle draken sprang rett ut og gnei hovudet mot armen hans."
        ),
        en=(
            "{name} found the lock and took a firm grip.\n"
            "Once.\n"
            "Twice.\n"
            "CLICK!\n"
            "The gate swung open, and the little dragon ran straight out and rubbed its head against his arm."
        ),
        sv=(
            "{name} hittade låset och tog ett stadigt tag.\n"
            "En gång.\n"
            "Två gånger.\n"
            "KLICK!\n"
            "Porten öppnades, och den lilla draken sprang rakt ut och gned huvudet mot hans arm."
        ),
    ),
    dict(
        n=12, side="right", strong=True, expr="smil",
        hl=["(navn)", "dragen", "Dragejakten", "smilte"],
        nb=(
            "Den store dragen skyndte seg fram.\n"
            "Den lille dragen kastet seg inntil faren sin, og de la vingene rundt hverandre.\n"
            "(navn) smilte.\n"
            "Dragejakten var endelig over."
        ),
        nn=(
            "Den store draken skunda seg fram.\n"
            "Den vesle draken kasta seg inntil far sin, og dei la vengene rundt kvarandre.\n"
            "{name} smilte.\n"
            "Dragejakta var endeleg over."
        ),
        en=(
            "The big dragon hurried over.\n"
            "The little dragon threw itself against its father, and they folded their wings around each other.\n"
            "{name} smiled.\n"
            "The Dragon Quest was finally over."
        ),
        sv=(
            "Den stora draken skyndade fram.\n"
            "Den lilla draken kastade sig intill sin pappa, och de lade vingarna om varandra.\n"
            "{name} log.\n"
            "Drakjakten var äntligen över."
        ),
    ),
    dict(
        n=13, side="left", strong=True, expr="smil",
        hl=["(navn)", "fjellene", "dragen", "trygt"],
        nb=(
            "De tre fløy sammen tilbake over fjellene mens solen gikk ned.\n"
            "Den lille dragen fløy ved siden av faren sin, mens (navn) satt trygt på ryggen til den store dragen.\n"
            "Langt foran dem lå et sted (navn) aldri hadde sett før."
        ),
        nn=(
            "Dei tre flaug saman tilbake over fjella medan sola gjekk ned.\n"
            "Den vesle draken flaug ved sida av far sin, medan {name} sat trygt på ryggen til den store draken.\n"
            "Langt framfor dei låg ein stad {name} aldri hadde sett før."
        ),
        en=(
            "The three of them flew back together over the mountains as the sun went down.\n"
            "The little dragon flew beside its father, while {name} sat safely on the big dragon's back.\n"
            "Far ahead of them lay a place {name} had never seen before."
        ),
        sv=(
            "De tre flög tillsammans tillbaka över bergen medan solen gick ner.\n"
            "Den lilla draken flög bredvid sin pappa, medan {name} satt tryggt på den stora drakens rygg.\n"
            "Långt framför dem låg en plats {name} aldrig hade sett förut."
        ),
    ),
    dict(
        n=14, side="right", strong=True, expr="smil",
        hl=["(navn)", "hemmelig", "drageskjell", "Eventyret"],
        nb=(
            "Bak fjellene lå en hemmelig dal full av drager.\n"
            "Store og små, i alle farger, fløy de over trærne.\n"
            "Før (navn) dro hjem, ga dragen ham et glødende drageskjell.\n"
            "«Behold dette,» sa dragen. «En dag kan vi trenge deg igjen.»\n"
            "(navn) så ned på skjellet. Plutselig begynte det å lyse enda sterkere.\n"
            "Eventyret var kanskje ikke helt over likevel…"
        ),
        nn=(
            "Bak fjella låg ein hemmeleg dal full av drakar.\n"
            "Store og små, i alle fargar, flaug dei over trea.\n"
            "Før {name} drog heim, gav draken han eit glødande drakeskjel.\n"
            "«Behald dette,» sa draken. «Ein dag kan vi trenge deg igjen.»\n"
            "{name} såg ned på skjelet. Plutseleg byrja det å lyse endå sterkare.\n"
            "Eventyret var kanskje ikkje heilt over likevel…"
        ),
        en=(
            "Behind the mountains lay a secret valley full of dragons.\n"
            "Big ones and small ones, in every colour, flying above the trees.\n"
            "Before {name} went home, the dragon gave him a glowing dragon scale.\n"
            "\"Keep this,\" said the dragon. \"One day we may need you again.\"\n"
            "{name} looked down at the scale. Suddenly it began to shine even brighter.\n"
            "Maybe the adventure was not quite over after all…"
        ),
        sv=(
            "Bakom bergen låg en hemlig dal full av drakar.\n"
            "Stora och små, i alla färger, flög de över träden.\n"
            "Innan {name} åkte hem, gav draken honom ett glödande drakfjäll.\n"
            "«Behåll det här,» sa draken. «En dag kan vi behöva dig igen.»\n"
            "{name} tittade ner på drakfjället. Plötsligt började det lysa ännu starkare.\n"
            "Äventyret var kanske inte riktigt över ändå…"
        ),
    ),
]
