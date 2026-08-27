/**
 * Přípravná vrstva mezi korpusem staženým ze stenozáznamu (`src/data/psp/`)
 * a UI. Aplikuje publikační pravidla enginu:
 *
 *  - důkazní břemeno: anotace pod prahem 0,80 se nepublikují (Fáze 4–5),
 *  - řazení od nejzávažnějších rozporů,
 *  - audiovizuální ukotvení: napárování vystoupení na záznam (Fáze 6).
 *
 * UI čte výhradně `DEBATES`, nikdy `PSP_DEBATES` — jinak by se do rozhraní
 * dostaly i anotace, které důkazní břemeno neunesly.
 */

import { Annotation, Debate, Message } from "@/types/debate";
import {
  ANALYSIS_PENDING,
  PSP_DEBATES,
  PSP_META,
  PSP_PARTIES,
  PSP_POLITICIANS,
} from "@/data/psp";
import { resolveMessageMedia, SESSION_RECORDINGS } from "@/data/mediaMap";
import { buildArchiveUrl } from "@/lib/media";
import { getPresentationTier, sortBySeverity } from "@/lib/utils";

/** Projde anotaci publikačními pravidly enginu (obvinění i neutrální kontext — jen ne DROPPED). */
export function isPublishable(annotation: Annotation): boolean {
  return getPresentationTier(annotation.confidenceScore) !== "DROPPED";
}

/**
 * Dopočítá `presentationTier` z `confidenceScore` a vyřadí DROPPED.
 *
 * Nedůvěřuje se poli `presentationTier`, jak přišlo ze surových dat — stejný
 * princip jako `hasAnomalies` níž: odvozené pole se v přípravné vrstvě vždy
 * přepočítá ze zdroje pravdy (`confidenceScore`), ne přebírá bez kontroly.
 */
function preparePublishableAnnotations(annotations: Annotation[]): Annotation[] {
  return annotations
    .map((ann) => ({ ...ann, presentationTier: getPresentationTier(ann.confidenceScore) }))
    .filter((ann) => ann.presentationTier !== "DROPPED");
}

function prepareMessage(debateId: string, message: Message): Message {
  // Fáze 1 klasifikuje řečnický akt; citace oponenta ani rétorická figura se
  // řečníkovi nepřipisují, takže z nich nesmí vzniknout vykázaný rozpor.
  const attributable = !message.speechAct || message.speechAct === "OWN_STANCE";
  const annotations = attributable
    ? sortBySeverity(preparePublishableAnnotations(message.annotations))
    : [];
  return {
    ...message,
    annotations,
    hasAnomalies: annotations.length > 0,
    media: resolveMessageMedia(debateId, message),
  };
}

export function prepareDebate(debate: Debate): Debate {
  const recording = SESSION_RECORDINGS[debate.debateId];

  return {
    ...debate,
    media: recording
      ? {
          pspCastId: recording.pspCastId,
          speechStartSeconds: 0,
          alignment: "OFFSET_SYNC",
          streamStartedAt: recording.streamStartedAt,
          archiveUrl: buildArchiveUrl(recording.pspCastId),
        }
      : { pspCastId: null, speechStartSeconds: 0, alignment: "UNPAIRED" },
    messages: debate.messages.map((message) => prepareMessage(debate.debateId, message)),
  };
}

/** Rozpravy připravené k zobrazení – jediný zdroj pravdy pro UI. */
export const DEBATES: Debate[] = PSP_DEBATES.map(prepareDebate);

/* ------------------------------------------------------------------ */
/* Stav analýzy                                                        */
/* ------------------------------------------------------------------ */

/**
 * Přehled o tom, co jsme skutečně zkontrolovali.
 *
 * `annotations: []` znamená dvě různé věci — „zkontrolováno, čisté" a „zatím
 * nezkontrolováno". Rozhraní je musí rozlišit, jinak vydává neprovedenou
 * kontrolu za dobrý výsledek. Rozlišuje je `Message.analyzedAt`.
 */
export const ANALYZA = {
  /** Nad žádným vystoupením zatím neproběhla detekce. */
  ceka: ANALYSIS_PENDING,
  zkontrolovano: PSP_META.analyzedMessageCount,
  vystoupeniCelkem: PSP_META.messageCount,
  rozpravCelkem: PSP_META.debateCount,
  jednaciDny: PSP_META.sittingDays.length,
  zdroj: PSP_META.source,
  obdobi: PSP_META.term,
  aktualizovano: PSP_META.generatedAt,
} as const;

/** Prošlo vystoupení detekcí? Prázdné `annotations` samo o sobě nestačí. */
export function jeZkontrolovano(message: Message): boolean {
  return Boolean(message.analyzedAt);
}

/* ------------------------------------------------------------------ */
/* Odvozené číselníky                                                  */
/* ------------------------------------------------------------------ */

const BARVY_KLUBU: Record<string, string> = Object.fromEntries(
  PSP_PARTIES.map((strana) => [strana.name, strana.color])
);

/** Barva klubu pro rozlišení v UI; neznámý klub dostane neutrální šedou. */
export function partyColor(party: string): string {
  return BARVY_KLUBU[party] ?? "#64748B";
}

/** Kolik kandidátů skončilo v pásmu DROPPED a do UI se nedostalo vůbec. */
export const REJECTED_BELOW_THRESHOLD = PSP_DEBATES.reduce(
  (total, debata) =>
    total +
    debata.messages.reduce(
      (sum, msg) => sum + msg.annotations.filter((ann) => !isPublishable(ann)).length,
      0
    ),
  0
);

/** Kolik anotací vyšlo v pásmu PUBLISHED (>= PUBLISH_THRESHOLD, obviňující rámování). */
export const PUBLISHED_COUNT = DEBATES.reduce(
  (total, debata) =>
    total +
    debata.messages.reduce(
      (sum, msg) => sum + msg.annotations.filter((ann) => ann.presentationTier === "PUBLISHED").length,
      0
    ),
  0
);

/** Kolik anotací vyšlo v neutrálním pásmu CONTEXT_DEVELOPMENT ("Kontext a vývoj stanoviska"). */
export const CONTEXT_DEVELOPMENT_COUNT = DEBATES.reduce(
  (total, debata) =>
    total +
    debata.messages.reduce(
      (sum, msg) => sum + msg.annotations.filter((ann) => ann.presentationTier === "CONTEXT_DEVELOPMENT").length,
      0
    ),
  0
);

/**
 * Průměrná jistota publikovaných anomálií (PUBLISHED i CONTEXT_DEVELOPMENT), 0–1.
 *
 * `null` znamená "není z čeho počítat". Nula by se v rozhraní přečetla jako
 * naměřená hodnota — tedy že engine si není jistý ničím.
 */
export const AVERAGE_CONFIDENCE: number | null = (() => {
  const scores = DEBATES.flatMap((debata) =>
    debata.messages.flatMap((msg) => msg.annotations.map((ann) => ann.confidenceScore))
  );
  if (scores.length === 0) return null;
  return scores.reduce((a, b) => a + b, 0) / scores.length;
})();

/** Poslanci s počtem publikovaných anomálií — čísla plynou přímo z datasetu. */
export const POLITICIANS_WITH_COUNTS = PSP_POLITICIANS.map((politik) => ({
  ...politik,
  count: DEBATES.reduce(
    (total, debata) =>
      total +
      debata.messages
        .filter((msg) => msg.speaker === politik.name)
        .reduce((sum, msg) => sum + msg.annotations.length, 0),
    0
  ),
})).sort((a, b) => b.count - a.count || a.name.localeCompare(b.name, "cs"));
