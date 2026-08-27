/**
 * Registr oficiálních videozáznamů schůzí PSP ČR.
 *
 * Sněmovna nehostuje záznamy schůzí na YouTube — vlastní videoarchiv
 * (`videoarchiv.psp.cz`) je jediný ověřený zdroj. Data se sem NEPÍŠÍ ručně:
 * generuje je `pipeline/build_video_map.py` (přes `pipeline/psp/videoarchiv.py`)
 * do `src/data/psp/videoRecordings.json`, stejně jako `export_web.py`
 * generuje `dataset.json`. Přegenerování: `python pipeline/build_video_map.py`.
 *
 * Debata bez záznamu v `videoRecordings.json` zůstává v režimu `UNPAIRED` –
 * anomálie se zobrazují bez videa a bez smyšlených odkazů.
 */

import { MediaRef, Message } from "@/types/debate";
import { buildArchiveUrl, offsetSyncSeconds } from "@/lib/media";
import videoRecordings from "@/data/psp/videoRecordings.json";

export interface SessionRecording {
  /** ID "cast" (jednacího dne) ve videoarchivu PSP. */
  pspCastId: string;
  /** Čas startu streamu toho dne ve tvaru "HH:MM" nebo ISO 8601. */
  streamStartedAt: string;
  /** Popisek zdroje, zobrazuje se u přehrávače. */
  sourceLabel?: string;
}

/** debateId -> záznam jednacího dne. Generováno `pipeline/build_video_map.py`. */
export const SESSION_RECORDINGS: Record<string, SessionRecording> = videoRecordings;

const UNPAIRED: MediaRef = {
  pspCastId: null,
  speechStartSeconds: 0,
  alignment: "UNPAIRED",
};

/** Sestaví `MediaRef` pro jedno vystoupení podle času bloku ve stenozáznamu. */
export function resolveMessageMedia(
  debateId: string,
  message: Message
): MediaRef {
  if (message.media?.pspCastId) return message.media;

  const recording = SESSION_RECORDINGS[debateId];
  if (!recording) return message.media ?? UNPAIRED;

  const offset = offsetSyncSeconds(message.timestamp, recording.streamStartedAt);
  if (offset === null) return UNPAIRED;

  return {
    pspCastId: recording.pspCastId,
    speechStartSeconds: offset,
    alignment: "OFFSET_SYNC",
    streamStartedAt: recording.streamStartedAt,
    archiveUrl: buildArchiveUrl(recording.pspCastId),
  };
}
