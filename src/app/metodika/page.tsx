import React from "react";
import {
  ANALYZA,
  AVERAGE_CONFIDENCE,
  CONTEXT_DEVELOPMENT_COUNT,
  PUBLISHED_COUNT,
  REJECTED_BELOW_THRESHOLD,
} from "@/lib/debate";
import { formatJistota } from "@/lib/ui";
import { CONTEXT_THRESHOLD, PUBLISH_THRESHOLD } from "@/types/debate";

export const metadata = { title: "Metodika | Nezalžeme.cz" };

function kandidatSklonovano(pocet: number): string {
  if (pocet === 1) return "kandidát";
  if (pocet >= 2 && pocet <= 4) return "kandidáti";
  return "kandidátů";
}

function vystoupeniSklonovano(pocet: number): string {
  if (pocet === 1) return "vystoupení";
  return "vystoupení";
}

export default function MetodikaPage() {
  return (
    <div className="max-w-6xl mx-auto px-6">
      <div className="max-w-[66ch] py-9 pb-20">
        {ANALYZA.ceka && (
          <div className="border border-linka rounded-sm bg-list px-5 py-4 mb-8">
            <div className="font-mono text-[10.5px] uppercase tracking-[0.09em] text-inkoust-3 mb-1.5">
              Stav k {new Date(ANALYZA.aktualizovano).toLocaleDateString("cs-CZ")}
            </div>
            <p className="font-serif font-serif-text text-[15px] leading-[1.55] text-inkoust-2">
              Máme přepsaných {ANALYZA.vystoupeniCelkem} {vystoupeniSklonovano(ANALYZA.vystoupeniCelkem)} z{" "}
              {ANALYZA.jednaciDny} jednacích dnů, každé s odkazem na přesné místo ve stenoprotokolu. Postup popsaný
              níž zatím nad žádným z nich neproběhl, takže na webu není ani jedna značka. To, co následuje, je tedy
              popis toho, jak budeme postupovat — ne popis něčeho, co už proběhlo.
            </p>
          </div>
        )}

        <h2 className="text-[20px] font-bold tracking-[-0.018em] mt-0 mb-2.5">Co porovnáváme</h2>
        <p className="font-serif font-serif-text text-[17px] leading-[1.62] text-inkoust-2 mb-3.5">
          Bereme stenozáznamy Poslanecké sněmovny a záznamy hlasování — obojí jsou veřejná data na psp.cz. Každý věcný
          výrok porovnáme s tím, co <strong className="text-inkoust font-semibold">týž poslanec</strong> řekl dřív ke
          stejné věci, a s tím, jak o ní hlasoval.
        </p>
        <p className="font-serif font-serif-text text-[17px] leading-[1.62] text-inkoust-2 mb-3.5">
          Neposuzujeme názory, ideologii ani to, jestli byl návrh dobrý. Posuzujeme jedinou věc:{" "}
          <strong className="text-inkoust font-semibold">drží řečník to, co sám dřív řekl a udělal?</strong> Tohle
          pravidlo platí pro vládu i opozici beze zbytku stejně.
        </p>

        <h2 className="text-[20px] font-bold tracking-[-0.018em] mt-9 mb-2.5">Čtyři značky</h2>
        <div className="flex flex-col mt-4">
          <Pravidlo nazev="Opak dřívějšího výroku" popis="Ke stejné věci týž poslanec dřív tvrdil pravý opak. Doložíme oba stenozáznamy." />
          <Pravidlo nazev="Rozpor s hlasováním" popis="Výrok neodpovídá tomu, jak poslanec o téže věci hlasoval. Doložíme číslo hlasování a tisk." />
          <Pravidlo nazev="Údaj neodpovídá zdroji" popis="Číslo nebo fakt se rozchází s ověřitelným veřejným zdrojem — ČSÚ, ČNB, SFDI, NKÚ. Doložíme zdroj i datum." />
          <Pravidlo nazev="Změna postoje" popis="Postoj se v čase posunul. Nezapočítává se mezi rozpory — měnit názor je legitimní. Zaznamenáváme ji jen proto, aby byl vývoj dohledatelný." posun />
        </div>

        <h2 className="text-[20px] font-bold tracking-[-0.018em] mt-9 mb-2.5">Jak ověřujeme, než značku zveřejníme</h2>
        <p className="font-serif font-serif-text text-[17px] leading-[1.62] text-inkoust-2 mb-3.5">
          Každý kandidát na značku projde oponentním přezkumem: Žalobce postaví obžalobu, Obhájce hledá nejsilnější
          možnou obhajobu poslance a Soudce obojí zváží. Když obhajoba obstojí, kategorii zmírníme nebo značku vůbec
          nezveřejníme — u každé značky proto vidíte i to, jaké obhajoby jsme zvažovali a jak Soudce rozhodl.
        </p>
        <p className="font-serif font-serif-text text-[17px] leading-[1.62] text-inkoust-2 mb-3.5">
          Oponentní přezkum sám o sobě ale nestačí — každá značka nese i jistotu detekce, a tu měříme dvěma prahy,
          ne jedním. Nad {formatJistota(PUBLISH_THRESHOLD)} zveřejňujeme kandidáta jako{" "}
          <strong className="text-inkoust font-semibold">obvinění</strong> — jednu ze čtyř značek výš. Mezi{" "}
          {formatJistota(CONTEXT_THRESHOLD)} a {formatJistota(PUBLISH_THRESHOLD)} jistota na obvinění nestačí, takže
          kandidáta ukážeme jen jako neutrální{" "}
          <strong className="text-inkoust font-semibold">Kontext a vývoj stanoviska</strong> — stejné dvě karty,
          stejné odkazy na zdroj, ale bez obviňujícího rámování. Pod {formatJistota(CONTEXT_THRESHOLD)} se kandidát na
          web vůbec nedostane.
        </p>
        {AVERAGE_CONFIDENCE === null ? (
          <p className="font-serif font-serif-text text-[17px] leading-[1.62] text-inkoust-2 mb-3.5">
            Zatím ale není zveřejněná ani jedna značka — porovnání zatím neproběhlo, takže průměrnou jistotu
            neuvádíme; nebylo by z čeho ji počítat.
          </p>
        ) : (
          <p className="font-serif font-serif-text text-[17px] leading-[1.62] text-inkoust-2 mb-3.5">
            Dnes je to {PUBLISHED_COUNT} {kandidatSklonovano(PUBLISHED_COUNT)} jako obvinění a{" "}
            {CONTEXT_DEVELOPMENT_COUNT} {kandidatSklonovano(CONTEXT_DEVELOPMENT_COUNT)} jako kontext a vývoj
            stanoviska, dohromady v průměru s jistotou {formatJistota(AVERAGE_CONFIDENCE)}. Zbytek (
            {REJECTED_BELOW_THRESHOLD} {kandidatSklonovano(REJECTED_BELOW_THRESHOLD)}) neunes
            {REJECTED_BELOW_THRESHOLD === 1 ? "l" : "lo"} ani nižší práh a zobrazí se jako vystoupení bez námitky.
          </p>
        )}
        <p className="font-serif font-serif-text text-[15px] leading-[1.55] text-inkoust-3 mb-3.5">
          Oba prahy zatím stanovujeme odborným úsudkem, ne statistickou kalibrací — na tu je gold sada příkladů,
          kterou máme, zatím malá. Poroste s každou vyřízenou námitkou.
        </p>

        <h2 className="text-[20px] font-bold tracking-[-0.018em] mt-9 mb-2.5">Proč vidíte jmenovatele</h2>
        <p className="font-serif font-serif-text text-[17px] leading-[1.62] text-inkoust-2 mb-3.5">
          U každého poslance je vždycky vidět, kolik vystoupení jsme prošli. Bez toho by vycházel hůř ten, kdo mluví
          často — a to by nebylo poctivé měření, jen měření výřečnosti.
        </p>

        <h2 className="text-[20px] font-bold tracking-[-0.018em] mt-9 mb-2.5">Nadsázku neznačíme</h2>
        <p className="font-serif font-serif-text text-[17px] leading-[1.62] text-inkoust-2 mb-3.5">
          Ironii, metaforu a řečnickou nadsázku nepovažujeme za tvrzení. Stejně tak neznačíme citaci nebo parafrázi
          oponenta — značíme jen to, co poslanec sám míní jako vlastní tvrzení.
        </p>

        <h2 id="namitka" className="text-[20px] font-bold tracking-[-0.018em] mt-9 mb-2.5 scroll-mt-20">
          Když se spleteme
        </h2>
        <p className="font-serif font-serif-text text-[17px] leading-[1.62] text-inkoust-2 mb-3.5">
          U každé značky je tlačítko <strong className="text-inkoust font-semibold">Namítnout</strong>. Napište nám na{" "}
          <a href="mailto:namitky@nezalzeme.cz" className="text-overeno border-b border-overeno/20 hover:border-overeno">
            namitky@nezalzeme.cz
          </a>{" "}
          s odkazem na značku — vyřídíme do 14 dnů.
          Systém, který neumí přiznat chybu, nemá právo hlídat cizí.
        </p>
      </div>
    </div>
  );
}

function Pravidlo({ nazev, popis, posun }: { nazev: string; popis: string; posun?: boolean }) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-[210px_1fr] gap-2 md:gap-5 py-4 border-t border-linka-2 items-start">
      <div className={`font-mono text-[11px] font-bold uppercase tracking-wide pt-0.5 ${posun ? "text-inkoust-2" : "text-rozpor"}`}>
        {nazev}
      </div>
      <p className="font-serif font-serif-text text-[15.5px] leading-[1.55] text-inkoust-2">{popis}</p>
    </div>
  );
}
