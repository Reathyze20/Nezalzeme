"use client";

import React, { useState, useMemo, useEffect } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { ChevronRight } from "lucide-react";
import { PoslanecSouhrn } from "@/lib/poslanci";
import { PasmoZaznamu } from "@/components/zaznam/PasmoZaznamu";
import { cn } from "@/lib/utils";

type Razeni = "abeceda" | "podil" | "overeno";

const RAZENI: { klic: Razeni; nazev: string }[] = [
  { klic: "abeceda", nazev: "Abecedně" },
  { klic: "podil", nazev: "Podíl rozporů" },
  { klic: "overeno", nazev: "Počet vystoupení" },
];

function prijmeniZ(jmeno: string): string {
  const casti = jmeno.trim().split(/\s+/);
  return casti.length > 1 ? casti.slice(1).join(" ") : jmeno;
}

interface RejstrikTabulkaProps {
  poslanci: PoslanecSouhrn[];
  /** True, dokud nad vystoupeními neproběhla detekce. */
  analyzaCeka?: boolean;
}

export function RejstrikTabulka({ poslanci, analyzaCeka }: RejstrikTabulkaProps) {
  const searchParams = useSearchParams();
  const [radit, setRadit] = useState<Razeni>("abeceda");
  // Řadit podle podílu rozporů jde až tehdy, když nějaké rozpory známe.
  // Prázdné tlačítko by tvrdilo, že žebříček existuje.
  const razeni = analyzaCeka ? RAZENI.filter((r) => r.klic !== "podil") : RAZENI;
  const [dotaz, setDotaz] = useState("");

  useEffect(() => {
    const q = searchParams.get("q");
    if (q) setDotaz(q);
  }, [searchParams]);

  const zobrazeni = useMemo(() => {
    const d = dotaz.trim().toLocaleLowerCase("cs");
    let sez = poslanci.filter((p) =>
      d ? `${p.jmeno} ${p.klub} ${p.role}`.toLocaleLowerCase("cs").includes(d) : true
    );
    if (radit === "abeceda") {
      sez = [...sez].sort((a, b) => prijmeniZ(a.jmeno).localeCompare(prijmeniZ(b.jmeno), "cs"));
    } else if (radit === "podil") {
      sez = [...sez].sort((a, b) => b.rozpor / Math.max(1, b.overeno) - a.rozpor / Math.max(1, a.overeno));
    } else {
      sez = [...sez].sort((a, b) => b.vystoupeni - a.vystoupeni);
    }
    return sez;
  }, [poslanci, dotaz, radit]);

  return (
    <div>
      <div className="flex items-end justify-between gap-5 flex-wrap pb-3.5">
        <div>
          <h2 className="text-[21px] font-bold tracking-[-0.018em]">Rejstřík poslanců</h2>
          <p className="font-serif font-serif-text text-[13px] text-inkoust-2 mt-1 max-w-[54ch]">
            Řadíme abecedně a měříme všechny kluby stejným pravidlem. Pořadí neurčuje redakce — přeřaďte si ho sami.
          </p>
        </div>
        <div className="flex items-center gap-3 flex-wrap">
          <input
            type="search"
            placeholder="Hledat poslance, klub..."
            value={dotaz}
            onChange={(e) => setDotaz(e.target.value)}
            className="w-full sm:w-56 px-3 py-1.5 text-[12.5px] bg-papir border border-linka rounded-sm placeholder:text-inkoust-3 focus:outline-none focus:border-overeno transition-colors"
          />
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="font-mono text-[10.5px] uppercase tracking-wider text-inkoust-3 mr-0.5">Řadit</span>
            {razeni.map((r) => (
              <button
                key={r.klic}
                type="button"
                aria-pressed={radit === r.klic}
                onClick={() => setRadit(r.klic)}
                className={cn(
                  "font-sans text-[12.5px] font-semibold px-3 py-1.5 border rounded-sm transition-colors",
                  radit === r.klic
                    ? "text-overeno border-overeno bg-overeno-tl"
                    : "text-inkoust-2 border-linka hover:text-inkoust hover:border-inkoust-3"
                )}
              >
                {r.nazev}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="border-t border-inkoust">
        <div
          className="hidden md:grid gap-4 items-center px-3.5 py-2.5 border-b border-linka font-mono text-[10px] uppercase tracking-wider text-inkoust-3"
          style={{ gridTemplateColumns: MRIZKA_DESKTOP }}
        >
          <span>Poslanec</span>
          <span>Klub</span>
          <span>Vystoupení v přepisu</span>
          <span className="text-right">{analyzaCeka ? "Značky" : "Rozpory / zkontrolováno"}</span>
          <span />
        </div>

        {zobrazeni.length === 0 ? (
          <p className="font-serif font-serif-text text-[16px] text-inkoust-2 py-10 px-3.5">
            Nikoho takového v rejstříku nemáme. Zkuste jen příjmení.
          </p>
        ) : (
          zobrazeni.map((p) => <RadekPoslance key={p.id} p={p} analyzaCeka={analyzaCeka} />)
        )}
      </div>
    </div>
  );
}

const MRIZKA_DESKTOP = "minmax(180px,1.5fr) 86px minmax(180px,2fr) 128px 22px";

function Pomer({ p, analyzaCeka }: { p: PoslanecSouhrn; analyzaCeka?: boolean }) {
  // Zelená nula u jmenovitého poslance se čte jako naměřený výsledek.
  // Dokud se nekontrolovalo, patří sem pomlčka, ne číslo.
  if (analyzaCeka) {
    return (
      <span className="text-inkoust-3" title="analýza zatím neproběhla">
        —
      </span>
    );
  }
  return (
    <>
      <span className={cn("font-bold", p.rozpor === 0 ? "text-overeno" : "text-rozpor")}>{p.rozpor}</span> /{" "}
      {p.overeno}
    </>
  );
}

function RadekPoslance({ p, analyzaCeka }: { p: PoslanecSouhrn; analyzaCeka?: boolean }) {
  return (
    <Link
      href={`/poslanec/${p.id}`}
      className="group block px-2.5 md:px-3.5 py-4 border-b border-linka-2 hover:bg-list transition-colors"
    >
      {/* Mobil: jméno+čísla na jednom řádku, pásmo pod tím přes celou šířku. */}
      <div className="grid grid-cols-[1fr_auto] gap-x-3 gap-y-2.5 items-center md:hidden">
        <div>
          <div className="text-[15.5px] font-medium tracking-[-0.008em]">
            {prijmeniZ(p.jmeno)}, {p.jmeno.split(" ")[0]}
          </div>
          <div className="text-[12px] text-inkoust-3">{p.role}</div>
        </div>
        <div className="font-mono text-[12.5px] tabular-nums text-right text-inkoust-2">
          <Pomer p={p} analyzaCeka={analyzaCeka} />
        </div>
        <PasmoZaznamu tally={p.tally} className="col-span-2 h-4" />
      </div>

      {/* Desktop: jeden řádek tabulky. */}
      <div className="hidden md:grid md:items-center md:gap-4" style={{ gridTemplateColumns: MRIZKA_DESKTOP }}>
        <div>
          <div className="text-[15.5px] font-medium tracking-[-0.008em]">
            {prijmeniZ(p.jmeno)}, {p.jmeno.split(" ")[0]}
          </div>
          <div className="text-[12px] text-inkoust-3">{p.role}</div>
        </div>
        <div className="font-mono text-[11.5px] font-medium text-inkoust-2 tracking-wide">{p.klub}</div>
        <PasmoZaznamu tally={p.tally} className="h-5" />
        <div className="font-mono text-[12.5px] tabular-nums text-right text-inkoust-2">
          <Pomer p={p} analyzaCeka={analyzaCeka} />
        </div>
        <ChevronRight className="w-3.5 h-3.5 text-inkoust-3 opacity-0 group-hover:opacity-100 group-hover:translate-x-0.5 transition-all" />
      </div>
    </Link>
  );
}
