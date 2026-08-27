"use client";

import React, { useState, useEffect } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { Search, Moon, Sun } from "lucide-react";
import { cn } from "@/lib/utils";

const ODKAZY = [
  { href: "/", label: "Rejstřík" },
  { href: "/rozpravy", label: "Rozpravy" },
  { href: "/metodika", label: "Metodika" },
];

export function Navbar() {
  const pathname = usePathname();
  const router = useRouter();
  const [dotaz, setDotaz] = useState("");
  const [tmavy, setTmavy] = useState(false);

  useEffect(() => {
    setTmavy(document.documentElement.classList.contains("dark"));
  }, []);

  const prepniMotiv = () => {
    const dalsi = !tmavy;
    setTmavy(dalsi);
    document.documentElement.classList.toggle("dark", dalsi);
    try {
      localStorage.setItem("motiv", dalsi ? "tmavy" : "svetly");
    } catch {
      // localStorage nedostupné — motiv se prostě neuloží mezi návštěvami
    }
  };

  const handleHledat = (e: React.FormEvent) => {
    e.preventDefault();
    router.push(dotaz.trim() ? `/?q=${encodeURIComponent(dotaz.trim())}` : "/");
  };

  const jeAktivni = (href: string) => (href === "/" ? pathname === "/" : pathname.startsWith(href));

  return (
    <header className="sticky top-0 z-30 w-full border-b border-linka bg-papir/92 backdrop-blur-md">
      <div className="max-w-6xl mx-auto px-6 h-[66px] flex items-center gap-7">
        <Link href="/" className="flex flex-col gap-px shrink-0">
          <span className="font-extrabold text-[19px] tracking-[0.045em]">NEZALŽEME</span>
          <span className="hidden sm:block font-mono text-[10px] text-inkoust-3 tracking-wide">
            veřejná kontrola výroků v Poslanecké sněmovně
          </span>
        </Link>

        <nav className="hidden sm:flex items-center gap-1 ml-1" aria-label="Hlavní">
          {ODKAZY.map((o) => (
            <Link
              key={o.href}
              href={o.href}
              aria-current={jeAktivni(o.href) ? "page" : undefined}
              className={cn(
                "text-[13.5px] font-semibold px-2.5 py-1.5 rounded-sm transition-colors",
                jeAktivni(o.href) ? "bg-linka-2 text-inkoust" : "text-inkoust-2 hover:bg-linka-2 hover:text-inkoust"
              )}
            >
              {o.label}
            </Link>
          ))}
        </nav>

        <form onSubmit={handleHledat} className="ml-auto relative flex items-center min-w-0">
          <Search className="absolute left-[11px] w-[13px] h-[13px] text-inkoust-3 pointer-events-none" />
          <input
            type="search"
            value={dotaz}
            onChange={(e) => setDotaz(e.target.value)}
            placeholder="Najít poslance"
            aria-label="Najít poslance"
            className="w-full max-w-[210px] sm:w-[232px] sm:max-w-none bg-list border border-linka rounded-sm text-[13.5px] pl-8 pr-3 py-2 placeholder:text-inkoust-3 focus:outline-none focus:border-overeno transition-colors"
          />
        </form>

        <button
          type="button"
          onClick={prepniMotiv}
          aria-label="Přepnout motiv"
          className="w-[34px] h-[34px] shrink-0 grid place-items-center border border-linka rounded-sm text-inkoust-2 hover:text-inkoust hover:border-inkoust-3 transition-colors"
        >
          {tmavy ? <Sun className="w-[15px] h-[15px]" /> : <Moon className="w-[15px] h-[15px]" />}
        </button>
      </div>
    </header>
  );
}
