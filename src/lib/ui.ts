import { AnomalyType, SeverityLevel, VoteValue, VoteValueLedger } from "@/types/debate";

/**
 * Popisky a odvozené UI hodnoty pro nový vizuální jazyk (rejstřík / profil /
 * rozprava). Záměrně oddělené od `src/lib/utils.ts`, který patří datové
 * a publikační vrstvě pipeline — nic tady na ní nezávisí a nic v ní na
 * tomhle souboru.
 */

export interface KategorieMeta {
  label: string;
  jePosun: boolean;
}

export function getKategorieMeta(type: AnomalyType): KategorieMeta {
  switch (type) {
    case "CONTRADICTION_TIME":
      return { label: "Opak dřívějška", jePosun: false };
    case "VOTE_MISMATCH":
      return { label: "Rozpor s hlasováním", jePosun: false };
    case "FACTUAL_MISSTATEMENT":
      return { label: "Údaj neodpovídá zdroji", jePosun: false };
    case "VALUE_SHIFT":
      return { label: "Změna postoje", jePosun: true };
    default:
      return { label: "Změna postoje", jePosun: true };
  }
}

const ZAVAZNOST_LABEL: Record<SeverityLevel, string> = {
  CRITICAL: "kritická závažnost",
  HIGH: "vysoká závažnost",
  MEDIUM: "střední závažnost",
  LOW: "nízká závažnost",
};

export function getZavaznostLabel(severity: SeverityLevel): string {
  return ZAVAZNOST_LABEL[severity];
}

export function formatJistota(score: number): string {
  return `jistota ${Math.round((score ?? 0) * 100)} %`;
}

export interface ConfidenceIntervalMeta {
  tier: "PROVEN" | "HIGH_PROBABILITY" | "INDICATOR" | "LOW";
  label: string;
  badgeClass: string;
  icon: string;
  pct: number;
}

/**
 * Pásma jistoty pro lidsky srozumitelné zobrazení (Fáze C1):
 * - >= 0.95: Prokazatelný rozpor
 * - 0.85-0.94: Vysoká pravděpodobnost
 * - 0.80-0.84: Indikátor obratu v čase
 * - < 0.80: K přezkumu
 */
export function getConfidenceInterval(score: number): ConfidenceIntervalMeta {
  const pct = Math.round((score ?? 0) * 100);
  if (score >= 0.95) {
    return {
      tier: "PROVEN",
      label: "Prokazatelný rozpor",
      badgeClass: "bg-red-50 text-red-700 border-red-200 dark:bg-red-950/40 dark:text-red-300 dark:border-red-800/60",
      icon: "🔴",
      pct,
    };
  }
  if (score >= 0.85) {
    return {
      tier: "HIGH_PROBABILITY",
      label: "Vysoká pravděpodobnost",
      badgeClass: "bg-amber-50 text-amber-800 border-amber-200 dark:bg-amber-950/40 dark:text-amber-300 dark:border-amber-800/60",
      icon: "🟠",
      pct,
    };
  }
  if (score >= 0.80) {
    return {
      tier: "INDICATOR",
      label: "Indikátor obratu",
      badgeClass: "bg-yellow-50 text-yellow-800 border-yellow-200 dark:bg-yellow-950/40 dark:text-yellow-300 dark:border-yellow-800/60",
      icon: "🟡",
      pct,
    };
  }
  return {
    tier: "LOW",
    label: "K přezkumu",
    badgeClass: "bg-slate-50 text-slate-700 border-slate-200 dark:bg-slate-900/40 dark:text-slate-300 dark:border-slate-800",
    icon: "⚪",
    pct,
  };
}

/** "2024-06-12" -> "12. 6. 2024" */
export function formatDatum(iso: string): string {
  const [rok, mesic, den] = iso.split("-");
  return `${parseInt(den, 10)}. ${parseInt(mesic, 10)}. ${rok}`;
}

/** Odstraní diakritiku a udělá URL-safe řetězec, např. "Alena Kovářová" -> "kovarova". */
export function slugify(input: string): string {
  return input
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/(^-|-$)/g, "");
}

/**
 * Slug poslance pro /poslanec/[slug].
 *
 * Z **celého** jména, ne jen z příjmení: ve sněmovně sedí dvě Kovářové
 * a dva Zůnové a slug z příjmení by je sloučil do jednoho profilu.
 * Autoritativní slug nese `PSP_POLITICIANS[].slug` — tahle funkce musí dávat
 * stejný výsledek, aby odkazy z rozpravy trefily existující profil.
 */
export function politicianSlug(jmeno: string): string {
  return slugify(jmeno);
}

/** "https://www.psp.cz/eknih/..." -> "psp.cz", "https://www.cssz.cz/..." -> "cssz.cz" */
export function hostname(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

/* ------------------------------------------------------------------ */
/* Hlasovací rejstřík (Fáze 2)                                         */
/* ------------------------------------------------------------------ */

/**
 * Popisek hlasu z otevřených dat.
 *
 * `ZDRZEL_SE_NEBO_NEHLASOVAL` se **nesmí** zkrátit na „zdržel se": dump
 * `hl-YYYYps.zip` obě možnosti slučuje do jednoho kódu, takže tvrdit jedno
 * z nich by bylo tvrzení nad rámec dat. Rozlišit je umí až HTML
 * `hlasy.sqw?G=`, kterým se dověřuje publikovaná položka (Fáze 3).
 */
const HLAS_LABEL: Record<VoteValueLedger, string> = {
  PRO: "pro",
  PROTI: "proti",
  ZDRZEL_SE_NEBO_NEHLASOVAL: "zdržel se / nehlasoval",
  NEPRIHLASEN: "nepřihlášen",
};

export function getHlasLabel(hlas: VoteValueLedger): string {
  return HLAS_LABEL[hlas] ?? "neznámo";
}

/**
 * Barva hlasu. Záměrně **nepoužívá** token `rozpor` (rez) ani zelenou:
 * rejstřík nic neobviňuje a „pro" není dobře ani špatně. Odlišují se jen
 * tvarem a sytostí inkoustu, aby se sloupec dal číst, ale nečetl se jako
 * hodnocení.
 */
export function getHlasClass(hlas: VoteValueLedger): string {
  switch (hlas) {
    case "PRO":
      return "text-inkoust font-semibold";
    case "PROTI":
      return "text-inkoust font-semibold";
    case "ZDRZEL_SE_NEBO_NEHLASOVAL":
      return "text-inkoust-3";
    default:
      return "text-inkoust-3 italic";
  }
}

/** Krátká značka do tabulky — „PRO" / „PROTI" / „ZDR./NEHL." / „NEPŘ." */
export function getHlasZnacka(hlas: VoteValueLedger): string {
  switch (hlas) {
    case "PRO":
      return "PRO";
    case "PROTI":
      return "PROTI";
    case "ZDRZEL_SE_NEBO_NEHLASOVAL":
      return "ZDR./NEHL.";
    default:
      return "NEPŘ.";
  }
}

/**
 * Minimální počet hlasování, od kterého má smysl ukazovat účast jako číslo.
 *
 * Poslanec, který složil mandát po dvou hlasováních, má v datech `celkem = 2`
 * — účast „0 %" by u něj byla formálně pravdivá a fakticky zavádějící. Stejná
 * logika jako práh `overeno < 5` na profilu poslance.
 */
export const MIN_HLASOVANI_PRO_UCAST = 20;

/** „přijat" / „nepřijat" — výsledek hlasování slovy. */
export function getVysledekLabel(prijato: boolean): string {
  return prijato ? "návrh přijat" : "návrh nepřijat";
}

/**
 * Popisek přesného hlasu z hlasovacího lístku (`VoteValue`).
 *
 * Odlišné od `getHlasLabel`, které popisuje hodnotu z otevřených dat, kde
 * „zdržel se" a „nehlasoval" splývají. Sem se dostane jen hlas dověřený
 * z HTML `hlasy.sqw`, takže „zdržel se" tu stát smí.
 */
const VOTE_VALUE_LABEL: Record<VoteValue, string> = {
  PRO: "pro",
  PROTI: "proti",
  ZDRZEL_SE: "zdržel se",
  NEPRIHLASEN: "nepřihlášen",
};

export function getVoteValueLabel(hlas: VoteValue): string {
  return VOTE_VALUE_LABEL[hlas] ?? "neznámo";
}
