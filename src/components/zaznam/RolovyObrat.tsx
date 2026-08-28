import React from "react";
import { ExternalLink } from "lucide-react";
import { RolovyObrat as RolovyObratZaznam, PolitickaRole, VoteValue } from "@/types/debate";
import { formatDatum, getVoteValueLabel } from "@/lib/ui";
import { formatTimestamp } from "@/lib/media";

/**
 * U videa (Fáze 6c) přidá `t=Ns` (YouTube podporuje na obou tvarech domény),
 * jinak URL beze změny. Časová značka je jen orientační pozice v přepisu —
 * ne forenzní forced alignment (viz `RolovyObrat.timestampSeconds` v `debate.ts`).
 */
function withTimestamp(url: string, seconds?: number): string {
  if (seconds === undefined) return url;
  try {
    const u = new URL(url);
    u.searchParams.set("t", `${Math.max(0, Math.floor(seconds))}s`);
    return u.toString();
  } catch {
    return url;
  }
}

interface RolovyObratProps {
  zaznam: RolovyObratZaznam;
}

const ROLE_LABEL: Record<PolitickaRole, string> = {
  MINISTER: "ministr",
  COALITION_DEPUTY: "poslanec koalice",
  OPPOSITION_DEPUTY: "poslanec opozice",
  INDEPENDENT: "nezávislý",
};

const POSTOJ_LABEL: Record<string, string> = {
  PRO: "podpořil návrh",
  PROTI: "odmítl návrh",
};

function shodaLabel(shoda: RolovyObratZaznam["shoda"], hlas: VoteValue): string {
  if (shoda === "SHODA") return "Postoj a pozdější hlas se shodují";
  if (shoda === "NESHODA") return "Postoj v opozici a pozdější hlas se rozcházejí";
  return hlas === "ZDRZEL_SE"
    ? "Postoj zazněl, u hlasování se poslanec zdržel"
    : "Postoj zazněl, poslanec nehlasoval";
}

/**
 * Doklad „řekl v opozici / hlasoval ve vládě" (nebo naopak) — Fáze 6b.
 *
 * Jediná veřejná komponenta enginu, jejíž levá karta NENÍ stenozáznam.
 * Proto navíc oproti `SlovoACin`: viditelné médium a datum článku, odkaz na
 * originál vždy nahoře (ne dole v patičce), a patička vysvětluje, že tenhle
 * konkrétní lead schválil ručně operátor — ne jen strojová brána.
 */
export function RolovyObrat({ zaznam }: RolovyObratProps) {
  const { receno, hlasovani, tisk, shoda, postoj } = zaznam;
  const jeNeshoda = shoda === "NESHODA";
  const klub = hlasovani.klubPomer;

  return (
    <article id={zaznam.id} className="py-8 border-b border-linka-2 scroll-mt-20">
      <div className="flex items-baseline gap-3 flex-wrap mb-4">
        <span className="font-mono text-[10.5px] font-bold uppercase tracking-wider px-2 py-1 rounded-[2px] bg-linka-2 text-inkoust-2">
          Rolový obrat
        </span>
        <span className="font-mono text-[13px] font-semibold">{zaznam.politik}</span>
        <span className="font-mono text-[11px] text-inkoust-2">{shodaLabel(shoda, hlasovani.hlas)}</span>
        <span className="font-mono text-[11.5px] text-inkoust-3 ml-auto">
          schváleno {formatDatum(zaznam.schvalenoAt)}
        </span>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-[1fr_58px_1fr] items-stretch">
        {/* ---------- ŘEČENO (novinový článek) ---------- */}
        <div className="bg-list border border-linka rounded-sm p-5 flex flex-col gap-3 shadow-sm">
          <span className="font-mono text-[10px] font-bold uppercase tracking-[0.13em] text-inkoust-3">
            Řečeno jako {ROLE_LABEL[receno.rolePriCitatu]}
          </span>
          <blockquote className="font-serif font-serif-text text-[17px] leading-[1.55] flex-1">
            „{receno.citace}"
          </blockquote>
          <div className="font-mono text-[11px] text-inkoust-3">
            čteno jako: <span className="text-inkoust-2">{POSTOJ_LABEL[postoj] ?? postoj}</span>
          </div>
          <div className="font-mono text-[11px] text-inkoust-3">
            {receno.zdroj.medium} · {formatDatum(receno.zdroj.datumClanku)}
          </div>
          <a
            href={withTimestamp(receno.zdroj.url, receno.zdroj.timestampSeconds)}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 self-start font-mono text-[11px] text-overeno border-b border-overeno/10 hover:border-overeno pb-0.5 transition-colors"
          >
            {receno.zdroj.timestampSeconds !== undefined
              ? `originál videa od ${formatTimestamp(receno.zdroj.timestampSeconds)}`
              : "originál článku"}
            <ExternalLink className="w-3 h-3" aria-hidden />
          </a>
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
            Hlasováno jako {ROLE_LABEL[hlasovani.rolePriHlasovani]}
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
            {tisk.nazev}
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
        Citace pochází z novinového článku nebo videa, ne ze stenozáznamu — ověřte ji prosím
        v originále (odkaz výše), než ji použijete dál. Postoj z citace určil jazykový model; jeho
        odůvodnění: „{zaznam.postojOduvodneni}". Hlas i to, že šlo o finální hlasování o tomto
        tisku, pocházejí z otevřených dat Sněmovny. Rozchod postoje a hlasu sám o sobě
        neznamená nepravdu ani pokrytectví — tenhle konkrétní pár před zveřejněním ručně
        posoudil redaktor Nezalžeme.cz, ne jen algoritmus.
      </p>
    </article>
  );
}
