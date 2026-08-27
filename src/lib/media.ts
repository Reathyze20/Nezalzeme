/**
 * FÁZE 6 – Audiovizuální ukotvení (Audiovisual Grounding).
 *
 * Dvě úrovně přesnosti:
 *  1. OFFSET_SYNC       – vteřina dopočtená z času bloku ve stenozáznamu a času startu streamu.
 *  2. FORCED_ALIGNMENT  – vteřina dodaná pipeline pro konkrétní větu (přesná).
 *
 * Video hostuje PSP ČR na vlastní infrastruktuře (`videoarchiv.psp.cz`), ne
 * na YouTube — `pspCastId` je jednacího dne, `archiveUrl` vede na oficiální
 * sdílitelnou stránku přehrávače pro celý ten den (`playa.php?cast=...`).
 * Přehrávač neumí seekovat na vteřinu přes URL, takže `archiveUrl` je pro
 * celé vystoupení i pro jednotlivou anotaci stejný — mění se jen zobrazený
 * časový popisek, na který má čtenář v přehrávači doskočit ručně.
 *
 * Python protějšek: `pipeline/aligner.py` (stejné konstanty i vzorce).
 */

import { Annotation, MediaEvidence, MediaRef, Message } from "@/types/debate";

/**
 * Průměrné tempo řeči v rozpravě PSP ČR ve znacích za sekundu.
 * Odvozeno z běžného tempa ~140 slov/min a průměrné délky českého slova ~6,2 znaku
 * včetně mezery: 140 * 6,2 / 60 ≈ 14,5.
 */
export const CHARS_PER_SECOND = 14.5;

const VIDEOARCHIV_BASE = "https://videoarchiv.psp.cz";

/** Oficiální sdílitelná stránka přehrávače PSP pro daný "cast" (jednací den). */
export function buildArchiveUrl(castId: string): string {
  return `${VIDEOARCHIV_BASE}/playa.php?cast=${encodeURIComponent(castId)}`;
}

/**
 * Offset Sync – převede čas bloku ve stenozáznamu ("14:32") na vteřinu ve streamu.
 * `streamStartedAt` je reálný čas startu záznamu (ISO 8601 nebo "HH:MM").
 * Vrací `null`, pokud vstupy nedávají smysl (např. blok začíná před startem streamu).
 */
export function offsetSyncSeconds(
  blockTimestamp: string,
  streamStartedAt: string
): number | null {
  const block = parseClockToSeconds(blockTimestamp);
  const start = parseClockToSeconds(streamStartedAt);
  if (block === null || start === null) return null;
  const delta = block - start;
  return delta >= 0 ? delta : null;
}

/** "14:32" | "14:32:05" | "2023-09-05T09:00:00" -> sekundy od půlnoci. */
export function parseClockToSeconds(value: string): number | null {
  if (!value) return null;
  const timePart = value.includes("T") ? value.split("T")[1] : value;
  const match = timePart.match(/^(\d{1,2}):(\d{2})(?::(\d{2}))?/);
  if (!match) return null;
  const [, h, m, s] = match;
  return Number(h) * 3600 + Number(m) * 60 + Number(s ?? 0);
}

/** 5284 -> "1:28:04" (nebo "12:31" pod hodinu). */
export function formatTimestamp(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds));
  const hours = Math.floor(s / 3600);
  const minutes = Math.floor((s % 3600) / 60);
  const seconds = s % 60;
  const mm = hours > 0 ? String(minutes).padStart(2, "0") : String(minutes);
  return hours > 0
    ? `${hours}:${mm}:${String(seconds).padStart(2, "0")}`
    : `${mm}:${String(seconds).padStart(2, "0")}`;
}

/**
 * Dopočet vteřiny konkrétní věty uvnitř vystoupení podle znakové pozice.
 * Používá se pouze tam, kde pipeline nedodala forced alignment.
 */
export function estimateClaimOffsetSeconds(charStart: number): number {
  return Math.round(Math.max(0, charStart) / CHARS_PER_SECOND);
}

/**
 * Sestaví `mediaEvidence` pro anotaci. Preferuje přesnou hodnotu z pipeline,
 * jinak ji odhadne z pozice ve `cleanText`. Vrací `null`, není-li video spárováno.
 */
export function resolveMediaEvidence(
  annotation: Annotation,
  media?: MediaRef
): MediaEvidence | null {
  if (annotation.mediaEvidence && annotation.mediaEvidence.archiveUrl) {
    return annotation.mediaEvidence;
  }
  if (!media?.pspCastId || !media.archiveUrl) return null;

  const exact = annotation.mediaEvidence?.exactTimestampSeconds;
  const isExact = typeof exact === "number" && media.alignment === "FORCED_ALIGNMENT";
  const seconds = isExact
    ? (exact as number)
    : media.speechStartSeconds + estimateClaimOffsetSeconds(annotation.start);

  return {
    exactTimestampSeconds: seconds,
    archiveUrl: media.archiveUrl,
    isExact,
  };
}

/** Doplní `archiveUrl`, pokud chybí, aby komponenty nemusely řešit dopočet. */
export function withArchiveUrl(media: MediaRef): MediaRef {
  if (!media.pspCastId || media.archiveUrl) return media;
  return {
    ...media,
    archiveUrl: buildArchiveUrl(media.pspCastId),
  };
}

/** Má vystoupení použitelný videozáznam? */
export function hasPairedVideo(message: Message): boolean {
  return Boolean(message.media?.pspCastId);
}
