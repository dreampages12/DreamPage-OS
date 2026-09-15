# -*- coding: utf-8 -*-
"""Kildetekst for Kongerikets Hemmelighet, 14 oppslag + forside/intro/bakside."""

COVER_NB = "Prinsesse (Navn) og\nKongerikets Hemmelighet"

INTRO_NB = (
    "Takk for at du kjøpte denne personlige historien!\n"
    "I denne boken våkner (Navn) til sin aller første dag som prinsesse, og oppdager en hemmelighet dypt under slottet som kan redde hele kongeriket.\n"
    "Vi håper historien bringer glede, spenning og fantasifulle øyeblikk."
)

BACK_NB = (
    "Denne boken handler om å lete videre når andre gir opp. Om å stille spørsmål, tenke selv og finne svar der ingen har lett før.\n"
    "Når vannet forsvinner fra kongeriket, følger (Navn) et gammelt kart ned i mørket under slottet – og finner en hemmelighet som har ligget skjult i mange år.\n"
    "En varm og spennende historie om mot, nysgjerrighet og om å ta ansvar for noe større enn seg selv.\n"
    "En bok som minner barnet på at små hender kan utgjøre en stor forskjell."
)
BACK_HL = ["hemmelighet", "kongeriket", "mot", "nysgjerrighet", "ansvar", "barnet"]

# (side, tekst, highlights) - side er regnet ut fra tyngdepunktet i headmasken
PAGES_NB = [
    ("left",
     "Det var den første morgenen til (Navn) som prinsesse.\n"
     "Fra balkongen kunne hun se hele kongeriket våkne.\n"
     "Elven glitret mellom åsene, og fuglene fløy over tårnene.\n"
     "(Navn) ante ikke at en stor oppgave allerede ventet.",
     ["prinsesse", "kongeriket", "oppgave"]),
    ("right",
     "Senere gikk (Navn) gjennom slottsgården da hun stoppet.\n"
     "Den store fontenen, som alltid sprutet mot himmelen, var stille.\n"
     "Blomstene hang tungt, og bare noen dråper rant fra steinen.\n"
     "«Hvor har alt vannet blitt av?» undret (Navn).",
     ["fontenen", "stille", "vannet"]),
    ("left",
     "Dronningen kom bort og så alvorlig på den tomme fontenen.\n"
     "«Elven som gir vann til hele kongeriket blir svakere,» sa hun.\n"
     "Ingen visste hvorfor, og snart kunne alle mangle vann.\n"
     "(Navn) rettet ryggen. Dette skulle bli hennes første oppgave.",
     ["Dronningen", "svakere", "oppgave"]),
    ("right",
     "(Navn) skyndte seg til det gamle biblioteket for å lete etter svar.\n"
     "Mellom støvete bøker fant hun et gammelt kart over slottet.\n"
     "Under slottet var det tegnet en vannvei hun aldri hadde sett.\n"
     "«Kanskje vannet ikke bare kommer fra elven,» tenkte hun.",
     ["biblioteket", "kart", "vannvei"]),
    ("left",
     "Kartet førte (Navn) til en bortgjemt del av slottsgården.\n"
     "Bak eføy og gamle roser oppdaget hun en liten steindør.\n"
     "Da hun skjøv greinene til side, strømmet kald luft ut fra mørket.\n"
     "(Navn) tok et dypt pust og åpnet døren.",
     ["steindør", "mørket", "eføy"]),
    ("right",
     "Med en lykt i hånden gikk (Navn) ned trappene under slottet.\n"
     "Steinveggene var kalde, og dryppende vann fulgte henne.\n"
     "Jo lenger hun gikk, desto tydeligere hørte hun noe som rant.\n"
     "Hun løftet lykten og fortsatte.",
     ["lykt", "trappene", "rant"]),
    ("left",
     "Plutselig åpnet tunnelen seg til en enorm hule.\n"
     "Foran (Navn) rant en skjult blå elv mellom gamle steinkanaler.\n"
     "Vannet glitret svakt, som en hemmelig verden under slottet.\n"
     "«Så det er her vannet kommer fra!» hvisket hun.",
     ["hule", "elv", "hemmelig"]),
    ("right",
     "(Navn) fulgte elven videre, men strømmen ble svakere.\n"
     "Til slutt var det bare små dammer igjen mellom steinene.\n"
     "Hun satte seg ned og studerte vannet nøye.\n"
     "Fant hun ut hvor strømmen stoppet, kunne hun redde kongeriket.",
     ["strømmen", "dammer", "redde"]),
    ("left",
     "Bak en gammel steinbue fant (Navn) et skjult rom.\n"
     "På veggene var det skåret ut elver, fontener og vannveier.\n"
     "Midt i rommet stod en stor mekanisme av stein og metall.\n"
     "Noen hadde bygget dette stedet for å lede vannet.",
     ["skjult", "mekanisme", "vannveier"]),
    ("right",
     "Bak kammeret fant hun noe enda mer utrolig.\n"
     "En klar kilde fylte et gammelt steinbasseng med friskt vann.\n"
     "Det var mer enn nok vann. Problemet var at det ikke kom videre.\n"
     "Da visste (Navn) at løsningen måtte være like i nærheten.",
     ["kilde", "friskt", "løsningen"]),
    ("left",
     "Hun fulgte kanalen til en gammel steinport og fant årsaken.\n"
     "Store steiner hadde rast ned og satt seg fast foran porten.\n"
     "Bak dem presset vannet på, men det hadde ingen vei ut.\n"
     "«Jeg har funnet det!» ropte (Navn).",
     ["steinport", "steiner", "funnet"]),
    ("right",
     "(Navn) hentet hjelp og viste arbeiderne veien gjennom tunnelene.\n"
     "Sammen flyttet de steinene og reparerte den gamle vannporten.\n"
     "(Navn) fulgte nøye med og viste hvor vannet skulle ledes.\n"
     "Så, med et kraftig brus, åpnet porten seg.",
     ["hjelp", "vannporten", "brus"]),
    ("left",
     "Vannet strømmet gjennom kanalene og tilbake til kongeriket.\n"
     "I slottsgården sprutet fontenen igjen, og blomstene løftet seg.\n"
     "Folk jublet mens (Navn) så utover alt hun hadde reddet.\n"
     "«Du fant løsningen da ingen andre visste hvor de skulle lete.»",
     ["strømmet", "fontenen", "jublet"]),
    ("right",
     "Den kvelden stod (Navn) sammen med dronningen på balkongen.\n"
     "Elven glitret igjen, og fontenene danset i slottsgården.\n"
     "(Navn) hadde lært at det å være prinsesse er mer enn en krone.\n"
     "Det handler om å lytte, tenke og ta vare på dem som trenger deg.",
     ["dronningen", "prinsesse", "lytte"]),
]

# ---------------------------------------------------------------- nynorsk
COVER_NN = "Prinsesse {name} og\nKongerikets Hemmelighet"
INTRO_NN = (
    "Takk for at du kjøpte denne personlege historia!\n"
    "I denne boka vaknar {name} til sin aller første dag som prinsesse, og oppdagar ein løyndom djupt under slottet som kan redde heile kongeriket.\n"
    "Vi håper historia gjev glede, spaning og fantasifulle augneblinkar."
)
BACK_NN = (
    "Denne boka handlar om å leite vidare når andre gjev opp. Om å stille spørsmål, tenkje sjølv og finne svar der ingen har leita før.\n"
    "Når vatnet forsvinn frå kongeriket, følgjer {name} eit gammalt kart ned i mørkret under slottet – og finn ein løyndom som har lege skjult i mange år.\n"
    "Ei varm og spennande historie om mot, nysgjerrigheit og om å ta ansvar for noko større enn seg sjølv.\n"
    "Ei bok som minner barnet på at små hender kan utgjere ein stor skilnad."
)
PAGES_NN = [
    "Det var den første morgonen til {name} som prinsesse.\n"
    "Frå balkongen kunne ho sjå heile kongeriket vakne.\n"
    "Elva glitra mellom åsane, og fuglane flaug over tårna.\n"
    "{name} ana ikkje at ei stor oppgåve alt venta.",

    "Seinare gjekk {name} gjennom slottsgarden då ho stoppa.\n"
    "Den store fontenen, som alltid spruta mot himmelen, var stille.\n"
    "Blomane hang tungt, og berre nokre dropar rann frå steinen.\n"
    "«Kvar har alt vatnet blitt av?» undra {name}.",

    "Dronninga kom bort og såg alvorleg på den tomme fontenen.\n"
    "«Elva som gjev vatn til heile kongeriket blir svakare,» sa ho.\n"
    "Ingen visste kvifor, og snart kunne alle mangle vatn.\n"
    "{name} retta ryggen. Dette skulle bli hennar første oppgåve.",

    "{name} skunda seg til det gamle biblioteket for å leite etter svar.\n"
    "Mellom støvete bøker fann ho eit gammalt kart over slottet.\n"
    "Under slottet var det teikna ein vassveg ho aldri hadde sett.\n"
    "«Kanskje vatnet ikkje berre kjem frå elva,» tenkte ho.",

    "Kartet førte {name} til ein bortgøymd del av slottsgarden.\n"
    "Bak eføy og gamle roser oppdaga ho ei lita steindør.\n"
    "Då ho skuva greinene til side, strøymde kald luft ut frå mørkret.\n"
    "{name} tok eit djupt pust og opna døra.",

    "Med ei lykt i handa gjekk {name} ned trappene under slottet.\n"
    "Steinveggene var kalde, og dryppande vatn følgde henne.\n"
    "Jo lenger ho gjekk, dess tydelegare høyrde ho noko som rann.\n"
    "Ho lyfte lykta og heldt fram.",

    "Brått opna tunnelen seg til ei enorm hole.\n"
    "Framfor {name} rann ei løynd blå elv mellom gamle steinkanalar.\n"
    "Vatnet glitra svakt, som ei hemmeleg verd under slottet.\n"
    "«Så det er her vatnet kjem frå!» kviskra ho.",

    "{name} følgde elva vidare, men straumen blei svakare.\n"
    "Til slutt var det berre små dammar att mellom steinane.\n"
    "Ho sette seg ned og studerte vatnet nøye.\n"
    "Fann ho ut kvar straumen stoppa, kunne ho redde kongeriket.",

    "Bak ein gammal steinboge fann {name} eit løynd rom.\n"
    "På veggene var det skore ut elvar, fontener og vassvegar.\n"
    "Midt i rommet stod ein stor mekanisme av stein og metall.\n"
    "Nokon hadde bygd denne staden for å leie vatnet.",

    "Bak kammeret fann ho noko endå meir utruleg.\n"
    "Ei klar kjelde fylte eit gammalt steinbasseng med friskt vatn.\n"
    "Det var meir enn nok vatn. Problemet var at det ikkje kom vidare.\n"
    "Då visste {name} at løysinga måtte vere like i nærleiken.",

    "Ho følgde kanalen til ein gammal steinport og fann årsaka.\n"
    "Store steinar hadde rasa ned og sett seg fast framfor porten.\n"
    "Bak dei pressa vatnet på, men det hadde ingen veg ut.\n"
    "«Eg har funne det!» ropte {name}.",

    "{name} henta hjelp og viste arbeidarane vegen gjennom tunnelane.\n"
    "Saman flytta dei steinane og reparerte den gamle vassporten.\n"
    "{name} følgde nøye med og viste kvar vatnet skulle leiast.\n"
    "Så, med eit kraftig brus, opna porten seg.",

    "Vatnet strøymde gjennom kanalane og tilbake til kongeriket.\n"
    "I slottsgarden spruta fontenen igjen, og blomane lyfte seg.\n"
    "Folk jubla medan {name} såg utover alt ho hadde redda.\n"
    "«Du fann løysinga då ingen andre visste kvar dei skulle leite.»",

    "Den kvelden stod {name} saman med dronninga på balkongen.\n"
    "Elva glitra igjen, og fontenene dansa i slottsgarden.\n"
    "{name} hadde lært at det å vere prinsesse er meir enn ei krone.\n"
    "Det handlar om å lytte, tenkje og ta vare på dei som treng deg.",
]

# ---------------------------------------------------------------- en-US
COVER_EN = "Princess {name} and\nThe Secret of the Kingdom"
INTRO_EN = (
    "Thank you for buying this personal story!\n"
    "In this book {name} wakes to her very first day as a princess, and discovers a secret deep beneath the castle that can save the whole kingdom.\n"
    "We hope the story brings joy, excitement and imaginative moments."
)
BACK_EN = (
    "This book is about looking further when others give up. About asking questions, thinking for yourself and finding answers where no one has looked before.\n"
    "When the water disappears from the kingdom, {name} follows an old map down into the dark beneath the castle – and finds a secret that has lain hidden for many years.\n"
    "A warm and exciting story about courage, curiosity and taking responsibility for something bigger than yourself.\n"
    "A book that reminds the child that small hands can make a big difference."
)
PAGES_EN = [
    "It was {name}'s very first morning as a princess.\n"
    "From the balcony she could see the whole kingdom wake up.\n"
    "The river glittered between the hills, and birds flew over the towers.\n"
    "{name} had no idea that a great task was already waiting.",

    "Later {name} walked through the castle courtyard and stopped.\n"
    "The great fountain, which always sprayed toward the sky, was silent.\n"
    "The flowers hung heavy, and only a few drops ran from the stone.\n"
    "“Where has all the water gone?” {name} wondered.",

    "The queen came over and looked gravely at the empty fountain.\n"
    "“The river that gives water to the kingdom is growing weaker,” she said.\n"
    "No one knew why, and soon everyone could run short of water.\n"
    "{name} straightened up. This would be her first task as a princess.",

    "{name} hurried to the old library to look for answers.\n"
    "Among dusty books she found an old map of the castle.\n"
    "Beneath the castle someone had drawn a waterway she had never seen.\n"
    "“Maybe the water doesn’t only come from the river,” she thought.",

    "The map led {name} to a hidden part of the castle garden.\n"
    "Behind ivy and old climbing roses she found a small stone door.\n"
    "When she pushed the branches aside, cold air poured out of the dark.\n"
    "{name} took a deep breath and opened the door.",

    "With a lantern in her hand, {name} went down the stairs below the castle.\n"
    "The stone walls were cold, and dripping water followed her.\n"
    "The farther she went, the more clearly she heard something running.\n"
    "She lifted the lantern and kept going.",

    "Suddenly the tunnel opened into an enormous cave.\n"
    "Before {name} ran a hidden blue river between old stone channels.\n"
    "The water glittered faintly, like a secret world beneath the castle.\n"
    "“So this is where the water comes from!” she whispered.",

    "{name} followed the river on, but the current grew weaker.\n"
    "At last only small pools were left between the stones.\n"
    "She sat down and studied the water carefully.\n"
    "If she found where the current stopped, she could save the kingdom.",

    "Behind an old stone arch {name} found a hidden room.\n"
    "Rivers, fountains and waterways were carved into the walls.\n"
    "In the middle stood a great mechanism of stone and metal.\n"
    "Someone had built this place to guide the water.",

    "Behind the chamber she found something even more amazing.\n"
    "A clear spring filled an old stone basin with fresh water.\n"
    "There was more than enough water. It simply wasn’t getting through.\n"
    "Then {name} knew the answer had to be close by.",

    "She followed the channel to an old stone gate and found the cause.\n"
    "Huge rocks had fallen down and wedged themselves in front of it.\n"
    "Behind them the water pressed on, but it had no way out.\n"
    "“I’ve found it!” {name} shouted.",

    "{name} fetched help and showed the workers the way through the tunnels.\n"
    "Together they moved the rocks and repaired the old water gate.\n"
    "{name} watched closely and showed where the water should go.\n"
    "Then, with a mighty rush, the gate swung open.",

    "The water streamed through the channels and back to the kingdom.\n"
    "In the courtyard the fountain sprayed again, and the flowers lifted.\n"
    "People cheered while {name} looked out over all she had saved.\n"
    "“You found the answer when no one else knew where to look.”",

    "That evening {name} stood with the queen on the balcony.\n"
    "The river glittered again, and the fountains danced in the garden.\n"
    "{name} had learned that being a princess is more than a crown.\n"
    "It is about listening, thinking and caring for those who need you.",
]

# ---------------------------------------------------------------- en-GB
COVER_GB = COVER_EN
INTRO_GB = INTRO_EN
BACK_GB = BACK_EN.replace("looked before", "looked before")
PAGES_GB = [
    t.replace("sprayed toward the sky", "sprayed towards the sky")
     .replace("The farther she went", "The further she went")
     .replace("something even more amazing", "something even more astonishing")
    for t in PAGES_EN
]

# ---------------------------------------------------------------- svenska
COVER_SV = "Prinsessan {name} och\nKungarikets Hemlighet"
INTRO_SV = (
    "Tack för att du köpte den här personliga berättelsen!\n"
    "I den här boken vaknar {name} till sin allra första dag som prinsessa, och upptäcker en hemlighet djupt under slottet som kan rädda hela kungariket.\n"
    "Vi hoppas att berättelsen ger glädje, spänning och fantasifulla stunder."
)
BACK_SV = (
    "Den här boken handlar om att leta vidare när andra ger upp. Om att ställa frågor, tänka själv och hitta svar där ingen har letat förut.\n"
    "När vattnet försvinner från kungariket följer {name} en gammal karta ner i mörkret under slottet – och hittar en hemlighet som legat dold i många år.\n"
    "En varm och spännande berättelse om mod, nyfikenhet och om att ta ansvar för något större än sig själv.\n"
    "En bok som påminner barnet om att små händer kan göra stor skillnad."
)
PAGES_SV = [
    "Det var {name_genitive} allra första morgon som prinsessa.\n"
    "Från balkongen kunde hon se hela kungariket vakna.\n"
    "Floden glittrade mellan kullarna, och fåglarna flög över tornen.\n"
    "{name} anade inte att en stor uppgift redan väntade.",

    "Senare gick {name} genom slottsgården när hon stannade.\n"
    "Den stora fontänen, som alltid sprutade mot himlen, var tyst.\n"
    "Blommorna hängde tunga, och bara några droppar rann från stenen.\n"
    "«Vart har allt vatten tagit vägen?» undrade {name}.",

    "Drottningen kom fram och såg allvarligt på den tomma fontänen.\n"
    "«Floden som ger vatten till hela kungariket blir svagare,» sa hon.\n"
    "Ingen visste varför, och snart kunde alla sakna vatten.\n"
    "{name} rätade på ryggen. Detta blev hennes första uppgift.",

    "{name} skyndade till det gamla biblioteket för att leta efter svar.\n"
    "Bland dammiga böcker hittade hon en gammal karta över slottet.\n"
    "Under slottet fanns en vattenväg hon aldrig hade sett.\n"
    "«Kanske kommer vattnet inte bara från floden,» tänkte hon.",

    "Kartan ledde {name} till en undanskymd del av slottsgården.\n"
    "Bakom murgröna och gamla rosor upptäckte hon en liten stendörr.\n"
    "När hon sköt undan grenarna strömmade kall luft ut ur mörkret.\n"
    "{name} tog ett djupt andetag och öppnade dörren.",

    "Med en lykta i handen gick {name} ner för trapporna under slottet.\n"
    "Stenväggarna var kalla, och droppande vatten följde henne.\n"
    "Ju längre hon gick, desto tydligare hörde hon något som rann.\n"
    "Hon lyfte lyktan och fortsatte.",

    "Plötsligt öppnade sig tunneln mot en enorm grotta.\n"
    "Framför {name} rann en dold blå flod mellan gamla stenkanaler.\n"
    "Vattnet glittrade svagt, som en hemlig värld under slottet.\n"
    "«Så det är härifrån vattnet kommer!» viskade hon.",

    "{name} följde floden vidare, men strömmen blev svagare.\n"
    "Till slut fanns bara små dammar kvar mellan stenarna.\n"
    "Hon satte sig ner och studerade vattnet noga.\n"
    "Om hon hittade var strömmen stannade kunde hon rädda kungariket.",

    "Bakom en gammal stenbåge hittade {name} ett dolt rum.\n"
    "På väggarna var floder, fontäner och vattenvägar uthuggna.\n"
    "Mitt i rummet stod en stor mekanism av sten och metall.\n"
    "Någon hade byggt platsen för att leda vattnet.",

    "Bakom kammaren hittade hon något ännu mer otroligt.\n"
    "En klar källa fyllde ett gammalt stenbassäng med friskt vatten.\n"
    "Det fanns mer än nog med vatten. Det kom bara inte vidare.\n"
    "Då visste {name} att lösningen måste finnas alldeles intill.",

    "Hon följde kanalen till en gammal stenport och hittade orsaken.\n"
    "Stora stenar hade rasat ner och fastnat framför porten.\n"
    "Bakom dem tryckte vattnet på, men det hade ingen väg ut.\n"
    "«Jag har hittat det!» ropade {name}.",

    "{name} hämtade hjälp och visade arbetarna vägen genom tunnlarna.\n"
    "Tillsammans flyttade de stenarna och lagade den gamla vattenporten.\n"
    "{name} följde noga med och visade vart vattnet skulle ledas.\n"
    "Sedan, med ett kraftigt brus, öppnades porten.",

    "Vattnet strömmade genom kanalerna och tillbaka till kungariket.\n"
    "På slottsgården sprutade fontänen igen, och blommorna lyfte sig.\n"
    "Folk jublade medan {name} såg ut över allt hon hade räddat.\n"
    "«Du fann lösningen när ingen annan visste var de skulle leta.»",

    "Den kvällen stod {name} tillsammans med drottningen på balkongen.\n"
    "Floden glittrade igen, och fontänerna dansade på slottsgården.\n"
    "{name} hade lärt sig att vara prinsessa är mer än en krona.\n"
    "Det handlar om att lyssna, tänka och ta hand om dem som behöver dig.",
]

TRANSLATIONS = {
    "nn": (COVER_NN, INTRO_NN, PAGES_NN, BACK_NN),
    "en-US": (COVER_EN, INTRO_EN, PAGES_EN, BACK_EN),
    "en-GB": (COVER_GB, INTRO_GB, PAGES_GB, BACK_GB),
    "sv": (COVER_SV, INTRO_SV, PAGES_SV, BACK_SV),
}
