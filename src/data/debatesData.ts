/**
 * NEPOUŽÍVANÁ FIXTURA — aplikace ji nečte.
 *
 * Od napojení na skutečný korpus (`src/data/psp/`) do UI nevstupuje. Zůstává
 * tu jako jediný dataset s vyplněnými anotacemi, tedy jediné pokrytí té
 * poloviny rozhraní, která zobrazuje značky — dokud ji nezačne plnit detektor.
 *
 * **Nikdy ji nevracet do `src/lib/debate.ts`.** Jména, kluby i citace jsou
 * smyšlené; kdyby se dostaly na web vedle skutečných, nešly by od nich odlišit.
 */

import { Annotation, Debate } from "@/types/debate";

/**
 * UKÁZKOVÁ DATA. Jména, kluby i citáty jsou smyšlené — pocházejí z návrhu
 * designu (`design/navrh-designu.html`) a slouží k předvedení datového modelu,
 * ne k hodnocení skutečných politiků. Trvalé označení zajišťuje
 * `src/components/layout/DemoBanner.tsx` na každé stránce.
 *
 * Struktura odpovídá výstupu šestistupňové pipeline: každá anotace nese
 * závažnost, jistotu detekce (Fáze 4–5), výsledek oponentního přezkumu
 * a odkaz na zdroj. Videozáznamy se párují zvlášť přes `src/data/mediaMap.ts`.
 */

/**
 * Sestaví anotaci z úryvku a dopočte znakové indexy uvnitř `cleanText`.
 * Vyhodí chybu, pokud úryvek v textu není — index tak nikdy neukazuje jinam,
 * než kam patří (požadavek "přesné znakové indexy" z architekturního promptu).
 */
function znacka(
  cleanText: string,
  snippet: string,
  rest: Omit<Annotation, "start" | "end" | "targetSnippet">
): Annotation {
  const start = cleanText.indexOf(snippet);
  if (start === -1) {
    throw new Error(`Značka nenalezena v textu vystoupení: "${snippet}"`);
  }
  return { ...rest, start, end: start + snippet.length, targetSnippet: snippet };
}

const EKNIH = "https://www.psp.cz/eknih/2021ps/stenprot";

/** Barvy klubů slouží jen k rozlišení v UI, nenesou hodnotící význam. */
export const PARTIES_LIST = [
  { name: "SDL", fullName: "Sociálně-demokratická levice", color: "#B45309" },
  { name: "ODU", fullName: "Občansko-demokratická unie", color: "#1D4ED8" },
  { name: "HNP", fullName: "Hnutí pro prosperitu", color: "#0F766E" },
  { name: "KLS", fullName: "Křesťansko-liberální strana", color: "#7C3AED" },
  { name: "NEZ", fullName: "nezařazení", color: "#64748B" },
];

const BARVA: Record<string, string> = Object.fromEntries(
  PARTIES_LIST.map((strana) => [strana.name, strana.color])
);

export const POLITICIANS_LIST = [
  { name: "Jiří Vrána", party: "SDL", role: "ministr financí" },
  { name: "Alena Kovářová", party: "ODU", role: "místopředsedkyně vlády" },
  { name: "Martin Doležal", party: "HNP", role: "předseda poslaneckého klubu" },
  { name: "Petra Marešová", party: "KLS", role: "poslankyně" },
  { name: "Věra Nedvědová", party: "SDL", role: "předsedkyně rozpočtového výboru" },
  { name: "Radek Souček", party: "HNP", role: "ministr dopravy" },
  { name: "Karel Dvořák", party: "KLS", role: "ministr práce a sociálních věcí" },
  { name: "Iva Bartošová", party: "ODU", role: "ministryně kultury" },
  { name: "Lenka Pospíšilová", party: "KLS", role: "předsedkyně Poslanecké sněmovny" },
];

/* ------------------------------------------------------------------ */
/* Texty vystoupení                                                    */
/* ------------------------------------------------------------------ */

const ROZ_01 =
  "Předkládám návrh, který srovná rozpočtová pravidla napříč kapitolami. Nezvyšujeme celkovou daňovou zátěž, jen zpřesňujeme, kdo za co odpovídá.";

const ROZ_02 =
  "Náš klub vždycky hájil nízké přímé daně pro zaměstnance a rodiny s dětmi. Nikdy jsme nepodpořili nic, co by lidem sáhlo na výplatu, a nepodpoříme to ani teď.";

const ROZ_03 =
  "Zeptám se věcně, protože z rozpravy to zatím nezaznělo: kolik obcí podle propočtu ministerstva přijde o víc než desetinu příjmů? V důvodové zprávě to číslo není.";

const ROZ_04 =
  "Zdanění nemovitostí je zásah do majetku, který si lidé pořídili z už jednou zdaněných peněz. Majetková daň je z principu nespravedlivá a my ji zvyšovat nebudeme.";

const ROZ_05 =
  "Doplním za resort dopravy. Investice do železnice loni klesly o víc než polovinu, což tenhle návrh nijak neřeší.";

const ROZ_06 =
  "Dnes jsem přesvědčená, že jednotná sazba DPH je pro rodiny výhodnější než dosavadní dvě sazby.";

const ROZ_07 =
  "Na dotaz kolegyně Marešové: podle propočtu výboru jde o 43 obcí, seznam je přílohou usnesení číslo 118. Rozešlu ho všem klubům do konce dnešního jednání.";

const DUCH_01 =
  "Pokud tuto reformu neprovedeme, systém se do deseti let propadne do neudržitelného deficitu. Navázání důchodového věku na dobu dožití zajistí, že každý stráví v průměru 21,5 roku v důchodu. Je to férový krok vůči budoucím generacím.";

const DUCH_02 =
  "Za našeho vedení jsme seniorům přidávali rekordní částky a nikdy jsme neuvažovali o tom, že by lidé měli pracovat do 67 nebo 68 let. Důchodový účet byl za nás v přebytku, stačí neutrácet jinde.";

const MEDIA_01 =
  "Poplatky se nezvýšily od roku 2008. Návrh přináší modernizaci definice přijímače. Nejde o žádnou novou daň z internetu, ale o narovnání podmínek pro ty, kdo obsah reálně konzumují na mobilu nebo notebooku.";

const MEDIA_02 =
  "Nezávislost veřejnoprávních médií musíme chránit před politickými tlaky. Valorizace poplatku o 15 korun měsíčně je minimální částka, která zajistí stabilitu bez závislosti na přímých dotacích ze státního rozpočtu.";

/* ------------------------------------------------------------------ */
/* Rozpravy                                                            */
/* ------------------------------------------------------------------ */

export const SAMPLE_DEBATES: Debate[] = [
  {
    debateId: "psp-9-schuze-84-2024-rozpoctova-pravidla",
    title: "Návrh zákona o úpravě rozpočtových pravidel",
    topic: "Sněmovní tisk 488 · úprava pravidel hospodaření kapitol státního rozpočtu",
    chamber: "Poslanecká sněmovna Parlamentu ČR",
    term: "9. volební období",
    sessionNumber: 84,
    date: "2024-06-12",
    tiskNumber: "ST 488",
    status: "SCHVÁLENO",
    description:
      "Druhé čtení návrhu, který upravuje rozpočtová pravidla napříč kapitolami a mění sazbu daně z příjmu právnických osob.",
    messages: [
      {
        messageId: "roz-01",
        speaker: "Jiří Vrána",
        party: "SDL",
        partyColor: BARVA.SDL,
        role: "ministr financí",
        timestamp: "14:15",
        date: "2024-06-12",
        cleanText: ROZ_01,
        speechAct: "OWN_STANCE",
        govTrackScore: { historicalConsistencyRate: 0.78, stanceShiftTrend: "STABLE", analyzedSpeeches: 41 },
        hasAnomalies: true,
        annotations: [
          znacka(ROZ_01, "Nezvyšujeme celkovou daňovou zátěž", {
            id: "roz-01-a1",
            type: "VOTE_MISMATCH",
            severity: "CRITICAL",
            shortBadgeLabel: "Rozpor s hlasováním",
            explanation:
              "Řečník hlasoval pro tisk se zvýšením sazby DPPO ve stejný den, kdy pronesl tento výrok.",
            confidenceScore: 0.96,
            presentationTier: "PUBLISHED",
            nliRelation: "CONTRADICTION",
            claimCategory: "STANCE_COMMITMENT",
            adversarialCheck: {
              passed: true,
              defenseEvaluated:
                "Zkoumáno, zda hlasoval o pozměněném znění bez daňové části; sněmovní tisk 488 obsahoval zvýšení sazby i ve schváleném znění.",
              defensesConsidered: [
                "Hlasovalo se o jiném znění tisku, než ke kterému se výrok vztahoval.",
                "Zvýšení sazby DPPO nezvyšuje celkovou zátěž, protože jinde klesá.",
                "Výrok mířil na domácnosti, nikoli na právnické osoby.",
              ],
            },
            proof: {
              pastQuote:
                "Hlasování č. 204 k tisku 488, 12. 6. 2024: Vrána J. — PRO. Tisk zvyšuje sazbu daně z příjmu právnických osob z 19 % na 21 %.",
              pastDate: "2024-06-12",
              pastContext: "Hlasování Poslanecké sněmovny o tisku 488",
              sourceUrl: `${EKNIH}/084schuz/hl204.htm`,
              voteRecorded: "PRO",
              votingBallotId: "Hlasování č. 204, 84. schůze (12. 6. 2024)",
              votingRecord:
                "Hlasoval PRO schválení tisku 488 zvyšujícího sazbu DPPO z 19 % na 21 %.",
            },
          }),
        ],
      },
      {
        messageId: "roz-02",
        speaker: "Alena Kovářová",
        party: "ODU",
        partyColor: BARVA.ODU,
        role: "místopředsedkyně vlády",
        timestamp: "14:32",
        date: "2024-06-12",
        cleanText: ROZ_02,
        speechAct: "OWN_STANCE",
        govTrackScore: { historicalConsistencyRate: 0.61, stanceShiftTrend: "HAWKISH_TO_DOVISH", analyzedSpeeches: 57 },
        hasAnomalies: true,
        annotations: [
          znacka(ROZ_02, "Nikdy jsme nepodpořili nic, co by lidem sáhlo na výplatu", {
            id: "roz-02-a1",
            type: "VOTE_MISMATCH",
            severity: "CRITICAL",
            shortBadgeLabel: "Rozpor s hlasováním",
            explanation:
              "Výrok se týká hlasování, které proběhlo sedm měsíců před ním. Systém neposuzuje, zda byl tisk 509 správný — pouze že mu výrok odporuje.",
            confidenceScore: 0.93,
            presentationTier: "CONTEXT_DEVELOPMENT",
            nliRelation: "CONTRADICTION",
            claimCategory: "STANCE_COMMITMENT",
            adversarialCheck: {
              passed: true,
              defenseEvaluated:
                "Zkoumáno, zda šlo o hlasování o jiné dani; tisk 509 rušil slevu na poplatníka, tedy přímý dopad na čistou mzdu.",
              defensesConsidered: [
                "Spotřební daň není zásah do výplaty, ale do spotřeby.",
                "Klub hlasoval jako celek, řečnice mohla být vázána koaliční dohodou.",
                "Mezi hlasováním a výrokem se změnila makroekonomická situace.",
              ],
            },
            proof: {
              pastQuote:
                "Hlasování č. 112 k tisku 509, 6. 11. 2023: Kovářová A. — PRO. Tisk zvýšil spotřební daň a zrušil slevu na poplatníka u druhého vyživovaného dítěte.",
              pastDate: "2023-11-06",
              pastContext: "Hlasování Poslanecké sněmovny o tisku 509",
              sourceUrl: `${EKNIH}/071schuz/hl112.htm`,
              voteRecorded: "PRO",
              votingBallotId: "Hlasování č. 112, 71. schůze (6. 11. 2023)",
            },
          }),
        ],
      },
      {
        messageId: "roz-03",
        speaker: "Petra Marešová",
        party: "KLS",
        partyColor: BARVA.KLS,
        role: "poslankyně",
        timestamp: "14:38",
        date: "2024-06-12",
        cleanText: ROZ_03,
        speechAct: "OWN_STANCE",
        hasAnomalies: false,
        annotations: [],
      },
      {
        messageId: "roz-04",
        speaker: "Alena Kovářová",
        party: "ODU",
        partyColor: BARVA.ODU,
        role: "místopředsedkyně vlády",
        timestamp: "14:41",
        date: "2024-06-12",
        cleanText: ROZ_04,
        speechAct: "OWN_STANCE",
        hasAnomalies: true,
        annotations: [
          znacka(ROZ_04, "Majetková daň je z principu nespravedlivá", {
            id: "roz-04-a1",
            type: "CONTRADICTION_TIME",
            severity: "HIGH",
            shortBadgeLabel: "Opak dřívějšího výroku",
            explanation:
              "Obě vystoupení se týkají téže daně a téhož paragrafu. Mezi nimi neproběhla změna zákona, která by rozdíl vysvětlovala.",
            confidenceScore: 0.91,
            presentationTier: "CONTEXT_DEVELOPMENT",
            nliRelation: "CONTRADICTION",
            claimCategory: "STANCE_COMMITMENT",
            adversarialCheck: {
              passed: true,
              defenseEvaluated:
                "Zkoumáno, zda se mezitím změnila právní úprava daně z nemovitostí; k žádné novele § 6 zákona o dani z nemovitých věcí nedošlo.",
              defensesConsidered: [
                "Dřívější výrok se týkal jiného typu majetkové daně.",
                "Mezi výroky proběhla novela, která základ daně změnila.",
                "Řečnice tehdy citovala stanovisko ministerstva, ne své vlastní.",
              ],
            },
            proof: {
              pastQuote:
                "Vyšší daň z nemovitosti je nejspravedlivější daň, jakou máme. Zatěžuje majetek, ne práci.",
              pastDate: "2021-05-14",
              pastContext: "Rozprava k daňovému balíčku, 53. schůze",
              sourceUrl: `${EKNIH}/053schuz/s053012.htm`,
            },
          }),
        ],
      },
      {
        messageId: "roz-05",
        speaker: "Radek Souček",
        party: "HNP",
        partyColor: BARVA.HNP,
        role: "ministr dopravy",
        timestamp: "14:44",
        date: "2024-06-12",
        cleanText: ROZ_05,
        speechAct: "OWN_STANCE",
        hasAnomalies: true,
        annotations: [
          znacka(ROZ_05, "Investice do železnice loni klesly o víc než polovinu", {
            id: "roz-05-a1",
            type: "FACTUAL_MISSTATEMENT",
            severity: "HIGH",
            shortBadgeLabel: "Údaj neodpovídá zdroji",
            explanation:
              "Uváděný pokles je zhruba pětinásobek doloženého. Zdroj je veřejný a byl v době vystoupení k dispozici.",
            confidenceScore: 0.94,
            presentationTier: "CONTEXT_DEVELOPMENT",
            nliRelation: "CONTRADICTION",
            claimCategory: "FACTUAL_CLAIM",
            adversarialCheck: {
              passed: true,
              defenseEvaluated:
                "Zkoumáno, zda řečník mohl mít na mysli jinou investiční kapitolu; výroční zpráva jinou kapitolu s takovým propadem neuvádí.",
              defensesConsidered: [
                "Řečník mohl mluvit o investicích jednoho konkrétního programu.",
                "Údaj mohl vycházet z předběžných dat před uzávěrkou.",
                "Šlo o řečnickou nadsázku, ne o tvrdé číslo.",
              ],
            },
            proof: {
              pastQuote:
                "Investice do železniční infrastruktury: 61,4 mld. Kč v roce 2023 oproti 68,2 mld. Kč v roce 2022 — pokles o 10 %.",
              pastDate: "2024-03-01",
              pastContext: "Výroční zpráva Státního fondu dopravní infrastruktury 2023, s. 24",
              sourceUrl: "https://www.sfdi.cz/vyrocni-zpravy",
            },
          }),
        ],
      },
      {
        messageId: "roz-06",
        speaker: "Alena Kovářová",
        party: "ODU",
        partyColor: BARVA.ODU,
        role: "místopředsedkyně vlády",
        timestamp: "14:47",
        date: "2024-06-12",
        cleanText: ROZ_06,
        speechAct: "OWN_STANCE",
        hasAnomalies: true,
        annotations: [
          znacka(ROZ_06, "jednotná sazba DPH je pro rodiny výhodnější", {
            id: "roz-06-a1",
            type: "VALUE_SHIFT",
            severity: "LOW",
            shortBadgeLabel: "Změna postoje",
            explanation:
              "Oponentní přezkum uznal, že mezi výroky se sjednotily sazby DPH a řečnice změnu postoje sama přiznává. Kategorie proto byla zmírněna z časového rozporu na názorový posun.",
            confidenceScore: 0.84,
            presentationTier: "CONTEXT_DEVELOPMENT",
            nliRelation: "NEUTRAL",
            claimCategory: "STANCE_COMMITMENT",
            adversarialCheck: {
              passed: false,
              downgradedFrom: "CONTRADICTION_TIME",
              defenseEvaluated:
                "Obhajoba obstála: mezi výroky vstoupila v účinnost novela sjednocující sníženou sazbu, čímž se změnily výchozí podmínky srovnání.",
              defensesConsidered: [
                "Mezi výroky se změnila právní úprava sazeb DPH.",
                "Řečnice změnu postoje výslovně uvádí slovem „dnes“, nezastírá ji.",
                "Dřívější výrok se týkal jiného rozsahu zboží v snížené sazbě.",
              ],
            },
            proof: {
              pastQuote:
                "Dvě sazby DPH chrání základní potraviny. Sjednocení by dopadlo na ty nejchudší.",
              pastDate: "2022-03-09",
              pastContext: "Rozprava k novele zákona o DPH, 61. schůze",
              sourceUrl: `${EKNIH}/061schuz/s061077.htm`,
            },
          }),
        ],
      },
      {
        messageId: "roz-07",
        speaker: "Věra Nedvědová",
        party: "SDL",
        partyColor: BARVA.SDL,
        role: "předsedkyně rozpočtového výboru",
        timestamp: "14:51",
        date: "2024-06-12",
        cleanText: ROZ_07,
        speechAct: "OWN_STANCE",
        // Kandidát pod publikačním prahem 0,80 — `prepareDebate` ho odfiltruje
        // a vystoupení se ve feedu zobrazí jako bezrozporné. Demonstruje
        // důkazní břemeno z instrukcí architekturního promptu.
        hasAnomalies: true,
        annotations: [
          znacka(ROZ_07, "podle propočtu výboru jde o 43 obcí", {
            id: "roz-07-a1",
            type: "FACTUAL_MISSTATEMENT",
            severity: "LOW",
            shortBadgeLabel: "Neověřený počet obcí",
            explanation:
              "Usnesení č. 118 nebylo v době analýzy zveřejněno, číslo tedy nelze proti zdroji ověřit ani vyvrátit.",
            confidenceScore: 0.62,
            presentationTier: "DROPPED",
            nliRelation: "NEUTRAL",
            claimCategory: "FACTUAL_CLAIM",
            adversarialCheck: {
              passed: false,
              defenseEvaluated:
                "Obhajoba obstála: podklad je přílohou dosud nezveřejněného usnesení, tvrzení proto nelze označit za nepravdivé.",
              defensesConsidered: [
                "Usnesení výboru zatím není veřejné, číslo může být správné.",
                "Propočet výboru se může lišit od propočtu ministerstva.",
                "Řečnice sama slibuje podklad rozeslat, tedy nabízí ověření.",
              ],
            },
            proof: {
              pastQuote: "Usnesení rozpočtového výboru č. 118 nebylo k datu analýzy publikováno.",
              pastDate: "2024-06-12",
              pastContext: "Rejstřík usnesení rozpočtového výboru",
              sourceUrl: `${EKNIH}/084schuz/s084043.htm`,
            },
          }),
        ],
      },
    ],
  },
  {
    debateId: "psp-9-schuze-98-2024-duchodova-reforma",
    title: "Návrh zákona o důchodovém pojištění",
    topic: "Sněmovní tisk 689 · posun věku odchodu do důchodu nad 65 let",
    chamber: "Poslanecká sněmovna Parlamentu ČR",
    term: "9. volební období",
    sessionNumber: 98,
    date: "2024-05-28",
    tiskNumber: "ST 689",
    status: "V_ŘEŠENÍ",
    description:
      "Střet o navázání důchodového věku na dobu dožití a o tempo valorizace nově přiznávaných důchodů.",
    messages: [
      {
        messageId: "duch-01",
        speaker: "Karel Dvořák",
        party: "KLS",
        partyColor: BARVA.KLS,
        role: "ministr práce a sociálních věcí",
        timestamp: "10:00",
        date: "2024-05-28",
        cleanText: DUCH_01,
        speechAct: "OWN_STANCE",
        govTrackScore: { historicalConsistencyRate: 0.7, stanceShiftTrend: "DOVISH_TO_HAWKISH", analyzedSpeeches: 33 },
        hasAnomalies: true,
        annotations: [
          znacka(DUCH_01, "Navázání důchodového věku na dobu dožití zajistí", {
            id: "duch-01-a1",
            type: "CONTRADICTION_TIME",
            severity: "HIGH",
            shortBadgeLabel: "Opak dřívějšího výroku",
            explanation:
              "Řečník i jeho klub v minulosti opakovaně označili hranici 65 let za nepřekročitelnou. Tento tisk ji sám navrhuje posunout.",
            confidenceScore: 0.89,
            presentationTier: "CONTEXT_DEVELOPMENT",
            nliRelation: "CONTRADICTION",
            claimCategory: "STANCE_COMMITMENT",
            adversarialCheck: {
              passed: true,
              defenseEvaluated:
                "Zkoumáno, zda dřívější závazek platil jen pro tehdejší volební období; formulace „v žádném případě“ žádné časové omezení neobsahovala.",
              defensesConsidered: [
                "Závazek se vztahoval pouze na tehdejší volební období.",
                "Demografická data se od roku 2021 zhoršila natolik, že vynutila revizi.",
                "Řečník tehdy mluvil za stranu, nyní předkládá vládní návrh.",
              ],
            },
            proof: {
              pastQuote:
                "Hranice 65 let pro odchod do důchodu je pevně daná a naše strana ji v žádném případě nebude posouvat výš.",
              pastDate: "2021-08-10",
              pastContext: "Volební program a vyjádření k sociální politice",
              sourceUrl: "https://www.psp.cz/sqw/hp.sqw",
              votingRecord:
                "Předložil vládní tisk č. 689 posouvající věk odchodu do důchodu nad 65 let.",
            },
          }),
        ],
      },
      {
        messageId: "duch-02",
        speaker: "Martin Doležal",
        party: "HNP",
        partyColor: BARVA.HNP,
        role: "předseda poslaneckého klubu",
        timestamp: "10:35",
        date: "2024-05-28",
        cleanText: DUCH_02,
        speechAct: "OWN_STANCE",
        hasAnomalies: true,
        annotations: [
          znacka(DUCH_02, "Důchodový účet byl za nás v přebytku", {
            id: "duch-02-a1",
            type: "FACTUAL_MISSTATEMENT",
            severity: "HIGH",
            shortBadgeLabel: "Údaj neodpovídá zdroji",
            explanation:
              "Podle statistické ročenky ČSSZ skončil důchodový účet v letech 2020 a 2021 v deficitu 40,6 mld. Kč a 33,2 mld. Kč — v přebytku nebyl.",
            confidenceScore: 0.92,
            presentationTier: "CONTEXT_DEVELOPMENT",
            nliRelation: "CONTRADICTION",
            claimCategory: "FACTUAL_CLAIM",
            adversarialCheck: {
              passed: true,
              defenseEvaluated:
                "Zkoumáno, zda „za nás“ mohlo odkazovat na dřívější období s přebytkem; klub byl ve vládě v letech 2018–2021, kdy účet skončil v deficitu ve třech ze čtyř let.",
              defensesConsidered: [
                "„Za nás“ mohlo odkazovat na jiné, dřívější období.",
                "Přebytek mohl platit před mimořádnými výdaji roku 2020.",
                "Řečník mohl mít na mysli celý účet sociálního pojištění, ne jen důchodový.",
              ],
            },
            proof: {
              pastQuote:
                "Deficit důchodového účtu za rok 2020 dosáhl vlivem propadu příjmů 40,6 miliard Kč, za rok 2021 pak 33,2 miliard Kč.",
              pastDate: "2022-03-15",
              pastContext: "Statistická ročenka České správy sociálního zabezpečení",
              sourceUrl: "https://www.cssz.cz/statisticke-rocenky",
            },
          }),
        ],
      },
    ],
  },
  {
    debateId: "psp-9-schuze-112-2024-koncesionarske-poplatky",
    title: "Novela zákona o rozhlasových a televizních poplatcích",
    topic: "Sněmovní tisk 740 · rozšíření poplatku na zařízení připojená k internetu",
    chamber: "Poslanecká sněmovna Parlamentu ČR",
    term: "9. volební období",
    sessionNumber: 112,
    date: "2024-07-10",
    tiskNumber: "ST 740",
    status: "PROJEDNÁNO",
    description:
      "Debata o financování veřejnoprávních médií a o rozšíření definice přijímače na mobilní telefony a počítače.",
    messages: [
      {
        messageId: "media-01",
        speaker: "Iva Bartošová",
        party: "ODU",
        partyColor: BARVA.ODU,
        role: "ministryně kultury",
        timestamp: "11:20",
        date: "2024-07-10",
        cleanText: MEDIA_01,
        speechAct: "OWN_STANCE",
        hasAnomalies: true,
        annotations: [
          znacka(MEDIA_01, "Nejde o žádnou novou daň z internetu", {
            id: "media-01-a1",
            type: "CONTRADICTION_TIME",
            severity: "HIGH",
            shortBadgeLabel: "Opak dřívějšího výroku",
            explanation:
              "O dva roky dříve řečnice přesně toto rozšíření poplatku odmítla jako věc, kterou vláda neplánuje. Nyní je sama předkládá.",
            confidenceScore: 0.87,
            presentationTier: "CONTEXT_DEVELOPMENT",
            nliRelation: "CONTRADICTION",
            claimCategory: "STANCE_COMMITMENT",
            adversarialCheck: {
              passed: true,
              defenseEvaluated:
                "Zkoumáno, zda jde o odlišný nástroj; předložená novela rozšiřuje povinnost přesně na zařízení s připojením k internetu, tedy na to, co dřívější výrok vylučoval.",
              defensesConsidered: [
                "Poplatek není daň, výroky se tedy netýkají téhož.",
                "V roce 2022 návrh skutečně na stole nebyl, situace se změnila.",
                "Řečnice tehdy mluvila za předchozí složení vlády.",
              ],
            },
            proof: {
              pastQuote:
                "Zpoplatnění internetových přípojek nebo mobilních telefonů televizním poplatkem není na stole a vláda to neplánuje.",
              pastDate: "2022-04-12",
              pastContext: "Tisková konference Ministerstva kultury k mediální legislativě",
              sourceUrl: "https://www.mkcr.cz/tiskove-zpravy",
              votingRecord:
                "Předložila vládní novelu zákona č. 348/2005 Sb., rozšiřující povinnost platit poplatek na zařízení s připojením k internetu.",
            },
          }),
        ],
      },
      {
        messageId: "media-02",
        speaker: "Lenka Pospíšilová",
        party: "KLS",
        partyColor: BARVA.KLS,
        role: "předsedkyně Poslanecké sněmovny",
        timestamp: "11:55",
        date: "2024-07-10",
        cleanText: MEDIA_02,
        speechAct: "OWN_STANCE",
        hasAnomalies: false,
        annotations: [],
      },
    ],
  },
];
