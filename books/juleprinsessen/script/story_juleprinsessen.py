# -*- coding: utf-8 -*-
"""Kildetekst for Juleprinsessen.

14 oppslag (2048x1024), ren annenhver side - ingen kvadratsider.

Sidevalget ("left"/"right") er regnet ut fra tyngdepunktet i headmasken:
cx < 0.5 -> figuren staar til venstre -> teksten skal til hoyre.
    01 .78 L | 02 .22 R | 03 .76 L | 04 .29 R | 05 .67 L | 06 .35 R | 07 .78 L
    08 .21 R | 09 .72 L | 10 .22 R | 11 .64 L | 12 .68 L | 13 .26 R | 14 .71 L

Side 1-6 foelger brukerens egen sidebeskrivelse.
Side 7-14 er skrevet etter illustrasjonene og skal erstattes hvis brukeren
sender sin egen tekst for dem.
"""

COVER_NB = "(Navn)\nJuleprinsessen"

BACK_NB = (
    "Denne boken handler om et lite juleønske. Om å tørre å gå ut i vinternatten "
    "alene, fordi noe inni deg sier at du må.\n"
    "Når (Navn) følger det gyldne lyset over himmelen, møter hun snøharen Fnugg, "
    "en glemt landsby og en jul som trenger akkurat henne.\n"
    "En varm fortelling om mot, vennskap og om å gi bort noe til noen andre.\n"
    "En bok som minner barnet på at de aller minste hendene kan redde den største kvelden."
)
BACK_HL = ["juleønske", "Fnugg", "mot", "vennskap", "barnet"]

# (side, tekst, highlights)
PAGES_NB = [
    # Side 1 - slottet der det aldri har snødd
    ("left",
     "Høyt oppe på en frostglitrende ås lå slottet der (Navn) bodde.\n"
     "Hun hadde hørt om snø. Hun hadde sett bilder av snø.\n"
     "Men aldri hadde et eneste snøfnugg landet i hånden hennes.\n"
     "Hver vinter så hun opp på himmelen og håpet at akkurat denne skulle bli annerledes.",
     ["slottet", "snøfnugg", "himmelen"]),

    # Side 2 - julaften inne, hun staar alene ved vinduet
    ("right",
     "Nå var det julaften, og hele slottet skinte.\n"
     "Juletreet lyste, lysene brant, og det luktet kaker i hver eneste gang.\n"
     "Men (Navn) stod ved vinduet og så ut på den bare bakken.\n"
     "«Jeg ønsker meg bare ett eneste snøfnugg,» hvisket hun.",
     ["julaften", "vinduet", "snøfnugg"]),

    # Side 3 - lyset paa himmelen
    ("left",
     "Akkurat da fór et gyllent lys over den mørkeblå himmelen.\n"
     "Det var varmere enn en stjerne, og det la igjen et glitrende spor.\n"
     "(Navn) trykket hendene mot det kalde vinduet.\n"
     "Det føltes ikke som noe hun bare skulle se på. Det føltes som om lyset hadde funnet henne.",
     ["gyllent", "stjerne", "glitrende"]),

    # Side 4 - ut gjennom porten
    ("right",
     "Hun tok på seg den røde kappen, luen og de varme støvlene.\n"
     "Så åpnet (Navn) den store slottsporten og gikk ut i vinternatten.\n"
     "Bak henne ble det varme lyset fra slottet mindre og mindre.\n"
     "Foran henne lå det gyldne sporet og ventet mellom trærne.",
     ["kappen", "slottsporten", "vinternatten"]),

    # Side 5 - skogen og motet med Fnugg
    ("left",
     "Inne mellom grantrærne hørte hun en liten lyd ved røttene.\n"
     "Et par lange ører kom til syne. Så en liten, hvit snøhare.\n"
     "«Hei,» sa (Navn) forsiktig. «Så du lyset, du også?»\n"
     "Haren pekte med nesen mot sporet på himmelen. Fra nå av het han Fnugg, og nå var de to.",
     ["snøhare", "Fnugg", "sporet"]),

    # Side 6 - det frosne vannet
    ("right",
     "Sporet førte dem ned til et vann som lå blankt og stille mellom trærne.\n"
     "Isen speilet stjernene, og det gyldne lyset glitret under føttene deres.\n"
     "(Navn) skled, fektet med armene og fant balansen igjen.\n"
     "Så begynte hun å le, og Fnugg hoppet etter henne over hele isen.",
     ["Isen", "stjernene", "le"]),

    # Side 7 - himmelen fylles av farger
    ("left",
     "På den andre siden av vannet stoppet de helt opp.\n"
     "Hele himmelen hadde fylt seg med grønne og fiolette bølger som beveget seg sakte.\n"
     "(Navn) satte seg ned i snøen ved siden av Fnugg og glemte å puste.\n"
     "Midt inne i fargene lyste det gyldne sporet videre, ned mot dalen.",
     ["himmelen", "bølger", "dalen"]),

    # Side 8 - landsbyen i dalen
    ("right",
     "Under dem lå en landsby hun aldri hadde sett på noe kart.\n"
     "Små hus med snødekte tak sto tett i tett, og fra hvert vindu kom det varmt lys.\n"
     "Men det var altfor stille dernede. Ingen sang, ingen bjeller.\n"
     "«Noe er galt,» sa (Navn), og begynte å gå ned mot lysene.",
     ["landsby", "lys", "stille"]),

    # Side 9 - verkstedet
    ("left",
     "Inne i det største huset sto det lange benker fulle av leker.\n"
     "Små nisser løp fram og tilbake, og midt i rommet sto en gammel mann med hvitt skjegg.\n"
     "Han snudde seg og så på (Navn) med trøtte øyne.\n"
     "«Du kom,» sa han stille. «Jeg håpet noen ville følge etter lyset.»",
     ["leker", "nisser", "lyset"]),

    # Side 10 - julestjernen er borte
    ("right",
     "Han tok henne med ut og pekte opp mot den mørke himmelen.\n"
     "«Julestjernen falt av sleden i natt. Uten den finner ikke reinsdyrene veien.»\n"
     "Nede ved gjerdet sto sleden ferdig pakket, og reinsdyrene ventet urolig.\n"
     "(Navn) kjente hjertet slå fortere. Hun visste hvor lyset hadde landet.",
     ["Julestjernen", "sleden", "reinsdyrene"]),

    # Side 11 - hun finner stjernen
    ("left",
     "Hun og Fnugg lette seg oppover bakken, dit sporet hadde sluttet.\n"
     "Og der, halvveis nede i den myke snøen, lå den.\n"
     "En gyllen stjerne som fortsatt pustet med et varmt lys.\n"
     "Forsiktig løftet (Navn) den opp med begge hendene.",
     ["Fnugg", "gyllen", "stjerne"]),

    # Side 12 - opp gjennom skogen
    ("left",
     "Stjernen var tyngre enn den så ut, men (Navn) bar den hele veien.\n"
     "Opp gjennom skogen, forbi de snødekte grantrærne, helt til toppen av åsen.\n"
     "Månen sto stor over dalen, og langt der nede ventet landsbyen.\n"
     "«Nå,» hvisket hun, og løftet stjernen så høyt hun kunne.",
     ["Stjernen", "Månen", "landsbyen"]),

    # Side 13 - stjernen tennes
    ("right",
     "Stjernen tente seg i hendene hennes og skjøt lyset ut over hele himmelen.\n"
     "Fjellene, vannet og hvert eneste tak i landsbyen ble badet i gull.\n"
     "Langt nede hørte hun bjeller, latter og en slede som lettet fra bakken.\n"
     "Julen var reddet, og det var (Navn) som hadde gjort det.",
     ["Stjernen", "gull", "bjeller"]),

    # Side 14 - snoen kommer hjem til slottet
    ("left",
     "Da (Navn) kom hjem til slottet, var himmelen helt stille igjen.\n"
     "Og så, langsomt, kom det første snøfnugget dalende ned og landet i hånden hennes.\n"
     "Så ett til. Og ett til. Snøen la seg over takene, over trærne, over hele åsen.\n"
     "(Navn) snurret rundt med Fnugg i den hvite julemorgenen, og lo.",
     ["snøfnugget", "Snøen", "Fnugg"]),
]

# ---------------------------------------------------------------- nynorsk
COVER_NN = "{name}\nJuleprinsessen"
BACK_NN = (
    "Denne boka handlar om eit lite juleønske. Om å våge å gå ut i vinternatta "
    "åleine, fordi noko inni deg seier at du må.\n"
    "Når {name} følgjer det gylne lyset over himmelen, møter ho snøharen Fnugg, "
    "ein gløymd landsby og ei jul som treng nettopp henne.\n"
    "Ei varm forteljing om mot, venskap og om å gje bort noko til nokon andre.\n"
    "Ei bok som minner barnet på at dei aller minste hendene kan redde den største kvelden."
)
PAGES_NN = [
    "Høgt oppe på ein frostglitrande ås låg slottet der {name} budde.\n"
    "Ho hadde høyrt om snø. Ho hadde sett bilete av snø.\n"
    "Men aldri hadde eit einaste snøfnugg landa i handa hennar.\n"
    "Kvar vinter såg ho opp på himmelen og håpa at nettopp denne skulle bli annleis.",

    "No var det julaftan, og heile slottet skein.\n"
    "Juletreet lyste, lysa brann, og det lukta kaker i kvar einaste gang.\n"
    "Men {name} stod ved vindauget og såg ut på den bare bakken.\n"
    "«Eg ønskjer meg berre eitt einaste snøfnugg,» kviskra ho.",

    "Akkurat då fór eit gylent lys over den mørkeblå himmelen.\n"
    "Det var varmare enn ei stjerne, og det la att eit glitrande spor.\n"
    "{name} trykte hendene mot det kalde vindauget.\n"
    "Det kjendest ikkje som noko ho berre skulle sjå på. Det kjendest som om lyset hadde funne henne.",

    "Ho tok på seg den raude kappa, lua og dei varme støvlane.\n"
    "Så opna {name} den store slottsporten og gjekk ut i vinternatta.\n"
    "Bak henne vart det varme lyset frå slottet mindre og mindre.\n"
    "Framfor henne låg det gylne sporet og venta mellom trea.",

    "Inne mellom granene høyrde ho ein liten lyd ved røtene.\n"
    "Eit par lange øyre kom til syne. Så ein liten, kvit snøhare.\n"
    "«Hei,» sa {name} forsiktig. «Såg du lyset, du òg?»\n"
    "Haren peika med nasen mot sporet på himmelen. Frå no av heitte han Fnugg, og no var dei to.",

    "Sporet førte dei ned til eit vatn som låg blankt og stille mellom trea.\n"
    "Isen spegla stjernene, og det gylne lyset glitra under føtene deira.\n"
    "{name} skleid, fekta med armane og fann balansen igjen.\n"
    "Så byrja ho å le, og Fnugg hoppa etter henne over heile isen.",

    "På den andre sida av vatnet stoppa dei heilt opp.\n"
    "Heile himmelen hadde fylt seg med grøne og fiolette bølgjer som rørte seg sakte.\n"
    "{name} sette seg ned i snøen ved sida av Fnugg og gløymde å puste.\n"
    "Midt inne i fargane lyste det gylne sporet vidare, ned mot dalen.",

    "Under dei låg ein landsby ho aldri hadde sett på noko kart.\n"
    "Små hus med snødekte tak stod tett i tett, og frå kvart vindauge kom det varmt lys.\n"
    "Men det var altfor stille der nede. Ingen song, ingen bjøller.\n"
    "«Noko er gale,» sa {name}, og byrja å gå ned mot lysa.",

    "Inne i det største huset stod det lange benker fulle av leiker.\n"
    "Små nissar sprang fram og tilbake, og midt i rommet stod ein gammal mann med kvitt skjegg.\n"
    "Han snudde seg og såg på {name} med trøytte auge.\n"
    "«Du kom,» sa han stille. «Eg håpa nokon ville følgje etter lyset.»",

    "Han tok henne med ut og peika opp mot den mørke himmelen.\n"
    "«Julestjerna fall av sleden i natt. Utan henne finn ikkje reinsdyra vegen.»\n"
    "Nede ved gjerdet stod sleden ferdig pakka, og reinsdyra venta uroleg.\n"
    "{name} kjende hjartet slå fortare. Ho visste kvar lyset hadde landa.",

    "Ho og Fnugg leita seg oppover bakken, dit sporet hadde slutta.\n"
    "Og der, halvvegs nede i den mjuke snøen, låg ho.\n"
    "Ei gylen stjerne som framleis pusta med eit varmt lys.\n"
    "Forsiktig lyfte {name} henne opp med begge hendene.",

    "Stjerna var tyngre enn ho såg ut, men {name} bar henne heile vegen.\n"
    "Opp gjennom skogen, forbi dei snødekte granene, heilt til toppen av åsen.\n"
    "Månen stod stor over dalen, og langt der nede venta landsbyen.\n"
    "«No,» kviskra ho, og lyfte stjerna så høgt ho kunne.",

    "Stjerna tende seg i hendene hennar og skaut lyset ut over heile himmelen.\n"
    "Fjella, vatnet og kvart einaste tak i landsbyen vart bada i gull.\n"
    "Langt nede høyrde ho bjøller, latter og ein slede som letta frå bakken.\n"
    "Jula var redda, og det var {name} som hadde gjort det.",

    "Då {name} kom heim til slottet, var himmelen heilt stille igjen.\n"
    "Og så, langsamt, kom det første snøfnugget dalande ned og landa i handa hennar.\n"
    "Så eitt til. Og eitt til. Snøen la seg over taka, over trea, over heile åsen.\n"
    "{name} snurra rundt med Fnugg i den kvite julemorgonen, og lo.",
]

# ---------------------------------------------------------------- english (US)
COVER_EN = "{name}\nThe Christmas Princess"
BACK_EN = (
    "This book is about one small Christmas wish. About daring to walk out into the "
    "winter night alone, because something inside you says you must.\n"
    "When {name} follows the golden light across the sky, she meets Snowflake the hare, "
    "a forgotten village and a Christmas that needs her.\n"
    "A warm story about courage, friendship and giving something away to someone else.\n"
    "A book that reminds a child that the smallest hands can save the biggest night of all."
)
PAGES_EN = [
    "High on a frost-glittering hill stood the castle where {name} lived.\n"
    "She had heard about snow. She had seen pictures of snow.\n"
    "But not once had a single snowflake landed in her hand.\n"
    "Every winter she looked up at the sky and hoped that this one would be different.",

    "Now it was Christmas Eve, and the whole castle was shining.\n"
    "The tree glowed, the candles burned, and every hallway smelled of cakes.\n"
    "But {name} stood at the window, looking out at the bare ground.\n"
    "\"All I want is one single snowflake,\" she whispered.",

    "Just then a golden light swept across the dark blue sky.\n"
    "It was warmer than a star, and it left a glittering trail behind it.\n"
    "{name} pressed her hands against the cold window.\n"
    "It did not feel like something to watch. It felt as if the light had found her.",

    "She put on her red cloak, her hat and her warm boots.\n"
    "Then {name} opened the great castle gate and stepped out into the winter night.\n"
    "Behind her the warm light of the castle grew smaller and smaller.\n"
    "Ahead of her the golden trail lay waiting between the trees.",

    "In among the spruce trees she heard a small sound down by the roots.\n"
    "A pair of long ears appeared. Then a little white snow hare.\n"
    "\"Hello,\" said {name} carefully. \"Did you see the light too?\"\n"
    "The hare pointed his nose at the trail in the sky. From now on his name was Snowflake, and now they were two.",

    "The trail led them down to a lake lying smooth and silent between the trees.\n"
    "The ice mirrored the stars, and the golden light glittered under their feet.\n"
    "{name} slipped, waved her arms and found her balance again.\n"
    "Then she began to laugh, and Snowflake hopped after her all across the ice.",

    "On the far side of the lake they stopped completely.\n"
    "The whole sky had filled with green and violet waves moving slowly above them.\n"
    "{name} sat down in the snow beside Snowflake and forgot to breathe.\n"
    "Right through the colours the golden trail shone on, down toward the valley.",

    "Below them lay a village she had never seen on any map.\n"
    "Small houses with snowy roofs stood close together, and warm light came from every window.\n"
    "But it was far too quiet down there. No singing, no bells.\n"
    "\"Something is wrong,\" said {name}, and started down toward the lights.",

    "Inside the biggest house stood long benches covered in toys.\n"
    "Little elves ran back and forth, and in the middle of the room stood an old man with a white beard.\n"
    "He turned and looked at {name} with tired eyes.\n"
    "\"You came,\" he said quietly. \"I hoped someone would follow the light.\"",

    "He took her outside and pointed up at the dark sky.\n"
    "\"The Christmas star fell off the sleigh tonight. Without it the reindeer cannot find the way.\"\n"
    "Down by the fence the sleigh stood packed and ready, and the reindeer waited restlessly.\n"
    "{name} felt her heart beat faster. She knew where the light had landed.",

    "She and Snowflake searched their way up the hillside, to where the trail had ended.\n"
    "And there, half buried in the soft snow, it lay.\n"
    "A golden star still breathing with a warm light.\n"
    "Carefully {name} lifted it up with both hands.",

    "The star was heavier than it looked, but {name} carried it the whole way.\n"
    "Up through the forest, past the snow-covered spruces, all the way to the top of the hill.\n"
    "The moon stood huge above the valley, and far below the village was waiting.\n"
    "\"Now,\" she whispered, and lifted the star as high as she could.",

    "The star lit up in her hands and threw its light out across the entire sky.\n"
    "The mountains, the lake and every single roof in the village were bathed in gold.\n"
    "Far below she heard bells, laughter and a sleigh lifting off the ground.\n"
    "Christmas was saved, and it was {name} who had done it.",

    "When {name} came home to the castle, the sky was completely still again.\n"
    "And then, slowly, the first snowflake came drifting down and landed in her hand.\n"
    "Then another. And another. The snow settled over the roofs, the trees, the whole hill.\n"
    "{name} spun around with Snowflake in the white Christmas morning, and laughed.",
]

# ---------------------------------------------------------------- english (GB)
COVER_GB = COVER_EN
BACK_GB = BACK_EN
PAGES_GB = [
    t.replace("down toward the valley", "down towards the valley")
     .replace("started down toward the lights", "started down towards the lights")
    for t in PAGES_EN
]

# ---------------------------------------------------------------- svenska
COVER_SV = "{name}\nJulprinsessan"
BACK_SV = (
    "Den här boken handlar om en liten julönskan. Om att våga gå ut i vinternatten "
    "ensam, för att något inom dig säger att du måste.\n"
    "När {name} följer det gyllene ljuset över himlen möter hon snöharen Fnugg, "
    "en glömd by och en jul som behöver just henne.\n"
    "En varm berättelse om mod, vänskap och om att ge bort något till någon annan.\n"
    "En bok som påminner barnet om att de allra minsta händerna kan rädda den största kvällen."
)
PAGES_SV = [
    "Högt uppe på en frostglittrande ås låg slottet där {name} bodde.\n"
    "Hon hade hört om snö. Hon hade sett bilder på snö.\n"
    "Men aldrig hade ett enda snöflingor landat i hennes hand.\n"
    "Varje vinter såg hon upp mot himlen och hoppades att just den här skulle bli annorlunda.",

    "Nu var det julafton, och hela slottet lyste.\n"
    "Granen glittrade, ljusen brann, och det doftade kakor i varenda korridor.\n"
    "Men {name} stod vid fönstret och såg ut över den bara marken.\n"
    "»Jag önskar mig bara en enda snöflinga,» viskade hon.",

    "Just då for ett gyllene ljus över den mörkblå himlen.\n"
    "Det var varmare än en stjärna, och det lämnade ett glittrande spår efter sig.\n"
    "{name} tryckte händerna mot det kalla fönstret.\n"
    "Det kändes inte som något att bara titta på. Det kändes som om ljuset hade hittat henne.",

    "Hon tog på sig den röda kappan, mössan och de varma stövlarna.\n"
    "Sedan öppnade {name} den stora slottsporten och gick ut i vinternatten.\n"
    "Bakom henne blev slottets varma ljus mindre och mindre.\n"
    "Framför henne låg det gyllene spåret och väntade mellan träden.",

    "Inne bland granarna hörde hon ett litet ljud nere vid rötterna.\n"
    "Ett par långa öron kom fram. Sedan en liten, vit snöhare.\n"
    "»Hej,» sa {name} försiktigt. »Såg du ljuset, du också?»\n"
    "Haren pekade med nosen mot spåret på himlen. Från och med nu hette han Fnugg, och nu var de två.",

    "Spåret ledde dem ner till en sjö som låg blank och tyst mellan träden.\n"
    "Isen speglade stjärnorna, och det gyllene ljuset glittrade under deras fötter.\n"
    "{name} halkade, viftade med armarna och hittade balansen igen.\n"
    "Sedan började hon skratta, och Fnugg hoppade efter henne över hela isen.",

    "På andra sidan sjön stannade de helt.\n"
    "Hela himlen hade fyllts av gröna och violetta vågor som rörde sig långsamt.\n"
    "{name} satte sig ner i snön bredvid Fnugg och glömde att andas.\n"
    "Mitt inne i färgerna lyste det gyllene spåret vidare, ner mot dalen.",

    "Under dem låg en by hon aldrig sett på någon karta.\n"
    "Små hus med snötäckta tak stod tätt ihop, och från varje fönster kom varmt ljus.\n"
    "Men det var alldeles för tyst där nere. Ingen sång, inga bjällror.\n"
    "»Något är fel,» sa {name}, och började gå ner mot ljusen.",

    "Inne i det största huset stod långa bänkar fulla av leksaker.\n"
    "Små tomtar sprang fram och tillbaka, och mitt i rummet stod en gammal man med vitt skägg.\n"
    "Han vände sig om och såg på {name} med trötta ögon.\n"
    "»Du kom,» sa han tyst. »Jag hoppades att någon skulle följa ljuset.»",

    "Han tog med henne ut och pekade upp mot den mörka himlen.\n"
    "»Julstjärnan föll av släden i natt. Utan den hittar inte renarna vägen.»\n"
    "Nere vid staketet stod släden färdigpackad, och renarna väntade oroligt.\n"
    "{name} kände hjärtat slå fortare. Hon visste var ljuset hade landat.",

    "Hon och Fnugg letade sig uppför backen, dit spåret hade slutat.\n"
    "Och där, halvvägs nere i den mjuka snön, låg den.\n"
    "En gyllene stjärna som fortfarande andades med ett varmt ljus.\n"
    "Försiktigt lyfte {name} upp den med båda händerna.",

    "Stjärnan var tyngre än den såg ut, men {name} bar den hela vägen.\n"
    "Upp genom skogen, förbi de snötäckta granarna, ända till toppen av åsen.\n"
    "Månen stod stor över dalen, och långt där nere väntade byn.\n"
    "»Nu,» viskade hon, och lyfte stjärnan så högt hon kunde.",

    "Stjärnan tändes i hennes händer och sköt ljuset ut över hela himlen.\n"
    "Bergen, sjön och varenda tak i byn badade i guld.\n"
    "Långt där nere hörde hon bjällror, skratt och en släde som lyfte från marken.\n"
    "Julen var räddad, och det var {name} som hade gjort det.",

    "När {name} kom hem till slottet var himlen alldeles stilla igen.\n"
    "Och så, långsamt, kom den första snöflingan singlande ner och landade i hennes hand.\n"
    "Sedan en till. Och en till. Snön lade sig över taken, över träden, över hela åsen.\n"
    "{name} snurrade runt med Fnugg i den vita julmorgonen, och skrattade.",
]

TRANSLATIONS = {
    "nn": (COVER_NN, PAGES_NN, BACK_NN),
    "en-US": (COVER_EN, PAGES_EN, BACK_EN),
    "en-GB": (COVER_GB, PAGES_GB, BACK_GB),
    "sv": (COVER_SV, PAGES_SV, BACK_SV),
}
