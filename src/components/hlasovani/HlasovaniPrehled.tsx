import React from "react";
import { ExternalLink } from "lucide-react";
import { Hlasovani, HlasyRecnika, BodPoradu, VoteValueLedger } from "@/types/debate";
import { getHlasZnacka, getHlasClass, getVysledekLabel, formatDatum } from "@/lib/ui";

interface HlasovaniPrehledProps {
  bod?: BodPoradu | null;
  hlasovani: Hlasovani[];
  hlasyRecniku?: HlasyRecnika[];
}

/**
 * Hlasovací rejstřík rozpravy — „o čem se u tohoto bodu hlasovalo a jak kdo hlasoval".
 *
 * Záměrně **nic netvrdí** o vztahu mezi tím, co řečník řekl, a tím, jak
 * hlasoval. To je Fáze 3 (`SlovoACin`), která navíc musí projít důkazní
 * bránou. Tady jde o doložený výpis, u kterého si závěr dělá čtenář — proto
 * žádná rez, žádná závažnost, žádné skóre.
 *
 * Tři věci, které se tu vždycky musí ukázat, protože bez nich je výpis
 * zavádějící:
 *   - **fáze a typ hlasování** — procedurální hlasování (pořad schůze,
 *     odročení) není hlasování o věci a nesmí se tak číst,
 *   - **poměr v klubu** — odchylka od klubu je jiný příběh než klubová kázeň,
 *   - **omluva** — omluvený poslanec není nepřítomný poslanec.
 */
export function HlasovaniPrehled({ bod, hlasovani, hlasyRecniku }: HlasovaniPrehledProps) {
  if (!hlasovani || hlasovani.length === 0) return null;

  const hlasyPodleBallotu = new Map<string, { jmeno: string; hlas: VoteValueLedger; omluven: boolean }[]>();
  for (const recnik of hlasyRecniku ?? []) {
    for (const h of recnik.hlasy) {
      const seznam = hlasyPodleBallotu.get(h.ballotId) ?? [];
      seznam.push({ jmeno: recnik.jmeno, hlas: h.hlas, omluven: h.omluven });
      hlasyPodleBallotu.set(h.ballotId, seznam);
    }
  }

  const vecnych = hlasovani.filter((h) => h.jeVecne).length;

  return (
    <section className="mt-12 pt-8 border-t border-linka" aria-labelledby="hlasovani-nadpis">
      <div className="flex items-baseline gap-3 flex-wrap mb-1">
        <h2 id="hlasovani-nadpis" className="font-mono text-[11px] font-bold uppercase tracking-[0.13em] text-inkoust-2">
          Hlasování o tomto bodu
        </h2>
        {bod?.cislo != null && (
          <span className="font-mono text-[11px] text-inkoust-3 tabular-nums">bod {bod.cislo} pořadu schůze</span>
        )}
      </div>
      <p className="font-mono text-[11px] text-inkoust-3 mb-6">
        {hlasovani.length}{" "}
        {hlasovani.length === 1 ? "jmenovité hlasování" : hlasovani.length < 5 ? "jmenovitá hlasování" : "jmenovitých hlasování"}
        {vecnych !== hlasovani.length && <> · {vecnych} věcných, {hlasovani.length - vecnych} procedurálních</>}
      </p>

      <div className="flex flex-col gap-6">
        {hlasovani.map((h) => {
          const hlasy = hlasyPodleBallotu.get(h.ballotId) ?? [];
          return (
            <article key={h.ballotId} className="bg-list border border-linka rounded-sm p-5">
              <div className="flex items-baseline gap-2.5 flex-wrap mb-3">
                <span className="font-mono text-[10px] font-bold uppercase tracking-wider px-2 py-1 rounded-[2px] bg-linka-2 text-inkoust-2">
                  {h.jeVecne ? "věcné hlasování" : "procedurální"}
                </span>
                {h.faze && <span className="font-mono text-[11px] text-inkoust-3">{h.faze}</span>}
                <span className="font-mono text-[11px] text-inkoust-3 tabular-nums">
                  hlasování č. {h.cislo}
                </span>
                <span className="font-mono text-[11px] text-inkoust-3 tabular-nums">
                  {formatDatum(h.datum)} · {h.cas}
                </span>
                <span className="font-mono text-[11px] text-inkoust-2 ml-auto">{getVysledekLabel(h.prijato)}</span>
              </div>

              {h.nazev && (
                <p className="font-serif font-serif-text text-[16px] leading-[1.5] mb-4">{h.nazev}</p>
              )}

              <dl className="flex flex-wrap gap-x-6 gap-y-1 font-mono text-[11.5px] tabular-nums mb-4">
                <div className="flex gap-1.5">
                  <dt className="text-inkoust-3">pro</dt>
                  <dd className="font-semibold">{h.pro}</dd>
                </div>
                <div className="flex gap-1.5">
                  <dt className="text-inkoust-3">proti</dt>
                  <dd className="font-semibold">{h.proti}</dd>
                </div>
                <div className="flex gap-1.5">
                  <dt className="text-inkoust-3">zdrželo se</dt>
                  <dd className="font-semibold">{h.zdrzel}</dd>
                </div>
                <div className="flex gap-1.5">
                  <dt className="text-inkoust-3">nehlasovalo</dt>
                  <dd className="font-semibold">{h.nehlasoval}</dd>
                </div>
              </dl>

              {h.klubyPomer.length > 0 && (
                <div className="mb-4">
                  <h3 className="font-mono text-[10px] font-bold uppercase tracking-[0.13em] text-inkoust-3 mb-2">
                    Po klubech
                  </h3>
                  <div className="overflow-x-auto">
                    <table className="w-full min-w-[420px] font-mono text-[11.5px] tabular-nums">
                      <thead>
                        <tr className="text-inkoust-3 text-left">
                          <th className="font-normal pb-1 pr-4">klub</th>
                          <th className="font-normal pb-1 pr-3 text-right">pro</th>
                          <th className="font-normal pb-1 pr-3 text-right">proti</th>
                          <th className="font-normal pb-1 pr-3 text-right">zdr./nehl.</th>
                          <th className="font-normal pb-1 text-right">nepřihl.</th>
                        </tr>
                      </thead>
                      <tbody>
                        {h.klubyPomer.map((k) => (
                          <tr key={k.klub} className="border-t border-linka-2">
                            <td className="py-1 pr-4">{k.klub}</td>
                            <td className="py-1 pr-3 text-right">{k.pro || "—"}</td>
                            <td className="py-1 pr-3 text-right">{k.proti || "—"}</td>
                            <td className="py-1 pr-3 text-right">{k.zdrzelNeboNehlasoval || "—"}</td>
                            <td className="py-1 text-right">{k.neprihlasen || "—"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {hlasy.length > 0 && (
                <details className="mb-4">
                  <summary className="font-mono text-[11px] text-inkoust-2 cursor-pointer hover:text-inkoust">
                    Jak hlasovali řečníci této rozpravy ({hlasy.length})
                  </summary>
                  <ul className="mt-3 grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-1">
                    {hlasy
                      .slice()
                      .sort((a, b) => a.jmeno.localeCompare(b.jmeno, "cs"))
                      .map((r) => (
                        <li key={r.jmeno} className="flex items-baseline justify-between gap-3 border-b border-linka-2 py-1">
                          <span className="font-serif font-serif-text text-[14px]">{r.jmeno}</span>
                          <span className={`font-mono text-[10.5px] uppercase tracking-wider shrink-0 ${getHlasClass(r.hlas)}`}>
                            {getHlasZnacka(r.hlas)}
                            {r.omluven && <span className="text-inkoust-3 normal-case tracking-normal"> · omluven</span>}
                          </span>
                        </li>
                      ))}
                  </ul>
                </details>
              )}

              <a
                href={h.url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 font-mono text-[11px] text-overeno border-b border-overeno/10 hover:border-overeno pb-0.5 transition-colors"
              >
                Hlasovací lístek na psp.cz
                <ExternalLink className="w-3 h-3" aria-hidden />
              </a>
            </article>
          );
        })}
      </div>
    </section>
  );
}
