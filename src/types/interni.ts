/**
 * Typy pro `/interni/prehled` (Fáze 6, novinářský nástroj) — čtou se z
 * `pipeline/data/interni_prehled.json`, který produkuje výhradně
 * `pipeline/journalist_tool.py`. Záměrně mimo `debate.ts`/`Annotation`:
 * tohle pásmo (NLI 0,50–0,80) nikdy neprošlo tribunálem, takže nesmí sdílet
 * typový tvar s ověřenými, veřejně publikovanými nálezy.
 */

export interface InterniOsoba {
  messageId: string;
  speaker: string;
  idOsoba: string | null;
  party: string | null;
  date: string;
  stenoUrl: string;
  citace: string;
  tvrzeni: string;
  casovyRamec: string;
  hlidacProfil?: {
    url: string;
    funkce: { role: string; organizace: string; od: string | null; do: string | null }[];
    firemniVazby: string[];
  };
}

export interface InterniClanek {
  url: string;
  title: string;
  popis: string;
}

export interface InterniLead {
  leadId: string;
  contradiction: number;
  similarity: number;
  vyrokA: InterniOsoba;
  vyrokB: InterniOsoba;
  hlidacStatu: null;
  makrokontext: { narrative?: string; month?: string; data_sources?: string[] } | null;
  clanky: InterniClanek[];
}

/**
 * Lead rolového obratu (Fáze 6b) — z `media_role_flip.load_leads()`, VŠECHNY
 * uložené leady (schválené i ne). Publikaci na veřejný web dělá výhradně
 * `promote_media_lead.py` + `export_web.py`; tady se jen zobrazuje fronta.
 */
export interface RolovyObratLead {
  id: string;
  idOsoba: string;
  politik: string;
  receno: {
    citace: string;
    rolePriCitatu: string;
    zdroj: { url: string; medium: string; datumClanku: string; timestampSeconds?: number };
  };
  postoj: "PRO" | "PROTI";
  postojOduvodneni: string;
  tisk: { cislo: string; nazev: string; url: string };
  hlasovani: {
    idHlasovani: string;
    url: string;
    cislo: number;
    schuze: number;
    vysledekSlovy: string;
    prijat: boolean;
    historieUrl: string;
    hlas: string;
    omluven: boolean;
    klub: string;
    klubPomer: { pro: number; proti: number; zdrzelNeboNehlasoval: number; neprihlasen: number } | null;
    rolePriHlasovani: string;
  };
  shoda: "SHODA" | "NESHODA" | "NEHLASOVAL";
  parovani?: string;
  obhajoba?: string;
  /** Nastavuje jen `promote_media_lead.py` — dokud `false`, nejde na veřejný web. */
  schvaleno: boolean;
  schvalenoAt: string | null;
  parovaniPlati: boolean;
  rozporMizi: boolean;
}

export interface InterniPrehled {
  generatedAt: string;
  nliBand: [number, number];
  poznamka: string;
  leadCount: number;
  hlidacStatuZapnuto: boolean;
  firecrawlZapnuto: boolean;
  leads: InterniLead[];
  rolovyObrat: RolovyObratLead[];
}
