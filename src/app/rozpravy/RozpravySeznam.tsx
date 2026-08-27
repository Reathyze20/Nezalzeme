"use client";

import React, { useState, useMemo } from "react";
import Link from "next/link";
import { ChevronRight, Search } from "lucide-react";
import { Debate } from "@/types/debate";
import { formatDatum } from "@/lib/ui";
import { cn } from "@/lib/utils";

const STAV_LABEL: Record<string, string> = {
  PROJEDNÁNO: "projednáno",
  SCHVÁLENO: "schváleno",
  ZAMÍTNUTO: "zamítnuto",
  V_ŘEŠENÍ: "v řešení",
};

function znackaSklonovano(pocet: number): string {
  if (pocet === 1) return "značka";
  if (pocet >= 2 && pocet <= 4) return "značky";
  return "značek";
}

function vystoupeniSklonovano(pocet: number): string {
  return "vystoupení";
}

interface RozpravySeznamProps {
  debates: Debate[];
  analyzaCeka: boolean;
}

export function RozpravySeznam({ debates, analyzaCeka }: RozpravySeznamProps) {
  const [dotaz, setDotaz] = useState("");
  const [jenSeZnackou, setJenSeZnackou] = useState(false);

  const filtrovane = useMemo(() => {
    const d = dotaz.trim().toLocaleLowerCase("cs");
    return debates.filter((deb) => {
      const rozporu = deb.messages.reduce((sum, m) => sum + m.annotations.length, 0);
      if (jenSeZnackou && rozporu === 0) return false;
      if (!d) return true;
      const haystack = `${deb.title} ${deb.topic} ${deb.sessionNumber} ${deb.date} ${deb.messages.map((m) => m.speaker).join(" ")}`.toLocaleLowerCase("cs");
      return haystack.includes(d);
    });
  }, [debates, dotaz, jenSeZnackou]);

  return (
    <div>
      <div className="flex items-center justify-between gap-4 flex-wrap py-4">
        <div className="relative w-full sm:w-72">
          <input
            type="search"
            placeholder="Hledat rozpravu, téma, řečníka..."
            value={dotaz}
            onChange={(e) => setDotaz(e.target.value)}
            className="w-full pl-8 pr-3 py-1.5 text-[13px] bg-papir border border-linka rounded-sm placeholder:text-inkoust-3 focus:outline-none focus:border-overeno transition-colors"
          />
          <Search className="w-3.5 h-3.5 text-inkoust-3 absolute left-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setJenSeZnackou(!jenSeZnackou)}
            className={cn(
              "font-sans text-[12px] font-semibold px-3 py-1.5 border rounded-sm transition-colors",
              jenSeZnackou ? "text-overeno border-overeno bg-overeno-tl" : "text-inkoust-2 border-linka hover:text-inkoust hover:border-inkoust-3"
            )}
          >
            Jen se zjištěnými rozpory
          </button>
        </div>
      </div>

      <div className="border-t border-inkoust pb-16">
        {filtrovane.length === 0 ? (
          <p className="font-serif font-serif-text text-[15px] text-inkoust-2 py-10">
            Žádná rozprava neodpovídá zadání.
          </p>
        ) : (
          filtrovane.map((d) => {
            const rozporu = d.messages.reduce((sum, m) => sum + m.annotations.length, 0);
            return (
              <Link
                key={d.debateId}
                href={`/rozprava/${d.debateId}`}
                className="group flex items-start gap-4 py-5 border-b border-linka-2 hover:bg-list transition-colors px-2"
              >
                <div className="flex-1 min-w-0">
                  <div className="font-mono text-[10.5px] uppercase tracking-wide text-inkoust-3">
                    {d.sessionNumber}. schůze · {formatDatum(d.date)} · {STAV_LABEL[d.status] || d.status}
                  </div>
                  <div className="text-[16px] font-medium tracking-[-0.01em] mt-1">{d.title}</div>
                  <p className="font-serif font-serif-text text-[13.5px] text-inkoust-2 mt-1 line-clamp-1">{d.topic}</p>
                </div>
                <div className="font-mono text-[11.5px] text-inkoust-3 tabular-nums shrink-0 pt-0.5">
                  {rozporu > 0
                    ? `${rozporu} ${znackaSklonovano(rozporu)}`
                    : analyzaCeka
                      ? `${d.messages.length} ${vystoupeniSklonovano(d.messages.length)}`
                      : "bez značky"}
                </div>
                <ChevronRight className="w-3.5 h-3.5 text-inkoust-3 opacity-0 group-hover:opacity-100 group-hover:translate-x-0.5 transition-all shrink-0 mt-0.5" />
              </Link>
            );
          })
        )}
      </div>
    </div>
  );
}
