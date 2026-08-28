import React from "react";
import Link from "next/link";
import { notFound } from "next/navigation";
import { getPoslanecDetail, getVsichniPoslanci } from "@/lib/poslanci";
import { PasmoZaznamu } from "@/components/zaznam/PasmoZaznamu";
import { ZaznamySeznam } from "@/components/poslanec/ZaznamySeznam";
import { CasovaOsaRozporu } from "@/components/zaznam/CasovaOsaRozporu";
import { SlovoACin } from "@/components/zaznam/SlovoACin";
import { ANALYZA } from "@/lib/debate";
import { cn } from "@/lib/utils";
import { MIN_HLASOVANI_PRO_UCAST } from "@/lib/ui";

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

        {p.stanceConsistency && (
          <div className="mt-7 p-4 bg-list border border-linka rounded-sm">
            <div className="flex items-center justify-between flex-wrap gap-2">
              <div className="flex items-center gap-2">
                <span className="text-base">🎯</span>
                <span className="font-mono text-[11px] font-bold uppercase tracking-wider text-inkoust-3">
                  Index konzistence postojů (SCI)
                </span>
              </div>
              <span className="font-mono text-[12px] font-semibold text-inkoust">
                {p.stanceConsistency.sciLabel}
              </span>
            </div>

            <div className="mt-3 flex items-baseline gap-3 flex-wrap">
              <div className="text-[28px] font-extrabold font-mono tabular-nums leading-none">
                {Math.round(p.stanceConsistency.sci * 100)} %
              </div>
              <div className="text-xs text-inkoust-3 font-serif">
                vypočteno z {p.stanceConsistency.commitmentCount} závazkových výroků ({p.stanceConsistency.contradictionCount} věcných rozporů)
              </div>
              {p.stanceConsistency.partyAverageSci !== undefined && (
                <div className="ml-auto font-mono text-[11.5px] text-inkoust-2 bg-podklad-2 px-2.5 py-1 rounded border border-inkoust/10">
                  Průměr klubu ({p.klub || "strana"}): {Math.round(p.stanceConsistency.partyAverageSci * 100)} %
                  {p.stanceConsistency.sciVsPartyDelta !== undefined && (
                    <span
                      className={cn(
                        "ml-1.5 font-bold",
                        p.stanceConsistency.sciVsPartyDelta >= 0
                          ? "text-emerald-600 dark:text-emerald-400"
                          : "text-rose-600 dark:text-rose-400"
                      )}
                    >
                      ({p.stanceConsistency.sciVsPartyDelta >= 0 ? "+" : ""}
                      {Math.round(p.stanceConsistency.sciVsPartyDelta * 100)} p.b.)
                    </span>
                  )}
                </div>
              )}
            </div>

            <div className="mt-3 relative w-full h-2 bg-podklad-2 rounded-full overflow-hidden border border-inkoust/10">
              <div
                className="h-full bg-inkoust transition-all duration-500"
                style={{ width: `${Math.round(p.stanceConsistency.sci * 100)}%` }}
              />
              {p.stanceConsistency.partyAverageSci !== undefined && (
                <div
                  className="absolute top-0 bottom-0 w-0.5 bg-rose-500 dark:bg-rose-400 z-10"
                  style={{ left: `${Math.round(p.stanceConsistency.partyAverageSci * 100)}%` }}
                  title={`Průměr klubu: ${Math.round(p.stanceConsistency.partyAverageSci * 100)} %`}
                />
              )}
            </div>
          </div>
        )}

        {p.hlasovaciBilance && (
          <div className="mt-4 p-4 bg-list border border-linka rounded-sm">
            <div className="flex items-center justify-between flex-wrap gap-2">
              <div className="flex items-center gap-2">
                <span className="text-base">🗳️</span>
                <span className="font-mono text-[11px] font-bold uppercase tracking-wider text-inkoust-3">
                  Hlasovací bilance
                </span>
              </div>
              <span className="font-mono text-[11px] text-inkoust-3 tabular-nums">
                {p.hlasovaciBilance.celkem} jmenovitých hlasování
              </span>
            </div>

            {p.hlasovaciBilance.celkem >= MIN_HLASOVANI_PRO_UCAST ? (
              <div className="mt-3 flex items-baseline gap-3 flex-wrap">
                <div className="text-[28px] font-extrabold font-mono tabular-nums leading-none">
                  {Math.round(p.hlasovaciBilance.ucast * 100)} %
                </div>
                <div className="text-xs text-inkoust-3 font-serif">
                  účast při hlasování
                  {p.hlasovaciBilance.omluven > 0 && (
                    <> · {p.hlasovaciBilance.omluven} nepřítomností krytých omluvou</>
                  )}
                </div>
              </div>
            ) : (
              /* Účast z hrstky hlasování nic neříká — poslanec, který složil mandát
                 po dvou hlasováních, by tu měl „0 %". Formálně pravda, fakticky
                 lživý dojem. Stejný důvod jako práh `overeno < 5` výš. */
              <p className="mt-3 font-serif font-serif-text text-[14px] leading-[1.55] text-inkoust-2 max-w-[62ch]">
                Poslanec je v datech veden jen u {p.hlasovaciBilance.celkem} hlasování — na výpočet účasti
                je to příliš málo. Rozpad hlasů níže platí, podíl by klamal.
              </p>
            )}

            <dl className="mt-4 flex flex-wrap gap-x-6 gap-y-1 font-mono text-[11.5px] tabular-nums">
              <div className="flex gap-1.5">
                <dt className="text-inkoust-3">pro</dt>
                <dd className="font-semibold">{p.hlasovaciBilance.pro}</dd>
              </div>
              <div className="flex gap-1.5">
                <dt className="text-inkoust-3">proti</dt>
                <dd className="font-semibold">{p.hlasovaciBilance.proti}</dd>
              </div>
              <div className="flex gap-1.5">
                <dt className="text-inkoust-3">zdržel se / nehlasoval</dt>
                <dd className="font-semibold">{p.hlasovaciBilance.zdrzelNeboNehlasoval}</dd>
              </div>
              <div className="flex gap-1.5">
                <dt className="text-inkoust-3">nepřihlášen</dt>
                <dd className="font-semibold">{p.hlasovaciBilance.neprihlasen}</dd>
              </div>
            </dl>

            <p className="mt-3 font-mono text-[10.5px] text-inkoust-3 leading-[1.5]">
              Z otevřených dat PSP ČR. Dump slučuje „zdržel se" a „nehlasoval" do jednoho kódu,
              proto zůstávají spolu — rozlišit je umí až hlasovací lístek u konkrétního hlasování.
            </p>
          </div>
        )}

        {p.indexVecnosti && (
          <div className="mt-4 p-4 bg-list border border-linka rounded-sm">
            <div className="flex items-center gap-2">
              <span className="text-base">📋</span>
              <span className="font-mono text-[11px] font-bold uppercase tracking-wider text-inkoust-3">
                Index věcnosti
              </span>
            </div>

            <div className="mt-3 flex items-baseline gap-3 flex-wrap">
              <div className="text-[28px] font-extrabold font-mono tabular-nums leading-none">
                {p.indexVecnosti.poslaneckeNavrhyZakonu}
              </div>
              <div className="text-xs text-inkoust-3 font-serif">
                poslaneckých návrhů zákonů za celé volební období
              </div>
            </div>

            {p.indexVecnosti.vzorekVystoupeni ? (
              <>
                <dl className="mt-4 flex flex-wrap gap-x-6 gap-y-1 font-mono text-[11.5px] tabular-nums">
                  <div className="flex gap-1.5">
                    <dt className="text-inkoust-3">medián délky vystoupení</dt>
                    <dd className="font-semibold">
                      {Math.round(p.indexVecnosti.vzorekVystoupeni.medianDelkyZnaku)} znaků
                    </dd>
                  </div>
                  <div className="flex gap-1.5">
                    <dt className="text-inkoust-3">podíl krátkých vystoupení</dt>
                    <dd className="font-semibold">
                      {Math.round(p.indexVecnosti.vzorekVystoupeni.podilKratkychVystoupeni * 100)} %
                    </dd>
                  </div>
                </dl>
                <p className="mt-3 font-mono text-[10.5px] text-inkoust-3 leading-[1.5]">
                  Spočteno z {p.indexVecnosti.vzorekVystoupeni.vystoupeniVeVzorku} vystoupení ve
                  staženém vzorku ({ANALYZA.jednaciDny} z {ANALYZA.hlasovaniDnuCelkem ?? "?"} dnů
                  s hlasováním za celé období) — ne za celé volební období. Nízké číslo tu může
                  znamenat malou aktivitu, nebo jen to, že poslanec mluvil hlavně mimo stažené dny.
                </p>
              </>
            ) : (
              <p className="mt-3 font-serif font-serif-text text-[14px] leading-[1.55] text-inkoust-2 max-w-[62ch]">
                Ve staženém vzorku ({ANALYZA.jednaciDny} z {ANALYZA.hlasovaniDnuCelkem ?? "?"} dnů
                s hlasováním) má poslanec příliš málo vystoupení na spočtení podílu krátkých
                vystoupení a mediánu délky — je to mezera ve vzorku, ne doklad nečinnosti.
              </p>
            )}
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
        <div className="flex items-center gap-4 font-mono text-[11px] text-inkoust-3 mt-6">
          <a href={p.profilUrl} target="_blank" rel="noopener noreferrer" className="hover:text-overeno">
            profil na psp.cz ↗
          </a>
          {p.hlidacStatu && (
            <>
              <span>·</span>
              <a
                href={p.hlidacStatu.profileUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="hover:text-overeno"
              >
                profil na hlidacstatu.cz ↗
              </a>
            </>
          )}
        </div>

        {p.hlidacStatu && (
          <div className="mt-6 pt-5 border-t border-inkoust/10">
            <div className="flex items-center gap-2 text-[12px] font-mono text-inkoust-2">
              <span className="inline-block w-2 h-2 rounded-full bg-overeno"></span>
              <span>Ověřený profil Hlídač Státu:</span>
              <a
                href={p.hlidacStatu.profileUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="underline hover:text-overeno font-semibold"
              >
                {p.hlidacStatu.osobaId} ↗
              </a>
              {p.hlidacStatu.birthYear && (
                <span className="text-inkoust-3">(*{p.hlidacStatu.birthYear})</span>
              )}
            </div>

            {p.hlidacStatu.historicalRoles.length > 0 && (
              <div className="mt-3 flex flex-wrap gap-1.5">
                {p.hlidacStatu.historicalRoles.map((role, idx) => (
                  <span
                    key={idx}
                    className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-mono bg-podklad-2 text-inkoust-2 border border-inkoust/10"
                  >
                    {role.role}
                    {role.organization ? ` (${role.organization})` : ""}
                    {role.since ? ` · ${role.since}` : ""}
                    {role.until ? `–${role.until}` : ""}
                  </span>
                ))}
              </div>
            )}

            {p.hlidacStatu.corporateTiesCount > 0 && (
              <p className="font-mono text-[11px] text-inkoust-3 mt-2">
                Obchodní rejstřík: {p.hlidacStatu.corporateTiesCount} navázaných subjektů
                {p.hlidacStatu.corporateEntities.length > 0 && ` (${p.hlidacStatu.corporateEntities.slice(0, 3).join(", ")})`}
              </p>
            )}
          </div>
        )}
      </div>

      {p.slovoCin.length > 0 && (
        <section className="mt-12 pt-8 border-t border-inkoust" aria-labelledby="slovo-cin-nadpis">
          <h2 id="slovo-cin-nadpis" className="font-mono text-[11px] font-bold uppercase tracking-[0.13em] text-inkoust-2">
            Slovo a čin
          </h2>
          <p className="font-serif font-serif-text text-[14.5px] leading-[1.55] text-inkoust-2 mt-2 max-w-[62ch]">
            Výroky z rozpravy postavené vedle toho, jak {prijmeni === p.jmeno ? "poslanec" : prijmeni}
            {" "}nakonec hlasoval o témže sněmovním tisku. Porovnává se jen s{" "}
            <strong className="text-inkoust font-semibold">finálním hlasováním</strong>, které jako
            finální označuje sama Sněmovna v historii tisku — ne s pozměňovacími návrhy ani
            procedurálními hlasováními.
          </p>
          <div className="mt-4">
            {p.slovoCin.map((z) => (
              <SlovoACin key={z.id} zaznam={z} />
            ))}
          </div>
        </section>
      )}

      {!ANALYZA.ceka && p.zaznamy.length > 0 && (
        <CasovaOsaRozporu zaznamy={p.zaznamy} jmeno={p.jmeno} />
      )}

      <div className="pb-16">
        <ZaznamySeznam zaznamy={p.zaznamy} jmeno={p.jmeno} analyzaCeka={ANALYZA.ceka} />
      </div>
    </div>
  );
}
