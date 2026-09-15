# -*- coding: utf-8 -*-
"""Kildetekst for Fotball VM (bok 2 i fotballstjernen-serien).

14 sider: 13 oppslag (2048x1024) + side 12 som to kvadratsider
(12-left = comfy-headswap uten tekst, 12-right = statisk bilde med teksten).

Sidevalget ("left"/"right") er regnet ut fra tyngdepunktet i headmasken:
cx < 0.5 -> figuren staar til venstre -> teksten skal til hoyre.

Teksten er kortet ned fra manuset til ca. fire linjer per side, slik de
andre boekene i serien (motet-i-hjertet, fotballstjernen) ligger.
"""

COVER_NB = "(Navn) vinner\nFotball-VM"

BACK_NB = (
    "Denne boken handler om å reise seg igjen. Om lagånd, om nerver før en stor kamp, "
    "og om å tro på seg selv mens hele verden ser på.\n"
    "Etter finalen hjemme får (Navn) et brev han knapt tør å åpne: "
    "landslaget vil ha ham med til VM.\n"
    "En varm og spennende fortelling om vennskap, mot og drømmer som blir større "
    "enn man tør å håpe på.\n"
    "For den største forskjellen mellom en drøm og et eventyr er at noen tør å "
    "fortsette når det blir vanskelig."
)
BACK_HL = ["lagånd", "landslaget", "vennskap", "mot", "eventyr"]

# (side, tekst, highlights)
PAGES_NB = [
    ("right",
     "Noen dager etter den store finalen var (Navn) tilbake på treningsbanen.\n"
     "Alt så helt vanlig ut, helt til treneren ropte ham bort.\n"
     "I hånden holdt han en konvolutt med et lite norsk flagg på.\n"
     "(Navn) kjente hjertet begynne å hamre.",
     ["treneren", "konvolutt", "flagg"]),
    ("left",
     "En landslagsspeider hadde sittet på tribunen under finalen.\n"
     "Han hadde sett at (Navn) kjempet videre da kampen ble vanskelig.\n"
     "Nå ville de se ham igjen.\n"
     "(Navn) åpnet brevet: han var invitert til landslagssamling.",
     ["landslagsspeider", "brevet", "landslagssamling"]),
    ("left",
     "På samlingen møtte (Navn) spillere han aldri hadde sett før.\n"
     "De var raske. Veldig raske.\n"
     "Allerede i den første øvelsen mistet han ballen. Så én gang til.\n"
     "Men han husket hva treneren hadde lært ham, og jaget ballen igjen.",
     ["raske", "ballen", "treneren"]),
    ("right",
     "På slutten av dagen leste landslagstreneren opp navnene.\n"
     "Det var bare én plass igjen på laget som skulle til VM.\n"
     "(Navn) hørte mange andre bli valgt, men ikke sitt eget navn.\n"
     "Så løftet treneren blikket, og alt ble stille.",
     ["landslagstreneren", "plass", "stille"]),
    ("left",
     "«(Navn)!»\n"
     "Lagkameratene jublet, og (Navn) fikk landslagsdrakten i hendene.\n"
     "På brystet satt det norske flagget.\n"
     "Nå var det ikke lenger bare trening. Han skulle spille for Norge.",
     ["landslagsdrakten", "flagget", "Norge"]),
    ("right",
     "Flyet landet i vertslandet.\n"
     "Gjennom vinduet så (Navn) enorme stadioner og flagg fra hele verden.\n"
     "På hotellet fikk laget vite hvem de skulle møte først:\n"
     "et av verdens beste lag. VM hadde begynt.",
     ["vertslandet", "stadioner", "verden"]),
    ("left",
     "Den første kampen gikk ikke slik Norge håpet.\n"
     "Motstanderne scoret. Så scoret de igjen.\n"
     "(Navn) mistet ballen i et viktig angrep, og kampen endte med tap.\n"
     "I garderoben sa nesten ingen noe.",
     ["Norge", "ballen", "garderoben"]),
    ("right",
     "«Dere er ikke her fordi alt alltid går perfekt,» sa treneren.\n"
     "«Dere er her fordi dere reiser dere igjen.»\n"
     "(Navn) tenkte på sitt aller første bomskudd hjemme på banen.\n"
     "Så reiste han seg: «Da vinner vi den neste.»",
     ["treneren", "bomskudd", "neste"]),
    ("left",
     "Den neste kampen ble vill. Norge lå under, og tiden rant ut.\n"
     "(Navn) fikk ballen på kanten og driblet forbi den ene, så den andre.\n"
     "Han kunne skutt selv, men foran mål sto en lagkamerat helt alene.\n"
     "(Navn) sendte ballen inn. Mål! 1–1.",
     ["vill", "driblet", "lagkamerat"]),
    ("right",
     "Det sto bare sekunder igjen da ballen havnet hos (Navn) igjen.\n"
     "Tribunen reiste seg.\n"
     "Han løp mot mål mens forsvarerne kom fra begge sider.\n"
     "(Navn) så målet og trakk foten bakover.",
     ["sekunder", "Tribunen", "målet"]),
    ("left",
     "Skuddet suste mot hjørnet. Keeperen strakte seg, men rakk den ikke.\n"
     "MÅL! Lagkameratene stormet mot (Navn), og Norge var videre.\n"
     "Så vant de den neste kampen. Og den neste.\n"
     "Helt til bare fire lag var igjen i hele verden.",
     ["Keeperen", "videre", "verden"]),
    # Side 12 = kvadratparet. Teksten staar paa hoyre kvadrat (det statiske bildet).
    ("square",
     "Semifinalen ble den tøffeste kampen (Navn) hadde spilt.\n"
     "Det sto uavgjort helt mot slutten da motstanderne kom alene mot mål.\n"
     "(Navn) spurtet tilbake og klarte akkurat å stoppe angrepet.\n"
     "Sekunder senere kontret Norge, og lagkameraten scoret. Finale!",
     ["Semifinalen", "spurtet", "Finale"]),
    ("left",
     "Finaledagen kom, og (Navn) sto i spillertunnelen.\n"
     "Foran ham lå den største stadion han noen gang hadde sett.\n"
     "Ved siden av banen glitret VM-pokalen under lysene.\n"
     "Én kamp. Det var alt som gjensto. Så åpnet dørene seg.",
     ["spillertunnelen", "stadion", "lysene"]),
    ("right",
     "Finalen sto 1–1 da Norge fikk frispark like utenfor sekstenmeteren.\n"
     "(Navn) la ballen til rette, løp frem og skjøt. Rett i krysset!\n"
     "Da dommeren blåste av, løftet lagkameratene (Navn) opp i konfettien.\n"
     "Han hadde vært fotballstjerne. Nå var han verdensmester.",
     ["frispark", "krysset", "verdensmester"]),
]

# ---------------------------------------------------------------------------
#  NYNORSK
# ---------------------------------------------------------------------------
COVER_NN = "{name} vinn\nFotball-VM"

PAGES_NN = [
    "Nokre dagar etter den store finalen var {name} tilbake på treningsbanen.\n"
    "Alt såg heilt vanleg ut, heilt til trenaren ropte han bort.\n"
    "I handa heldt han ein konvolutt med eit lite norsk flagg på.\n"
    "{name} kjende hjartet byrje å hamre.",

    "Ein landslagsspeidar hadde sete på tribunen under finalen.\n"
    "Han hadde sett at {name} kjempa vidare då kampen vart vanskeleg.\n"
    "No ville dei sjå han igjen.\n"
    "{name} opna brevet: han var invitert til landslagssamling.",

    "På samlinga møtte {name} spelarar han aldri hadde sett før.\n"
    "Dei var raske. Veldig raske.\n"
    "Alt i den første øvinga mista han ballen. Så éin gong til.\n"
    "Men han hugsa kva trenaren hadde lært han, og jaga ballen igjen.",

    "På slutten av dagen las landslagstrenaren opp namna.\n"
    "Det var berre éin plass igjen på laget som skulle til VM.\n"
    "{name} høyrde mange andre bli valde, men ikkje sitt eige namn.\n"
    "Så lyfte trenaren blikket, og alt vart stille.",

    "«{name}!»\n"
    "Lagkameratane jubla, og {name} fekk landslagsdrakta i hendene.\n"
    "På brystet sat det norske flagget.\n"
    "No var det ikkje lenger berre trening. Han skulle spele for Noreg.",

    "Flyet landa i vertslandet.\n"
    "Gjennom vindauget såg {name} enorme stadion og flagg frå heile verda.\n"
    "På hotellet fekk laget vite kven dei skulle møte først:\n"
    "eit av dei beste laga i verda. VM hadde byrja.",

    "Den første kampen gjekk ikkje slik Noreg håpa.\n"
    "Motstandarane skåra. Så skåra dei igjen.\n"
    "{name} mista ballen i eit viktig angrep, og kampen enda med tap.\n"
    "I garderoben sa nesten ingen noko.",

    "«De er ikkje her fordi alt alltid går perfekt,» sa trenaren.\n"
    "«De er her fordi de reiser dykk igjen.»\n"
    "{name} tenkte på sitt aller første bomskot heime på banen.\n"
    "Så reiste han seg: «Då vinn vi den neste.»",

    "Den neste kampen vart vill. Noreg låg under, og tida rann ut.\n"
    "{name} fekk ballen på kanten og dribla forbi den eine, så den andre.\n"
    "Han kunne skote sjølv, men framfor mål stod ein lagkamerat heilt åleine.\n"
    "{name} sende ballen inn. Mål! 1–1.",

    "Det stod berre sekund igjen då ballen hamna hos {name} igjen.\n"
    "Tribunen reiste seg.\n"
    "Han sprang mot mål medan forsvararane kom frå begge sider.\n"
    "{name} såg målet og drog foten bakover.",

    "Skotet suste mot hjørnet. Keeparen strekte seg, men rakk den ikkje.\n"
    "MÅL! Lagkameratane storma mot {name}, og Noreg var vidare.\n"
    "Så vann dei den neste kampen. Og den neste.\n"
    "Heilt til berre fire lag var igjen i heile verda.",

    "Semifinalen vart den tøffaste kampen {name} hadde spelt.\n"
    "Det stod uavgjort heilt mot slutten då motstandarane kom åleine mot mål.\n"
    "{name} spurta tilbake og klarte akkurat å stoppe angrepet.\n"
    "Sekund seinare kontra Noreg, og lagkameraten skåra. Finale!",

    "Finaledagen kom, og {name} stod i spelartunnelen.\n"
    "Framfor han låg den største stadion han nokon gong hadde sett.\n"
    "Ved sida av bana glitra VM-pokalen under lysa.\n"
    "Éin kamp. Det var alt som stod att. Så opna dørene seg.",

    "Finalen stod 1–1 då Noreg fekk frispark like utanfor sekstenmeteren.\n"
    "{name} la ballen til rette, sprang fram og skaut. Rett i krysset!\n"
    "Då dommaren bles av, lyfte lagkameratane {name} opp i konfettien.\n"
    "Han hadde vore fotballstjerne. No var han verdsmeister.",
]

BACK_NN = (
    "Denne boka handlar om å reise seg igjen. Om lagånd, om nervar før ein stor kamp, "
    "og om å tru på seg sjølv medan heile verda ser på.\n"
    "Etter finalen heime får {name} eit brev han knapt vågar å opne: "
    "landslaget vil ha han med til VM.\n"
    "Ei varm og spennande forteljing om venskap, mot og draumar som blir større "
    "enn ein torer å håpe på.\n"
    "For den største skilnaden mellom ein draum og eit eventyr er at nokon torer å "
    "halde fram når det blir vanskeleg."
)

# ---------------------------------------------------------------------------
#  ENGELSK (US = soccer/field, GB = football/pitch)
# ---------------------------------------------------------------------------
COVER_EN = "{name} Wins the\nWorld Cup"

PAGES_EN = [
    "A few days after the big final, {name} was back at the training ground.\n"
    "Everything looked normal, until the coach called him over.\n"
    "In his hand he held an envelope with a small Norwegian flag on it.\n"
    "{name} felt his heart start to pound.",

    "A national team scout had been sitting in the stands during the final.\n"
    "He had seen {name} keep fighting when the game got hard.\n"
    "Now they wanted to see him again.\n"
    "{name} opened the letter: he was invited to the national team camp.",

    "At the camp {name} met players he had never seen before.\n"
    "They were fast. Very fast.\n"
    "In the very first drill he lost the ball. Then once more.\n"
    "But he remembered what his coach had taught him, and chased the ball again.",

    "At the end of the day the national coach read out the names.\n"
    "There was only one place left on the team going to the World Cup.\n"
    "{name} heard many others being picked, but not his own name.\n"
    "Then the coach looked up, and everything went quiet.",

    "\"{name}!\"\n"
    "His teammates cheered, and {name} was handed the national jersey.\n"
    "On the chest sat the Norwegian flag.\n"
    "This was no longer just practice. He was going to play for Norway.",

    "The plane landed in the host country.\n"
    "Through the window {name} saw huge stadiums and flags from all over the world.\n"
    "At the hotel the team learned who they would face first:\n"
    "one of the best teams in the world. The World Cup had begun.",

    "The first game did not go the way Norway had hoped.\n"
    "The opponents scored. Then they scored again.\n"
    "{name} lost the ball in an important attack, and the game ended in defeat.\n"
    "In the locker room almost nobody said a word.",

    "\"You are not here because everything always goes perfectly,\" said the coach.\n"
    "\"You are here because you get back up.\"\n"
    "{name} thought about his very first missed shot back home on the field.\n"
    "Then he stood up: \"Then we win the next one.\"",

    "The next game was wild. Norway were behind, and time was running out.\n"
    "{name} got the ball on the wing and dribbled past one, then another.\n"
    "He could have shot himself, but a teammate stood all alone in front of goal.\n"
    "{name} passed it in. Goal! 1-1.",

    "There were only seconds left when the ball found {name} again.\n"
    "The whole stand rose to its feet.\n"
    "He ran toward the goal while defenders closed in from both sides.\n"
    "{name} saw the goal and pulled his foot back.",

    "The shot flew toward the corner. The keeper stretched, but could not reach it.\n"
    "GOAL! His teammates stormed toward {name}, and Norway were through.\n"
    "Then they won the next game. And the next.\n"
    "Until only four teams were left in the whole world.",

    "The semifinal was the toughest game {name} had ever played.\n"
    "It was tied right to the end when the opponents broke through alone.\n"
    "{name} sprinted back and just managed to stop the attack.\n"
    "Seconds later Norway countered, and a teammate scored. The final!",

    "Final day came, and {name} stood in the players' tunnel.\n"
    "In front of him lay the biggest stadium he had ever seen.\n"
    "Beside the field the World Cup trophy glittered under the lights.\n"
    "One game. That was all that was left. Then the doors opened.",

    "The final was 1-1 when Norway won a free kick just outside the box.\n"
    "{name} placed the ball, ran up and struck it. Right in the top corner!\n"
    "When the referee blew the whistle, his teammates lifted {name} into the confetti.\n"
    "He had become a soccer star. Now he was a world champion.",
]

BACK_EN = (
    "This book is about getting back up. About team spirit, about nerves before a big "
    "game, and about believing in yourself while the whole world is watching.\n"
    "After the final back home, {name} receives a letter he hardly dares to open: "
    "the national team wants him at the World Cup.\n"
    "A warm and exciting story about friendship, courage and dreams that grow bigger "
    "than you dare to hope for.\n"
    "Because the biggest difference between a dream and an adventure is that someone "
    "dares to keep going when it gets hard."
)

_GB = [
    ("training ground", "training ground"),
    ("on the field", "on the pitch"),
    ("Beside the field", "Beside the pitch"),
    ("locker room", "changing room"),
    ("a soccer star", "a football star"),
]

COVER_GB = COVER_EN


def _to_gb(text):
    for src, dst in _GB:
        text = text.replace(src, dst)
    return text


PAGES_GB = [_to_gb(t) for t in PAGES_EN]
BACK_GB = _to_gb(BACK_EN)

# ---------------------------------------------------------------------------
#  SVENSK
# ---------------------------------------------------------------------------
COVER_SV = "{name} vinner\nFotbolls-VM"

PAGES_SV = [
    "Några dagar efter den stora finalen var {name} tillbaka på träningsplanen.\n"
    "Allt såg helt vanligt ut, ända tills tränaren ropade på honom.\n"
    "I handen höll han ett kuvert med en liten norsk flagga på.\n"
    "{name} kände hjärtat börja bulta.",

    "En landslagsscout hade suttit på läktaren under finalen.\n"
    "Han hade sett att {name} fortsatte kämpa när matchen blev svår.\n"
    "Nu ville de se honom igen.\n"
    "{name} öppnade brevet: han var kallad till landslagssamling.",

    "På samlingen mötte {name} spelare han aldrig hade sett förut.\n"
    "De var snabba. Väldigt snabba.\n"
    "Redan i den första övningen tappade han bollen. Sedan en gång till.\n"
    "Men han mindes vad tränaren hade lärt honom, och jagade bollen igen.",

    "I slutet av dagen läste landslagstränaren upp namnen.\n"
    "Det fanns bara en plats kvar i laget som skulle till VM.\n"
    "{name} hörde många andra bli uttagna, men inte sitt eget namn.\n"
    "Sedan lyfte tränaren blicken, och allt blev tyst.",

    "\"{name}!\"\n"
    "Lagkamraterna jublade, och {name} fick landslagströjan i händerna.\n"
    "På bröstet satt den norska flaggan.\n"
    "Nu var det inte längre bara träning. Han skulle spela för Norge.",

    "Planet landade i värdlandet.\n"
    "Genom fönstret såg {name} enorma arenor och flaggor från hela världen.\n"
    "På hotellet fick laget veta vilka de skulle möta först:\n"
    "ett av världens bästa lag. VM hade börjat.",

    "Den första matchen gick inte som Norge hoppats.\n"
    "Motståndarna gjorde mål. Sedan gjorde de mål igen.\n"
    "{name} tappade bollen i ett viktigt anfall, och matchen slutade med förlust.\n"
    "I omklädningsrummet sa nästan ingen ett ord.",

    "\"Ni är inte här för att allt alltid går perfekt,\" sa tränaren.\n"
    "\"Ni är här för att ni reser er igen.\"\n"
    "{name} tänkte på sitt allra första bomskott hemma på planen.\n"
    "Sedan reste han sig: \"Då vinner vi nästa.\"",

    "Nästa match blev vild. Norge låg under, och tiden rann ut.\n"
    "{name} fick bollen på kanten och dribblade förbi den ene, sedan den andre.\n"
    "Han kunde ha skjutit själv, men framför mål stod en lagkamrat helt ensam.\n"
    "{name} spelade in bollen. Mål! 1-1.",

    "Det återstod bara sekunder när bollen hamnade hos {name} igen.\n"
    "Läktaren reste sig.\n"
    "Han sprang mot mål medan försvararna kom från båda håll.\n"
    "{name} såg målet och drog foten bakåt.",

    "Skottet susade mot hörnet. Målvakten sträckte sig, men nådde det inte.\n"
    "MÅL! Lagkamraterna stormade mot {name}, och Norge var vidare.\n"
    "Sedan vann de nästa match. Och nästa.\n"
    "Ända tills bara fyra lag återstod i hela världen.",

    "Semifinalen blev den tuffaste match {name} någonsin spelat.\n"
    "Det stod oavgjort ända till slutet när motståndarna kom ensamma mot mål.\n"
    "{name} spurtade tillbaka och lyckades precis stoppa anfallet.\n"
    "Sekunder senare kontrade Norge, och lagkamraten gjorde mål. Final!",

    "Finaldagen kom, och {name} stod i spelartunneln.\n"
    "Framför honom låg den största arena han någonsin sett.\n"
    "Bredvid planen glittrade VM-pokalen under strålkastarna.\n"
    "En match. Det var allt som återstod. Sedan öppnades dörrarna.",

    "Finalen stod 1-1 när Norge fick frispark strax utanför straffområdet.\n"
    "{name} lade bollen till rätta, sprang fram och sköt. Rakt i krysset!\n"
    "När domaren blåste av lyfte lagkamraterna {name} upp i konfettin.\n"
    "Han hade blivit fotbollsstjärna. Nu var han världsmästare.",
]

BACK_SV = (
    "Den här boken handlar om att resa sig igen. Om laganda, om nerver före en stor "
    "match, och om att tro på sig själv medan hela världen ser på.\n"
    "Efter finalen hemma får {name} ett brev han knappt vågar öppna: "
    "landslaget vill ha med honom till VM.\n"
    "En varm och spännande berättelse om vänskap, mod och drömmar som blir större "
    "än man vågar hoppas på.\n"
    "För den största skillnaden mellan en dröm och ett äventyr är att någon vågar "
    "fortsätta när det blir svårt."
)

TRANSLATIONS = {
    "nn": (COVER_NN, PAGES_NN, BACK_NN),
    "en-US": (COVER_EN, PAGES_EN, BACK_EN),
    "en-GB": (COVER_GB, PAGES_GB, BACK_GB),
    "sv": (COVER_SV, PAGES_SV, BACK_SV),
}
