import React from "react";
import Link from "next/link";
import { notFound } from "next/navigation";
import { getPoslanecDetail, getVsichniPoslanci } from "@/lib/poslanci";
import { PasmoZaznamu } from "@/components/zaznam/PasmoZaznamu";
import { ZaznamySeznam } from "@/components/poslanec/ZaznamySeznam";
import { CasovaOsaRozporu } from "@/components/zaznam/CasovaOsaRozporu";
import { ANALYZA } from "@/lib/debate";

export function generateStaticParams() {
  return getVsichniPoslanci().map((p) => ({ id: p.id }));
}

export async function generateMetadata({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const p = getPoslanecDetail(id);
  return { title: p ? `${p.jmeno} | Nezalžeme.cz` : "Poslanec nenalezen | Nezalžeme.cz" };
}

export default async function PoslanecPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const p = getPoslanecDetail(id);
  if (!p) notFound();

  const bezNamitky = p.overeno - p.rozpor - p.posun - p.vyvoj;
  const prijmeni = p.jmeno.split(" ").slice(1).join(" ") || p.jmeno;

  return (
    <div className="max-w-6xl mx-auto px-6">
      <Link href="/" className="inline-flex items-center gap-1.5 font-mono text-[11.5px] text-inkoust-2 hover:text-overeno mt-7 mb-5">
        ← Zpět do rejstříku
      </Link>

      <div className="pb-8 border-b border-inkoust">
        <h1 className="font-bold text-[2rem] md:text-[2.9rem] leading-[1.04] tracking-[-0.035em]">{p.jmeno}</h1>
        <div className="font-mono text-[12px] text-inkoust-2 mt-2 tracking-wide">
          {[p.klub || "bez klubu", p.role, ANALYZA.obdobi].join(" · ")}
        </div>

        <PasmoZaznamu tally={p.tally} className="h-[34px] my-7" />

        {ANALYZA.ceka ? (
          /* Tři nuly vedle jména konkrétního člověka by byly vystavené
             vysvědčení bezúhonnosti. Nikdo ho nevystavil — nekontrolovalo se. */
          <div>
            <div className="text-[27px] md:text-[34px] font-extrabold leading-none tabular-nums tracking-[-0.028em]">
              {p.vystoupeni}
            </div>
            <p className="font-serif font-serif-text text-[14px] text-inkoust-2 mt-1.5 max-w-[46ch]">
              vystoupení v přepisu
            </p>
            <p className="font-serif font-serif-text text-[14.5px] leading-[1.55] text-inkoust-2 mt-4 max-w-[62ch]">
              Rozpory ani změny postoje zatím neuvádíme — porovnání vystoupení, která tu jsou, s dřívějšími výroky
              {" "}{prijmeni === p.jmeno ? "tohoto poslance" : prijmeni + "a"} a s hlasováním ještě neproběhlo.{" "}
              <strong className="text-inkoust font-semibold">
                Nula značek by tady byla jen zdání, ne zjištění.
              </strong>
            </p>
          </div>
        ) : (
          <div className="flex gap-10 flex-wrap">
            <div>
              <div className="text-[27px] md:text-[34px] font-extrabold leading-none tabular-nums tracking-[-0.028em] text-rozpor">
                {p.rozpor}
              </div>
              <p className="font-serif font-serif-text text-[14px] text-inkoust-2 mt-1.5 max-w-[21ch]">
                výroků v rozporu se záznamem
              </p>
            </div>
            <div>
              <div className="text-[27px] md:text-[34px] font-extrabold leading-none tabular-nums tracking-[-0.028em]">
                {p.posun}
              </div>
              <p className="font-serif font-serif-text text-[14px] text-inkoust-2 mt-1.5 max-w-[21ch]">
                doložených změn postoje
              </p>
            </div>
            <div>
              <div className="text-[27px] md:text-[34px] font-extrabold leading-none tabular-nums tracking-[-0.028em]">
                {p.vyvoj}
              </div>
              <p className="font-serif font-serif-text text-[14px] text-inkoust-2 mt-1.5 max-w-[21ch]">
                v pásmu kontext a vývoj stanoviska
              </p>
            </div>
            <div>
              <div className="text-[27px] md:text-[34px] font-extrabold leading-none tabular-nums tracking-[-0.028em]">
                {bezNamitky}
              </div>
              <p className="font-serif font-serif-text text-[14px] text-inkoust-2 mt-1.5 max-w-[21ch]">
                vystoupení bez námitky
              </p>
            </div>
          </div>
        )}

        {p.govTrackScore?.analyzedSpeeches && (
          <p className="font-mono text-[11px] text-inkoust-3 mt-6">
            Engine u tohoto poslance sleduje {p.govTrackScore.analyzedSpeeches} vystoupení; {p.overeno} z nich je
            v této ukázce podrobně rozepsáno.
          </p>
        )}
        {!ANALYZA.ceka && p.overeno < 5 && (
          <p className="font-serif font-serif-text text-[13.5px] text-inkoust-3 mt-3 max-w-[60ch] italic">
            Tak málo zkontrolovaných vystoupení nic samo o sobě neprokazuje. Poměr má vypovídací hodnotu až
            u desítek a stovek vystoupení.
          </p>
        )}
        <p className="font-mono text-[11px] text-inkoust-3 mt-6">
          <a href={p.profilUrl} target="_blank" rel="noopener noreferrer" className="hover:text-overeno">
            profil na psp.cz ↗
          </a>
        </p>
      </div>

      {!ANALYZA.ceka && p.zaznamy.length > 0 && (
        <CasovaOsaRozporu zaznamy={p.zaznamy} jmeno={p.jmeno} />
      )}

      <div className="pb-16">
        <ZaznamySeznam zaznamy={p.zaznamy} jmeno={p.jmeno} analyzaCeka={ANALYZA.ceka} />
      </div>
    </div>
  );
}
