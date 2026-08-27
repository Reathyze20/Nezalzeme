"use client";

import React, { useState } from "react";
import { Link2, Check } from "lucide-react";

interface AkceZaznamuProps {
  kotva: string;
}

export function KopirovatOdkaz({ kotva }: AkceZaznamuProps) {
  const [zkopirovano, setZkopirovano] = useState(false);

  const handleClick = async () => {
    try {
      const url = `${window.location.origin}${window.location.pathname}#${kotva}`;
      await navigator.clipboard.writeText(url);
      setZkopirovano(true);
      setTimeout(() => setZkopirovano(false), 1800);
    } catch {
      // schránka nedostupná — tiše ignorujeme, odkaz jde zkopírovat i ručně
    }
  };

  return (
    <button
      type="button"
      onClick={handleClick}
      className="inline-flex items-center gap-1.5 font-mono text-[10.5px] tracking-wide px-2.5 py-1.5 border border-linka rounded-sm text-inkoust-2 hover:text-inkoust hover:border-inkoust-3 transition-colors"
    >
      {zkopirovano ? <Check className="w-3 h-3" /> : <Link2 className="w-3 h-3" />}
      {zkopirovano ? "Zkopírováno" : "Zkopírovat odkaz"}
    </button>
  );
}
