# -*- coding: utf-8 -*-
"""Ny historie for Motet i Hjertet (14 sider) - kilde + oversettelser.

Kildeteksten bruker (Navn) slik build_pages gjor. Oversettelsesnoklene
bruker {name}, som _dreampage_text_key lager.
"""

NB = [
    # 1
    "Det var en gang en jente som het (Navn).\n"
    "Fra vinduet sitt kunne hun se det store slottet langt borte mellom åsene.\n"
    "Men denne morgenen lå det en konvolutt utenfor døren hennes, forseglet med en liten gullkrone.\n"
    "På forsiden stod det bare: Til (Navn).",
    # 2
    "(Navn) åpnet brevet forsiktig.\n"
    "«Du er invitert til slottet for å gjennomføre Prinsessens prøve,» stod det.\n"
    "«Bare den som finner motet i hjertet, kan bære kongerikets krone.»\n"
    "(Navn) kjente hjertet slå fortere. Kunne hun virkelig bli prinsesse?",
    # 3
    "Da (Navn) kom frem, åpnet de enorme slottsportene seg foran henne.\n"
    "Inne ventet dronningen med en glitrende krone i hendene.\n"
    "«En krone alene gjør ingen til prinsesse,» sa hun vennlig.\n"
    "«Først må du vise hva som finnes her.» Hun pekte mot (Navn) sitt hjerte.",
    # 4
    "Bak slottet begynte en smal sti som forsvant inn mellom trærne.\n"
    "«Følg stien helt til den kommer tilbake til slottet,» forklarte dronningen.\n"
    "«Underveis vil du møte Prinsessens prøve.»\n"
    "(Navn) tok et dypt pust og gikk av sted.",
    # 5
    "Jo dypere (Navn) gikk inn i skogen, desto mer forandret den seg.\n"
    "Små lys blinket mellom trærne, og fargerike sommerfugler fløy foran henne.\n"
    "Hver gang stien delte seg, samlet sommerfuglene seg ved den riktige veien.\n"
    "(Navn) smilte. Kanskje prøven ikke var så vanskelig likevel.",
    # 6
    "Men plutselig stoppet (Navn).\n"
    "Foran henne lå en gammel trebro over en brusende bekk. Noen av plankene knirket i vinden.\n"
    "På den andre siden fortsatte sommerfuglene videre.\n"
    "(Navn) kjente en liten uro i magen. Nå begynte prøven på ordentlig.",
    # 7
    "(Navn) satte én fot på broen. Så én til.\n"
    "Hun var fortsatt litt redd, men hun fortsatte likevel.\n"
    "Da hun nådde den andre siden, snudde hun seg og så tilbake på broen.\n"
    "«Jeg gjorde det,» hvisket hun og kjente et lite smil vokse frem.",
    # 8
    "Snart hørte (Navn) lyden av fossende vann.\n"
    "En bred elv sperret veien, og den eneste veien over var noen store steiner ute i vannet.\n"
    "Denne gangen kjente hun virkelig frykten komme.\n"
    "«Hva om jeg faller?» tenkte hun.",
    # 9
    "(Navn) lukket øynene og la hånden mot hjertet.\n"
    "Da husket hun det dronningen hadde sagt. Mot betydde ikke at man aldri var redd.\n"
    "Mot var å prøve selv når man var redd.\n"
    "Hun åpnet øynene. «Jeg klarer dette.»",
    # 10
    "(Navn) hoppet til den første steinen. Så den neste.\n"
    "Vannet sprutet rundt føttene hennes mens hun beveget seg stadig nærmere den andre siden.\n"
    "Med ett siste stort hopp landet hun trygt på bredden.\n"
    "Hun lo høyt. Hun hadde klart den vanskeligste delen av prøven!",
    # 11
    "Da (Navn) skulle gå videre, hørte hun plutselig en svak lyd bak seg.\n"
    "På en liten stein ved elvekanten satt en reveunge og pep etter hjelp.\n"
    "Slottet kunne allerede skimtes mellom trærne. Hun var nesten ferdig.\n"
    "Likevel snudde (Navn) seg. Hun kunne ikke bare gå fra den.",
    # 12
    "(Navn) hjalp den lille reven tilbake til trygg grunn og skyndte seg videre mot slottet.\n"
    "«Beklager,» sa hun til dronningen. «Jeg stoppet for å hjelpe noen.»\n"
    "Men dronningen begynte å smile.\n"
    "«Du trenger ikke beklage. Det var den siste delen av prøven.»",
    # 13
    "Slottsportene åpnet seg, og hele kongeriket ventet innenfor.\n"
    "Dronningen løftet den glitrende kronen og satte den forsiktig på hodet til (Navn).\n"
    "«Du viste mot da du var redd, og du hjalp noen da du kunne ha gått videre.»\n"
    "«Fra denne dagen er du Prinsesse (Navn).»",
    # 14
    "Den kvelden lyste himmelen i rosa og gull over slottet.\n"
    "Fyrverkeri fylte himmelen mens hele kongeriket feiret sin nye prinsesse.\n"
    "(Navn) så utover landet som nå var blitt hennes hjem.\n"
    "Hun hadde fått en krone – men hennes største skatt var fortsatt motet i hjertet.",
]

# Uthevede ord - matches mot den norske teksten (bare nb/nn treffer i praksis)
HIGHLIGHTS = [
    ["gullkrone", "slottet"],
    ["motet", "prinsesse"],
    ["krone", "hjerte"],
    ["sti", "dypt"],
    ["sommerfuglene", "smilte"],
    ["uro", "gammel"],
    ["gjorde", "smil"],
    ["frykten", "elv"],
    ["mot", "klarer"],
    ["hopp", "klart"],
    ["hjelp", "snudde"],
    ["hjelpe", "smile"],
    ["mot", "kronen"],
    ["motet", "krone"],
]

NN = [
    "Det var ein gong ei jente som heitte {name}.\n"
    "Frå vindauget sitt kunne ho sjå det store slottet langt borte mellom åsane.\n"
    "Men denne morgonen låg det ein konvolutt utanfor døra hennar, forsegla med ei lita gullkrone.\n"
    "På framsida stod det berre: Til {name}.",

    "{name} opna brevet forsiktig.\n"
    "«Du er invitert til slottet for å gjennomføre Prinsesseprova,» stod det.\n"
    "«Berre den som finn motet i hjartet, kan bere krona til kongeriket.»\n"
    "{name} kjende hjartet slå fortare. Kunne ho verkeleg bli prinsesse?",

    "Då {name} kom fram, opna dei enorme slottsportane seg framfor henne.\n"
    "Inne venta dronninga med ei glitrande krone i hendene.\n"
    "«Ei krone åleine gjer ingen til prinsesse,» sa ho venleg.\n"
    "«Først må du vise kva som finst her.» Ho peika mot hjartet til {name}.",

    "Bak slottet byrja ein smal sti som forsvann inn mellom trea.\n"
    "«Følg stien heilt til han kjem tilbake til slottet,» forklarte dronninga.\n"
    "«Undervegs vil du møte Prinsesseprova.»\n"
    "{name} tok eit djupt pust og gjekk av stad.",

    "Jo djupare {name} gjekk inn i skogen, dess meir forandra han seg.\n"
    "Små lys blinka mellom trea, og fargerike sommarfuglar flaug framfor henne.\n"
    "Kvar gong stien delte seg, samla sommarfuglane seg ved den rette vegen.\n"
    "{name} smilte. Kanskje prova ikkje var så vanskeleg likevel.",

    "Men brått stoppa {name}.\n"
    "Framfor henne låg ei gammal trebru over ein brusande bekk. Nokre av plankane knirka i vinden.\n"
    "På den andre sida heldt sommarfuglane fram.\n"
    "{name} kjende ei lita uro i magen. No byrja prova på ordentleg.",

    "{name} sette éin fot på brua. Så éin til.\n"
    "Ho var framleis litt redd, men ho heldt fram likevel.\n"
    "Då ho nådde den andre sida, snudde ho seg og såg tilbake på brua.\n"
    "«Eg gjorde det,» kviskra ho og kjende eit lite smil vekse fram.",

    "Snart høyrde {name} lyden av fossande vatn.\n"
    "Ei brei elv sperra vegen, og den einaste vegen over var nokre store steinar ute i vatnet.\n"
    "Denne gongen kjende ho verkeleg frykta kome.\n"
    "«Kva om eg fell?» tenkte ho.",

    "{name} lukka auga og la handa mot hjartet.\n"
    "Då hugsa ho det dronninga hadde sagt. Mot tydde ikkje at ein aldri var redd.\n"
    "Mot var å prøve sjølv når ein var redd.\n"
    "Ho opna auga. «Eg klarar dette.»",

    "{name} hoppa til den første steinen. Så den neste.\n"
    "Vatnet spruta rundt føtene hennar medan ho kom stadig nærare den andre sida.\n"
    "Med eitt siste stort hopp landa ho trygt på breidda.\n"
    "Ho lo høgt. Ho hadde klart den vanskelegaste delen av prova!",

    "Då {name} skulle gå vidare, høyrde ho brått ein svak lyd bak seg.\n"
    "På ein liten stein ved elvekanten sat ein reveunge og peip etter hjelp.\n"
    "Slottet kunne alt skimtast mellom trea. Ho var nesten ferdig.\n"
    "Likevel snudde {name} seg. Ho kunne ikkje berre gå frå han.",

    "{name} hjelpte den vesle reven tilbake til trygg grunn og skunda seg vidare mot slottet.\n"
    "«Orsak,» sa ho til dronninga. «Eg stoppa for å hjelpe nokon.»\n"
    "Men dronninga byrja å smile.\n"
    "«Du treng ikkje orsake. Det var den siste delen av prova.»",

    "Slottsportane opna seg, og heile kongeriket venta innanfor.\n"
    "Dronninga lyfte den glitrande krona og sette henne forsiktig på hovudet til {name}.\n"
    "«Du viste mot då du var redd, og du hjelpte nokon då du kunne ha gått vidare.»\n"
    "«Frå denne dagen er du Prinsesse {name}.»",

    "Den kvelden lyste himmelen i rosa og gull over slottet.\n"
    "Fyrverkeri fylte himmelen medan heile kongeriket feira den nye prinsessa si.\n"
    "{name} såg utover landet som no var blitt heimen hennar.\n"
    "Ho hadde fått ei krone – men den største skatten hennar var framleis motet i hjartet.",
]

EN_US = [
    "Once upon a time there was a girl named {name}.\n"
    "From her window she could see the great castle far away between the hills.\n"
    "But this morning there was an envelope outside her door, sealed with a tiny golden crown.\n"
    "On the front it simply said: To {name}.",

    "{name} opened the letter carefully.\n"
    "\"You are invited to the castle to take the Princess's Test,\" it said.\n"
    "\"Only the one who finds the courage in her heart can wear the kingdom's crown.\"\n"
    "{name} felt her heart beat faster. Could she really become a princess?",

    "When {name} arrived, the enormous castle gates opened before her.\n"
    "Inside, the queen was waiting with a glittering crown in her hands.\n"
    "\"A crown alone makes no one a princess,\" she said kindly.\n"
    "\"First you must show what is in here.\" She pointed to {name}'s heart.",

    "Behind the castle began a narrow path that disappeared among the trees.\n"
    "\"Follow the path all the way until it comes back to the castle,\" the queen explained.\n"
    "\"Along the way you will meet the Princess's Test.\"\n"
    "{name} took a deep breath and set off.",

    "The deeper {name} went into the forest, the more it changed.\n"
    "Little lights blinked between the trees, and colorful butterflies flew ahead of her.\n"
    "Every time the path split in two, the butterflies gathered by the right way.\n"
    "{name} smiled. Maybe the test would not be so hard after all.",

    "But suddenly {name} stopped.\n"
    "Before her lay an old wooden bridge over a rushing stream. Some of the planks creaked in the wind.\n"
    "On the other side, the butterflies carried on.\n"
    "{name} felt a little worry in her stomach. Now the test was starting for real.",

    "{name} put one foot on the bridge. Then another.\n"
    "She was still a little afraid, but she kept going anyway.\n"
    "When she reached the other side, she turned and looked back at the bridge.\n"
    "\"I did it,\" she whispered, and felt a small smile grow.",

    "Soon {name} heard the sound of rushing water.\n"
    "A wide river blocked the way, and the only way across was a few big stones out in the water.\n"
    "This time she really felt the fear come.\n"
    "\"What if I fall?\" she thought.",

    "{name} closed her eyes and put her hand on her heart.\n"
    "Then she remembered what the queen had said. Courage did not mean never being afraid.\n"
    "Courage was trying even when you were afraid.\n"
    "She opened her eyes. \"I can do this.\"",

    "{name} jumped to the first stone. Then the next.\n"
    "The water splashed around her feet as she moved closer and closer to the other side.\n"
    "With one last big leap she landed safely on the bank.\n"
    "She laughed out loud. She had done the hardest part of the test!",

    "As {name} was about to walk on, she suddenly heard a faint sound behind her.\n"
    "On a little rock by the river's edge sat a fox cub, squeaking for help.\n"
    "The castle could already be glimpsed between the trees. She was almost finished.\n"
    "Still, {name} turned around. She could not just leave it there.",

    "{name} helped the little fox back to safe ground and hurried on toward the castle.\n"
    "\"I'm sorry,\" she said to the queen. \"I stopped to help someone.\"\n"
    "But the queen began to smile.\n"
    "\"You don't need to be sorry. That was the last part of the test.\"",

    "The castle gates opened, and the whole kingdom was waiting inside.\n"
    "The queen lifted the glittering crown and placed it gently on {name}'s head.\n"
    "\"You showed courage when you were afraid, and you helped someone when you could have walked on.\"\n"
    "\"From this day you are Princess {name}.\"",

    "That evening the sky glowed pink and gold above the castle.\n"
    "Fireworks filled the sky as the whole kingdom celebrated its new princess.\n"
    "{name} looked out over the land that was now her home.\n"
    "She had been given a crown, but her greatest treasure was still the courage in her heart.",
]

EN_GB = [
    t.replace("colorful", "colourful").replace("toward the castle", "towards the castle")
    for t in EN_US
]

SV = [
    "Det var en gång en flicka som hette {name}.\n"
    "Från sitt fönster kunde hon se det stora slottet långt borta mellan kullarna.\n"
    "Men den här morgonen låg det ett kuvert utanför hennes dörr, förseglat med en liten guldkrona.\n"
    "På framsidan stod det bara: Till {name}.",

    "{name} öppnade brevet försiktigt.\n"
    "\"Du är inbjuden till slottet för att genomföra Prinsessans prov\", stod det.\n"
    "\"Bara den som finner modet i hjärtat kan bära kungarikets krona.\"\n"
    "{name} kände hjärtat slå fortare. Kunde hon verkligen bli prinsessa?",

    "När {name} kom fram öppnades de enorma slottsportarna framför henne.\n"
    "Inne väntade drottningen med en glittrande krona i händerna.\n"
    "\"En krona ensam gör ingen till prinsessa\", sa hon vänligt.\n"
    "\"Först måste du visa vad som finns här inne.\" Hon pekade mot {name}s hjärta.",

    "Bakom slottet började en smal stig som försvann in mellan träden.\n"
    "\"Följ stigen ända tills den kommer tillbaka till slottet\", förklarade drottningen.\n"
    "\"På vägen kommer du att möta Prinsessans prov.\"\n"
    "{name} tog ett djupt andetag och gav sig av.",

    "Ju djupare {name} gick in i skogen, desto mer förändrades den.\n"
    "Små ljus blinkade mellan träden, och färgglada fjärilar flög framför henne.\n"
    "Varje gång stigen delade sig samlades fjärilarna vid den rätta vägen.\n"
    "{name} log. Kanske var provet inte så svårt ändå.",

    "Men plötsligt stannade {name}.\n"
    "Framför henne låg en gammal träbro över en brusande bäck. Några av plankorna knarrade i vinden.\n"
    "På andra sidan fortsatte fjärilarna vidare.\n"
    "{name} kände en liten oro i magen. Nu började provet på riktigt.",

    "{name} satte en fot på bron. Sedan en till.\n"
    "Hon var fortfarande lite rädd, men hon fortsatte ändå.\n"
    "När hon nådde andra sidan vände hon sig om och såg tillbaka på bron.\n"
    "\"Jag gjorde det\", viskade hon och kände ett litet leende växa fram.",

    "Snart hörde {name} ljudet av forsande vatten.\n"
    "En bred flod spärrade vägen, och den enda vägen över var några stora stenar ute i vattnet.\n"
    "Den här gången kände hon verkligen rädslan komma.\n"
    "\"Tänk om jag faller?\" tänkte hon.",

    "{name} blundade och lade handen mot hjärtat.\n"
    "Då mindes hon vad drottningen hade sagt. Mod betydde inte att man aldrig var rädd.\n"
    "Mod var att försöka även när man var rädd.\n"
    "Hon öppnade ögonen. \"Jag klarar det här.\"",

    "{name} hoppade till den första stenen. Sedan till nästa.\n"
    "Vattnet stänkte runt hennes fötter medan hon kom allt närmare andra sidan.\n"
    "Med ett sista stort skutt landade hon tryggt på stranden.\n"
    "Hon skrattade högt. Hon hade klarat den svåraste delen av provet!",

    "När {name} skulle gå vidare hörde hon plötsligt ett svagt ljud bakom sig.\n"
    "På en liten sten vid flodkanten satt en rävunge och pep efter hjälp.\n"
    "Slottet kunde redan skönjas mellan träden. Hon var nästan klar.\n"
    "Ändå vände {name} sig om. Hon kunde inte bara gå ifrån den.",

    "{name} hjälpte den lilla räven tillbaka till trygg mark och skyndade vidare mot slottet.\n"
    "\"Förlåt\", sa hon till drottningen. \"Jag stannade för att hjälpa någon.\"\n"
    "Men drottningen började le.\n"
    "\"Du behöver inte be om ursäkt. Det var den sista delen av provet.\"",

    "Slottsportarna öppnades, och hela kungariket väntade därinne.\n"
    "Drottningen lyfte den glittrande kronan och satte den försiktigt på {name}s huvud.\n"
    "\"Du visade mod när du var rädd, och du hjälpte någon när du kunde ha gått vidare.\"\n"
    "\"Från den här dagen är du Prinsessan {name}.\"",

    "Den kvällen lyste himlen i rosa och guld över slottet.\n"
    "Fyrverkerier fyllde himlen medan hela kungariket firade sin nya prinsessa.\n"
    "{name} såg ut över landet som nu hade blivit hennes hem.\n"
    "Hon hade fått en krona – men hennes största skatt var fortfarande modet i hjärtat.",
]

TRANSLATIONS = {
    "nn": NN,
    "en-US": EN_US,
    "en-GB": EN_GB,
    "sv": SV,
}
