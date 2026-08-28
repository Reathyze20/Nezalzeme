import React from "react";
import { notFound } from "next/navigation";
import { DEBATES, slovoCinProRozpravu } from "@/lib/debate";
import { formatDatum } from "@/lib/ui";
import { Replika } from "@/components/rozprava/Replika";
import { HlasovaniPrehled } from "@/components/hlasovani/HlasovaniPrehled";
import { SlovoACin } from "@/components/zaznam/SlovoACin";

export function generateStaticParams() {
  return DEBATES.map((d) => ({ id: d.debateId }));
}

export async function generateMetadata({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const debata = DEBATES.find((d) => d.debateId === id);
  return { title: debata ? `${debata.title} | Nezalžeme.cz` : "Rozprava nenalezena | Nezalžeme.cz" };
}

const STAV_LABEL: Record<string, string> = {
  PROJEDNÁNO: "projednáno",
  SCHVÁLENO: "schváleno",
  ZAMÍTNUTO: "zamítnuto",
  V_ŘEŠENÍ: "v řešení",
};

export default async function RozpravaPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const debata = DEBATES.find((d) => d.debateId === id);
  if (!debata) notFound();

  const slovoCin = slovoCinProRozpravu(debata.debateId);

  return (
    <div className="max-w-[880px] mx-auto px-6">
      <div className="pt-8 pb-6 border-b border-inkoust">
        <div className="font-mono text-[11px] uppercase tracking-wide text-inkoust-3">
          {debata.tiskNumber && <>Sněmovní tisk {debata.tiskNumber.replace("ST ", "")} · </>}
          {debata.sessionNumber}. schůze · {formatDatum(debata.date)} · {STAV_LABEL[debata.status]}
        </div>
        <h1 className="font-bold text-[1.5rem] md:text-[2.05rem] leading-[1.14] tracking-[-0.03em] mt-2.5 text-balance">
          {debata.title}
        </h1>
        <p className="font-serif font-serif-text text-[16px] text-inkoust-2 mt-3 max-w-[62ch]">{debata.description}</p>
      </div>

      <div className="pt-3">
        {debata.messages.map((m) => (
          <Replika key={m.messageId} message={m} sessionNumber={debata.sessionNumber} />
        ))}
      </div>

      {slovoCin.length > 0 && (
        <section className="mt-12 pt-8 border-t border-linka" aria-labelledby="slovo-cin-rozprava">
          <h2 id="slovo-cin-rozprava" className="font-mono text-[11px] font-bold uppercase tracking-[0.13em] text-inkoust-2">
            Slovo a čin v této rozpravě
          </h2>
          <p className="font-serif font-serif-text text-[14.5px] leading-[1.55] text-inkoust-2 mt-2 max-w-[62ch]">
            Postoje, které tu zazněly, vedle jmenovitého hlasu o témže tisku. Porovnává se jen
            s finálním hlasováním, které jako finální označuje sama Sněmovna.
          </p>
          <div className="mt-4">
            {slovoCin.map((z) => (
              <SlovoACin key={z.id} zaznam={z} />
            ))}
          </div>
        </section>
      )}

      <div className="pb-16">
        <HlasovaniPrehled
          bod={debata.bod}
          hlasovani={debata.hlasovani ?? []}
          hlasyRecniku={debata.hlasyRecniku}
        />
      </div>
    </div>
  );
}
