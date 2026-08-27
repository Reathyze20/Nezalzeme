import React from "react";
import { notFound } from "next/navigation";
import { DEBATES } from "@/lib/debate";
import { formatDatum } from "@/lib/ui";
import { Replika } from "@/components/rozprava/Replika";

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

      <div className="pt-3 pb-16">
        {debata.messages.map((m) => (
          <Replika key={m.messageId} message={m} sessionNumber={debata.sessionNumber} />
        ))}
      </div>
    </div>
  );
}
