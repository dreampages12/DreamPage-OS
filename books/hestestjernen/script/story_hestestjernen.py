# -*- coding: utf-8 -*-
"""Kildetekst for Hestestjernen.

14 oppslag (2048x1024), ren annenhver side - ingen kvadratsider, ingen
Lastpage. Sideregnskap: 14 x 2 + intro + blank-back = 30 innersider.

Sidevalget ("left"/"right") er REGNET UT fra tyngdepunktet i headmasken, ikke
gjettet: cx < 0.5 -> figuren staar til venstre -> teksten skal til hoeyre.

    01 .78 L | 02 .18 R | 03 .68 L | 04 .34 R | 05 .62 L | 06 .75 L | 07 .79 L
    08 .25 R | 09 .34 R | 10 .31 R | 11 .67 L | 12 .77 L | 13 .72 L | 14 .74 L

Alle 15 maskene i bildepakka er ekte (dekning 0.004-0.043). Ingen av dem er en
forkledd kopi av illustrasjonen - det var fella i den-skjulte-verdenen, der
side 03 hadde dekning 0.68.

MERK: kommentarene i denne fila er ASCII, men SELVE TEKSTEN skal ha ekte
norske tegn. Den trykkes.

Historien er skrevet etter illustrasjonene: stall -> stell -> foerste ridetur
-> hinder -> vennskap -> trener -> stevnedag -> seier. Erstattes hvis brukeren
sender sin egen tekst.

MERK om side 6: treneren staar omtrent paa cx 0.35, altsaa inne i
tekstkolonnen paa venstre side. Teksten er holdt kort der, og
`_dp_layout_offsets` i build-scriptet skyver blokkene klar av henne.
"""

COVER_NB = "(Navn) blir\nHestestjerne"

BACK_NB = (
    "Denne boken handler om det som skjer når et barn og en hest finner "
    "hverandre.\n"
    "(Navn) har aldri sittet på en hest før. Hun vet ikke om hun tør. Men "
    "Stjerne ser på henne med de rolige, mørke øynene sine — og så begynner "
    "alt.\n"
    "En varm fortelling om tålmodighet, om å falle og reise seg igjen, og om "
    "et vennskap som bærer helt fram til stevnedagen.\n"
    "En bok som minner barnet på at de aller største drømmene begynner med "
    "ett rolig skritt."
)
BACK_HL = ["hest", "Stjerne", "tålmodighet", "vennskap", "drømmene"]

# (side, tekst, highlights)
PAGES_NB = [
    # Side 1 - foerste moete i stallen. Jenta til hoeyre, gangen tom til venstre.
    ("left",
     "Det luktet høy og sol inne i stallen.\n"
     "Helt bakerst, i den siste boksen, stod en stor brun hest og så rett på "
     "(Navn).\n"
     "Hun hadde en hvit stjerne midt i pannen.\n"
     "«Hei,» sa (Navn) stille, og rakte hånden forsiktig fram.",
     ["høy", "stjerne", "hånden"]),

    # Side 2 - stell. Jenta til venstre.
    ("right",
     "Hver dag etter skolen kom (Navn) tilbake til stallen.\n"
     "Hun lærte hvordan man holder en børste, og hvor hardt man tør å ta.\n"
     "Stjerne stod helt stille og lot henne holde på.\n"
     "Det var da (Navn) skjønte at hesten hadde begynt å stole på henne.",
     ["børste", "stille", "stole"]),

    # Side 3 - foerste ridetur i ridebanen, kveldssol.
    ("left",
     "En kveld sa treneren: «I dag tror jeg du er klar.»\n"
     "(Navn) satte foten i stigbøylen, og så satt hun der oppe.\n"
     "Bakken var lenger unna enn hun hadde trodd, og hjertet slo hardt.\n"
     "Men Stjerne gikk rolig av seg selv, skritt for skritt langs gjerdet.",
     ["treneren", "stigbøylen", "rolig"]),

    # Side 4 - foerste lille hinder. Jenta til venstre.
    ("right",
     "Etter noen uker lå det en liten bom på banen.\n"
     "«Hun hopper hvis du tør å la henne,» sa treneren.\n"
     "(Navn) tok et tak i manen, lente seg framover og lukket øynene.\n"
     "Ett sprang, og så var de på andre siden. Hun hadde ikke engang skreket.",
     ["bom", "manen", "sprang"]),

    # Side 5 - stille oeyeblikk i hagen.
    ("left",
     "Noen dager ble de bare stående sammen i hagen bak stallen.\n"
     "(Navn) la kinnet mot den varme halsen og kjente hesten puste.\n"
     "Hun sa ingenting, for det var ingenting som måtte sies.\n"
     "Dette var favorittstedet hennes i hele verden.",
     ["hagen", "puste", "favorittstedet"]),

    # Side 6 - treneren. KORT: treneren staar i tekstkolonnen.
    ("left",
     "«Det er et stevne om tre uker,» sa treneren en morgen.\n"
     "«Vil du prøve?»\n"
     "(Navn) kjente det kribble helt ut i fingrene.\n"
     "Så nikket hun.",
     ["stevne", "prøve", "nikket"]),

    # Side 7 - dagen foer. Sal paa stativet, hun leier Stjerne ut.
    ("left",
     "De trente hver eneste dag som var igjen.\n"
     "(Navn) lærte å legge på salen selv, og å stramme gjorden akkurat nok.\n"
     "Hun pusset Stjerne til pelsen skinte som våt stein.\n"
     "Dagen før stevnet stod de to lenge i stalldøra og så ut på banen.",
     ["salen", "gjorden", "skinte"]),

    # Side 8 - ridning i dressurbanen, sommerfugler.
    ("right",
     "Den siste kvelden red de en runde helt alene.\n"
     "Solen lå lavt over gjerdene, og sommerfuglene fulgte dem langs rosene.\n"
     "(Navn) kjente at hun ikke var nervøs lenger.\n"
     "Hun og Stjerne kunne dette. De hadde gjort det hundre ganger.",
     ["Solen", "sommerfuglene", "nervøs"]),

    # Side 9 - stevnemorgen, veien inn.
    ("right",
     "Stevnemorgenen var lys og helt stille.\n"
     "De gikk sakte nedover stien mellom blomsterkassene.\n"
     "Langt framme hørte (Navn) stemmer og en høyttaler.\n"
     "Stjerne løftet hodet og spisset ørene, som om hun visste hva som ventet.",
     ["Stevnemorgenen", "stien", "ørene"]),

    # Side 10 - inn i den store hallen. Publikum, dommere.
    ("right",
     "Så åpnet portene seg til den store hallen.\n"
     "Det satt folk på alle tribunene, og dommerne satt ved et langt bord.\n"
     "Hindrene virket høyere her inne enn hjemme på banen.\n"
     "(Navn) tok et dypt pust og klappet Stjerne to ganger på halsen.",
     ["hallen", "dommerne", "Hindrene"]),

    # Side 11 - selve hoppet.
    ("left",
     "Klokken ringte, og de satte av.\n"
     "Ett hinder. To. Tre. (Navn) hørte bare hovene og sin egen pust.\n"
     "Foran det siste hoppet kjente hun Stjerne samle seg under henne.\n"
     "Så løftet de seg, og et øyeblikk var de ikke borti bakken i det hele "
     "tatt.",
     ["hinder", "hovene", "løftet"]),

    # Side 12 - siste galopp ut.
    ("left",
     "De landet mykt og galopperte videre mot utgangen.\n"
     "Ingen bommer var nede. Ikke en eneste.\n"
     "Publikum reiste seg, men (Navn) hørte det nesten ikke.\n"
     "Hun bare bøyde seg fram og hvisket: «Du gjorde det. Du gjorde det.»",
     ["bommer", "Publikum", "hvisket"]),

    # Side 13 - klemmen etterpaa.
    ("left",
     "Utenfor banen hoppet (Navn) av og la begge armene rundt halsen på "
     "Stjerne.\n"
     "Hesten stod stille og lot henne holde på, akkurat som den første dagen "
     "i stallen.\n"
     "«Vi klarte det sammen,» sa hun inn i den varme pelsen.\n"
     "Det var det beste øyeblikket i hele boken, og det stod ingen dommere og "
     "så på.",
     ["armene", "sammen", "øyeblikket"]),

    # Side 14 - seieren.
    ("left",
     "Da navnet hennes ble ropt opp, gikk de inn i ringen igjen.\n"
     "Noen hengte en blå sløyfe på hodelaget til Stjerne, og ga (Navn) en "
     "pokal som skinte i solen.\n"
     "Alle klappet, og blomsterblader fauk gjennom luften.\n"
     "Men (Navn) så ikke på pokalen. Hun så på hesten sin.",
     ["sløyfe", "pokal", "klappet"]),
]

# ---------------------------------------------------------------------------
# nynorsk
# ---------------------------------------------------------------------------
COVER_NN = "{name} blir\nHestestjerne"

BACK_NN = (
    "Denne boka handlar om det som skjer når eit barn og ein hest finn "
    "kvarandre.\n"
    "{name} har aldri sete på ein hest før. Ho veit ikkje om ho vågar. Men "
    "Stjerne ser på henne med dei rolege, mørke augo sine — og så byrjar "
    "alt.\n"
    "Ei varm forteljing om tålmod, om å falle og reise seg att, og om eit "
    "venskap som ber heilt fram til stemnedagen.\n"
    "Ei bok som minner barnet på at dei aller største draumane byrjar med "
    "eitt roleg steg."
)

PAGES_NN = [
    "Det lukta høy og sol inne i stallen.\n"
    "Heilt bakarst, i den siste boksen, stod ein stor brun hest og såg rett "
    "på {name}.\n"
    "Ho hadde ei kvit stjerne midt i panna.\n"
    "«Hei,» sa {name} stilt, og rekte handa varsamt fram.",

    "Kvar dag etter skulen kom {name} attende til stallen.\n"
    "Ho lærte korleis ein held ein børste, og kor hardt ein vågar å ta.\n"
    "Stjerne stod heilt stille og lét henne halde på.\n"
    "Det var då {name} skjøna at hesten hadde byrja å stole på henne.",

    "Ein kveld sa trenaren: «I dag trur eg du er klar.»\n"
    "{name} sette foten i stigbøylen, og så sat ho der oppe.\n"
    "Bakken var lenger unna enn ho hadde trutt, og hjartet slo hardt.\n"
    "Men Stjerne gjekk roleg av seg sjølv, steg for steg langs gjerdet.",

    "Etter nokre veker låg det ein liten bom på banen.\n"
    "«Ho hoppar om du vågar å la henne,» sa trenaren.\n"
    "{name} tok eit tak i manen, lente seg framover og lukka augo.\n"
    "Eitt sprang, og så var dei på andre sida. Ho hadde ikkje eingong "
    "skrike.",

    "Nokre dagar vart dei berre ståande saman i hagen bak stallen.\n"
    "{name} la kinnet mot den varme halsen og kjende hesten pusta.\n"
    "Ho sa ingenting, for det var ingenting som måtte seiast.\n"
    "Dette var favorittstaden hennar i heile verda.",

    "«Det er eit stemne om tre veker,» sa trenaren ein morgon.\n"
    "«Vil du prøve?»\n"
    "{name} kjende det kriple heilt ut i fingrane.\n"
    "Så nikka ho.",

    "Dei trena kvar einaste dag som var att.\n"
    "{name} lærte å leggje på salen sjølv, og å stramme gjorda akkurat nok.\n"
    "Ho pussa Stjerne til pelsen skein som våt stein.\n"
    "Dagen før stemnet stod dei to lenge i stalldøra og såg ut på banen.",

    "Den siste kvelden reid dei ein runde heilt åleine.\n"
    "Sola låg lågt over gjerda, og sommarfuglane følgde dei langs rosene.\n"
    "{name} kjende at ho ikkje var nervøs lenger.\n"
    "Ho og Stjerne kunne dette. Dei hadde gjort det hundre gonger.",

    "Stemnemorgonen var lys og heilt still.\n"
    "Dei gjekk sakte nedover stien mellom blomekassene.\n"
    "Langt framme høyrde {name} stemmer og ein høgtalar.\n"
    "Stjerne løfta hovudet og spissa øyra, som om ho visste kva som venta.",

    "Så opna portane seg til den store hallen.\n"
    "Det sat folk på alle tribunane, og dommarane sat ved eit langt bord.\n"
    "Hindera verka høgare her inne enn heime på banen.\n"
    "{name} tok eit djupt pust og klappa Stjerne to gonger på halsen.",

    "Klokka ringde, og dei sette av.\n"
    "Eitt hinder. To. Tre. {name} høyrde berre hovane og sin eigen pust.\n"
    "Framfor det siste hoppet kjende ho Stjerne samle seg under seg.\n"
    "Så løfta dei seg, og eit augeblink var dei ikkje nedi bakken i det "
    "heile.",

    "Dei landa mjukt og galopperte vidare mot utgangen.\n"
    "Ingen bommar var nede. Ikkje ein einaste.\n"
    "Publikum reiste seg, men {name} høyrde det nesten ikkje.\n"
    "Ho berre bøygde seg fram og kviskra: «Du gjorde det. Du gjorde det.»",

    "Utanfor banen hoppa {name} av og la båe armane rundt halsen på "
    "Stjerne.\n"
    "Hesten stod stille og lét henne halde på, akkurat som den første dagen "
    "i stallen.\n"
    "«Vi klarte det saman,» sa ho inn i den varme pelsen.\n"
    "Det var det beste augeblinket i heile boka, og det stod ingen dommarar "
    "og såg på.",

    "Då namnet hennar vart ropa opp, gjekk dei inn i ringen att.\n"
    "Nokon hengde ei blå sløyfe på hovudlaget til Stjerne, og gav {name} ein "
    "pokal som skein i sola.\n"
    "Alle klappa, og blomeblad fauk gjennom lufta.\n"
    "Men {name} såg ikkje på pokalen. Ho såg på hesten sin.",
]

# ---------------------------------------------------------------------------
# engelsk (US)
# ---------------------------------------------------------------------------
COVER_EN = "{name} Becomes a\nRiding Star"

BACK_EN = (
    "This book is about what happens when a child and a horse find each "
    "other.\n"
    "{name} has never sat on a horse before. She isn't sure she dares. But "
    "Star looks at her with those calm, dark eyes — and then everything "
    "begins.\n"
    "A warm story about patience, about falling and getting back up, and about "
    "a friendship that carries all the way to competition day.\n"
    "A book to remind a child that the very biggest dreams begin with one "
    "quiet step."
)

PAGES_EN = [
    "The stable smelled of hay and sunshine.\n"
    "All the way at the back, in the last stall, a big brown horse stood "
    "looking straight at {name}.\n"
    "She had a white star in the middle of her forehead.\n"
    "“Hello,” {name} said quietly, and held out her hand.",

    "Every day after school {name} came back to the stable.\n"
    "She learned how to hold a brush, and how firmly she could press.\n"
    "Star stood perfectly still and let her carry on.\n"
    "That was when {name} understood that the horse had begun to trust her.",

    "One evening the trainer said, “Today I think you're ready.”\n"
    "{name} put her foot in the stirrup, and then she was up there.\n"
    "The ground was further away than she had expected, and her heart "
    "pounded.\n"
    "But Star walked calmly on her own, step by step along the fence.",

    "After a few weeks there was a low pole set out in the arena.\n"
    "“She'll jump it if you dare let her,” said the trainer.\n"
    "{name} took hold of the mane, leaned forward and closed her eyes.\n"
    "One leap, and they were on the other side. She hadn't even shrieked.",

    "Some days they simply stood together in the garden behind the stable.\n"
    "{name} laid her cheek against the warm neck and felt the horse "
    "breathing.\n"
    "She said nothing, because nothing needed saying.\n"
    "This was her favourite place in the whole world.",

    "“There's a show in three weeks,” the trainer said one morning.\n"
    "“Do you want to try?”\n"
    "{name} felt it tingle all the way out to her fingertips.\n"
    "Then she nodded.",

    "They trained every single day that was left.\n"
    "{name} learned to saddle up herself, and to tighten the girth just "
    "enough.\n"
    "She groomed Star until her coat shone like wet stone.\n"
    "The day before the show the two of them stood a long while in the stable "
    "doorway, looking out at the arena.",

    "On that last evening they rode a round entirely alone.\n"
    "The sun lay low over the fences, and butterflies followed them along the "
    "roses.\n"
    "{name} realised she wasn't nervous any more.\n"
    "She and Star could do this. They had done it a hundred times.",

    "The morning of the show was bright and completely still.\n"
    "They walked slowly down the path between the flower boxes.\n"
    "Far ahead {name} could hear voices and a loudspeaker.\n"
    "Star lifted her head and pricked her ears, as if she knew what was "
    "coming.",

    "Then the gates opened into the great hall.\n"
    "People filled every stand, and the judges sat at a long table.\n"
    "The jumps looked higher in here than they did at home.\n"
    "{name} took a deep breath and patted Star twice on the neck.",

    "The bell rang, and they set off.\n"
    "One jump. Two. Three. {name} heard only the hooves and her own "
    "breathing.\n"
    "Before the last fence she felt Star gather herself beneath her.\n"
    "Then they lifted, and for a moment they weren't touching the ground at "
    "all.",

    "They landed softly and cantered on towards the exit.\n"
    "Not a single pole was down. Not one.\n"
    "The crowd rose to its feet, but {name} barely heard them.\n"
    "She just leaned forward and whispered, “You did it. You did it.”",

    "Outside the arena {name} jumped down and put both arms around Star's "
    "neck.\n"
    "The horse stood still and let her hold on, just as she had on that first "
    "day in the stable.\n"
    "“We did it together,” she said into the warm coat.\n"
    "It was the best moment in the whole book, and there were no judges "
    "watching.",

    "When her name was called, they walked back into the ring.\n"
    "Someone hung a blue rosette on Star's bridle and handed {name} a trophy "
    "that shone in the sun.\n"
    "Everyone applauded, and flower petals drifted through the air.\n"
    "But {name} wasn't looking at the trophy. She was looking at her horse.",
]

# ---------------------------------------------------------------------------
# engelsk (GB). Samme tekst - forskjellen ligger i sideoppdelingen, ikke ordene.
# ---------------------------------------------------------------------------
COVER_GB = COVER_EN
BACK_GB = BACK_EN
PAGES_GB = list(PAGES_EN)

# ---------------------------------------------------------------------------
# svensk
# ---------------------------------------------------------------------------
COVER_SV = "{name} blir en\nRidstjärna"

BACK_SV = (
    "Den här boken handlar om vad som händer när ett barn och en häst hittar "
    "varandra.\n"
    "{name} har aldrig suttit på en häst förut. Hon vet inte om hon vågar. "
    "Men Stjärna ser på henne med sina lugna, mörka ögon — och så börjar "
    "allt.\n"
    "En varm berättelse om tålamod, om att falla och resa sig igen, och om en "
    "vänskap som bär ända fram till tävlingsdagen.\n"
    "En bok som påminner barnet om att de allra största drömmarna börjar med "
    "ett lugnt steg."
)

PAGES_SV = [
    "Det luktade hö och sol inne i stallet.\n"
    "Allra längst bak, i den sista boxen, stod en stor brun häst och såg rakt "
    "på {name}.\n"
    "Hon hade en vit stjärna midt i pannan.\n"
    "”Hej,” sa {name} tyst, och räckte fram handen försiktigt.",

    "Varje dag efter skolan kom {name} tillbaka till stallet.\n"
    "Hon lärde sig hur man håller en borste, och hur hårt man vågar ta.\n"
    "Stjärna stod helt stilla och lät henne hålla på.\n"
    "Det var då {name} förstod att hästen hade börjat lita på henne.",

    "En kväll sa tränaren: ”I dag tror jag att du är klar.”\n"
    "{name} satte foten i stigbygeln, och så satt hon där uppe.\n"
    "Marken var längre bort än hon hade trott, och hjärtat slog hårt.\n"
    "Men Stjärna gick lugnt av sig själv, steg för steg längs staketet.",

    "Efter några veckor låg det en låg bom i ridbanan.\n"
    "”Hon hoppar om du vågar låta henne,” sa tränaren.\n"
    "{name} tog tag i manen, lutade sig framåt och blundade.\n"
    "Ett skutt, och så var de på andra sidan. Hon hade inte ens skrikit.",

    "Vissa dagar stod de bara tillsammans i trädgården bakom stallet.\n"
    "{name} lade kinden mot den varma halsen och kände hästen andas.\n"
    "Hon sa ingenting, för det fanns ingenting som måste sägas.\n"
    "Det här var hennes favoritplats i hela världen.",

    "”Det är en tävling om tre veckor,” sa tränaren en morgon.\n"
    "”Vill du prova?”\n"
    "{name} kände det pirra ända ut i fingrarna.\n"
    "Så nickade hon.",

    "De tränade varje enda dag som fanns kvar.\n"
    "{name} lärde sig att sadla själv, och att spänna gjorden precis rätt.\n"
    "Hon ryktade Stjärna tills pälsen glänste som våt sten.\n"
    "Dagen före tävlingen stod de två länge i stalldörren och såg ut över "
    "banan.",

    "Den sista kvällen red de ett varv helt ensamma.\n"
    "Solen låg lågt över staketen, och fjärilarna följde dem längs rosorna.\n"
    "{name} kände att hon inte var nervös längre.\n"
    "Hon och Stjärna kunde det här. De hade gjort det hundra gånger.",

    "Tävlingsmorgonen var ljus och alldeles stilla.\n"
    "De gick sakta nedåt stigen mellan blomlådorna.\n"
    "Långt fram hörde {name} röster och en högtalare.\n"
    "Stjärna lyfte huvudet och spetsade öronen, som om hon visste vad som "
    "väntade.",

    "Så öppnade sig portarna in till den stora hallen.\n"
    "Det satt folk på alla läktare, och domarna satt vid ett långt bord.\n"
    "Hindren verkade högre här inne än hemma på banan.\n"
    "{name} tog ett djupt andetag och klappade Stjärna två gånger på halsen.",

    "Klockan ringde, och de satte av.\n"
    "Ett hinder. Två. Tre. {name} hörde bara hovarna och sin egen andning.\n"
    "Före det sista hoppet kände hon Stjärna samla sig under sig.\n"
    "Så lyfte de, och ett ögonblick var de inte vid marken alls.",

    "De landade mjukt och galopperade vidare mot utgången.\n"
    "Inte en enda bom låg nere. Inte en.\n"
    "Publiken reste sig, men {name} hörde det nästan inte.\n"
    "Hon bara lutade sig fram och viskade: ”Du gjorde det. Du gjorde det.”",

    "Utanför banan hoppade {name} av och lade båda armarna om halsen på "
    "Stjärna.\n"
    "Hästen stod stilla och lät henne hålla på, precis som den första dagen i "
    "stallet.\n"
    "”Vi klarade det tillsammans,” sa hon in i den varma pälsen.\n"
    "Det var det bästa ögonblicket i hela boken, och det stod inga domare och "
    "såg på.",

    "När hennes namn ropades upp gick de in i ringen igen.\n"
    "Någon hängde en blå rosett på Stjärnas huvudlag och gav {name} en pokal "
    "som glänste i solen.\n"
    "Alla applåderade, och blomblad virvlade genom luften.\n"
    "Men {name} tittade inte på pokalen. Hon tittade på sin häst.",
]

TRANSLATIONS = {
    "nn": (COVER_NN, PAGES_NN, BACK_NN),
    "en-US": (COVER_EN, PAGES_EN, BACK_EN),
    "en-GB": (COVER_GB, PAGES_GB, BACK_GB),
    "sv": (COVER_SV, PAGES_SV, BACK_SV),
}
