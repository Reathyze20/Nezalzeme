import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";
import {
  AnomalyType,
  AnomalyTypeAlias,
  Annotation,
  CONTEXT_THRESHOLD,
  PresentationTier,
  PUBLISH_THRESHOLD,
  SeverityLevel,
} from "@/types/debate";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function getAnomalyMeta(type: AnomalyType) {
  switch (type) {
    case 'CONTRADICTION_TIME':
      return {
        label: 'Časový rozpor (Flip-Flop)',
        shortLabel: 'Časový rozpor',
        color: 'red',
        bgLight: 'bg-red-50 hover:bg-red-100 border-red-300 text-red-900',
        bgDark: 'dark:bg-red-950/40 dark:hover:bg-red-950/60 dark:border-red-600/60 dark:text-red-200',
        badge: 'bg-red-600 text-white dark:bg-red-600',
        badgeLight: 'bg-red-100 text-red-800 border-red-200 dark:bg-red-950/70 dark:text-red-300 dark:border-red-800',
        icon: 'ClockRewind',
        description: 'Poslanec v minulosti na stejné téma tvrdil přímý opak.'
      };
    case 'VOTE_MISMATCH':
      return {
        label: 'Rozpor se skutečným hlasováním',
        shortLabel: 'Rozpor s hlasováním',
        color: 'purple',
        bgLight: 'bg-purple-50 hover:bg-purple-100 border-purple-300 text-purple-900',
        bgDark: 'dark:bg-purple-950/40 dark:hover:bg-purple-950/60 dark:border-purple-600/60 dark:text-purple-200',
        badge: 'bg-purple-600 text-white dark:bg-purple-600',
        badgeLight: 'bg-purple-100 text-purple-800 border-purple-200 dark:bg-purple-950/70 dark:text-purple-300 dark:border-purple-800',
        icon: 'Vote',
        description: 'Výrok poslance přímo odporuje tomu, jak reálně v PSP hlasoval.'
      };
    case 'FACTUAL_MISSTATEMENT':
      return {
        label: 'Faktická / statistická nepřesnost',
        shortLabel: 'Faktická nepřesnost',
        color: 'amber',
        bgLight: 'bg-amber-50 hover:bg-amber-100 border-amber-300 text-amber-900',
        bgDark: 'dark:bg-amber-950/40 dark:hover:bg-amber-950/60 dark:border-amber-600/60 dark:text-amber-200',
        badge: 'bg-amber-500 text-white dark:bg-amber-600',
        badgeLight: 'bg-amber-100 text-amber-800 border-amber-200 dark:bg-amber-950/70 dark:text-amber-300 dark:border-amber-800',
        icon: 'AlertTriangle',
        description: 'Tvrzení operující s objektivně nepravdivým statistickým nebo historickým údajem.'
      };
    case 'VALUE_SHIFT':
      return {
        label: 'Názorový / hodnotový posun',
        shortLabel: 'Názorový posun',
        color: 'blue',
        bgLight: 'bg-blue-50 hover:bg-blue-100 border-blue-300 text-blue-900',
        bgDark: 'dark:bg-blue-950/40 dark:hover:bg-blue-950/60 dark:border-blue-600/60 dark:text-blue-200',
        badge: 'bg-blue-600 text-white dark:bg-blue-600',
        badgeLight: 'bg-blue-100 text-blue-800 border-blue-200 dark:bg-blue-950/70 dark:text-blue-300 dark:border-blue-800',
        icon: 'TrendingUp',
        description: 'Změna politického postoje v čase (uvedeno věcně a neutrálně).'
      };
  }
}

export function getSeverityMeta(severity: SeverityLevel) {
  switch (severity) {
    case 'CRITICAL':
      return {
        label: 'Kritická závažnost',
        shortLabel: 'Kritická',
        color: 'rose',
        badge: 'bg-rose-700 text-white dark:bg-rose-700',
        dot: 'bg-rose-600',
      };
    case 'HIGH':
      return {
        label: 'Vysoká závažnost',
        shortLabel: 'Vysoká',
        color: 'red',
        badge: 'bg-rose-600 text-white dark:bg-rose-600',
        dot: 'bg-rose-500',
      };
    case 'MEDIUM':
      return {
        label: 'Střední závažnost',
        shortLabel: 'Střední',
        color: 'amber',
        badge: 'bg-amber-500 text-white dark:bg-amber-600',
        dot: 'bg-amber-500',
      };
    case 'LOW':
      return {
        label: 'Nízká závažnost',
        shortLabel: 'Nízká',
        color: 'blue',
        badge: 'bg-sky-500 text-white dark:bg-sky-600',
        dot: 'bg-sky-400',
      };
  }
}

/* ------------------------------------------------------------------ */
/* Normalizace vstupu z LLM (architekturní prompt v2)                  */
/* ------------------------------------------------------------------ */

const ANOMALY_TYPE_ALIASES: Record<string, AnomalyType> = {
  TIME_CONTRADICTION: 'CONTRADICTION_TIME',
  CONTRADICTION_TIME: 'CONTRADICTION_TIME',
  FACTUAL_ERROR: 'FACTUAL_MISSTATEMENT',
  FACTUAL_MISSTATEMENT: 'FACTUAL_MISSTATEMENT',
  VOTE_MISMATCH: 'VOTE_MISMATCH',
  VALUE_SHIFT: 'VALUE_SHIFT',
};

/** Převede název kategorie z promptu na kanonický interní název. */
export function normalizeAnomalyType(type: AnomalyTypeAlias | string): AnomalyType | null {
  return ANOMALY_TYPE_ALIASES[type] ?? null;
}

const SEVERITY_ORDER: Record<SeverityLevel, number> = {
  CRITICAL: 3,
  HIGH: 2,
  MEDIUM: 1,
  LOW: 0,
};

/** Seřadí anotace od nejzávažnějších; při shodě rozhoduje jistota detekce. */
export function sortBySeverity(annotations: Annotation[]): Annotation[] {
  return [...annotations].sort((a, b) => {
    const bySeverity = SEVERITY_ORDER[b.severity] - SEVERITY_ORDER[a.severity];
    if (bySeverity !== 0) return bySeverity;
    return b.confidenceScore - a.confidenceScore;
  });
}

/** Trojcestné pásmo prezentace podle kalibrované jistoty (Fáze 5). */
export function getPresentationTier(score: number): PresentationTier {
  if (score >= PUBLISH_THRESHOLD) return "PUBLISHED";
  if (score >= CONTEXT_THRESHOLD) return "CONTEXT_DEVELOPMENT";
  return "DROPPED";
}

/** 0.96 -> "96 %" pro zobrazení v UI. */
export function formatConfidence(score: number): string {
  return `${Math.round(score * 100)} %`;
}

/** Skloňování: 0 a 5+ „anomálií", 1 „anomálie", 2–4 „anomálie". */
export function pocetAnomalii(count: number): string {
  return count === 0 || count > 4 ? 'anomálií' : 'anomálie';
}

/** Doména zdroje pro popisek odkazu, např. "psp.cz". */
export function sourceHost(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, '');
  } catch {
    return 'zdroj';
  }
}

/** Odkazuje důkaz přímo do stenozáznamu nebo hlasování PSP? */
export function isPspRecord(url: string): boolean {
  return /(^|\.)psp\.cz$/.test(sourceHost(url)) && /\/eknih\//.test(url);
}
