import React from "react";
import { MediaEvidence } from "@/types/debate";
import { formatTimestamp } from "@/lib/media";
import { Video, VideoOff, ExternalLink, Clock3 } from "lucide-react";

interface VideoEvidenceProps {
  evidence: MediaEvidence | null;
  /** Popisek nad kartou, např. "Aktuální výrok" / "Historický výrok". */
  label: string;
  /** Odkaz na stenoprotokol, použije se v nespárovaném stavu. */
  fallbackUrl?: string;
}

/**
 * FÁZE 6 – odkaz na oficiální videozáznam PSP ČR.
 *
 * PSP ČR hostuje záznamy schůzí na vlastní infrastruktuře
 * (`videoarchiv.psp.cz`), ne na YouTube, a jejich přehrávač neumí přes URL
 * seekovat na přesnou vteřinu. Karta proto neembeduje přehrávač na stránku
 * — jen odkazuje na oficiální stránku přehrávače a řekne, na jaký čas má
 * čtenář v přehrávači doskočit ručně.
 */
export function VideoEvidence({ evidence, label, fallbackUrl }: VideoEvidenceProps) {
  if (!evidence) {
    return (
      <div className="p-4 rounded-sm border border-dashed border-linka bg-list/60 font-sans">
        <div className="flex items-center gap-2 text-xs font-semibold text-inkoust-3">
          <VideoOff className="w-4 h-4" />
          <span>Videozáznam k tomuto úseku není spárován</span>
        </div>
        <p className="text-[11px] text-inkoust-3 mt-1.5 leading-relaxed">
          Oficiální záznam této schůze zatím není spárován. Důkazem zůstává
          stenoprotokol a záznam o hlasování.
        </p>
        {fallbackUrl && (
          <a
            href={fallbackUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-2.5 inline-flex items-center gap-1.5 text-[11px] font-semibold text-overeno hover:underline"
          >
            <span>Otevřít zdroj</span>
            <ExternalLink className="w-3 h-3" />
          </a>
        )}
      </div>
    );
  }

  const timeLabel = formatTimestamp(evidence.exactTimestampSeconds);

  return (
    <div className="rounded-sm border border-linka bg-neutral-900 overflow-hidden shadow-sm font-sans">
      <div className="flex items-center justify-between px-3 py-2 bg-neutral-950/80 border-b border-neutral-800">
        <span className="flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-wider text-neutral-300">
          <Video className="w-3.5 h-3.5 text-rozpor" />
          {label}
        </span>
        <span className="flex items-center gap-1.5 text-[11px] font-mono text-neutral-400">
          <Clock3 className="w-3.5 h-3.5" />
          {timeLabel}
          <span
            className={`ml-1 px-1.5 py-0.5 rounded text-[9px] font-sans font-bold uppercase tracking-wide ${
              evidence.isExact
                ? "bg-emerald-500/15 text-emerald-300 border border-emerald-500/30"
                : "bg-amber-500/15 text-amber-300 border border-amber-500/30"
            }`}
            title={
              evidence.isExact
                ? "Čas určen forced alignmentem přepisu a zvukové stopy."
                : "Čas dopočten z tempa řeči a startu streamu – může se lišit o jednotky sekund."
            }
          >
            {evidence.isExact ? "přesný čas" : "orientační čas"}
          </span>
        </span>
      </div>

      <a
        href={evidence.archiveUrl}
        target="_blank"
        rel="noopener noreferrer"
        className="flex flex-col items-center justify-center gap-2 py-8 text-neutral-300 hover:text-white transition-colors group"
      >
        <Video className="w-10 h-10 text-rozpor group-hover:scale-110 transition-transform" />
        <span className="text-xs font-semibold">Otevřít videoarchiv PSP ČR</span>
        <span className="text-[10px] text-neutral-500 px-4 text-center leading-relaxed">
          Přehrávač se neumí odkázat přímo na vteřinu — po otevření doskočte na čas {timeLabel}.
        </span>
      </a>

      <div className="px-3 py-2 bg-neutral-950/80 border-t border-neutral-800 flex items-center justify-end">
        <a
          href={evidence.archiveUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1.5 text-[11px] font-semibold text-neutral-300 hover:text-white"
        >
          <span>Otevřít na videoarchiv.psp.cz (čas {timeLabel})</span>
          <ExternalLink className="w-3 h-3" />
        </a>
      </div>
    </div>
  );
}
