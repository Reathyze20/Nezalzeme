import React from "react";
import { cn } from "@/lib/utils";

interface AnnotatedQuoteProps {
  text: string;
  start: number;
  end: number;
  jePosun?: boolean;
  className?: string;
}

/**
 * Vykreslí výrok s dvojitým podtržením přes sporný úsek — korektorská značka
 * místo odznaku vloženého doprostřed věty, aby zůstala čitelná jako věta.
 */
export function AnnotatedQuote({ text, start, end, jePosun, className }: AnnotatedQuoteProps) {
  const pred = text.slice(0, start);
  const sporne = text.slice(start, end);
  const po = text.slice(end);

  return (
    <p className={cn("font-serif font-serif-text text-[17px] leading-[1.55]", className)}>
      „{pred}
      <span className={cn("sporne", jePosun && "sporne--posun")}>{sporne}</span>
      {po}“
    </p>
  );
}
