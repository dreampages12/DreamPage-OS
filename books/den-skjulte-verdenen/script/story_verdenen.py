# -*- coding: utf-8 -*-
"""Kildetekst for Den Skjulte Verdenen.

14 sider: 13 oppslag (2048x1024) + side 4 som to kvadratsider
(04-left = statisk handbilde med teksten, 04-right = comfy-headswap uten tekst).

Sidevalget ("left"/"right") er regnet ut fra tyngdepunktet i headmasken:
cx < 0.5 -> figuren staar til venstre -> teksten skal til hoyre.
Side 3 er lest av bildet (headmasken i pakka var oedelagt).
"""

COVER_NB = "(Navn) og\nDen Skjulte Verdenen"

BACK_NB = (
    "Denne boken handler om nysgjerrighet. Om å følge et lite lys inn i det ukjente, "
    "selv når man ikke vet hva som venter på den andre siden.\n"
    "Når (Navn) går gjennom fossen, åpner det seg en verden med svevende øyer, "
    "en glemt by og en drage som blir hans venn.\n"
    "En varm og spennende fortelling om mot, vennskap og om å våge å ta det første skrittet.\n"
    "En bok som minner barnet på at de aller største eventyrene begynner med ett eneste skritt."
)
BACK_HL = ["nysgjerrighet", "fossen", "drage", "mot", "vennskap", "barnet"]

# (side, tekst, highlights)
PAGES_NB = [
    ("left",
     "En dag var (Navn) ute på tur i skogen.\n"
     "Han hadde gått denne veien mange ganger før.\n"
     "Men akkurat i dag føltes noe annerledes.\n"
     "Plutselig glitret et lite lys mellom trærne.",
     ["skogen", "lys", "annerledes"]),
    ("right",
     "Det lille lyset danset videre mellom trærne.\n"
     "Det var nesten som om det ville at (Navn) skulle følge etter.\n"
     "Han gikk forsiktig etter, lenger og lenger inn i skogen.\n"
     "Hver gang han kom nær, fløy lyset videre.",
     ["danset", "følge", "skogen"]),
    ("right",
     "Til slutt førte lyset (Navn) frem til en stor foss.\n"
     "Han stoppet og så opp.\n"
     "Midt i alt det kalde vannet skinte et svakt, gyllent lys.\n"
     "Og den lille gnisten fløy rett mot fossen.",
     ["foss", "gyllent", "gnisten"]),
    # Side 4 = kvadratparet. Teksten staar paa venstre kvadrat (handbildet).
    ("square",
     "(Navn) gikk helt bort til fossen og strakte hånden forsiktig frem.\n"
     "Da vannet traff fingrene hans, skjedde noe utrolig.\n"
     "Vannet rundt hånden begynte å gløde som flytende gull.\n"
     "Dette var ingen vanlig foss.",
     ["hånden", "gløde", "gull"]),
    ("right",
     "Han tok et lite skritt nærmere.\n"
     "Bak det glitrende vannet skimtet (Navn) noe på den andre siden.\n"
     "Farger. Lys. Fjell.\n"
     "Han samlet motet sitt og gikk rett gjennom fossen.",
     ["skimtet", "Fjell", "motet"]),
    ("left",
     "På den andre siden mistet (Navn) nesten pusten.\n"
     "Foran ham lå en verden han aldri hadde sett maken til.\n"
     "Fjell strakte seg mot skyene, og øyer svevde i luften.\n"
     "Han hadde funnet den skjulte verden.",
     ["verden", "skyene", "skjulte"]),
    ("right",
     "Plutselig raslet det mellom plantene bak ham.\n"
     "(Navn) snudde seg raskt.\n"
     "Ut mellom de gamle steinene kom en ung, blågrønn drage.\n"
     "(Navn) sto helt stille. Dragen gjorde det samme.",
     ["raslet", "drage", "stille"]),
    ("left",
     "Dragen virket ikke sint.\n"
     "Den så på (Navn) med store, kloke øyne og begynte å gå.\n"
     "Etter noen skritt stoppet den og så tilbake på ham.\n"
     "«Vil du at jeg skal følge etter deg?» spurte (Navn).",
     ["Dragen", "kloke", "følge"]),
    ("right",
     "Sammen fulgte de en gammel sti gjennom den skjulte verden.\n"
     "Til slutt kom de opp på en høy klippe.\n"
     "Langt nedenfor lå en enorm, forlatt by.\n"
     "Tårn og broer var dekket av planter, som om ingen hadde vært der på hundre år.",
     ["klippe", "forlatt", "Tårn"]),
    ("left",
     "(Navn) og dragen gikk inn mellom de gamle bygningene.\n"
     "Alt var stille.\n"
     "Så begynte små symboler i steinveggene å lyse idet han gikk forbi.\n"
     "Ett etter ett våknet de til liv.",
     ["dragen", "symboler", "våknet"]),
    ("right",
     "Innerst i byen fant de et enormt gammelt tempel.\n"
     "Midt i mørket stod en stor krystall på en steinsokkel.\n"
     "Da (Navn) kom nærmere, glødet ett av symbolene sterkere enn alle de andre.\n"
     "Det var det samme lyset som hadde ledet ham gjennom skogen.",
     ["tempel", "krystall", "symbolene"]),
    ("left",
     "Forsiktig la (Navn) hånden mot krystallen.\n"
     "I samme øyeblikk fyltes hele rommet av gyllent lys.\n"
     "Lyset skjøt gjennom gulvet og ut i hele byen.\n"
     "Utenfor begynte tårnene å gløde. Den glemte byen våknet.",
     ["krystallen", "gyllent", "glemte"]),
    ("right",
     "(Navn) løp ut sammen med dragen.\n"
     "Overalt rundt dem kom den skjulte verden til liv.\n"
     "Men så stivnet dragen og stirret mot et mørkt fjell langt borte.\n"
     "Høyt oppe tente et rødt lys seg. De hadde vekket noe annet også.",
     ["stivnet", "mørkt", "vekket"]),
    ("left",
     "Ved fossen stoppet (Navn) og så tilbake på dragen.\n"
     "I hånden lå en liten bit av den lysende krystallen.\n"
     "Den pulserte svakt, nesten som et hjerte.\n"
     "Eventyret i den skjulte verden hadde bare så vidt begynt.",
     ["krystallen", "hjerte", "Eventyret"]),
]

# ---------------------------------------------------------------- nynorsk
COVER_NN = "{name} og\nDen Skjulte Verdenen"
BACK_NN = (
    "Denne boka handlar om nysgjerrigheit. Om å følgje eit lite lys inn i det ukjende, "
    "sjølv når ein ikkje veit kva som ventar på den andre sida.\n"
    "Når {name} går gjennom fossen, opnar det seg ei verd med svevande øyar, "
    "ein gløymd by og ein drake som blir venen hans.\n"
    "Ei varm og spennande forteljing om mot, venskap og om å våge å ta det første steget.\n"
    "Ei bok som minner barnet på at dei aller største eventyra byrjar med eitt einaste steg."
)
PAGES_NN = [
    "Ein dag var {name} ute på tur i skogen.\n"
    "Han hadde gått denne vegen mange gonger før.\n"
    "Men akkurat i dag kjendest noko annleis.\n"
    "Brått glitra eit lite lys mellom trea.",

    "Det vesle lyset dansa vidare mellom trea.\n"
    "Det var nesten som om det ville at {name} skulle følgje etter.\n"
    "Han gjekk forsiktig etter, lenger og lenger inn i skogen.\n"
    "Kvar gong han kom nær, flaug lyset vidare.",

    "Til slutt førte lyset {name} fram til ein stor foss.\n"
    "Han stoppa og såg opp.\n"
    "Midt i alt det kalde vatnet skein eit svakt, gyllent lys.\n"
    "Og den vesle gnisten flaug rett mot fossen.",

    "{name} gjekk heilt bort til fossen og strekte handa forsiktig fram.\n"
    "Då vatnet traff fingrane hans, hende det noko utruleg.\n"
    "Vatnet rundt handa byrja å gløde som flytande gull.\n"
    "Dette var ingen vanleg foss.",

    "Han tok eit lite steg nærare.\n"
    "Bak det glitrande vatnet skimta {name} noko på den andre sida.\n"
    "Fargar. Lys. Fjell.\n"
    "Han samla motet sitt og gjekk rett gjennom fossen.",

    "På den andre sida mista {name} nesten pusten.\n"
    "Framfor han låg ei verd han aldri hadde sett maken til.\n"
    "Fjell strekte seg mot skyene, og øyar sveva i lufta.\n"
    "Han hadde funne den skjulte verda.",

    "Brått rasla det mellom plantene bak han.\n"
    "{name} snudde seg raskt.\n"
    "Ut mellom dei gamle steinane kom ein ung, blågrøn drake.\n"
    "{name} stod heilt stille. Draken gjorde det same.",

    "Draken verka ikkje sint.\n"
    "Han såg på {name} med store, kloke auge og byrja å gå.\n"
    "Etter nokre steg stoppa han og såg tilbake.\n"
    "«Vil du at eg skal følgje etter deg?» spurde {name}.",

    "Saman følgde dei ein gammal sti gjennom den skjulte verda.\n"
    "Til slutt kom dei opp på ei høg klippe.\n"
    "Langt nedanfor låg ein enorm, forlaten by.\n"
    "Tårn og bruer var dekte av plantar, som om ingen hadde vore der på hundre år.",

    "{name} og draken gjekk inn mellom dei gamle bygningane.\n"
    "Alt var stille.\n"
    "Så byrja små symbol i steinveggene å lyse idet han gjekk forbi.\n"
    "Eitt etter eitt vakna dei til liv.",

    "Innarst i byen fann dei eit enormt gammalt tempel.\n"
    "Midt i mørkret stod ein stor krystall på ein steinsokkel.\n"
    "Då {name} kom nærare, glødde eitt av symbola sterkare enn alle dei andre.\n"
    "Det var det same lyset som hadde leidd han gjennom skogen.",

    "Forsiktig la {name} handa mot krystallen.\n"
    "I same augeblink vart heile rommet fylt av gyllent lys.\n"
    "Lyset skaut gjennom golvet og ut i heile byen.\n"
    "Utanfor byrja tårna å gløde. Den gløymde byen vakna.",

    "{name} sprang ut saman med draken.\n"
    "Overalt rundt dei kom den skjulte verda til liv.\n"
    "Men så stivna draken og stirde mot eit mørkt fjell langt borte.\n"
    "Høgt oppe tende eit raudt lys seg. Dei hadde vekt noko anna òg.",

    "Ved fossen stoppa {name} og såg tilbake på draken.\n"
    "I handa låg ein liten bit av den lysande krystallen.\n"
    "Han pulserte svakt, nesten som eit hjarte.\n"
    "Eventyret i den skjulte verda hadde berre så vidt byrja.",
]

# ---------------------------------------------------------------- english (US)
COVER_EN = "{name} and\nThe Hidden World"
BACK_EN = (
    "This book is about curiosity. About following a tiny light into the unknown, "
    "even when you don't know what is waiting on the other side.\n"
    "When {name} steps through the waterfall, a world opens up with floating islands, "
    "a forgotten city and a dragon who becomes his friend.\n"
    "A warm and exciting story about courage, friendship and daring to take the first step.\n"
    "A book that reminds a child that the greatest adventures begin with a single step."
)
PAGES_EN = [
    "One day {name} was out walking in the forest.\n"
    "He had taken this path many times before.\n"
    "But today something felt different.\n"
    "Suddenly a tiny light glittered between the trees.",

    "The little light danced on between the trees.\n"
    "It was almost as if it wanted {name} to follow.\n"
    "He walked carefully after it, deeper and deeper into the forest.\n"
    "Every time he came close, the light flew farther away.",

    "At last the light led {name} to a great waterfall.\n"
    "He stopped and looked up.\n"
    "In the middle of all that cold water shone a faint, golden glow.\n"
    "And the little spark flew straight toward the falls.",

    "{name} walked right up to the waterfall and carefully reached out his hand.\n"
    "When the water touched his fingers, something incredible happened.\n"
    "The water around his hand began to glow like liquid gold.\n"
    "This was no ordinary waterfall.",

    "He took one small step closer.\n"
    "Behind the glittering water {name} could glimpse something on the other side.\n"
    "Colors. Light. Mountains.\n"
    "He gathered his courage and walked straight through the falls.",

    "On the other side, {name} almost lost his breath.\n"
    "Before him lay a world unlike anything he had ever seen.\n"
    "Mountains reached for the clouds, and islands floated in the air.\n"
    "He had found the hidden world.",

    "Suddenly something rustled in the plants behind him.\n"
    "{name} spun around.\n"
    "Out from between the old stones came a young, blue-green dragon.\n"
    "{name} stood perfectly still. The dragon did the same.",

    "The dragon did not seem angry.\n"
    "It looked at {name} with big, wise eyes and began to walk.\n"
    "After a few steps it stopped and looked back at him.\n"
    "\"Do you want me to follow you?\" asked {name}.",

    "Together they followed an old trail through the hidden world.\n"
    "At last they came out onto a high cliff.\n"
    "Far below lay an enormous, abandoned city.\n"
    "Towers and bridges were covered in plants, as if no one had been there for a hundred years.",

    "{name} and the dragon walked in among the old buildings.\n"
    "Everything was silent.\n"
    "Then small symbols in the stone walls began to shine as he passed.\n"
    "One by one they woke to life.",

    "Deep inside the city they found an enormous old temple.\n"
    "In the middle of the darkness stood a great crystal on a stone pedestal.\n"
    "When {name} came closer, one of the symbols glowed brighter than all the others.\n"
    "It was the same light that had led him through the forest.",

    "Carefully {name} laid his hand on the crystal.\n"
    "In that very moment the whole room filled with golden light.\n"
    "The light shot through the floor and out into the entire city.\n"
    "Outside, the towers began to glow. The forgotten city was waking.",

    "{name} ran out together with the dragon.\n"
    "All around them the hidden world was coming alive.\n"
    "But then the dragon froze and stared at a dark mountain far away.\n"
    "High up, a red light lit up. They had woken something else too.",

    "By the waterfall {name} stopped and looked back at the dragon.\n"
    "In his hand lay a small piece of the shining crystal.\n"
    "It pulsed softly, almost like a heart.\n"
    "The adventure in the hidden world had only just begun.",
]

# ---------------------------------------------------------------- english (GB)
COVER_GB = COVER_EN
BACK_GB = BACK_EN
PAGES_GB = [
    t.replace("Colors.", "Colours.")
     .replace("the light flew farther away", "the light flew further away")
     .replace("straight toward the falls", "straight towards the falls")
     .replace("an old trail through", "an old path through")
    for t in PAGES_EN
]

# ---------------------------------------------------------------- svenska
COVER_SV = "{name} och\nDen Dolda Världen"
BACK_SV = (
    "Den här boken handlar om nyfikenhet. Om att följa ett litet ljus in i det okända, "
    "även när man inte vet vad som väntar på andra sidan.\n"
    "När {name} går genom vattenfallet öppnar sig en värld med svävande öar, "
    "en glömd stad och en drake som blir hans vän.\n"
    "En varm och spännande berättelse om mod, vänskap och om att våga ta det första steget.\n"
    "En bok som påminner barnet om att de allra största äventyren börjar med ett enda steg."
)
PAGES_SV = [
    "En dag var {name} ute på tur i skogen.\n"
    "Han hade gått den här vägen många gånger förut.\n"
    "Men just idag kändes något annorlunda.\n"
    "Plötsligt glittrade ett litet ljus mellan träden.",

    "Det lilla ljuset dansade vidare mellan träden.\n"
    "Det var nästan som om det ville att {name} skulle följa efter.\n"
    "Han gick försiktigt efter, längre och längre in i skogen.\n"
    "Varje gång han kom nära flög ljuset vidare.",

    "Till slut ledde ljuset {name} fram till ett stort vattenfall.\n"
    "Han stannade och såg upp.\n"
    "Mitt i allt det kalla vattnet lyste ett svagt, gyllene sken.\n"
    "Och den lilla gnistan flög rakt mot vattenfallet.",

    "{name} gick ända fram till vattenfallet och sträckte försiktigt fram handen.\n"
    "När vattnet träffade hans fingrar hände något otroligt.\n"
    "Vattnet runt handen började glöda som flytande guld.\n"
    "Det här var inget vanligt vattenfall.",

    "Han tog ett litet steg närmare.\n"
    "Bakom det glittrande vattnet skymtade {name} något på andra sidan.\n"
    "Färger. Ljus. Berg.\n"
    "Han samlade sitt mod och gick rakt genom vattenfallet.",

    "På andra sidan tappade {name} nästan andan.\n"
    "Framför honom låg en värld han aldrig sett maken till.\n"
    "Berg sträckte sig mot molnen, och öar svävade i luften.\n"
    "Han hade hittat den dolda världen.",

    "Plötsligt prasslade det bland växterna bakom honom.\n"
    "{name} vände sig snabbt om.\n"
    "Ut mellan de gamla stenarna kom en ung, blågrön drake.\n"
    "{name} stod alldeles stilla. Draken gjorde likadant.",

    "Draken verkade inte arg.\n"
    "Den tittade på {name} med stora, kloka ögon och började gå.\n"
    "Efter några steg stannade den och såg tillbaka på honom.\n"
    "»Vill du att jag ska följa efter dig?» frågade {name}.",

    "Tillsammans följde de en gammal stig genom den dolda världen.\n"
    "Till slut kom de upp på en hög klippa.\n"
    "Långt nedanför låg en enorm, övergiven stad.\n"
    "Torn och broar var täckta av växter, som om ingen varit där på hundra år.",

    "{name} och draken gick in bland de gamla byggnaderna.\n"
    "Allt var tyst.\n"
    "Sedan började små symboler i stenväggarna lysa när han gick förbi.\n"
    "En efter en vaknade de till liv.",

    "Längst inne i staden hittade de ett enormt gammalt tempel.\n"
    "Mitt i mörkret stod en stor kristall på en stensockel.\n"
    "När {name} kom närmare glödde en av symbolerna starkare än alla de andra.\n"
    "Det var samma ljus som hade lett honom genom skogen.",

    "Försiktigt lade {name} handen mot kristallen.\n"
    "I samma ögonblick fylldes hela rummet av gyllene ljus.\n"
    "Ljuset sköt genom golvet och ut i hela staden.\n"
    "Utanför började tornen glöda. Den glömda staden vaknade.",

    "{name} sprang ut tillsammans med draken.\n"
    "Överallt runt dem vaknade den dolda världen till liv.\n"
    "Men så stelnade draken och stirrade mot ett mörkt berg långt borta.\n"
    "Högt uppe tändes ett rött ljus. De hade väckt något annat också.",

    "Vid vattenfallet stannade {name} och såg tillbaka på draken.\n"
    "I handen låg en liten bit av den lysande kristallen.\n"
    "Den pulserade svagt, nästan som ett hjärta.\n"
    "Äventyret i den dolda världen hade bara just börjat.",
]

TRANSLATIONS = {
    "nn": (COVER_NN, PAGES_NN, BACK_NN),
    "en-US": (COVER_EN, PAGES_EN, BACK_EN),
    "en-GB": (COVER_GB, PAGES_GB, BACK_GB),
    "sv": (COVER_SV, PAGES_SV, BACK_SV),
}
