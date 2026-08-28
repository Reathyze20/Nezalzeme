"use client";

import React, { useState, useEffect } from "react";
import { MediaEvidence } from "@/types/debate";
import { formatTimestamp } from "@/lib/media";
import { Play, Pause, ExternalLink, Check, Copy, Volume2, Sparkles, Clock } from "lucide-react";

interface VideoRozporPlayerProps {
  evidence: MediaEvidence | null;
  snippetText: string;
  speakerName?: string;
  label?: string;
}

/**
 * Interaktivní přehrávač audiovizuálního důkazu (WhisperX & Forced Alignment).
 * Umožňuje občanovi přehrát časovaný výsek výroku a otevřít originální videoarchiv PSP ČR.
 */
export function VideoRozporPlayer({
  evidence,
  snippetText,
  speakerName,
  label = "Autentický záznam vystoupení",
}: VideoRozporPlayerProps) {
  const [isPlaying, setIsPlaying] = useState(false);
  const [progress, setProgress] = useState(0);
  const [copied, setCopied] = useState(false);

  const duration = evidence?.durationSeconds || 12;
  const timeLabel = evidence ? formatTimestamp(evidence.exactTimestampSeconds) : "00:00";

  // Simulace přehrávání časovaného výseku
  useEffect(() => {
    let interval: NodeJS.Timeout;
    if (isPlaying) {
      interval = setInterval(() => {
        setProgress((prev) => {
          if (prev >= 100) {
            setIsPlaying(false);
            return 0;
          }
          return prev + 100 / (duration * 10);
        });
      }, 100);
    }
    return () => clearInterval(interval);
  }, [isPlaying, duration]);

  const handleCopyLink = () => {
    if (evidence?.archiveUrl) {
      navigator.clipboard.writeText(`${evidence.archiveUrl}#t=${evidence.exactTimestampSeconds}`);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  if (!evidence) {
    return (
      <div className="p-3.5 rounded bg-podklad-2 border border-dashed border-inkoust/20 text-inkoust-3 font-mono text-[12px]">
        Zvukový záznam pro tento konkrétní výrok se právě zpracovává.
      </div>
    );
  }

  return (
    <div className="rounded-md border border-neutral-800 bg-neutral-950/90 text-neutral-100 overflow-hidden shadow-md my-3">
      {/* Horní lišta: čas a stav zarovnání */}
      <div className="flex items-center justify-between px-3.5 py-2 bg-neutral-900 border-b border-neutral-800 text-[11px] font-mono">
        <div className="flex items-center gap-2">
          <Volume2 className="w-3.5 h-3.5 text-rozpor" />
          <span className="font-semibold text-neutral-200 uppercase tracking-wider text-[10px]">
            {label}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span className="flex items-center gap-1 text-neutral-400">
            <Clock className="w-3 h-3" />
            {timeLabel}
          </span>
          <span
            className={`px-1.5 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider ${
              evidence.isExact
                ? "bg-emerald-950 text-emerald-300 border border-emerald-700/50"
                : "bg-amber-950 text-amber-300 border border-amber-700/50"
            }`}
          >
            {evidence.isExact ? "WhisperX Přesný čas" : "Orientační čas"}
          </span>
        </div>
      </div>

      {/* Tělo: Citovaný výsek */}
      <div className="p-4 bg-neutral-950">
        <div className="relative">
          <p className="font-serif text-[14.5px] leading-relaxed text-neutral-200 italic pl-3 border-l-2 border-rozpor/70">
            „{snippetText}“
          </p>
          {speakerName && (
            <p className="text-[11px] font-mono text-neutral-400 mt-2 pl-3">
              — {speakerName}
            </p>
          )}
        </div>

        {/* Lišta přehrávání */}
        <div className="mt-4 pt-3 border-t border-neutral-800/80 flex items-center gap-3">
          <button
            type="button"
            onClick={() => setIsPlaying(!isPlaying)}
            className="flex items-center justify-center w-8 h-8 rounded-full bg-rozpor hover:bg-rose-700 text-white transition-colors"
            title={isPlaying ? "Pozastavit náhled" : "Přehrát autentický výsek"}
          >
            {isPlaying ? <Pause className="w-4 h-4" /> : <Play className="w-4 h-4 ml-0.5" />}
          </button>

          {/* Progress bar */}
          <div className="flex-1">
            <div className="h-1.5 bg-neutral-800 rounded-full overflow-hidden">
              <div
                className="h-full bg-rozpor transition-all duration-100 ease-linear"
                style={{ width: `${progress}%` }}
              />
            </div>
            <div className="flex justify-between text-[10px] font-mono text-neutral-400 mt-1">
              <span>{isPlaying ? `${Math.round((progress / 100) * duration)} s` : "0 s"}</span>
              <span>{duration} s</span>
            </div>
          </div>

          {/* Akční tlačítka */}
          <div className="flex items-center gap-1.5">
            <button
              type="button"
              onClick={handleCopyLink}
              className="p-1.5 rounded hover:bg-neutral-800 text-neutral-400 hover:text-neutral-200 transition-colors"
              title="Zkopírovat odkaz na čas"
            >
              {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
            </button>
            <a
              href={evidence.archiveUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 px-2.5 py-1 rounded bg-neutral-800 hover:bg-neutral-700 text-neutral-200 text-[11px] font-mono transition-colors"
              title="Otevřít oficiální videoarchiv PSP ČR v novém okně"
            >
              <span>Videoarchiv PSP</span>
              <ExternalLink className="w-3 h-3 text-neutral-400" />
            </a>
          </div>
        </div>
      </div>
    </div>
  );
}
