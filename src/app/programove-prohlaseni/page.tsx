import React from "react";
import { PROGRAMOVA_VERNOST } from "@/lib/debate";
import { ZavazekKarta } from "@/components/programove-prohlaseni/ZavazekKarta";

export const metadata = { title: "Programová věrnost | Nezalžeme.cz" };

export default function ProgramovaVernostPage() {
  return (
    <div className="max-w-6xl mx-auto px-6">
      <div className="pt-10 pb-2">
        <h1 className="text-[21px] font-bold tracking-[-0.018em]">Programová věrnost</h1>
        <p className="font-serif font-serif-text text-[15px] text-inkoust-2 mt-1.5 max-w-[68ch]">
          Slib z Programového prohlášení vlády (schváleno 5. 1. 2026, koalice ANO 2011,
          Motoristé sobě a SPD) vedle hlasování těchto klubů o sněmovním tisku, který mu podle
          modelu — a nezávislého přezkumu — může odpovídat. Srovnáváme jen název tisku, ne jeho
          plné znění, a nevynášíme verdikt splněno/nesplněno. Metodika a pojistky proti křivému
          spárování jsou na stránce{" "}
          <a href="/metodika" className="text-overeno border-b border-overeno/10 hover:border-overeno">
            Metodika
          </a>
          .
        </p>
      </div>

      {PROGRAMOVA_VERNOST.length === 0 ? (
        <p className="font-mono text-[13px] text-inkoust-3 py-10">
          Zatím žádná položka neprošla ověřením. Fáze ještě neběžela, nebo žádné spárování
          neobstálo v nezávislém přezkumu.
        </p>
      ) : (
        <div>
          {PROGRAMOVA_VERNOST.map((zaznam) => (
            <ZavazekKarta key={zaznam.id} zaznam={zaznam} />
          ))}
        </div>
      )}
    </div>
  );
}
