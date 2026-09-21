# -*- coding: utf-8 -*-
"""Kildetekst for Fotball VM (bok 2 i fotballstjernen-serien).

14 sider: 13 oppslag (2048x1024) + side 10 som to kvadratsider
(10-left = comfy-headswap uten tekst, 10-right = statisk bilde med teksten).

Sidevalget ("left"/"right") er regnet ut fra tyngdepunktet i headmasken:
cx < 0.5 -> figuren staar til venstre -> teksten skal til hoyre.

19.09.2026: hele kunsten for innersidene ble byttet ut og historien skrevet
om. Kvadratparet flyttet fra side 12 til side 10 (semifinalen mot Argentina),
og side 14 er den eneste sida som er beholdt fra den gamle serien - derfor
peker page14 fortsatt paa 14(fotball-vm).png. Teksten er kortere enn i bok 1
fordi manuset er kortere; boksen skalerer selv.
"""

COVER_NB = "(Navn) vinner\nFotball-VM"

BACK_NB = (
    "Denne boken handler om å reise seg igjen. Om lagånd, om nerver før en stor kamp, "
    "og om å tro på seg selv mens hele verden ser på.\n"
    "Etter den store kampen hjemme får (Navn) beskjeden han knapt tør å tro på: "
    "landslaget vil ha ham med til VM.\n"
    "En varm og spennende fortelling om vennskap, mot og drømmer som blir større "
    "enn man tør å håpe på.\n"
    "For den største forskjellen mellom en drøm og et eventyr er at noen tør å "
    "fortsette når det blir vanskelig."
)
BACK_HL = ["lagånd", "landslaget", "vennskap", "mot", "eventyr"]

# (side, tekst, highlights)
PAGES_NB = [
    ("left",
     "Etter den store kampen får (Navn) en helt spesiell beskjed.\n"
     "En speider har sett ham spille, og nå er han invitert til landslagssamling.",
     ["speider", "landslagssamling"]),
    ("left",
     "På samlingen trener (Navn) sammen med mange andre flinke barn.\n"
     "Han gir alt han har og håper at treneren legger merke til ham.",
     ["samlingen", "treneren"]),
    ("right",
     "Til slutt leser treneren opp navnene på spillerne som skal til VM.\n"
     "Så hører (Navn) sitt eget navn.\n"
     "Han skal spille for Norge!",
     ["treneren", "VM", "Norge"]),
    ("right",
     "VM starter mot Tyskland, men kampen blir tøff.\n"
     "Da dommeren blåser av, står det 2–0 til Tyskland.\n"
     "Det var ikke starten Norge hadde håpet på.",
     ["Tyskland", "dommeren", "Norge"]),
    ("left",
     "(Navn) sitter stille i garderoben etter tapet.\n"
     "For første gang begynner han å lure på om VM-eventyret kan være over\n"
     "før det egentlig har begynt.",
     ["garderoben", "VM-eventyret"]),
    ("right",
     "Treneren samler laget.\n"
     "«Én kamp bestemmer ikke hvem vi er.»\n"
     "(Navn) ser på lagkameratene. De er ikke ferdige ennå.",
     ["Treneren", "lagkameratene"]),
    ("left",
     "Norge kjemper seg videre, og neste store utfordring er Brasil.\n"
     "(Navn) løper ut på banen klar for en av de største kampene i livet sitt.",
     ["Norge", "Brasil", "banen"]),
    ("right",
     "Brasil presser hardt, men (Navn) nekter å gi seg.\n"
     "Han dribler mellom motstanderne og leter etter åpningen som Norge trenger.",
     ["Brasil", "dribler", "Norge"]),
    ("left",
     "Da sluttsignalet går, bryter jubelen løs.\n"
     "Norge har slått Brasil!\n"
     "Nå er de bare én kamp unna VM-finalen.",
     ["jubelen", "Brasil", "VM-finalen"]),
    # Side 10 = kvadratparet. Teksten staar paa hoyre kvadrat (det statiske bildet).
    ("square",
     "I semifinalen mot Argentina står det 2–2 mot slutten.\n"
     "Så får (Navn) sjansen.\n"
     "Han scorer — og sender Norge til VM-finalen.",
     ["semifinalen", "Argentina", "VM-finalen"]),
    ("left",
     "(Navn) står i spillertunnelen og ser ut mot stadion.\n"
     "På den andre siden venter Spania.\n"
     "Bare én kamp står mellom Norge og VM-pokalen.",
     ["spillertunnelen", "Spania", "VM-pokalen"]),
    ("left",
     "Finalen blir jevn og nervepirrende.\n"
     "Begge lag får sjanser, men ingen klarer å avgjøre.\n"
     "Mot slutten står det fortsatt 1–1.",
     ["Finalen", "sjanser"]),
    ("right",
     "Så får (Navn) ballen.\n"
     "Han ser åpningen, skyter —\n"
     "MÅL!\n"
     "Norge leder 2–1.",
     ["ballen", "MÅL", "Norge"]),
    ("right",
     "Sluttsignalet går.\n"
     "Norge har slått Spania 2–1 og vunnet Fotball-VM!\n"
     "(Navn) jubler med laget. Han er verdensmester.",
     ["Sluttsignalet", "Fotball-VM", "verdensmester"]),
]

# ---------------------------------------------------------------------------
#  NYNORSK
# ---------------------------------------------------------------------------
COVER_NN = "{name} vinn\nFotball-VM"

PAGES_NN = [
    "Etter den store kampen får {name} ein heilt spesiell beskjed.\n"
    "Ein speidar har sett han spele, og no er han invitert til landslagssamling.",

    "På samlinga trenar {name} saman med mange andre flinke barn.\n"
    "Han gjev alt han har og håpar at trenaren legg merke til han.",

    "Til slutt les trenaren opp namna på spelarane som skal til VM.\n"
    "Så høyrer {name} sitt eige namn.\n"
    "Han skal spele for Noreg!",

    "VM startar mot Tyskland, men kampen blir tøff.\n"
    "Då dommaren bles av, står det 2–0 til Tyskland.\n"
    "Det var ikkje starten Noreg hadde håpa på.",

    "{name} sit stille i garderoben etter tapet.\n"
    "For første gong byrjar han å lure på om VM-eventyret kan vere over\n"
    "før det eigentleg har byrja.",

    "Trenaren samlar laget.\n"
    "«Éin kamp avgjer ikkje kven vi er.»\n"
    "{name} ser på lagkameratane. Dei er ikkje ferdige enno.",

    "Noreg kjempar seg vidare, og neste store utfordring er Brasil.\n"
    "{name} spring ut på bana klar for ein av dei største kampane i livet sitt.",

    "Brasil pressar hardt, men {name} nektar å gje seg.\n"
    "Han driblar mellom motstandarane og leitar etter opninga som Noreg treng.",

    "Då sluttsignalet går, bryt jubelen laus.\n"
    "Noreg har slått Brasil!\n"
    "No er dei berre éin kamp unna VM-finalen.",

    "I semifinalen mot Argentina står det 2–2 mot slutten.\n"
    "Så får {name} sjansen.\n"
    "Han skårar — og sender Noreg til VM-finalen.",

    "{name} står i spelartunnelen og ser ut mot stadion.\n"
    "På den andre sida ventar Spania.\n"
    "Berre éin kamp står mellom Noreg og VM-pokalen.",

    "Finalen blir jamn og nervepirrande.\n"
    "Begge laga får sjansar, men ingen klarer å avgjere.\n"
    "Mot slutten står det framleis 1–1.",

    "Så får {name} ballen.\n"
    "Han ser opninga, skyt —\n"
    "MÅL!\n"
    "Noreg leier 2–1.",

    "Sluttsignalet går.\n"
    "Noreg har slått Spania 2–1 og vunne Fotball-VM!\n"
    "{name} jublar med laget. Han er verdsmeister.",
]

BACK_NN = (
    "Denne boka handlar om å reise seg igjen. Om lagånd, om nervar før ein stor kamp, "
    "og om å tru på seg sjølv medan heile verda ser på.\n"
    "Etter den store kampen heime får {name} beskjeden han knapt vågar å tru på: "
    "landslaget vil ha han med til VM.\n"
    "Ei varm og spennande forteljing om venskap, mot og draumar som blir større "
    "enn ein torer å håpe på.\n"
    "For den største skilnaden mellom ein draum og eit eventyr er at nokon vågar å "
    "halde fram når det blir vanskeleg."
)

# ---------------------------------------------------------------------------
#  ENGELSK (US = soccer/field, GB = football/pitch)
# ---------------------------------------------------------------------------
COVER_EN = "{name} Wins the\nWorld Cup"

PAGES_EN = [
    "After the big game, {name} gets a very special message.\n"
    "A scout has seen him play, and now he is invited to the national team camp.",

    "At the camp {name} trains with many other talented kids.\n"
    "He gives everything he has and hopes the coach will notice him.",

    "At last the coach reads out the names of the players going to the World Cup.\n"
    "Then {name} hears his own name.\n"
    "He is going to play for Norway!",

    "The World Cup starts against Germany, but the game is tough.\n"
    "When the referee blows the whistle, it is 2-0 to Germany.\n"
    "That was not the start Norway had hoped for.",

    "{name} sits quietly in the locker room after the defeat.\n"
    "For the first time he starts to wonder if the World Cup adventure is over\n"
    "before it has really begun.",

    "The coach gathers the team.\n"
    "\"One game does not decide who we are.\"\n"
    "{name} looks at his teammates. They are not finished yet.",

    "Norway fight their way on, and the next big challenge is Brazil.\n"
    "{name} runs onto the field ready for one of the biggest games of his life.",

    "Brazil press hard, but {name} refuses to give up.\n"
    "He dribbles between the defenders, looking for the opening Norway needs.",

    "When the final whistle goes, the cheering breaks loose.\n"
    "Norway have beaten Brazil!\n"
    "Now they are only one game away from the World Cup final.",

    "In the semifinal against Argentina it is 2-2 near the end.\n"
    "Then {name} gets his chance.\n"
    "He scores - and sends Norway to the World Cup final.",

    "{name} stands in the players' tunnel and looks out at the stadium.\n"
    "On the other side, Spain are waiting.\n"
    "Only one game stands between Norway and the World Cup trophy.",

    "The final is close and nerve-racking.\n"
    "Both teams get chances, but nobody can settle it.\n"
    "Near the end it is still 1-1.",

    "Then {name} gets the ball.\n"
    "He sees the opening, shoots -\n"
    "GOAL!\n"
    "Norway lead 2-1.",

    "The final whistle goes.\n"
    "Norway have beaten Spain 2-1 and won the World Cup!\n"
    "{name} celebrates with the team. He is a world champion.",
]

BACK_EN = (
    "This book is about getting back up. About team spirit, about nerves before a big "
    "game, and about believing in yourself while the whole world is watching.\n"
    "After the big game back home, {name} gets the message he hardly dares to believe: "
    "the national team wants him at the World Cup.\n"
    "A warm and exciting story about friendship, courage and dreams that grow bigger "
    "than you dare to hope for.\n"
    "Because the biggest difference between a dream and an adventure is that someone "
    "dares to keep going when it gets hard."
)

_GB = [
    ("training ground", "training ground"),
    ("onto the field", "onto the pitch"),
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
    "Efter den stora matchen får {name} ett alldeles särskilt besked.\n"
    "En scout har sett honom spela, och nu är han kallad till landslagssamling.",

    "På samlingen tränar {name} tillsammans med många andra duktiga barn.\n"
    "Han ger allt han har och hoppas att tränaren ska lägga märke till honom.",

    "Till slut läser tränaren upp namnen på spelarna som ska till VM.\n"
    "Så hör {name} sitt eget namn.\n"
    "Han ska spela för Norge!",

    "VM börjar mot Tyskland, men matchen blir tuff.\n"
    "När domaren blåser av står det 2–0 till Tyskland.\n"
    "Det var inte starten Norge hade hoppats på.",

    "{name} sitter tyst i omklädningsrummet efter förlusten.\n"
    "För första gången börjar han undra om VM-äventyret kan vara över\n"
    "innan det egentligen har börjat.",

    "Tränaren samlar laget.\n"
    "«En match avgör inte vilka vi är.»\n"
    "{name} ser på lagkamraterna. De är inte färdiga än.",

    "Norge kämpar sig vidare, och nästa stora utmaning är Brasilien.\n"
    "{name} springer ut på planen redo för en av de största matcherna i sitt liv.",

    "Brasilien pressar hårt, men {name} vägrar att ge sig.\n"
    "Han dribblar mellan motståndarna och letar efter öppningen som Norge behöver.",

    "När slutsignalen går bryter jublet loss.\n"
    "Norge har slagit Brasilien!\n"
    "Nu är de bara en match från VM-finalen.",

    "I semifinalen mot Argentina står det 2–2 mot slutet.\n"
    "Så får {name} chansen.\n"
    "Han gör mål — och skickar Norge till VM-finalen.",

    "{name} står i spelartunneln och ser ut mot arenan.\n"
    "På andra sidan väntar Spanien.\n"
    "Bara en match står mellan Norge och VM-pokalen.",

    "Finalen blir jämn och nervkittlande.\n"
    "Båda lagen får chanser, men ingen lyckas avgöra.\n"
    "Mot slutet står det fortfarande 1–1.",

    "Så får {name} bollen.\n"
    "Han ser öppningen, skjuter —\n"
    "MÅL!\n"
    "Norge leder 2–1.",

    "Slutsignalen går.\n"
    "Norge har slagit Spanien 2–1 och vunnit Fotbolls-VM!\n"
    "{name} jublar med laget. Han är världsmästare.",
]

BACK_SV = (
    "Den här boken handlar om att resa sig igen. Om laganda, om nerver före en stor "
    "match, och om att tro på sig själv medan hela världen tittar på.\n"
    "Efter den stora matchen hemma får {name} beskedet han knappt vågar tro på: "
    "landslaget vill ha honom med till VM.\n"
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
