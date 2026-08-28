import React from "react";
import Link from "next/link";
import { ExternalLink } from "lucide-react";
import { PoslanecZaznam } from "@/lib/poslanci";
import { getKategorieMeta, getZavaznostLabel, getConfidenceInterval, formatDatum, hostname } from "@/lib/ui";
import { AnnotatedQuote } from "./AnnotatedQuote";
import { KopirovatOdkaz } from "./AkceZaznamu";
import { VideoEvidence } from "@/components/media/VideoEvidence";
import { cn } from "@/lib/utils";

interface DvojiceZaznamuProps {
  zaznam: PoslanecZaznam;
}

/**
 * ŘEČENO / ZÁZNAM — jádro celého webu. Dvě karty vedle sebe, jeden pohled,
 * žádný postranní panel. Čtenář vidí obě strany a udělá si závěr sám.
 */
export function DvojiceZaznamu({ zaznam }: DvojiceZaznamuProps) {
  const kategorie = getKategorieMeta(zaznam.kategorie);
  const interval = getConfidenceInterval(zaznam.confidenceScore);
  const glyf = zaznam.jePosun ? "→" : "≠";
  const zdroj = hostname(zaznam.zaznamUrl);

  return (
    <article id={zaznam.id} className="py-8 border-b border-linka-2 scroll-mt-20">
      <div className="flex items-baseline gap-2.5 flex-wrap mb-4">
        <span
          className={cn(
            "font-mono text-[10.5px] font-bold uppercase tracking-wider px-2 py-1 rounded-[2px]",
            zaznam.jePosun ? "bg-linka-2 text-inkoust-2" : "bg-rozpor-tl text-rozpor"
          )}
        >
          {kategorie.label}
        </span>
        <span
          className={cn(
            "inline-flex items-center gap-1 font-mono text-[10.5px] font-semibold px-2 py-0.5 rounded-[2px] border",
            interval.badgeClass
          )}
          title={`Vážené skóre důkazů: ${interval.pct} %`}
        >
          <span>{interval.icon}</span>
          <span>{interval.label} ({interval.pct} %)</span>
        </span>
        {zaznam.debateTisk && zaznam.debateTisk.cisloTisku && (
          <a
            href={zaznam.debateTisk.url || undefined}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 font-mono text-[10.5px] px-2 py-0.5 rounded-[2px] bg-sky-50 text-sky-800 border border-sky-200 dark:bg-sky-950/40 dark:text-sky-300 dark:border-sky-800/60 hover:underline"
            title={zaznam.debateTisk.nazev || "Sněmovní tisk"}
          >
            <span>Tisk {zaznam.debateTisk.cisloTisku}</span>
            <span className="text-sky-400">·</span>
            <span>{zaznam.debateTisk.faze}</span>
          </a>
        )}
        {zaznam.votingBallotId && (
          <a
            href={
              zaznam.votingBallotId.match(/\d+/)?.[0]
                ? `https://www.psp.cz/sqw/hlasy.sqw?g=${zaznam.votingBallotId.match(/\d+/)?.[0]}`
                : undefined
            }
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 font-mono text-[10.5px] px-2 py-0.5 rounded-[2px] bg-amber-50 text-amber-900 border border-amber-300 dark:bg-amber-950/40 dark:text-amber-300 dark:border-amber-700/60 hover:underline font-medium"
            title="Ověřit jmenovité hlasování v hlasovací knize PSP ČR"
          >
            <span>🗳️ {zaznam.votingBallotId}</span>
            {zaznam.voteRecorded && (
              <>
                <span className="text-amber-400">·</span>
                <span>Hlas: <strong>{zaznam.voteRecorded}</strong></span>
              </>
            )}
          </a>
        )}
        <span className="font-mono text-[11px] text-inkoust-3">{getZavaznostLabel(zaznam.severity)}</span>
        <span className="font-mono text-[11.5px] text-inkoust-3 ml-auto">{zaznam.casZobrazeni}</span>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-[1fr_58px_1fr] items-stretch">
        <div className="bg-list border border-linka rounded-sm p-5 flex flex-col gap-3 shadow-sm">
          <span className="font-mono text-[10px] font-bold uppercase tracking-[0.13em] text-inkoust-3">Řečeno</span>
          <AnnotatedQuote text={zaznam.recenoText} start={zaznam.recenoStart} end={zaznam.recenoEnd} jePosun={zaznam.jePosun} className="flex-1" />
          <Link
            href={`/rozprava/${zaznam.debateId}#${zaznam.messageId}`}
            className="inline-flex items-center gap-1.5 self-start font-mono text-[11px] text-overeno border-b border-overeno/10 hover:border-overeno pb-0.5 transition-colors"
          >
            {zaznam.debateTitle} · zobrazit v rozpravě
          </Link>
        </div>

        <div className="relative flex items-center justify-center py-2 md:py-0">
          <span className="hidden md:block absolute top-6 bottom-6 w-px bg-linka" />
          <span className="md:hidden absolute left-1/2 -translate-x-1/2 top-0 bottom-0 w-px bg-linka" />
          <span
            className={cn(
              "relative z-10 w-[30px] h-[30px] rounded-full border border-linka bg-papir flex items-center justify-center font-mono text-[13px] font-bold",
              zaznam.jePosun ? "text-inkoust-2" : "text-rozpor"
            )}
          >
            {glyf}
          </span>
        </div>

        <div
          className={cn(
            "bg-list border border-linka rounded-sm p-5 flex flex-col gap-3 shadow-sm border-t-[3px] md:border-t md:border-l-[3px]",
            zaznam.jePosun ? "md:border-l-inkoust-3 border-t-inkoust-3" : "md:border-l-rozpor border-t-rozpor"
          )}
        >
          <span className="font-mono text-[10px] font-bold uppercase tracking-[0.13em] text-inkoust-3">Záznam</span>
          <p className="font-serif font-serif-text text-[17px] leading-[1.55] flex-1">{zaznam.zaznamText}</p>
          <a
            href={zaznam.zaznamUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 self-start font-mono text-[11px] text-overeno border-b border-overeno/10 hover:border-overeno pb-0.5 transition-colors"
          >
            {zdroj} · {zaznam.zaznamKontext} · {formatDatum(zaznam.zaznamDatum)}
            <ExternalLink className="w-2.5 h-2.5" />
          </a>
        </div>
      </div>

      <div className="mt-5 max-w-md">
        <VideoEvidence evidence={zaznam.media} label="Aktuální výrok" />
      </div>

      <div className="mt-5 flex flex-col md:flex-row gap-4 md:items-start">
        <p className="font-serif font-serif-text text-[15px] leading-[1.55] text-inkoust-2 flex-1 max-w-[68ch]">
          {zaznam.vysvetleni}
          {zaznam.downgradedFrom && (
            <span className="block mt-1.5 text-inkoust-3">
              Původně detekováno jako {getKategorieMeta(zaznam.downgradedFrom).label.toLowerCase()}; po oponentním přezkumu zmírněno, protože obhajoba obstála.
            </span>
          )}
        </p>
        <div className="flex gap-1.5 flex-wrap shrink-0">
          <KopirovatOdkaz kotva={zaznam.id} />
          <Link
            href="/metodika#namitka"
            className="inline-flex items-center font-mono text-[10.5px] tracking-wide px-2.5 py-1.5 border border-linka rounded-sm text-inkoust-2 hover:text-inkoust hover:border-inkoust-3 transition-colors"
          >
            Namítnout
          </Link>
        </div>
      </div>

      {zaznam.defenseEvaluated && (
        <div className="mt-4 p-3.5 bg-list border border-linka-2 rounded-sm">
          <div className="flex items-center gap-1.5 font-mono text-[10.5px] font-bold uppercase tracking-[0.1em] text-inkoust-3 mb-1">
            <span>⚖️</span>
            <span>Oponentní posouzení obhajoby</span>
          </div>
          <p className="font-serif font-serif-text text-[14px] leading-[1.55] text-inkoust-2 italic">
            {zaznam.defenseEvaluated}
          </p>
        </div>
      )}

      {zaznam.defensesConsidered && zaznam.defensesConsidered.length > 0 && (
        <details className="mt-3 group">
          <summary className="cursor-pointer font-mono text-[11px] text-inkoust-2 hover:text-inkoust list-none flex items-center gap-1.5">
            <span className="inline-block transition-transform group-open:rotate-90">›</span>
            Zvažované alternativní výklady ({zaznam.defensesConsidered.length})
          </summary>
          <div className="mt-3 pl-4 border-l border-linka-2 space-y-2">
            <ul className="space-y-1.5">
              {zaznam.defensesConsidered.map((obhajoba, i) => (
                <li key={i} className="font-serif font-serif-text text-[14px] leading-[1.5] text-inkoust-2">
                  — {obhajoba}
                </li>
              ))}
            </ul>
            {zaznam.arbiterRationale && (
              <p className="font-serif font-serif-text text-[14px] leading-[1.5] text-inkoust-2 pt-1">
                <span className="font-mono text-[10px] font-bold uppercase tracking-[0.13em] text-inkoust-3 mr-1.5">
                  Rozhodnutí:
                </span>
                {zaznam.arbiterRationale}
              </p>
            )}
          </div>
        </details>
      )}
    </article>
  );
}
