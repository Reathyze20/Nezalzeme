import "server-only";
import fs from "node:fs";
import path from "node:path";
import { InterniPrehled } from "@/types/interni";

const INTERNI_PREHLED_PATH = path.join(process.cwd(), "pipeline", "data", "interni_prehled.json");

/**
 * Načte interní přehled ze souboru, který zapisuje výhradně
 * `pipeline/journalist_tool.py`. `null`, pokud soubor ještě neexistuje
 * (fáze zatím neběžela) — stránka to musí rozlišit od prázdného seznamu.
 */
export function nactiInterniPrehled(): InterniPrehled | null {
  try {
    const raw = fs.readFileSync(INTERNI_PREHLED_PATH, "utf-8");
    return JSON.parse(raw) as InterniPrehled;
  } catch {
    return null;
  }
}
