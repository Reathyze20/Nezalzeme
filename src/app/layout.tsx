import type { Metadata } from "next";
import { Roboto, Roboto_Serif, Roboto_Mono } from "next/font/google";
import "./globals.css";
import { DemoBanner } from "@/components/layout/DemoBanner";
import { ThemeScript } from "@/components/layout/ThemeScript";
import { Navbar } from "@/components/layout/Navbar";
import { Footer } from "@/components/layout/Footer";

const roboto = Roboto({
  variable: "--font-roboto",
  weight: ["400", "500", "700", "900"],
  subsets: ["latin", "latin-ext"],
});

const robotoSerif = Roboto_Serif({
  variable: "--font-roboto-serif",
  style: ["normal", "italic"],
  subsets: ["latin", "latin-ext"],
});

const robotoMono = Roboto_Mono({
  variable: "--font-roboto-mono",
  weight: ["400", "500", "700"],
  subsets: ["latin", "latin-ext"],
});

export const metadata: Metadata = {
  title: "Nezalžeme.cz | Rejstřík výroků poslanců Poslanecké sněmovny ČR",
  description:
    "Ke každému výroku patří záznam. Porovnáváme, co poslanci říkají ve Sněmovně, s tím, co řekli dřív a jak hlasovali — s odkazem na přesné místo ve stenozáznamu.",
  keywords: ["PSP ČR", "Poslanecká sněmovna", "politika", "stenozáznamy", "hlasování", "faktická kontrola", "parlament"],
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="cs" suppressHydrationWarning>
      <head>
        <ThemeScript />
      </head>
      <body
        className={`${roboto.variable} ${robotoSerif.variable} ${robotoMono.variable} min-h-screen flex flex-col bg-papir text-inkoust font-sans antialiased transition-colors`}
      >
        <DemoBanner />
        <Navbar />
        <main className="flex-1">{children}</main>
        <Footer />
      </body>
    </html>
  );
}
