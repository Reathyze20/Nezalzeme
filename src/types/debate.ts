/**
 * Datový kontrakt enginu "Multi-Stage Parliamentary Verification & Multimedia
 * Engine" (v2) — šestistupňová verifikační pipeline nad stenozáznamy PSP ČR.
 *
 * Interní názvy kategorií jsou kanonické (CONTRADICTION_TIME,
 * FACTUAL_MISSTATEMENT); názvy z architekturního promptu (TIME_CONTRADICTION,
 * FACTUAL_ERROR) překládá `normalizeAnomalyType` v `src/lib/utils.ts`.
 */

export type AnomalyType =
  | 'CONTRADICTION_TIME'
  | 'VOTE_MISMATCH'
  | 'FACTUAL_MISSTATEMENT'
  | 'VALUE_SHIFT';

/** Názvy kategorií tak, jak je produkuje LLM dle architekturního promptu. */
export type AnomalyTypeAlias = 'TIME_CONTRADICTION' | 'FACTUAL_ERROR' | AnomalyType;

export type SeverityLevel = 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW';

/** Klasifikace řečnického aktu (Fáze 1). */
export type SpeechAct =
  | 'OWN_STANCE'        // vlastní postoj / faktický argument
  | 'QUOTING_OPPONENT'  // citace či parafráze oponenta – nepřipisuje se řečníkovi
  | 'RHETORICAL';       // ironie, hyperbola, metafora – mimo faktické ověřování

/** Kategorie extrahovaného tvrzení (Fáze 2). */
export type ClaimCategory =
  | 'FACTUAL_CLAIM'      // statistiky, rozpočtová čísla, legislativní fakta
  | 'STANCE_COMMITMENT'  // normativní závazek / slib
  | 'PROCEDURAL';        // formální vyjádření k proceduře – ignorováno

/** Výsledek dvoucestné NLI analýzy (Fáze 4). */
export type NliRelation = 'ENTAILMENT' | 'NEUTRAL' | 'CONTRADICTION';

/** Zaznamenané hlasování v PSP ČR (Voting Ledger Pairing, Fáze 3). */
export type VoteValue = 'PRO' | 'PROTI' | 'ZDRZEL_SE' | 'NEPRIHLASEN';

/** Fáze 5 – nad tímto prahem se anotace publikuje jako obvinění (pásmo PUBLISHED). */
export const PUBLISH_THRESHOLD = 0.95;
/**
 * Fáze 5 – nad tímto prahem (ale pod `PUBLISH_THRESHOLD`) se anotace zveřejní
 * jen jako neutrální „Kontext a vývoj stanoviska" (pásmo CONTEXT_DEVELOPMENT).
 * Pod ním se anotace na web vůbec nedostane (pásmo DROPPED) — číselně stejná
 * hodnota, jakou dřív nesl jediný `CONFIDENCE_THRESHOLD`.
 */
export const CONTEXT_THRESHOLD = 0.8;

/**
 * Kalibrovaná jistota, tři prezentační pásma (Fáze 5) místo dřívější
 * binární brány:
 *  - `PUBLISHED` — confidenceScore >= `PUBLISH_THRESHOLD`, obviňující
 *    rámování (`DvojiceZaznamu`).
 *  - `CONTEXT_DEVELOPMENT` — confidenceScore >= `CONTEXT_THRESHOLD`,
 *    neutrální rámování („Kontext a vývoj stanoviska").
 *  - `DROPPED` — pod `CONTEXT_THRESHOLD`, anotace se na web vůbec nedostane.
 */
export type PresentationTier = 'PUBLISHED' | 'CONTEXT_DEVELOPMENT' | 'DROPPED';

/* ------------------------------------------------------------------ */
/* Fáze 6: Audiovizuální ukotvení                                      */
/* ------------------------------------------------------------------ */

/**
 * Napárování celého vystoupení na oficiální videozáznam.
 *
 * PSP ČR nehostuje záznamy schůzí na YouTube — vlastní videoarchiv
 * (`videoarchiv.psp.cz`) je jediný ověřený zdroj (viz `pipeline/psp/videoarchiv.py`).
 * `archiveUrl` je vždy oficiální sdílitelná stránka přehrávače
 * (`playa.php?cast=...`), ne přímý odkaz na syrový mp4 segment — engine tam
 * nikdy nic nehotlinkuje. Přehrávač tahle stránka neumí přesně seekovat na
 * vteřinu URL parametrem, takže na rozdíl od YouTube je `archiveUrl` stejný
 * pro celý jednací den; přesnost nese jen zobrazený časový popisek.
 */
export interface MediaRef {
  /** ID "cast" (jednacího dne) ve videoarchivu PSP; `null` = záznam k tomuto bloku není spárován. */
  pspCastId: string | null;
  /** Vteřina začátku vystoupení ve streamu (Offset Sync). */
  speechStartSeconds: number;
  /** Zdroj časového ukotvení – ovlivňuje, zda UI hlásí "přesný" nebo "orientační" čas. */
  alignment: 'FORCED_ALIGNMENT' | 'OFFSET_SYNC' | 'UNPAIRED';
  /** Reálný čas startu streamu toho dne, vstup pro výpočet Offset Syncu. */
  streamStartedAt?: string;
  /** Oficiální sdílitelná stránka přehrávače PSP pro celý jednací den. */
  archiveUrl?: string;
}

/** Napárování konkrétní věty (anomálie) na vteřinu ve videu. */
export interface MediaEvidence {
  exactTimestampSeconds: number;
  /** Oficiální stránka přehrávače PSP; čtenář v ní čas najde ručně podle zobrazeného časového razítka. */
  archiveUrl: string;
  /** `false` = hodnota dopočtena z tempa řeči, nikoli forced alignmentem. */
  isExact: boolean;
  /** Délka časovaného výseku v sekundách. */
  durationSeconds?: number;
  /** Přímý URL odkaz na konkrétní čas v archivu. */
  clipUrl?: string;
}

/** Historický výrok napárovaný na svůj vlastní záznam. */
export interface HistoricalMedia {
  pspCastId: string | null;
  historicalTimestampSeconds: number;
  historicalArchiveUrl?: string;
}

/* ------------------------------------------------------------------ */
/* Fáze 5: Adversarial Filter                                          */
/* ------------------------------------------------------------------ */

export interface AdversarialCheck {
  /** `true` = žádná obhajoba neobstála, rozpor zůstává v původní kategorii. */
  passed: boolean;
  /** Shrnutí nejsilnější posouzené obhajoby a jejího výsledku (role Obhájce). */
  defenseEvaluated: string;
  /** Tři nejlepší obhajoby poslance, které byly zvažovány. */
  defensesConsidered?: string[];
  /** Původní kategorie před zmírněním (např. CONTRADICTION_TIME -> VALUE_SHIFT). */
  downgradedFrom?: AnomalyType;
  /** Fáze 4: obžaloba sestavená rolí Žalobce z `Claim` + `Fact` důkazů. */
  prosecutorCase?: string;
  /**
   * Fáze 4: zdůvodnění role Soudce, PROČ zvážil obojí (obžalobu i obhajobu)
   * tak, jak zvážil — odlišné od `defenseEvaluated`, což je jen shrnutí
   * obhájce; tohle je vlastní úvaha arbitra nad oběma stranami.
   */
  arbiterRationale?: string;
  /** Fáze 4: který model/verze tribunálu tenhle verdikt vyprodukoval (auditní stopa). */
  modelProvenance?: string;
}

/* ------------------------------------------------------------------ */
/* Fáze 2b: Atomické tvrzení                                           */
/* ------------------------------------------------------------------ */

/**
 * Atomické, kanonické tvrzení rozložené z vystoupení: `[Subjekt][Predikát]
 * [Objekt][Časový rámec][Podmínka]`. Jedno vystoupení může obsahovat víc
 * `Claim` s různým `speechAct` (např. vlastní postoj i citaci oponenta v
 * jedné větě) — na rozdíl od `Message.speechAct`, který platí pro celé
 * vystoupení a zůstává jako hrubší, zpětně kompatibilní pole.
 */
export interface Claim {
  claimId: string;
  messageId: string;
  speakerIdOsoba: string;
  subject: string;
  /** Vztah mezi Subjektem a Objektem jako volný text (např. "slíbil", "hlasoval pro"). */
  predicate: string;
  object: string;
  /** Explicitní časový rámec tvrzení — nikdy implicitní "teď". */
  timeFrame: string;
  /** Podmínka, za které tvrzení platí; prázdný řetězec, není-li vyjádřená. */
  condition: string;
  claimCategory: ClaimCategory;
  speechAct: SpeechAct;
  sourceCharStart: number;
  sourceCharEnd: number;
  rawSpan: string;
  /** Jistota, že extrakce věrně odpovídá výroku — odlišné od `confidenceScore` rozporu (Fáze 4–5). */
  extractionConfidence: number;
  /** `Fact.factId` z `pipeline/psp/facts.py`, napárované Fází 3 retrievalem. */
  linkedFactIds: string[];
}

/* ------------------------------------------------------------------ */
/* Důkazní aparát                                                      */
/* ------------------------------------------------------------------ */

export interface Proof {
  pastQuote: string;
  pastDate: string;
  pastContext: string;
  /** Přímý odkaz na stenozáznam, hlasování nebo jiný veřejný zdroj. */
  sourceUrl: string;
  votingRecord?: string;
  /** Strojově čitelný záznam hlasování. */
  voteRecorded?: VoteValue;
  /** Identifikace hlasování, např. "Hlasování č. 204, 84. schůze (12. 6. 2024)". */
  votingBallotId?: string;
  historicalMedia?: HistoricalMedia;
  /** Odkaz na historický `Claim.claimId` (Fáze 2b) místo volného textu v `pastQuote`. */
  pastClaimId?: string;
}

export interface Annotation {
  id?: string;
  start: number;
  end: number;
  targetSnippet: string;
  type: AnomalyType;
  severity: SeverityLevel;
  shortBadgeLabel: string;
  explanation: string;
  proof: Proof;
  /** Fáze 4–5: jistota detekce. Publikuje se pouze >= CONTEXT_THRESHOLD. */
  confidenceScore: number;
  /** Fáze 5: kam confidenceScore anotaci zařadil — dopočítává `prepareMessage`, nedůvěřuje se vstupu ze surových dat. */
  presentationTier: PresentationTier;
  nliRelation?: NliRelation;
  claimCategory?: ClaimCategory;
  adversarialCheck?: AdversarialCheck;
  mediaEvidence?: MediaEvidence;
  /**
   * Auditní stopa provenience: `"engine"` pro výstup run_pipeline.py,
   * `"hand-authored-seed"` pro ruční ukázky z analyze_temporal.py.
   * Přítomnost tohoto pole je povinná od Fáze A — engine ji plní automaticky.
   */
  producedBy?: string;
  /** Verze enginu (git hash nebo číslo releasu), která anotaci vyrobila. */
  engineVersion?: string;
}

/* ------------------------------------------------------------------ */
/* Řečník a vystoupení                                                 */
/* ------------------------------------------------------------------ */

/** Longitudinální skóre konzistence (inspirace GovTrack / Voteview). */
export interface GovTrackScore {
  /** Podíl vystoupení bez detekovaného rozporu, 0–1. */
  historicalConsistencyRate: number;
  /** Slovní popis trendu posunu postoje, např. "HAWKISH_TO_DOVISH". */
  stanceShiftTrend?: string;
  analyzedSpeeches?: number;
}

export interface Message {
  messageId: string;
  speaker: string;
  party: string;
  partyColor?: string;
  avatarUrl?: string;
  role: string;
  timestamp: string;
  date: string;
  rawText?: string;
  cleanText: string;
  hasAnomalies: boolean;
  annotations: Annotation[];
  /** Atomická tvrzení rozložená z vystoupení (Fáze 2b). Nepřítomnost = zatím neextrahováno. */
  claims?: Claim[];
  /**
   * Kdy nad vystoupením proběhla analýza. **Nepřítomnost znamená
   * "nekontrolováno", ne "čisté"** — bez toho rozdílu by rozhraní vydávalo
   * neprovedenou kontrolu za dobrý výsledek.
   */
  analyzedAt?: string;
  /** Kotva do stenoprotokolu a napárovaná hlasování. */
  source?: MessageSource;
  speechAct?: SpeechAct;
  /** Fáze 6 – doplňuje `src/data/mediaMap.ts` při přípravě dat. */
  media?: MediaRef;
  govTrackScore?: GovTrackScore;
}

/* ------------------------------------------------------------------ */
/* Doložitelnost — co o vystoupení víme ze samotného záznamu            */
/* ------------------------------------------------------------------ */

/** Jmenovité hlasování napárované na vystoupení, ve kterém se o něm mluví. */
export interface BallotRef {
  ballotId: string;
  url: string;
  number: number | null;
  subject: string;
  result: string;
  clock: string | null;
  /** Jak hlasoval řečník tohoto vystoupení; null, pokud u hlasování nebyl. */
  voteOfSpeaker: VoteValue | null;
}

/* ------------------------------------------------------------------ */
/* Hlasovací rejstřík (Fáze 2)                                         */
/* ------------------------------------------------------------------ */

/**
 * Hodnota hlasu tak, jak ji dokládají **otevřená data** PSP ČR.
 *
 * Liší se od `VoteValue` v jednom podstatném bodě: dump `hl-YYYYps.zip`
 * slučuje „zdržel se" a „nehlasoval" do jediného kódu `K`, takže z něj nejde
 * poznat, které z toho nastalo. Rozlišit to umí jen HTML `hlasy.sqw?G=`
 * (`pipeline/psp/hlasovani.py`). Dokud se konkrétní hlas z HTML nedověří,
 * musí se hlásit jako `ZDRZEL_SE_NEBO_NEHLASOVAL` — tvrdit jedno z toho by
 * bylo tvrzení nad rámec dat.
 */
export type VoteValueLedger =
  | 'PRO'
  | 'PROTI'
  | 'ZDRZEL_SE_NEBO_NEHLASOVAL'
  | 'NEPRIHLASEN';

/** Poměr hlasů jednoho klubu u jednoho hlasování; klub k datu hlasování. */
export interface KlubPomer {
  klub: string;
  pro: number;
  proti: number;
  zdrzelNeboNehlasoval: number;
  neprihlasen: number;
}

/** Bod pořadu schůze, ke kterému rozprava patří. */
export interface BodPoradu {
  idBod: string;
  /** Číslo bodu na pořadu schůze (např. 51). */
  cislo: number | null;
  nazev: string;
  idTisk: string | null;
  /** Textová zmínka tisku z dat Sněmovny, např. `/sněmovní tisk 17/`. */
  tiskRef: string | null;
  /** Podíl vystoupení rozpravy, která se na tenhle bod napárovala (0–1). */
  podilVystoupeni: number;
}

/** Jedno jmenovité hlasování o bodu pořadu, z otevřených dat PSP ČR. */
export interface Hlasovani {
  ballotId: string;
  url: string;
  /** Pořadové číslo hlasování na schůzi. */
  cislo: number;
  nazev: string;
  datum: string;
  cas: string;
  /** `A` = návrh přijat, `R` = nepřijat. */
  vysledek: string;
  prijato: boolean;
  pro: number;
  proti: number;
  zdrzel: number;
  nehlasoval: number;
  /** Klasifikace z `pipeline/psp/vote_classifier.py` (SUBSTANTIVE_* / PROCEDURAL_*). */
  typ: string;
  /**
   * `false` = procedurální hlasování (pořad schůze, odročení, volba orgánů).
   * Postoj k zákonu se s procedurálním hlasováním párovat nesmí.
   */
  jeVecne: boolean;
  /** Fáze projednávání (1./2./3. čtení), pokud ji jde odvodit z názvu rozpravy. */
  faze: string | null;
  klubyPomer: KlubPomer[];
}

/** Jak hlasoval konkrétní řečník u konkrétního hlasování. */
export interface HlasRecnika {
  ballotId: string;
  hlas: VoteValueLedger;
  /** Poslanec měl na dobu hlasování zaznamenanou omluvu — není to prostá absence. */
  omluven: boolean;
}

/** Hlasy jednoho řečníka napříč hlasováními o daném bodu. */
export interface HlasyRecnika {
  idOsoba: string;
  jmeno: string;
  hlasy: HlasRecnika[];
}

/**
 * Hlasovací bilance poslance za volební období — samá počitatelná veličina,
 * žádný odhad modelu.
 *
 * `celkem` je počet hlasování, u kterých je poslanec v datech vůbec veden;
 * u někoho, kdo mandát složil po dvou hlasováních, jsou to dvě. Bez `celkem`
 * se `ucast` nesmí zobrazovat jako srovnatelné číslo.
 */
export interface HlasovaciBilance {
  celkem: number;
  pro: number;
  proti: number;
  zdrzelNeboNehlasoval: number;
  neprihlasen: number;
  /** Kolik z `neprihlasen` je krytých omluvou. */
  omluven: number;
  /** Podíl hlasování, u kterých byl poslanec přihlášen (0–1). */
  ucast: number;
}

/**
 * Index věcnosti (Fáze 5) — jen dvě složky, které jinde na profilu nejsou.
 * Docházka žije v `HlasovaciBilance`, SCI vzniká ze Slova a činu — sem
 * nepatří, viz `pipeline/index_vecnosti.py`.
 *
 * Žádná položka nevznikla z jazykového modelu — obojí je počítáno přímo
 * z otevřených dat, resp. z délky stažených stenozáznamů.
 */
export interface IndexVecnosti {
  /** Poslanecké návrhy zákonů za celé volební období (vládní návrhy se nepočítají). */
  poslaneckeNavrhyZakonu: number;
  /**
   * Rozklad vystoupení ze STAŽENÉHO VZORKU stenozáznamů, `null` pod
   * minimálním počtem vystoupení k publikaci (viz `MIN_VYSTOUPENI_PRO_VECNOST`).
   * Nejde o celé volební období — `meta.hlasovaniDnuCelkem` v datasetu dá
   * srovnání, kolik dnů z celku vzorek pokrývá.
   */
  vzorekVystoupeni: {
    vystoupeniVeVzorku: number;
    medianDelkyZnaku: number;
    /** Podíl vystoupení kratších než práh pro extrakci tvrzení (0–1). */
    podilKratkychVystoupeni: number;
  } | null;
}

/**
 * Kotva vystoupení do oficiálního záznamu.
 *
 * Tohle je jediné, co data dokládají i bez jediné značky — a proto to UI
 * potřebuje: u neanalyzovaného vystoupení je odkaz do stenoprotokolu jediné
 * ověřitelné tvrzení, které smíme udělat.
 */
export interface MessageSource {
  idOsoba: string;
  idPoslanec?: string | null;
  /** Kotva na běžnou stránku stenozáznamu, `sSSSTTT.htm#rN`. */
  stenoUrl: string;
  /** Stránka `bqbs/`, ze které byl text přečtený. */
  sectionUrl: string;
  turn?: number | null;
  clockExact?: string | null;
  spokenAt?: string | null;
  dayOffset?: number;
  /** True, když byla kotva ověřena proti běžné stránce stenozáznamu. */
  anchorVerified?: boolean;
  /** Vystoupení řídí schůzi, nezaujímá postoj. */
  isChair?: boolean;
  ballots: BallotRef[];
}

export interface DebateSource {
  dayUrl: string;
  sectionUrls: string[];
  ballotIds: string[];
}

export interface Debate {
  debateId: string;
  title: string;
  topic: string;
  chamber: string;
  term: string; // Volební období (e.g. 9. volební období)
  sessionNumber: number; // Číslo schůze (e.g. 65. schůze)
  date: string;
  tiskNumber?: string; // Sněmovní tisk č.
  description: string;
  status: 'PROJEDNÁNO' | 'SCHVÁLENO' | 'ZAMÍTNUTO' | 'V_ŘEŠENÍ';
  messages: Message[];
  /** Záznam celé schůze (přebírá se z `src/data/mediaMap.ts`). */
  media?: MediaRef;
  /** Odkazy na zdrojové stránky jednacího dne. */
  source?: DebateSource;
  /**
   * Bod pořadu, ke kterému rozprava patří (Fáze 2). Chybí u bloků mimo
   * projednávání bodu — zahájení jednacího dne, procedurální vsuvky.
   */
  bod?: BodPoradu | null;
  /**
   * Jmenovitá hlasování o tomhle bodu pořadu. Uložena na rozpravě, ne na
   * vystoupení: v rozpravě o jednom bodu jsou pro všechny řečníky stejná.
   */
  hlasovani?: Hlasovani[];
  /** Jak hlasovali jednotliví řečníci téhle rozpravy. */
  hlasyRecniku?: HlasyRecnika[];
}

/* ------------------------------------------------------------------ */
/* Slovo vs. Čin (Fáze 3)                                              */
/* ------------------------------------------------------------------ */

/**
 * Postoj, který výrok zaujímá k přijetí projednávaného návrhu.
 *
 * `NEUTRALNI` a `NEURCITELNE` se nikdy nepublikují — z výroku, který
 * k návrhu stanovisko nezaujímá, se nedá dovodit ani shoda, ani rozpor.
 */
export type SlovoCinPostoj = 'PRO' | 'PROTI' | 'NEUTRALNI' | 'NEURCITELNE';

/**
 * Vztah mezi postojem v rozpravě a hlasem.
 *
 * Vědomě to není `AnomalyType`: rejstřík nikoho neobviňuje. `NESHODA`
 * znamená „řekl jedno, hlasoval druhé", ne „lhal" — důvodů může být víc
 * (klubová dohoda, změna návrhu mezi rozpravou a hlasováním) a čtenář
 * dostane vedle sebe obojí i s poměrem v klubu.
 */
export type SlovoCinShoda = 'SHODA' | 'NESHODA' | 'NEHLASOVAL';

/**
 * Jeden doklad „řečeno vs. hlasováno".
 *
 * Každá položka stojí na řetězu, kde má každý článek vlastní ověřitelný
 * zdroj: výrok má kotvu do stenozáznamu, hlasování má hlasovací lístek
 * a to, že jde o **finální** hlasování o tom zákoně, říká stránka historie
 * tisku (`tiskUrl`) — ne naše klasifikace. Viz `pipeline/slovo_cin.py`.
 */
export interface SlovoCin {
  id: string;
  claimId: string;
  messageId: string;
  idOsoba: string;
  receno: {
    citace: string;
    start: number;
    end: number;
    datum: string;
    stenoUrl: string;
    debateId: string;
    debateTitle: string;
  };
  postoj: SlovoCinPostoj;
  /** Proč model postoj takto určil — publikuje se, aby šel přezkoumat. */
  postojOduvodneni: string;
  hlasovani: {
    idHlasovani: string;
    url: string;
    cislo: number;
    schuze: number;
    nazev: string;
    /** Formulace Sněmovny: „schválen" / „zamítnut". */
    vysledekSlovy: string;
    prijat: boolean;
    /** Stránka historie tisku — doklad, že tohle je to finální hlasování. */
    historieUrl: string;
    /** Hlas z HTML hlasovacího lístku, kde se „zdržel se" a „nehlasoval" rozlišují. */
    hlas: VoteValue;
    /** Poslanec měl na dobu hlasování omluvu — není to prostá absence. */
    omluven: boolean;
    klub: string;
    /** Jak hlasoval zbytek klubu — odchylka od klubu je jiný příběh než kázeň. */
    klubPomer: {
      pro: number;
      proti: number;
      zdrzelNeboNehlasoval: number;
      neprihlasen: number;
    } | null;
  };
  tisk: {
    cislo: string;
    nazev: string;
    url: string;
  };
  shoda: SlovoCinShoda;
}

/** Poměr hlasů jednoho klubu u jednoho hlasování — bez jména klubu, to nese klíč objektu. */
export interface KlubHlasovaniPocty {
  pro: number;
  proti: number;
  zdrzelNeboNehlasoval: number;
  neprihlasen: number;
}

/**
 * Jeden doklad „slib z vládního prohlášení vs. hlasování koaličních klubů".
 *
 * Záměrně bez verdiktu (žádné `splneno`/`nesplneno`): vazba slib -> tisk není
 * strukturální jako u `SlovoCin` — určuje ji model podle NÁZVU tisku, ne podle
 * jeho plného znění, a i po nezávislém přezkumu (`pipeline/programova_vernost.py`,
 * `challenge_pairing`) je to posouzení, ne fakt. Web proto ukazuje slib, název
 * tisku, výsledek hlasování a poměr v každém klubu vedle sebe a závěr nechává
 * na čtenáři.
 */
export interface ProgramovaVernost {
  id: string;
  zavazekId: string;
  zavazek: {
    kapitolaId: string;
    /** Pořadí kapitoly na stránce prohlášení (1–18) — pro řazení v UI. */
    kapitolaPoradi: number;
    kapitolaNazev: string;
    citace: string;
    /** Kotva na kapitolu v Programovém prohlášení — prohlášení nemá kotvy jemnější než kapitola. */
    url: string;
    /** Datum schválení prohlášení vládou (2026-01-05). */
    schvaleno: string;
  };
  tisk: {
    cislo: string;
    nazev: string;
    url: string;
  };
  hlasovani: {
    idHlasovani: string;
    url: string;
    cislo: number;
    schuze: number;
    datum: string;
    /** Formulace Sněmovny: „schválen" / „zamítnut". */
    vysledekSlovy: string;
    prijat: boolean;
    /** Stránka historie tisku — doklad, že jde o (poslední) finální hlasování o tomto tisku. */
    historieUrl: string;
  };
  /** Zdůvodnění spárování slibu s tiskem, jak ho vrátil model — publikuje se k přezkumu. */
  duvodSparovani: string;
  /** Poměr hlasů každého koaličního klubu u finálního hlasování; `null`, když se nedal spočítat. */
  kluby: {
    ANO2011: KlubHlasovaniPocty | null;
    MS: KlubHlasovaniPocty | null;
    SPD: KlubHlasovaniPocty | null;
  };
}

/** Role k datu — přímo z `psp.opendata.Registry.political_role_at()`. */
export type PolitickaRole = 'MINISTER' | 'COALITION_DEPUTY' | 'OPPOSITION_DEPUTY' | 'INDEPENDENT';

/**
 * Jeden doklad „řekl v opozici / hlasoval ve vládě" (nebo naopak) — Fáze 6b.
 *
 * Jediný veřejný typ v enginu, jehož zdroj NENÍ oficiální záznam: citace
 * pochází z novinového článku, ne ze stenozáznamu. Proto na rozdíl od
 * `SlovoCin`/`ProgramovaVernost` prošel navíc RUČNÍM schválením
 * (`pipeline/promote_media_lead.py`) — `schvalenoAt` je datum, kdy si
 * operátor přečetl `receno.zdroj.url` sám, ne datum strojového ověření.
 * Bez rezervy na verdikt (žádné `SeverityLevel`) — stejná disciplína jako
 * `SlovoCin`.
 */
export interface RolovyObrat {
  id: string;
  idOsoba: string;
  politik: string;
  receno: {
    citace: string;
    rolePriCitatu: PolitickaRole;
    zdroj: {
      url: string;
      /** Doména zdroje (např. „seznamzpravy.cz") nebo „YouTube · <kanál>" u videa. */
      medium: string;
      /** U videa: datum publikace videa (ne datum zveřejnění článku). */
      datumClanku: string;
      /**
       * Jen u zdroje typu video (Fáze 6c) — orientační vteřina, kde citace v
       * přepisu začíná. Odvozeno z pořadí úseků diarizovaného přepisu, NE
       * forenzní forced-alignment přesnost (na rozdíl od `mediaEvidence`
       * u stenozáznamu) — proto se řetězec citace vždy ověřuje samostatně.
       */
      timestampSeconds?: number;
    };
  };
  postoj: 'PRO' | 'PROTI';
  /** Proč model postoj takto určil — publikuje se, aby šel přezkoumat. */
  postojOduvodneni: string;
  tisk: {
    cislo: string;
    nazev: string;
    url: string;
  };
  hlasovani: {
    idHlasovani: string;
    url: string;
    cislo: number;
    schuze: number;
    /** Formulace Sněmovny: „schválen" / „zamítnut". */
    vysledekSlovy: string;
    prijat: boolean;
    /** Stránka historie tisku — doklad, že jde o (poslední) finální hlasování o tomto tisku. */
    historieUrl: string;
    hlas: VoteValue;
    omluven: boolean;
    klub: string;
    klubPomer: {
      pro: number;
      proti: number;
      zdrzelNeboNehlasoval: number;
      neprihlasen: number;
    } | null;
    rolePriHlasovani: PolitickaRole;
  };
  shoda: SlovoCinShoda;
  /** Zdůvodnění spárování citace s tiskem — publikuje se k přezkumu. */
  parovani?: string;
  /** Jen u NESHODA: proč obhájce rozpor nepovažoval za vyvrácený. */
  obhajoba?: string;
  /** Kdy operátor lead ručně schválil (`promote_media_lead.py`), ne kdy vznikl. */
  schvalenoAt: string;
}

/* ------------------------------------------------------------------ */
/* UI stav                                                             */
/* ------------------------------------------------------------------ */

/** Výběr anotace ve feedu – nese i vystoupení, kvůli napárovanému videu. */
export interface AnnotationSelection {
  annotation: Annotation;
  message: Message;
}

export interface PoliticianFilter {
  selectedPoliticians: string[];
  selectedParties: string[];
  selectedTypes: AnomalyType[];
  selectedSeverities: SeverityLevel[];
  searchQuery: string;
  onlyAnomalies: boolean;
}

export interface AnomalyStats {
  totalSpeeches: number;
  totalAnomalies: number;
  byType: Record<AnomalyType, number>;
  bySeverity: Record<SeverityLevel, number>;
  topContradictoryPoliticians: { name: string; party: string; count: number }[];
}
