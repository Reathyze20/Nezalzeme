import React from "react";
import Link from "next/link";
import { ANALYZA } from "@/lib/debate";

export function Footer() {
  return (
    <footer className="border-t border-linka mt-16">
      <div className="max-w-6xl mx-auto px-6 py-9 flex flex-col sm:flex-row gap-7 justify-between">
        <div className="font-mono text-[11px] leading-[1.9] text-inkoust-3 max-w-[46ch]">
          NEZALŽEME.CZ
          <br />
          Zdroj dat: stenoprotokoly a hlasování Poslanecké sněmovny Parlamentu ČR (
          <a href="https://www.psp.cz/eknih/" target="_blank" rel="noopener noreferrer" className="text-inkoust-2 hover:text-overeno">
            psp.cz/eknih
          </a>
          ){ANALYZA.ceka
            ? " — přepis bez analýzy, viz banner výše."
            : `. Zkontrolováno ${ANALYZA.zkontrolovano} z ${ANALYZA.vystoupeniCelkem} vystoupení.`}
        </div>
        <div className="font-mono text-[11px] leading-[1.9] text-inkoust-3">
          <Link href="/" className="text-inkoust-2 hover:text-overeno">
            Rejstřík
          </Link>{" "}
          ·{" "}
          <Link href="/rozpravy" className="text-inkoust-2 hover:text-overeno">
            Rozpravy
          </Link>{" "}
          ·{" "}
          <Link href="/metodika" className="text-inkoust-2 hover:text-overeno">
            Metodika
          </Link>{" "}
          ·{" "}
          <Link href="/metodika#namitka" className="text-inkoust-2 hover:text-overeno">
            Namítnout značku
          </Link>
        </div>
      </div>
    </footer>
  );
}
