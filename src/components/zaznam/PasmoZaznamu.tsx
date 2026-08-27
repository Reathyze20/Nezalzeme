import React from "react";
import { StavVystoupeni } from "@/lib/poslanci";
import { cn } from "@/lib/utils";

interface PasmoZaznamuProps {
  tally: StavVystoupeni[];
  className?: string;
  dilekClassName?: string;
  ariaLabel?: string;
}

/**
 * Pásmo záznamu — podpisový prvek celého webu. Jeden dílek = jedno vystoupení
 * v přepisu. Jmenovatel je vždy vidět, takže nevychází hůř ten, kdo mluví
 * častěji.
 *
 * Nezkontrolované vystoupení má **vlastní neutrální barvu**, ne zelenou.
 * Souvislý zelený pruh je nejsilnější tvrzení na celém webu a nesmí vzniknout
 * z toho, že se ještě nic nekontrolovalo.
 */
/** Nad tolik dílků se pásmo slučuje — 1 180 × 2 px by přeteklo mřížku. */
const MAX_DILKU = 180;

/** Pořadí závažnosti; sloučený dílek dostane barvu nejzávažnějšího stavu. */
const ZAVAZNOST: StavVystoupeni[] = ["rozpor", "vyvoj", "posun", "ciste", "nezkontrolovano"];

function slucDilky(tally: StavVystoupeni[]): StavVystoupeni[] {
  if (tally.length <= MAX_DILKU) return tally;
  const naDilek = Math.ceil(tally.length / MAX_DILKU);
  const slouceno: StavVystoupeni[] = [];
  for (let i = 0; i < tally.length; i += naDilek) {
    const skupina = tally.slice(i, i + naDilek);
    slouceno.push(ZAVAZNOST.find((stav) => skupina.includes(stav)) ?? "nezkontrolovano");
  }
  return slouceno;
}

export function PasmoZaznamu({ tally, className, dilekClassName, ariaLabel }: PasmoZaznamuProps) {
  const rozpor = tally.filter((s) => s === "rozpor").length;
  const posun = tally.filter((s) => s === "posun").length;
  const vyvoj = tally.filter((s) => s === "vyvoj").length;
  const zkontrolovano = tally.filter((s) => s !== "nezkontrolovano").length;

  const popis =
    ariaLabel ??
    (zkontrolovano === 0
      ? `Pásmo ${tally.length} vystoupení v přepisu. Analýza zatím neproběhla, žádné vystoupení není označené.`
      : `Ze ${zkontrolovano} zkontrolovaných vystoupení je ${rozpor} v rozporu se záznamem, ${vyvoj} je jen kontext a vývoj stanoviska a ${posun} představuje změnu postoje.`);

  if (tally.length === 0) {
    return (
      <div
        className={cn("flex items-center h-full rounded-sm border border-dashed border-linka-2 px-3", className)}
        role="img"
        aria-label="Zatím žádné vystoupení v přepisu."
      >
        <span className="font-mono text-[11px] text-inkoust-3">zatím žádné vystoupení v přepisu</span>
      </div>
    );
  }

  // Popis i počty se počítají z celého pásma, kreslí se ale sloučená podoba.
  const dilky = slucDilky(tally);

  return (
    <div className={cn("flex items-end gap-[2px]", className)} role="img" aria-label={popis}>
      {dilky.map((stav, i) => (
        <span
          key={i}
          className={cn(
            "flex-1 min-w-[2px] rounded-[0.5px] h-full",
            stav === "rozpor" && "bg-rozpor",
            stav === "vyvoj" && "bg-inkoust-3/45",
            stav === "posun" && "bg-inkoust-3/80",
            stav === "ciste" && "bg-dilek",
            stav === "nezkontrolovano" && "bg-inkoust-3/20",
            dilekClassName
          )}
        />
      ))}
    </div>
  );
}

interface LegendaProps {
  className?: string;
  /** Když je zadaný, vypíšou se jen stavy, které se v pásmu opravdu vyskytují. */
  tally?: StavVystoupeni[];
}

const POPIS_STAVU: Array<{ stav: StavVystoupeni; barva: string; label: string }> = [
  { stav: "nezkontrolovano", barva: "bg-inkoust-3/20", label: "zatím neanalyzováno" },
  { stav: "ciste", barva: "bg-dilek", label: "bez námitky" },
  { stav: "rozpor", barva: "bg-rozpor", label: "rozpor se záznamem" },
  { stav: "vyvoj", barva: "bg-inkoust-3/45", label: "kontext a vývoj stanoviska" },
  { stav: "posun", barva: "bg-inkoust-3/80", label: "změna postoje" },
];

export function LegendaPasma({ className, tally }: LegendaProps) {
  // Legenda nesmí vysvětlovat barvy, které na stránce nejsou — čtenář by je
  // hledal a domýšlel si, že tam někde jsou.
  const pritomne = tally ? new Set(tally) : null;
  const polozky = pritomne ? POPIS_STAVU.filter((p) => pritomne.has(p.stav)) : POPIS_STAVU;

  return (
    <div className={cn("flex flex-wrap items-center gap-5 font-mono text-[11px] text-inkoust-2", className)}>
      {polozky.map((p) => (
        <span key={p.stav} className="flex items-center gap-1.5">
          <span className={cn("w-[9px] h-[15px] rounded-[1px]", p.barva)} /> {p.label}
        </span>
      ))}
    </div>
  );
}
