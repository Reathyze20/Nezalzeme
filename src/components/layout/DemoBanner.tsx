import React from "react";
import { Info } from "lucide-react";
import { ANALYZA } from "@/lib/debate";

/**
 * Trvalé označení stavu dat.
 *
 * Data jsou skutečná — jména, kluby, citace i odkazy pocházejí ze
 * stenoprotokolů Poslanecké sněmovny. Chybí ale to podstatné: porovnání
 * výroků s minulostí a s hlasováním. Bez tohohle pruhu by čtenář prázdný
 * rejstřík přečetl jako „nic se nenašlo" místo „nic se ještě nehledalo".
 *
 * Až detekce naběhne, pruh zmizí sám (`ANALYZA.ceka`).
 */
export function DemoBanner() {
  if (!ANALYZA.ceka) return null;

  return (
    <div className="w-full sticky top-0 z-[60] bg-amber-100 dark:bg-amber-950/60 border-b border-amber-300/80 dark:border-amber-900 text-amber-900 dark:text-amber-200">
      <div className="max-w-6xl mx-auto px-6 py-2 flex items-start gap-2 text-[11px] sm:text-xs font-medium leading-relaxed">
        <Info className="w-4 h-4 shrink-0 mt-px" />
        <p>
          <span className="font-mono font-bold uppercase tracking-wider">Přepis bez analýzy.</span>{" "}
          Jména poslanců, kluby, citace i odkazy na stenoprotokoly jsou skutečné a pocházejí z otevřených dat
          Poslanecké sněmovny. Porovnání výroků s dřívějšími vyjádřeními a s hlasováním ale zatím neproběhlo, takže
          na webu není ani jedna značka —{" "}
          <strong className="font-semibold">nula značek tu neznamená nula rozporů.</strong> Zveřejněno je{" "}
          {ANALYZA.jednaciDny} jednacích dnů, ne celé volební období.
        </p>
      </div>
    </div>
  );
}
