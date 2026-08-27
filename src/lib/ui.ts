import { AnomalyType, SeverityLevel } from "@/types/debate";

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
      return { label: "Opak dřívějšího výroku", jePosun: false };
    case "VOTE_MISMATCH":
      return { label: "Rozpor s hlasováním", jePosun: false };
    case "FACTUAL_MISSTATEMENT":
      return { label: "Údaj neodpovídá zdroji", jePosun: false };
    case "VALUE_SHIFT":
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
  return `jistota ${Math.round(score * 100)} %`;
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
