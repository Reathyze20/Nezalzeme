import "server-only";
import {
  Debate,
  HlasovaciBilance,
  IndexVecnosti,
  ProgramovaVernost,
  RolovyObrat,
  SlovoCin,
} from "@/types/debate";
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
  /**
   * Kolik dnů CELÉHO volebního období má aspoň jedno jmenovité hlasování —
   * z kompletního dumpu, nezávisle na tom, kolik dnů je v `sittingDays`
   * (ty jsou jen ze staženého vzorku stenozáznamů). Jmenovatel pro "vzorek
   * N z M" u Indexu věcnosti (Fáze 5). `null`, když se nedalo spočítat.
   */
  hlasovaniDnuCelkem: number | null;
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

export interface HlidacHistoricalRole {
  role: string;
  organization: string;
  since: string | null;
  until: string | null;
}

export interface HlidacProfile {
  osobaId: string;
  profileUrl: string;
  fullName: string;
  birthYear?: number | null;
  historicalRoles: HlidacHistoricalRole[];
  corporateTiesCount: number;
  corporateEntities: string[];
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
  hlidacStatu?: HlidacProfile;
  /**
   * Hlasovací bilance za volební období (Fáze 2). Chybí u členů vlády bez
   * poslaneckého mandátu — ti v `poslanec.unl` nemají `id_poslanec`, takže
   * pro ně jmenovité hlasování neexistuje.
   */
  hlasovaciBilance?: HlasovaciBilance;
  /** Index věcnosti (Fáze 5) — poslanecké návrhy zákonů a rozklad vystoupení. */
  indexVecnosti?: IndexVecnosti;
}

export const PSP_META = dataset.meta as PspMeta;
export const PSP_PARTIES = dataset.parties as PspParty[];
export const PSP_POLITICIANS = dataset.politicians as PspPolitician[];
export const PSP_DEBATES = dataset.debates as Debate[];

/**
 * Slovo vs. Čin (Fáze 3) — jen položky, které prošly důkazní bránou
 * v `export_web.verify_slovo_cin` (každá znovu odvozená z otevřených dat).
 */
export const PSP_SLOVO_CIN = ((dataset as { slovoCin?: unknown }).slovoCin ?? []) as SlovoCin[];

/**
 * Programová věrnost (Fáze 4) — jen položky, které prošly důkazní bránou
 * v `export_web.verify_programova_vernost`.
 */
export const PSP_PROGRAMOVA_VERNOST = (
  (dataset as { programovaVernost?: unknown }).programovaVernost ?? []
) as ProgramovaVernost[];

/**
 * Rolový obrat v médiích (Fáze 6b) — jen položky, které prošly DVOJÍ bránou:
 * strojovou (`export_web.verify_media_role_flip`) A ruční
 * (`pipeline/promote_media_lead.py`, operátor si přečetl zdrojový článek).
 */
export const PSP_ROLOVY_OBRAT = (
  (dataset as { rolovyObrat?: unknown }).rolovyObrat ?? []
) as RolovyObrat[];

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
