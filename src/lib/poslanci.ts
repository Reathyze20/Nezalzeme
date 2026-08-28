import { DEBATES, jeZkontrolovano } from "@/lib/debate";
import { PSP_POLITICIANS, PSP_SLOVO_CIN, HlidacProfile } from "@/data/psp";
import { AnomalyType, GovTrackScore, HlasovaciBilance, IndexVecnosti, MediaEvidence, PresentationTier, SeverityLevel, SlovoCin } from "@/types/debate";
import { formatDatum } from "@/lib/ui";
import { resolveMediaEvidence } from "@/lib/media";

/**
 * Agregace nad `DEBATES` (publikovaná, filtrovaná data z `src/lib/debate.ts`)
 * — nikdy nad `PSP_DEBATES`. Anotace pod prahem důkazního břemene se sem
 * tedy nedostanou stejně jako do zbytku UI.
 *
 * Univerzum poslanců pochází z korpusu, ne z ručního seznamu: profil smí mít
 * jen ten, kdo v záznamu skutečně mluvil.
 */

/**
 * Stav jednoho vystoupení v pásmu.
 *
 * `nezkontrolovano` je vlastní stav, ne odrůda `ciste`. Bez něj by pásmo
 * u neanalyzovaného záznamu vypadalo stejně jako u prověřeného a bez nálezu.
 *
 * `vyvoj` (Fáze 5, pásmo CONTEXT_DEVELOPMENT) je od `posun` (VALUE_SHIFT)
 * záměrně oddělený stav: `posun` je neutrální podle KATEGORIE (změna
 * postoje je vždycky legitimní, bez ohledu na jistotu), `vyvoj` je
 * neutrální podle JISTOTY (kandidát nedosáhl na práh pro obvinění, ať je
 * kategorie jakákoli). Splynutí obou by v pásmu smazalo rozdíl mezi
 * "změnil názor" a "nejsme si dost jistí, že šlo o rozpor".
 */
export type StavVystoupeni = "nezkontrolovano" | "ciste" | "rozpor" | "posun" | "vyvoj";

export interface PoslanecZaznam {
  id: string;
  kategorie: AnomalyType;
  jePosun: boolean;
  presentationTier: PresentationTier;
  severity: SeverityLevel;
  confidenceScore: number;
  casRadit: string;
  casZobrazeni: string;
  debateId: string;
  debateTitle: string;
  messageId: string;
  recenoText: string;
  recenoStart: number;
  recenoEnd: number;
  zaznamText: string;
  zaznamUrl: string;
  zaznamKontext: string;
  zaznamDatum: string;
  vysvetleni: string;
  media: MediaEvidence | null;
  downgradedFrom?: AnomalyType;
  defensesConsidered?: string[];
  defenseEvaluated?: string;
  /** Fáze 4: vlastní zdůvodnění role Soudce, odlišné od `defenseEvaluated` (shrnutí Obhájce). */
  arbiterRationale?: string;
  votingBallotId?: string;
  voteRecorded?: string;
  debateTisk?: {
    cisloTisku: string | null;
    faze: string;
    nazev: string;
    url: string;
  };
}

export interface PoslanecSouhrn {
  id: string;
  jmeno: string;
  klub: string;
  role: string;
  /** Kolik vystoupení tohoto poslance je v korpusu. */
  vystoupeni: number;
  /** Kolik z nich už prošlo detekcí. */
  overeno: number;
  rozpor: number;
  posun: number;
  /** Fáze 5: kolik vystoupení skončilo v neutrálním pásmu CONTEXT_DEVELOPMENT. */
  vyvoj: number;
  tally: StavVystoupeni[];
  /** Odkaz na profil na psp.cz. */
  profilUrl: string;
  hlidacStatu?: HlidacProfile;
  stanceConsistency?: {
    sci: number;
    sciLabel: string;
    contradictionCount: number;
    commitmentCount: number;
    partyAverageSci?: number;
    sciVsPartyDelta?: number;
  };
  /** Hlasovací bilance za volební období (Fáze 2) — z otevřených dat PSP ČR. */
  hlasovaciBilance?: HlasovaciBilance;
  /** Index věcnosti (Fáze 5) — poslanecké návrhy zákonů a rozklad vystoupení. */
  indexVecnosti?: IndexVecnosti;
}

export interface PoslanecDetail extends PoslanecSouhrn {
  zaznamy: PoslanecZaznam[];
  govTrackScore?: GovTrackScore;
  /** Doklady „řečeno vs. hlasováno" (Fáze 3) pro tohoto poslance. */
  slovoCin: SlovoCin[];
}

interface VystoupeniZaznam {
  cas: string;
  stav: StavVystoupeni;
}

let cache: Map<string, PoslanecDetail> | null = null;

function sestavDetaily(): Map<string, PoslanecDetail> {
  if (cache) return cache;
  cache = new Map();

  const bySpeaker = new Map<string, { debate: (typeof DEBATES)[0]; msg: (typeof DEBATES)[0]["messages"][0] }[]>();
  for (const debata of DEBATES) {
    for (const msg of debata.messages) {
      const list = bySpeaker.get(msg.speaker);
      if (list) {
        list.push({ debate: debata, msg });
      } else {
        bySpeaker.set(msg.speaker, [{ debate: debata, msg }]);
      }
    }
  }

  for (const p of PSP_POLITICIANS) {
    const list = bySpeaker.get(p.name) || [];
    const vystoupeni: VystoupeniZaznam[] = [];
    const zaznamy: PoslanecZaznam[] = [];
    let govTrackScore: GovTrackScore | undefined;

    for (const { debate, msg } of list) {
      const cas = `${msg.date}T${msg.timestamp}`;
      if (msg.govTrackScore) govTrackScore = msg.govTrackScore;

      if (msg.annotations.length === 0) {
        vystoupeni.push({ cas, stav: jeZkontrolovano(msg) ? "ciste" : "nezkontrolovano" });
        continue;
      }

      for (const ann of msg.annotations) {
        const jePosun = ann.type === "VALUE_SHIFT";
        const stav: StavVystoupeni = jePosun ? "posun" : ann.presentationTier === "CONTEXT_DEVELOPMENT" ? "vyvoj" : "rozpor";
        vystoupeni.push({ cas, stav });
        zaznamy.push({
          id: ann.id ?? `${msg.messageId}-${ann.start}`,
          kategorie: ann.type,
          jePosun,
          presentationTier: ann.presentationTier,
          severity: ann.severity,
          confidenceScore: ann.confidenceScore,
          casRadit: cas,
          casZobrazeni: `${formatDatum(msg.date)} · ${debate.sessionNumber}. schůze · ${msg.timestamp}`,
          debateId: debate.debateId,
          debateTitle: debate.title,
          messageId: msg.messageId,
          recenoText: msg.cleanText,
          recenoStart: ann.start,
          recenoEnd: ann.end,
          zaznamText: ann.proof.pastQuote,
          zaznamUrl: ann.proof.sourceUrl,
          zaznamKontext: ann.proof.pastContext,
          zaznamDatum: ann.proof.pastDate,
          vysvetleni: ann.explanation,
          media: resolveMediaEvidence(ann, msg.media),
          downgradedFrom: ann.adversarialCheck?.downgradedFrom,
          defensesConsidered: ann.adversarialCheck?.defensesConsidered,
          defenseEvaluated: ann.adversarialCheck?.defenseEvaluated,
          arbiterRationale: ann.adversarialCheck?.arbiterRationale,
          votingBallotId: ann.proof?.votingBallotId,
          voteRecorded: ann.proof?.voteRecorded,
          debateTisk: (debate as any).tisk,
        });
      }
    }

    vystoupeni.sort((a, b) => a.cas.localeCompare(b.cas));
    zaznamy.sort((a, b) => a.casRadit.localeCompare(b.casRadit));

    const tally = vystoupeni.map((v) => v.stav);
    const rozpor = tally.filter((s) => s === "rozpor").length;
    const posun = tally.filter((s) => s === "posun").length;
    const vyvoj = tally.filter((s) => s === "vyvoj").length;

    cache.set(p.slug, {
      id: p.slug,
      jmeno: p.name,
      klub: p.party,
      role: p.role,
      profilUrl: p.profileUrl,
      vystoupeni: tally.length,
      overeno: tally.filter((s) => s !== "nezkontrolovano").length,
      rozpor,
      posun,
      vyvoj,
      tally,
      zaznamy,
      govTrackScore,
      hlidacStatu: p.hlidacStatu,
      stanceConsistency: (p as any).stanceConsistency,
      hlasovaciBilance: p.hlasovaciBilance,
      indexVecnosti: p.indexVecnosti,
      slovoCin: PSP_SLOVO_CIN.filter((z) => z.idOsoba === String(p.idOsoba)),
    });
  }

  return cache;
}

export function getVsichniPoslanci(): PoslanecSouhrn[] {
  return [...sestavDetaily().values()]
    .map(({ zaznamy, govTrackScore, slovoCin, ...souhrn }) => souhrn)
    .sort((a, b) => prijmeniZ(a.jmeno).localeCompare(prijmeniZ(b.jmeno), "cs"));
}

export function getPoslanecDetail(id: string): PoslanecDetail | undefined {
  return sestavDetaily().get(id);
}

function prijmeniZ(jmeno: string): string {
  const casti = jmeno.trim().split(/\s+/);
  return casti.length > 1 ? casti.slice(1).join(" ") : jmeno;
}

/** Souhrnná čísla přes všechny poslance — úvodní měřidlo v rejstříku. */
export function getCelkoveMeridlo() {
  const vsichni = [...sestavDetaily().values()];
  const vystoupeni = vsichni.reduce((a, p) => a + p.vystoupeni, 0);
  const overeno = vsichni.reduce((a, p) => a + p.overeno, 0);
  const rozpor = vsichni.reduce((a, p) => a + p.rozpor, 0);
  const posun = vsichni.reduce((a, p) => a + p.posun, 0);
  const vyvoj = vsichni.reduce((a, p) => a + p.vyvoj, 0);
  const tally: StavVystoupeni[] = vsichni.flatMap((p) => p.tally);
  return { vystoupeni, overeno, rozpor, posun, vyvoj, tally };
}
