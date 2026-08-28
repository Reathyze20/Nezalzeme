import React from "react";
import { nactiInterniPrehled } from "@/lib/interni";
import { InterniLead, InterniOsoba, RolovyObratLead } from "@/types/interni";

export const dynamic = "force-dynamic";
export const metadata = { title: "Interní přehled | Nezalžeme.cz", robots: { index: false, follow: false } };

function VyrokKarta({ osoba, label }: { osoba: InterniOsoba; label: string }) {
  return (
    <div className="flex-1 min-w-0 p-4 bg-list border border-linka rounded-sm">
      <div className="font-mono text-[10.5px] font-bold uppercase tracking-wider text-inkoust-3">
        {label}
      </div>
      <div className="mt-1.5 font-serif font-serif-text text-[14.5px] leading-[1.55]">
        „{osoba.citace}"
      </div>
      <div className="mt-2.5 font-mono text-[11px] text-inkoust-2 flex flex-wrap gap-x-3 gap-y-1">
        <span className="font-semibold">{osoba.speaker}</span>
        {osoba.party && <span>{osoba.party}</span>}
        <span>{osoba.date}</span>
        {osoba.stenoUrl && (
          <a href={osoba.stenoUrl} target="_blank" rel="noreferrer" className="text-overeno underline">
            stenozáznam
          </a>
        )}
      </div>
      {osoba.hlidacProfil && (
        <div className="mt-2 font-mono text-[10.5px] text-inkoust-3">
          <a href={osoba.hlidacProfil.url} target="_blank" rel="noreferrer" className="text-overeno underline">
            profil na Hlídači státu
          </a>
          {osoba.hlidacProfil.firemniVazby.length > 0 && (
            <span> · firemní vazby: {osoba.hlidacProfil.firemniVazby.join(", ")}</span>
          )}
        </div>
      )}
    </div>
  );
}

function LeadKarta({ lead }: { lead: InterniLead }) {
  return (
    <div className="mb-6 p-4 border border-linka-2 rounded-sm">
      <div className="flex items-center justify-between mb-3">
        <span className="font-mono text-[10.5px] text-inkoust-3">lead {lead.leadId}</span>
        <span className="font-mono text-[11px] tabular-nums text-inkoust-2">
          NLI rozpor {Math.round(lead.contradiction * 100)} % · podobnost {Math.round(lead.similarity * 100)} %
        </span>
      </div>
      <div className="flex flex-col md:flex-row gap-3">
        <VyrokKarta osoba={lead.vyrokA} label="Novější výrok" />
        <VyrokKarta osoba={lead.vyrokB} label="Starší výrok" />
      </div>
      {lead.makrokontext?.narrative && (
        <p className="mt-3 font-mono text-[10.5px] text-inkoust-3">
          makrokontext ({lead.makrokontext.month}): {lead.makrokontext.narrative}
        </p>
      )}
      {lead.clanky.length > 0 && (
        <div className="mt-3">
          <div className="font-mono text-[10.5px] font-bold uppercase tracking-wider text-inkoust-3">
            Dosavadní pokrytí
          </div>
          <ul className="mt-1 space-y-0.5">
            {lead.clanky.map((clanek) => (
              <li key={clanek.url} className="font-mono text-[11px]">
                <a href={clanek.url} target="_blank" rel="noreferrer" className="text-overeno underline">
                  {clanek.title || clanek.url}
                </a>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function RolovyObratKarta({ lead }: { lead: RolovyObratLead }) {
  return (
    <div className="mb-6 p-4 border border-linka-2 rounded-sm">
      <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <span className="font-mono text-[10.5px] text-inkoust-3">lead {lead.id}</span>
          <span className="font-mono text-[12px] font-semibold">{lead.politik}</span>
        </div>
        {lead.schvaleno ? (
          <span className="font-mono text-[10.5px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-[2px] bg-overeno/10 text-overeno">
            schváleno {lead.schvalenoAt}
          </span>
        ) : (
          <span className="font-mono text-[10.5px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-[2px] bg-linka-2 text-inkoust-3">
            čeká na schválení
          </span>
        )}
      </div>
      <div className="flex flex-col md:flex-row gap-3">
        <div className="flex-1 min-w-0 p-3 bg-list border border-linka rounded-sm">
          <div className="font-mono text-[10px] font-bold uppercase tracking-wider text-inkoust-3">
            Řečeno jako {lead.receno.rolePriCitatu}
          </div>
          <div className="mt-1.5 font-serif font-serif-text text-[14px] leading-[1.5]">
            „{lead.receno.citace}"
          </div>
          <div className="mt-2 font-mono text-[10.5px] text-inkoust-3">
            {lead.receno.zdroj.medium} · {lead.receno.zdroj.datumClanku} ·{" "}
            <a href={lead.receno.zdroj.url} target="_blank" rel="noreferrer" className="text-overeno underline">
              originál
            </a>
          </div>
        </div>
        <div className="flex-1 min-w-0 p-3 bg-list border border-linka rounded-sm">
          <div className="font-mono text-[10px] font-bold uppercase tracking-wider text-inkoust-3">
            Hlasováno jako {lead.hlasovani.rolePriHlasovani}
          </div>
          <div className="mt-1.5 font-serif font-serif-text text-[14px] leading-[1.5]">
            {lead.hlasovani.hlas} · {lead.tisk.nazev}
          </div>
          <div className="mt-2 font-mono text-[10.5px] text-inkoust-3">
            shoda: {lead.shoda} · {" "}
            <a href={lead.hlasovani.url} target="_blank" rel="noreferrer" className="text-overeno underline">
              hlasovací lístek
            </a>
          </div>
        </div>
      </div>
      <div className="mt-3 font-mono text-[10.5px] text-inkoust-3 space-y-1">
        <div>
          párování: {lead.parovaniPlati ? "platí" : "OPONENT ZAMÍTL"} — {lead.parovani}
        </div>
        {lead.obhajoba && (
          <div>obhájce k neshodě: {lead.rozporMizi ? "rozpor mizí" : "rozpor OBSTÁL"} — {lead.obhajoba}</div>
        )}
      </div>
      {!lead.schvaleno && (
        <div className="mt-3 font-mono text-[11px] text-inkoust-2">
          Ke schválení: <code className="bg-list px-1 py-0.5 rounded-[2px]">python pipeline/promote_media_lead.py --lead-id {lead.id}</code>
        </div>
      )}
    </div>
  );
}

export default function InterniPrehledPage() {
  const prehled = nactiInterniPrehled();

  return (
    <div className="max-w-5xl mx-auto px-6">
      <div className="pt-10 pb-4">
        <h1 className="text-[21px] font-bold tracking-[-0.018em]">Interní přehled — pásmo k prošetření</h1>
        <div className="mt-2 p-3 bg-list border border-linka rounded-sm font-mono text-[11.5px] text-inkoust-2 leading-[1.5]">
          NEVEŘEJNÉ. Tohle není publikovaná značka ani ověřený rozpor — jde o slabší signál
          (NLI 0,50–0,80), který nikdy neprošel Tribunálem. Podklad k vlastnímu prošetření,
          ne hotové obvinění. Nikdy neodkazovat ani necitovat bez nezávislého ověření zdroje.
        </div>
      </div>

      {!prehled ? (
        <p className="font-mono text-[13px] text-inkoust-3 py-10">
          Soubor `pipeline/data/interni_prehled.json` neexistuje. Spusť
          `python pipeline/journalist_tool.py`.
        </p>
      ) : (
        <>
          <div className="font-mono text-[11px] text-inkoust-3 mb-4">
            {prehled.leadCount} leadů · vygenerováno {prehled.generatedAt} ·{" "}
            {prehled.hlidacStatuZapnuto ? "Hlídač státu zapnut" : "Hlídač státu vypnut (chybí token)"} ·{" "}
            {prehled.firecrawlZapnuto ? "Firecrawl zapnut" : "Firecrawl vypnut (chybí klíč)"}
          </div>
          {prehled.leads.length === 0 ? (
            <p className="font-mono text-[13px] text-inkoust-3 py-10">Žádné leady v pásmu.</p>
          ) : (
            prehled.leads.map((lead) => <LeadKarta key={lead.leadId} lead={lead} />)
          )}

          <div className="pt-10 pb-4">
            <h2 className="text-[16px] font-bold tracking-[-0.018em]">
              Rolový obrat v médiích (Fáze 6b)
            </h2>
            <p className="mt-1.5 font-mono text-[11px] text-inkoust-2 leading-[1.5] max-w-[80ch]">
              Fronta k rozhodnutí — schválené i neschválené. Na veřejný web (/rolovy-obrat) jde
              jen to, co ručně schválíš přes <code>promote_media_lead.py</code> po přečtení zdroje.
            </p>
          </div>
          {prehled.rolovyObrat.length === 0 ? (
            <p className="font-mono text-[13px] text-inkoust-3 py-10">
              Žádné leady. Spusť `python pipeline/journalist_tool.py --poslanec "Jméno Příjmení"`.
            </p>
          ) : (
            prehled.rolovyObrat.map((lead) => <RolovyObratKarta key={lead.id} lead={lead} />)
          )}
        </>
      )}
    </div>
  );
}
