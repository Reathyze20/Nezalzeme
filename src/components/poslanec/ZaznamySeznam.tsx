"use client";

import React, { useMemo, useState } from "react";
import { PoslanecZaznam } from "@/lib/poslanci";
import { AnomalyType } from "@/types/debate";
import { getKategorieMeta } from "@/lib/ui";
import { DvojiceZaznamu } from "@/components/zaznam/DvojiceZaznamu";
import { KontextAVyvoj } from "@/components/zaznam/KontextAVyvoj";
import { cn } from "@/lib/utils";

const KATEGORIE: AnomalyType[] = ["CONTRADICTION_TIME", "VOTE_MISMATCH", "FACTUAL_MISSTATEMENT", "VALUE_SHIFT"];

interface ZaznamySeznamProps {
  zaznamy: PoslanecZaznam[];
  jmeno: string;
  /** True, dokud nad vystoupeními neproběhla detekce. */
  analyzaCeka?: boolean;
}

export function ZaznamySeznam({ zaznamy, jmeno, analyzaCeka }: ZaznamySeznamProps) {
  const [filtr, setFiltr] = useState<"vse" | AnomalyType>("vse");

  const pocty = useMemo(() => {
    const p: Record<string, number> = { vse: zaznamy.length };
    for (const k of KATEGORIE) p[k] = zaznamy.filter((z) => z.kategorie === k).length;
    return p;
  }, [zaznamy]);

  const zobrazene = filtr === "vse" ? zaznamy : zaznamy.filter((z) => z.kategorie === filtr);

  if (zaznamy.length === 0) {
    const prijmeni = jmeno.split(" ").slice(1).join(" ") || jmeno;
    // "Nenašli jsme" tvrdí, že hledání proběhlo. Dokud neproběhlo, je to
    // nepodložená očista — zrcadlově stejná chyba jako nepodložené obvinění.
    return (
      <p className="font-serif font-serif-text text-[16px] leading-[1.6] text-inkoust-2 py-8 max-w-[64ch]">
        {analyzaCeka
          ? `U ${prijmeni} zatím neuvádíme žádnou značku — porovnání jeho vystoupení s dřívějšími výroky a s hlasováním ještě neproběhlo. Není to zjištění, že rozpor není; je to stav, že jsme se ještě nedívali.`
          : `U zkontrolovaných vystoupení jsme u ${prijmeni} nenašli rozpor se záznamem. Kontrolujeme dál.`}
      </p>
    );
  }

  return (
    <div>
      <div className="flex flex-wrap gap-1.5 pt-6 pb-1">
        <button
          type="button"
          aria-pressed={filtr === "vse"}
          onClick={() => setFiltr("vse")}
          className={cn(
            "font-sans text-[12.5px] font-semibold px-3 py-1.5 border rounded-sm transition-colors",
            filtr === "vse" ? "text-overeno border-overeno bg-overeno-tl" : "text-inkoust-2 border-linka hover:text-inkoust hover:border-inkoust-3"
          )}
        >
          Vše ({pocty.vse})
        </button>
        {KATEGORIE.filter((k) => pocty[k] > 0).map((k) => (
          <button
            key={k}
            type="button"
            aria-pressed={filtr === k}
            onClick={() => setFiltr(k)}
            className={cn(
              "font-sans text-[12.5px] font-semibold px-3 py-1.5 border rounded-sm transition-colors",
              filtr === k ? "text-overeno border-overeno bg-overeno-tl" : "text-inkoust-2 border-linka hover:text-inkoust hover:border-inkoust-3"
            )}
          >
            {getKategorieMeta(k).label} ({pocty[k]})
          </button>
        ))}
      </div>

      {zobrazene.length === 0 ? (
        <p className="font-serif font-serif-text text-[16px] text-inkoust-2 py-8">V tomto výběru nic není. Zkuste jinou značku.</p>
      ) : (
        zobrazene.map((z) =>
          z.presentationTier === "CONTEXT_DEVELOPMENT" ? (
            <KontextAVyvoj key={z.id} zaznam={z} />
          ) : (
            <DvojiceZaznamu key={z.id} zaznam={z} />
          )
        )
      )}
    </div>
  );
}
