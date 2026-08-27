import "server-only";
import { Debate } from "@/types/debate";
import dataset from "./dataset.json";

/**
 * Korpus stažený z veřejného stenozáznamu Poslanecké sněmovny.
 *
 * Soubor `dataset.json` vedle je **generovaný** — vzniká příkazem
 * `python pipeline/export_web.py` a needituje se ručně. Je to jediný vstup dat
 * do aplikace; kde se korpus fyzicky drží (dnes JSON, později databáze) je
 * odsud neviditelné.
 *
 * `server-only` je pojistka proti nejdražší chybě, která tu jde udělat:
 * import korpusu do klientské komponenty by poslal 2,7 MB JSON do prohlížeče
 * (naměřeno: First Load JS ze 109 kB na 1,13 MB). Takhle je z toho chyba
 * při buildu, ne pomalý web.
 */

export interface PspSittingDay {
  sessionNumber: number;
  date: string;
}

export interface PspMeta {
  /** Kdy artefakt vznikl (ISO 8601, UTC). */
  generatedAt: string;
  /** Odkaz na rozcestník stenoprotokolů, ze kterých korpus pochází. */
  source: string;
  term: string;
  chamber: string;
  sittingDays: PspSittingDay[];
  debateCount: number;
  messageCount: number;
  /**
   * Kolik vystoupení už prošlo analýzou. Dokud je nula, nesmí rozhraní
   * tvrdit, že se u někoho nic nenašlo — nic se totiž nehledalo.
   */
  analyzedMessageCount: number;
  annotationCount: number;
  politicianCount: number;
  /**
   * Rozpad analyzovaných vystoupení podle původu anotací.
   * `engine` = strojové výstupy run_pipeline.py.
   * `handAuthored` = ruční ukázky (po Fázi A vždy 0 — odpojeny od korpusu).
   */
  byProvenance: {
    engine: number;
    handAuthored: number;
  };
}

export interface PspParty {
  name: string;
  fullName: string;
  color: string;
}

export interface PspPolitician {
  name: string;
  slug: string;
  idOsoba: string;
  /** Klub k poslednímu vystoupení v korpusu; prázdný u členů vlády bez mandátu. */
  party: string;
  role: string;
  speechCount: number;
  lastSpokeAt: string;
  profileUrl: string;
}

export const PSP_META = dataset.meta as PspMeta;
export const PSP_PARTIES = dataset.parties as PspParty[];
export const PSP_POLITICIANS = dataset.politicians as PspPolitician[];
export const PSP_DEBATES = dataset.debates as Debate[];

/**
 * Analýza zatím neproběhla — engine nikdy neběžel nad žádným vystoupením.
 *
 * Závisí na `byProvenance.engine`, ne na `analyzedMessageCount` — druhé bylo
 * náchylné k false-positive, když ruční ukázky nastavily `analyzedAt` na
 * 19 vystoupení a skryly DemoBanner, přestože žádný engine nikdy neběžel.
 * Po Fázi A jsou ruční ukázky odpojeny od korpusu a tenhle problém nemůže
 * nastat znovu.
 */
export const ANALYSIS_PENDING = PSP_META.byProvenance.engine === 0;
