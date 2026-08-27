import React from "react";
import Link from "next/link";
import { ExternalLink } from "lucide-react";
import { Message } from "@/types/debate";
import { getKategorieMeta, getZavaznostLabel, formatJistota, formatDatum, hostname, politicianSlug } from "@/lib/ui";
import { AnnotatedQuote } from "@/components/zaznam/AnnotatedQuote";
import { KopirovatOdkaz } from "@/components/zaznam/AkceZaznamu";
import { VideoEvidence } from "@/components/media/VideoEvidence";
import { resolveMediaEvidence } from "@/lib/media";
import { cn } from "@/lib/utils";

interface ReplikaProps {
  message: Message;
  sessionNumber: number;
}

/**
 * Jedna bublina v rozpravě. Sporné úseky mají inline rozbalitelný záznam
 * přímo v místě, kde slova padla — bez skoku jinam.
 */
export function Replika({ message, sessionNumber }: ReplikaProps) {
  const slug = politicianSlug(message.speaker);

  return (
    /* content-visibility: rozprava má i dvě stě vystoupení a některá jsou
       na několik obrazovek. Prohlížeč tak rozloží jen to, co je vidět. */
    <div
      id={message.messageId}
      className="grid grid-cols-1 md:grid-cols-[128px_1fr] gap-3 md:gap-5 py-5 scroll-mt-20 [content-visibility:auto] [contain-intrinsic-size:auto_200px]"
    >
      <div className="text-left md:text-right pt-0.5 flex md:flex-col items-baseline md:items-end gap-2 md:gap-0">
        <Link href={`/poslanec/${slug}`} className="text-[14px] font-semibold hover:text-overeno transition-colors">
          {message.speaker}
        </Link>
        {message.party && (
          <span className="font-mono text-[10.5px] text-inkoust-3">{message.party}</span>
        )}
        <span className="font-mono text-[10.5px] text-inkoust-3 tabular-nums md:mt-1.5">
          {sessionNumber}. schůze · {message.timestamp}
        </span>
      </div>

      <div className="flex flex-col gap-3">
        {message.annotations.length > 0 ? (
          <div className="bg-list border border-linka border-l-2 border-l-rozpor rounded-sm px-5 py-4 flex flex-col gap-3">
            <AnnotatedText message={message} />
            {message.annotations.map((ann) => (
              <ZaznamInline key={ann.id ?? `${message.messageId}-${ann.start}`} message={message} annotation={ann} />
            ))}
          </div>
        ) : (
          <div className="bg-list border border-linka border-l-2 border-l-inkoust-3 rounded-sm px-5 py-4 flex flex-col gap-3">
            <p className="font-serif font-serif-text text-[17px] leading-[1.55] whitespace-pre-line">
              {message.cleanText}
            </p>
            <div className="flex items-center gap-3 flex-wrap">
              {/* "Bez námitky" by tvrdilo, že vystoupení prošlo kontrolou. Dokud
                  detekce neproběhla, je jediné doložitelné tvrzení odkaz na
                  místo v oficiálním záznamu. */}
              <span className="font-mono text-[10.5px] text-inkoust-3">
                {message.analyzedAt ? "bez námitky" : "zatím neanalyzováno"}
              </span>
              {message.source?.stenoUrl && (
                <a
                  href={message.source.stenoUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 font-mono text-[10.5px] text-overeno border-b border-overeno/10 hover:border-overeno pb-0.5 transition-colors"
                >
                  stenozáznam
                  <ExternalLink className="w-2.5 h-2.5" />
                </a>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function AnnotatedText({ message }: { message: Message }) {
  if (message.annotations.length === 1) {
    const ann = message.annotations[0];
    const jeNeutralni = ann.type === "VALUE_SHIFT" || ann.presentationTier === "CONTEXT_DEVELOPMENT";
    return <AnnotatedQuote text={message.cleanText} start={ann.start} end={ann.end} jePosun={jeNeutralni} />;
  }
  // Víc anotací v jednom vystoupení: bez zvýraznění v textu, značky jsou níž jednotlivě.
  return (
    <p className="font-serif font-serif-text text-[17px] leading-[1.55] whitespace-pre-line">
      „{message.cleanText}“
    </p>
  );
}

function ZaznamInline({
  message,
  annotation,
}: {
  message: Message;
  annotation: Message["annotations"][number];
}) {
  const kategorie = getKategorieMeta(annotation.type);
  const zdroj = hostname(annotation.proof.sourceUrl);
  const kotva = annotation.id ?? `${message.messageId}-${annotation.start}`;
  const jeKontext = annotation.presentationTier === "CONTEXT_DEVELOPMENT";
  const jePosun = annotation.type === "VALUE_SHIFT" || jeKontext;
  const video = resolveMediaEvidence(annotation, message.media);

  return (
    <details className="group border-t border-linka-2 pt-3">
      <summary className="cursor-pointer list-none flex items-center gap-2 flex-wrap">
        <span
          className={cn(
            "font-mono text-[10.5px] font-bold uppercase tracking-wider px-2 py-1 rounded-[2px]",
            jePosun ? "bg-linka-2 text-inkoust-2" : "bg-rozpor-tl text-rozpor"
          )}
        >
          {jeKontext ? "Kontext a vývoj stanoviska" : kategorie.label}
        </span>
        <span className="font-mono text-[11px] text-inkoust-3">{getZavaznostLabel(annotation.severity)}</span>
        <span className="font-mono text-[11px] text-inkoust-3">{formatJistota(annotation.confidenceScore)}</span>
        <span className="ml-auto font-mono text-[10.5px] text-overeno group-open:hidden">zobrazit záznam</span>
        <span className="ml-auto font-mono text-[10.5px] text-overeno hidden group-open:inline">skrýt záznam</span>
      </summary>

      <div className="mt-3 grid grid-cols-1 md:grid-cols-[30px_1fr] gap-3 items-start">
        <div className="hidden md:flex justify-center pt-1">
          <span className={cn("font-mono text-[13px] font-bold", jePosun ? "text-inkoust-2" : "text-rozpor")}>
            {jePosun ? "→" : "≠"}
          </span>
        </div>
        <div className="bg-papir border border-linka rounded-sm p-4 flex flex-col gap-2.5">
          <span className="font-mono text-[10px] font-bold uppercase tracking-[0.13em] text-inkoust-3">Záznam</span>
          <p className="font-serif font-serif-text text-[15.5px] leading-[1.55]">{annotation.proof.pastQuote}</p>
          <a
            href={annotation.proof.sourceUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 self-start font-mono text-[11px] text-overeno border-b border-overeno/10 hover:border-overeno pb-0.5 transition-colors"
          >
            {zdroj} · {annotation.proof.pastContext} · {formatDatum(annotation.proof.pastDate)}
            <ExternalLink className="w-2.5 h-2.5" />
          </a>
          <p className="font-serif font-serif-text text-[14px] leading-[1.5] text-inkoust-2 pt-1">
            {annotation.explanation}
          </p>
          <div className="max-w-md pt-1">
            <VideoEvidence evidence={video} label="Aktuální výrok" />
          </div>
          <div className="flex gap-1.5 pt-1">
            <KopirovatOdkaz kotva={kotva} />
            <Link
              href="/metodika#namitka"
              className="inline-flex items-center font-mono text-[10.5px] tracking-wide px-2.5 py-1.5 border border-linka rounded-sm text-inkoust-2 hover:text-inkoust hover:border-inkoust-3 transition-colors"
            >
              Namítnout
            </Link>
          </div>
        </div>
      </div>
    </details>
  );
}
