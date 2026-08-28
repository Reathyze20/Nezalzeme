import React from "react";
import { ExternalLink } from "lucide-react";
import { ProgramovaVernost } from "@/types/debate";
import { getVysledekLabel } from "@/lib/ui";

interface ZavazekKartaProps {
  zaznam: ProgramovaVernost;
}

const KLUB_POPISEK: Record<string, string> = {
  ANO2011: "ANO 2011",
  MS: "Motoristé sobě",
  SPD: "SPD",
};

/**
 * Doklad „slib z vládního prohlášení vs. hlasování koaličních klubů" —
 * jádro Fáze 4. Stejná zdrženlivost jako `SlovoACin`: žádný verdikt
 * splněno/nesplněno. Spárování slibu s tiskem tu navíc není strukturální
 * (na rozdíl od Slova a činu) — určuje ho model podle NÁZVU tisku a i po
 * nezávislém přezkumu je to posouzení, ne fakt, proto karta vždy ukazuje
 * i zdůvodnění spárování a čtenář si může sám ověřit, jestli obstojí.
 */
export function ZavazekKarta({ zaznam }: ZavazekKartaProps) {
  const { zavazek, tisk, hlasovani, duvodSparovani, kluby } = zaznam;
  const kluby_list = (["ANO2011", "MS", "SPD"] as const).map((k) => ({
    klub: k,
    pocty: kluby[k],
  }));

  return (
    <article id={zaznam.id} className="py-8 border-b border-linka-2 scroll-mt-20">
      <div className="flex items-baseline gap-3 flex-wrap mb-4">
        <span className="font-mono text-[10.5px] font-bold uppercase tracking-wider px-2 py-1 rounded-[2px] bg-linka-2 text-inkoust-2">
          Programová věrnost
        </span>
        <span className="font-mono text-[11px] text-inkoust-3">{zavazek.kapitolaNazev}</span>
        <span className="font-mono text-[11px] text-inkoust-3 tabular-nums ml-auto">
          sněmovní tisk {tisk.cislo}
        </span>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-[1fr_58px_1fr] items-stretch">
        {/* ---------- SLIB ---------- */}
        <div className="bg-list border border-linka rounded-sm p-5 flex flex-col gap-3 shadow-sm">
          <span className="font-mono text-[10px] font-bold uppercase tracking-[0.13em] text-inkoust-3">
            Slib z Programového prohlášení vlády
          </span>
          <blockquote className="font-serif font-serif-text text-[17px] leading-[1.55] flex-1">
            „{zavazek.citace}"
          </blockquote>
          <div className="flex flex-col gap-1.5">
            <a
              href={zavazek.url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 self-start font-mono text-[11px] text-overeno border-b border-overeno/10 hover:border-overeno pb-0.5 transition-colors"
            >
              kapitola prohlášení na vlada.gov.cz
              <ExternalLink className="w-3 h-3" aria-hidden />
            </a>
          </div>
        </div>

        <div className="relative flex items-center justify-center py-2 md:py-0">
          <span className="hidden md:block absolute top-6 bottom-6 w-px bg-linka" />
          <span className="md:hidden absolute left-1/2 -translate-x-1/2 top-0 bottom-0 w-px bg-linka" />
          <span
            className="relative z-10 w-[30px] h-[30px] rounded-full border border-linka bg-papir flex items-center justify-center font-mono text-[13px] font-bold text-inkoust-2"
            aria-hidden
          >
            ?
          </span>
        </div>

        {/* ---------- TISK A HLASOVÁNÍ ---------- */}
        <div className="bg-list border border-linka rounded-sm p-5 flex flex-col gap-3 shadow-sm border-t-[3px] md:border-t md:border-l-[3px] md:border-l-inkoust-3 border-t-inkoust-3">
          <span className="font-mono text-[10px] font-bold uppercase tracking-[0.13em] text-inkoust-3">
            Sněmovní tisk určený jako možné naplnění
          </span>

          <p className="font-serif font-serif-text text-[15px] leading-[1.5] text-inkoust-2">
            {tisk.nazev}
          </p>

          <div className="flex items-baseline gap-2 flex-wrap">
            <span className="font-mono text-[16px] font-extrabold tracking-tight">
              {getVysledekLabel(hlasovani.prijat).toUpperCase()}
            </span>
          </div>

          <dl className="font-mono text-[11px] text-inkoust-3 flex flex-col gap-1 tabular-nums">
            <div className="flex gap-2">
              <dt>hlasování</dt>
              <dd className="text-inkoust-2">
                č. {hlasovani.cislo} · {hlasovani.schuze}. schůze
                {hlasovani.datum ? ` · ${hlasovani.datum}` : ""}
              </dd>
            </div>
            {kluby_list.map(
              ({ klub, pocty }) =>
                pocty && (
                  <div key={klub} className="flex gap-2">
                    <dt>{KLUB_POPISEK[klub] ?? klub}</dt>
                    <dd className="text-inkoust-2">
                      {pocty.pro} pro · {pocty.proti} proti · {pocty.zdrzelNeboNehlasoval} zdr./nehl.
                    </dd>
                  </div>
                )
            )}
          </dl>

          <div className="flex flex-col gap-1.5">
            <a
              href={hlasovani.url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 self-start font-mono text-[11px] text-overeno border-b border-overeno/10 hover:border-overeno pb-0.5 transition-colors"
            >
              hlasovací lístek
              <ExternalLink className="w-3 h-3" aria-hidden />
            </a>
            <a
              href={hlasovani.historieUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 self-start font-mono text-[11px] text-overeno border-b border-overeno/10 hover:border-overeno pb-0.5 transition-colors"
            >
              historie tisku
              <ExternalLink className="w-3 h-3" aria-hidden />
            </a>
          </div>
        </div>
      </div>

      <p className="mt-4 font-mono text-[10.5px] text-inkoust-3 leading-[1.55] max-w-[80ch]">
        Spárování slibu s tímto tiskem určil jazykový model podle názvu tisku — plné znění
        zákona k dispozici nemáme — a nezávisle ho přezkoumal druhý model. Zdůvodnění:
        „{duvodSparovani}" Schválení tisku samo o sobě neznamená, že slib beze zbytku naplňuje;
        je to nejsilnější doklad, jaký z názvu tisku jde vyvodit, ne rozsudek.
      </p>
    </article>
  );
}
