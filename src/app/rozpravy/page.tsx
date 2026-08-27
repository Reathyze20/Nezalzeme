import React from "react";
import { ANALYZA, DEBATES } from "@/lib/debate";
import { RozpravySeznam } from "./RozpravySeznam";

export const metadata = { title: "Rozpravy | Nezalžeme.cz" };

export default function RozpravyPage() {
  const razene = [...DEBATES].sort((a, b) => b.date.localeCompare(a.date));

  return (
    <div className="max-w-6xl mx-auto px-6">
      <div className="pt-10 pb-2">
        <h1 className="text-[21px] font-bold tracking-[-0.018em]">Rozpravy</h1>
        <p className="font-serif font-serif-text text-[15px] text-inkoust-2 mt-1.5 max-w-[62ch]">
          {ANALYZA.ceka
            ? "Rozpravy tak, jak proběhly, přepsané ze stenoprotokolu. Značky zatím nejsou u žádné z nich — porovnání s dřívějšími výroky a s hlasováním ještě neproběhlo."
            : "Rozpravy z uplynulých 6 měsíců tak, jak proběhly. Sporné úseky mají v místě, kde padly, rozbalitelný záznam a kontext."}
        </p>
      </div>

      <RozpravySeznam debates={razene} analyzaCeka={ANALYZA.ceka} />
    </div>
  );
}
