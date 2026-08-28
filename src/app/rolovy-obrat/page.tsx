import React from "react";
import { ROLOVY_OBRAT } from "@/lib/debate";
import { RolovyObrat } from "@/components/zaznam/RolovyObrat";

export const metadata = { title: "Rolový obrat | Nezalžeme.cz" };

export default function RolovyObratPage() {
  return (
    <div className="max-w-6xl mx-auto px-6">
      <div className="pt-10 pb-2">
        <h1 className="text-[21px] font-bold tracking-[-0.018em]">Rolový obrat</h1>
        <p className="font-serif font-serif-text text-[15px] text-inkoust-2 mt-1.5 max-w-[68ch]">
          Co politici napříč politickým spektrem říkali, dokud byli v opozici, vedle toho, jak
          později hlasovali ve vládní straně — a naopak. Na rozdíl od ostatních částí rejstříku
          tu citace nepochází ze stenozáznamu, ale z novinového rozhovoru nebo vyjádření, takže
          každý pár před zveřejněním ručně přečetl a schválil redaktor Nezalžeme.cz, ne jen
          algoritmus. Odkaz na původní článek je u každé citace. Metodika a pojistky jsou na
          stránce{" "}
          <a href="/metodika" className="text-overeno border-b border-overeno/10 hover:border-overeno">
            Metodika
          </a>
          .
        </p>
      </div>

      {ROLOVY_OBRAT.length === 0 ? (
        <p className="font-mono text-[13px] text-inkoust-3 py-10">
          Zatím žádná položka neprošla schválením. Fáze ještě neběžela, nebo žádný nalezený pár
          zatím nepotvrdil redaktor.
        </p>
      ) : (
        <div>
          {ROLOVY_OBRAT.map((zaznam) => (
            <RolovyObrat key={zaznam.id} zaznam={zaznam} />
          ))}
        </div>
      )}
    </div>
  );
}
