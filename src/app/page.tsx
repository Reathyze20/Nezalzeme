import React, { Suspense } from "react";
import { Clock, History, Calendar, CheckCircle2, ArrowRight } from "lucide-react";
import { getVsichniPoslanci, getCelkoveMeridlo } from "@/lib/poslanci";
import { PasmoZaznamu, LegendaPasma } from "@/components/zaznam/PasmoZaznamu";
import { RejstrikTabulka } from "@/components/rejstrik/RejstrikTabulka";
import { ANALYZA } from "@/lib/debate";

export default function Rejstrik() {
  const poslanci = getVsichniPoslanci();
  const meridlo = getCelkoveMeridlo();
  const podilRozpor = meridlo.overeno > 0 ? Math.round((meridlo.rozpor / meridlo.overeno) * 100) : 0;
  const podilPosun = meridlo.overeno > 0 ? Math.round((meridlo.posun / meridlo.overeno) * 100) : 0;
  const podilVyvoj = meridlo.overeno > 0 ? Math.round((meridlo.vyvoj / meridlo.overeno) * 100) : 0;

  return (
    <div className="max-w-6xl mx-auto px-6">
      <section className="grid grid-cols-1 md:grid-cols-[1.05fr_1fr] gap-14 items-start py-16 md:py-[68px]">
        <div>
          <div className="inline-flex items-center gap-1.5 font-mono text-[11px] font-semibold uppercase tracking-wider px-2.5 py-1 rounded-[2px] bg-linka-2 text-inkoust-2 mb-4">
            <Clock className="w-3.5 h-3.5 text-overeno" />
            Časová analýza · únor–srpen 2026
          </div>
          <h1 className="font-bold text-[2.1rem] md:text-[3.1rem] leading-[1.04] tracking-[-0.033em] text-balance">
            Ke každému výroku patří <em className="font-serif font-serif-text italic font-normal">záznam</em>.
          </h1>
          <p className="font-serif font-serif-text text-[18.5px] leading-[1.58] text-inkoust-2 mt-5 max-w-[46ch]">
            Porovnáváme, co poslanci říkají ve Sněmovně, s tím, co řekli dřív a jak potom hlasovali. Skutečné postoje se
            totiž ukazují až v čase — mezi prvním čtením, pozměňovacími návrhy a finálním hlasováním.
          </p>
          <div className="flex gap-2.5 mt-6 flex-wrap">
            <a
              href="#rejstrik"
              className="inline-flex items-center gap-1.5 font-semibold text-[13.5px] px-[18px] py-[11px] rounded-sm bg-overeno text-papir hover:opacity-90 transition-opacity"
            >
              Otevřít rejstřík poslanců
            </a>
            <a
              href="#casovy-kontext"
              className="inline-flex items-center gap-1.5 font-semibold text-[13.5px] px-[18px] py-[11px] rounded-sm border border-linka text-inkoust hover:border-inkoust-3 transition-colors"
            >
              Proč záleží na čase
            </a>
          </div>
        </div>

        <div className="bg-list border border-linka rounded-sm p-6 shadow-sm">
          <div className="font-mono text-[10.5px] uppercase tracking-[0.09em] text-inkoust-3">
            {ANALYZA.obdobi} · {ANALYZA.jednaciDny} jednacích dnů · {meridlo.vystoupeni} vystoupení v přepisu
          </div>
          <PasmoZaznamu tally={meridlo.tally} className="h-[46px] my-4.5" />
          {ANALYZA.ceka ? (
            <p className="font-serif font-serif-text text-[15px] leading-[1.5] text-inkoust-2">
              Máme {meridlo.vystoupeni} vystoupení přepsaných ze stenoprotokolu a u každého odkaz na přesné místo
              v záznamu. Porovnání s dřívějšími výroky a s hlasováním zatím neproběhlo, počet rozporů proto neuvádíme.{" "}
              <strong className="text-inkoust font-semibold">
                Nula značek neznamená nula rozporů — znamená, že analýza ještě nezačala.
              </strong>
            </p>
          ) : (
            <p className="font-serif font-serif-text text-[15px] leading-[1.5] text-inkoust-2">
              Z {meridlo.overeno} zkontrolovaných vystoupení se {meridlo.rozpor} ({podilRozpor} %) rozchází s dřívějším
              výrokem nebo s hlasováním téhož poslance natolik jistě, že to zveřejňujeme jako obvinění. U dalších{" "}
              {meridlo.vyvoj} ({podilVyvoj} %) jistota na obvinění nestačí, takže je ukazujeme jen jako neutrální
              kontext a vývoj stanoviska. U {meridlo.posun} ({podilPosun} %) jde o doloženou změnu postoje.
            </p>
          )}
          <LegendaPasma tally={meridlo.tally} className="mt-4.5 pt-4 border-t border-linka-2" />
        </div>
      </section>

      {/* Časový kontext a metodika projevu v čase */}
      <section id="casovy-kontext" className="py-10 border-t border-linka-2 scroll-mt-16">
        <div className="bg-papir border border-linka rounded-sm p-6 md:p-8 shadow-xs">
          <div className="flex items-center gap-2 mb-3">
            <History className="w-5 h-5 text-overeno" />
            <h2 className="font-bold text-[19px] md:text-[22px] tracking-tight">
              Až v čase se politický diskurz projevuje naplno
            </h2>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mt-6">
            <div className="bg-list/60 border border-linka-2 rounded-xs p-4.5">
              <div className="font-mono text-[11.5px] uppercase font-bold text-inkoust-3 tracking-wider mb-2">
                1. Čtení & Sliby (Měsíc T)
              </div>
              <p className="font-serif font-serif-text text-[14.5px] leading-[1.5] text-inkoust-2">
                V úvodní rozpravě zaznívají zásadní deklarace: „tuto daň nikdy nezvýšíme“, „proceduru nezkrátíme“,
                „rozpočtový schodek nepřekročíme“.
              </p>
            </div>
            <div className="bg-list/60 border border-linka-2 rounded-xs p-4.5">
              <div className="font-mono text-[11.5px] uppercase font-bold text-inkoust-3 tracking-wider mb-2">
                2. Pozměňovací návrhy (T + 2 měsíce)
              </div>
              <p className="font-serif font-serif-text text-[14.5px] leading-[1.5] text-inkoust-2">
                Ve výborech a 2. čtení se text zákona mění. Zde engine sleduje, zda se mění věcná podstata nebo zda
                poslanec uplatňuje oponentní výhrady.
              </p>
            </div>
            <div className="bg-list/60 border border-linka-2 rounded-xs p-4.5">
              <div className="font-mono text-[11.5px] uppercase font-bold text-inkoust-3 tracking-wider mb-2">
                3. Hlasování & Výsledek (T + 4–6 měsíců)
              </div>
              <p className="font-serif font-serif-text text-[14.5px] leading-[1.5] text-inkoust-2">
                Teprve stisknutí hlasovacího tlačítka a následné komentáře v dalších měsících odhalí skutečný soulad
                či rozpor mezi slovem a činem.
              </p>
            </div>
          </div>
        </div>
      </section>

      <section id="rejstrik" className="pb-20 scroll-mt-20">
        <Suspense fallback={<TabulkaSkeleton />}>
          <RejstrikTabulka poslanci={poslanci} analyzaCeka={ANALYZA.ceka} />
        </Suspense>
      </section>
    </div>
  );
}

function TabulkaSkeleton() {
  return <div className="h-96 animate-pulse bg-list rounded-sm border border-linka" />;
}
