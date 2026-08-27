import React from "react";
import Link from "next/link";
import { Clock, Calendar, ArrowRight, CheckCircle2, AlertTriangle, ExternalLink } from "lucide-react";
import { PoslanecZaznam } from "@/lib/poslanci";
import { formatDatum, getKategorieMeta } from "@/lib/ui";
import { cn } from "@/lib/utils";

interface CasovaOsaRozporuProps {
  zaznamy: PoslanecZaznam[];
  jmeno?: string;
  className?: string;
}

export function CasovaOsaRozporu({ zaznamy, jmeno, className }: CasovaOsaRozporuProps) {
  if (zaznamy.length === 0) return null;

  return (
    <div className={cn("bg-list border border-linka rounded-sm p-6 shadow-sm my-6", className)}>
      <div className="flex items-center gap-2 mb-3">
        <Clock className="w-4 h-4 text-overeno" />
        <h3 className="font-bold text-[16px] tracking-tight text-inkoust">
          Časová osa vývoje postojů {jmeno ? `(${jmeno})` : "v 6měsíčním horizontu"}
        </h3>
      </div>
      <p className="font-serif font-serif-text text-[14.5px] leading-[1.55] text-inkoust-2 mb-6 max-w-[68ch]">
        Politická tvrzení a jejich soulad s realitou se prověřují teprve s časovým odstupem — mezi prvním čtením,
        hlasováním o pozměňovacích návrzích a finálním schválením zákona. Níže je chronologický sled doložených událostí.
      </p>

      <div className="relative border-l-2 border-linka ml-3 pl-6 space-y-8">
        {zaznamy.map((z, idx) => {
          const kategorie = getKategorieMeta(z.kategorie);
          const jeNeutralni = z.jePosun || z.presentationTier === "CONTEXT_DEVELOPMENT";
          return (
            <div key={z.id || idx} className="relative group">
              {/* Timeline dot */}
              <div
                className={cn(
                  "absolute -left-[31px] top-1.5 w-4 h-4 rounded-full border-2 border-papir flex items-center justify-center",
                  jeNeutralni ? "bg-inkoust-3" : "bg-rozpor"
                )}
              />

              <div className="bg-papir border border-linka rounded-sm p-4.5 shadow-2xs hover:border-inkoust-3 transition-colors">
                <div className="flex items-center gap-2.5 flex-wrap mb-2">
                  <span
                    className={cn(
                      "font-mono text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-[2px]",
                      jeNeutralni ? "bg-linka-2 text-inkoust-2" : "bg-rozpor-tl text-rozpor"
                    )}
                  >
                    {z.presentationTier === "CONTEXT_DEVELOPMENT" ? "Kontext a vývoj stanoviska" : kategorie.label}
                  </span>
                  <span className="font-mono text-[11px] text-inkoust-3 flex items-center gap-1">
                    <Calendar className="w-3 h-3" />
                    {z.casZobrazeni}
                  </span>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-3">
                  {/* Minulost / Původní záznam */}
                  <div className="bg-list/60 border border-linka-2 rounded-xs p-3">
                    <div className="font-mono text-[9.5px] uppercase tracking-wider text-inkoust-3 font-semibold mb-1">
                      1. Původní výrok / záznam ({formatDatum(z.zaznamDatum)})
                    </div>
                    <p className="font-serif font-serif-text text-[13.5px] leading-[1.45] text-inkoust-2 italic">
                      „{z.zaznamText}“
                    </p>
                    <div className="mt-2 font-mono text-[10.5px] text-inkoust-3">
                      {z.zaznamKontext}
                    </div>
                  </div>

                  {/* Současnost / Pozdější výrok */}
                  <div className="bg-list/60 border border-linka-2 rounded-xs p-3">
                    <div className="font-mono text-[9.5px] uppercase tracking-wider text-inkoust-3 font-semibold mb-1">
                      2. Následné vyjádření v rozpravě
                    </div>
                    <p className="font-serif font-serif-text text-[13.5px] leading-[1.45] text-inkoust">
                      „{z.recenoText.slice(z.recenoStart, z.recenoEnd)}“
                    </p>
                    <div className="mt-2 font-mono text-[10.5px] text-inkoust-3">
                      {z.debateTitle}
                    </div>
                  </div>
                </div>

                <p className="font-serif font-serif-text text-[13.5px] leading-[1.5] text-inkoust-2 mt-3 pt-2.5 border-t border-linka-2">
                  {z.vysvetleni}
                </p>

                <div className="mt-3 flex items-center justify-between flex-wrap gap-2 pt-1">
                  <a
                    href={z.zaznamUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 font-mono text-[10.5px] text-overeno hover:underline"
                  >
                    Ověřit v originálním stenozáznamu PSP ČR
                    <ExternalLink className="w-2.5 h-2.5" />
                  </a>
                  <Link
                    href={`/rozprava/${z.debateId}#${z.messageId}`}
                    className="font-mono text-[10.5px] text-inkoust-2 hover:text-inkoust"
                  >
                    Přejít do kontextu rozpravy →
                  </Link>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
