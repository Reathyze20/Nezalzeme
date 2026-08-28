import React from "react";
import Link from "next/link";
import { ExternalLink } from "lucide-react";
import { SlovoCin, VoteValue } from "@/types/debate";
import { formatDatum, getVoteValueLabel } from "@/lib/ui";

interface SlovoACinProps {
  zaznam: SlovoCin;
}

const POSTOJ_LABEL: Record<string, string> = {
  PRO: "podpořil návrh",
  PROTI: "odmítl návrh",
  NEUTRALNI: "bez stanoviska",
  NEURCITELNE: "neurčitelné",
};

/**
 * Popisek shody. Pro `NEHLASOVAL` závisí na tom, co se skutečně stalo:
 * „zdržel se" je odevzdaný hlas, ne nepřítomnost, a tvrdit u něj „hlas
 * nepadl" by bylo nepřesné o poslanci, který v sále byl a zmáčkl tlačítko.
 */
function shodaLabel(shoda: SlovoCin["shoda"], hlas: VoteValue): string {
  if (shoda === "SHODA") return "Postoj a hlas se shodují";
  if (shoda === "NESHODA") return "Postoj v rozpravě a hlas se rozcházejí";
  return hlas === "ZDRZEL_SE"
    ? "Postoj zazněl, u hlasování se poslanec zdržel"
    : "Postoj zazněl, poslanec nehlasoval";
}

/**
 * Doklad „řečeno vs. hlasováno" — jádro Fáze 3.
 *
 * Vědomě **neobviňuje**. Žádná rez, žádná závažnost, žádné procento jistoty:
 * dvě karty vedle sebe, obojí s odkazem na originál, a závěr si dělá čtenář.
 * Předchozí engine na tomhle místě tvrdil „lhal" na základě dat, která to
 * neunesla; tenhle ukazuje výrok, hlas, poměr v klubu a fázi projednávání
 * a nechává je mluvit.
 *
 * Tři údaje, které tu musí zůstat i za cenu delší karty, protože bez nich
 * je rozchod postoje a hlasu zavádějící:
 *   - **poměr v klubu** — hlasovat s klubem proti vlastnímu slovu je jiný
 *     příběh než hlasovat proti klubu,
 *   - **omluva** — omluvený poslanec nehlasoval, neutekl,
 *   - **odkaz na historii tisku** — doklad, že tohle bylo *finální* hlasování
 *     o tom zákoně, a ne jeden z desítek pozměňovacích návrhů.
 */
export function SlovoACin({ zaznam }: SlovoACinProps) {
  const { receno, hlasovani, tisk, shoda, postoj } = zaznam;
  const jeNeshoda = shoda === "NESHODA";
  const klub = hlasovani.klubPomer;

  return (
    <article id={zaznam.id} className="py-8 border-b border-linka-2 scroll-mt-20">
      <div className="flex items-baseline gap-3 flex-wrap mb-4">
        <span className="font-mono text-[10.5px] font-bold uppercase tracking-wider px-2 py-1 rounded-[2px] bg-linka-2 text-inkoust-2">
          Slovo a čin
        </span>
        <span className="font-mono text-[11px] text-inkoust-2">
          {shodaLabel(shoda, hlasovani.hlas)}
        </span>
        <span className="font-mono text-[11px] text-inkoust-3 tabular-nums">
          sněmovní tisk {tisk.cislo}
        </span>
        <span className="font-mono text-[11.5px] text-inkoust-3 ml-auto">
          {formatDatum(receno.datum)}
        </span>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-[1fr_58px_1fr] items-stretch">
        {/* ---------- ŘEČENO ---------- */}
        <div className="bg-list border border-linka rounded-sm p-5 flex flex-col gap-3 shadow-sm">
          <span className="font-mono text-[10px] font-bold uppercase tracking-[0.13em] text-inkoust-3">
            Řečeno v rozpravě
          </span>
          <blockquote className="font-serif font-serif-text text-[17px] leading-[1.55] flex-1">
            „{receno.citace}"
          </blockquote>
          <div className="font-mono text-[11px] text-inkoust-3">
            čteno jako: <span className="text-inkoust-2">{POSTOJ_LABEL[postoj] ?? postoj}</span>
          </div>
          <div className="flex flex-col gap-1.5">
            <Link
              href={`/rozprava/${receno.debateId}#${zaznam.messageId}`}
              className="inline-flex items-center gap-1.5 self-start font-mono text-[11px] text-overeno border-b border-overeno/10 hover:border-overeno pb-0.5 transition-colors"
            >
              zobrazit v rozpravě
            </Link>
            <a
              href={receno.stenoUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 self-start font-mono text-[11px] text-overeno border-b border-overeno/10 hover:border-overeno pb-0.5 transition-colors"
            >
              stenozáznam na psp.cz
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
            {jeNeshoda ? "≠" : "="}
          </span>
        </div>

        {/* ---------- HLASOVÁNO ---------- */}
        <div className="bg-list border border-linka rounded-sm p-5 flex flex-col gap-3 shadow-sm border-t-[3px] md:border-t md:border-l-[3px] md:border-l-inkoust-3 border-t-inkoust-3">
          <span className="font-mono text-[10px] font-bold uppercase tracking-[0.13em] text-inkoust-3">
            Hlasováno
          </span>

          <div className="flex items-baseline gap-2 flex-wrap">
            <span className="font-mono text-[20px] font-extrabold tracking-tight">
              {getVoteValueLabel(hlasovani.hlas).toUpperCase()}
            </span>
            {hlasovani.omluven && (
              <span className="font-mono text-[11px] text-inkoust-3">· omluven</span>
            )}
          </div>

          <p className="font-serif font-serif-text text-[15px] leading-[1.5] text-inkoust-2 flex-1">
            {hlasovani.nazev}
          </p>

          <dl className="font-mono text-[11px] text-inkoust-3 flex flex-col gap-1 tabular-nums">
            <div className="flex gap-2">
              <dt>hlasování</dt>
              <dd className="text-inkoust-2">
                č. {hlasovani.cislo} · {hlasovani.schuze}. schůze · {hlasovani.vysledekSlovy}
              </dd>
            </div>
            {klub && (
              <div className="flex gap-2">
                <dt>klub {hlasovani.klub}</dt>
                <dd className="text-inkoust-2">
                  {klub.pro} pro · {klub.proti} proti · {klub.zdrzelNeboNehlasoval} zdr./nehl.
                </dd>
              </div>
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
              historie tisku — doklad finálního hlasování
              <ExternalLink className="w-3 h-3" aria-hidden />
            </a>
          </div>
        </div>
      </div>

      <p className="mt-4 font-mono text-[10.5px] text-inkoust-3 leading-[1.55] max-w-[80ch]">
        Postoj z výroku určil jazykový model; jeho odůvodnění: „{zaznam.postojOduvodneni}"
        {" "}Hlas i to, že šlo o finální hlasování o tomto tisku, pocházejí z otevřených dat
        a stránek Sněmovny — obojí je odkazované výše. Rozchod postoje a hlasu sám o sobě
        neznamená nepravdu: návrh se mezi rozpravou a hlasováním mění a klub se dohaduje.
      </p>
    </article>
  );
}
