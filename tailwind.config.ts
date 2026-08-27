import type { Config } from "tailwindcss";

export default {
  darkMode: ["class"],
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
    // Metadata anomálií a závažností se skládají v src/lib; bez tohoto glob
    // by Tailwind jejich třídy nevygeneroval a odznaky by zůstaly bez barvy.
    "./src/lib/**/*.{js,ts,jsx,tsx}",
    "./src/data/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        border: "hsl(var(--border))",
        papir: "hsl(var(--papir))",
        list: "hsl(var(--list))",
        "list-2": "hsl(var(--list-2))",
        inkoust: {
          DEFAULT: "hsl(var(--inkoust))",
          2: "hsl(var(--inkoust-2))",
          3: "hsl(var(--inkoust-3))",
        },
        linka: {
          DEFAULT: "hsl(var(--linka))",
          2: "hsl(var(--linka-2))",
        },
        dilek: "hsl(var(--dilek))",
        overeno: {
          DEFAULT: "hsl(var(--overeno))",
          tl: "hsl(var(--overeno-tl) / 0.1)",
        },
        rozpor: {
          DEFAULT: "hsl(var(--rozpor))",
          tl: "hsl(var(--rozpor-tl) / 0.1)",
        },
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
      fontFamily: {
        sans: ["var(--font-roboto)", "ui-sans-serif", "system-ui", "sans-serif"],
        serif: ["var(--font-roboto-serif)", "Georgia", "serif"],
        mono: ["var(--font-roboto-mono)", "ui-monospace", "monospace"],
      },
      keyframes: {
        "accordion-down": {
          from: { height: "0" },
          to: { height: "var(--radix-accordion-content-height)" },
        },
        "accordion-up": {
          from: { height: "var(--radix-accordion-content-height)" },
          to: { height: "0" },
        },
        "pulse-glow": {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0.6" },
        }
      },
      animation: {
        "accordion-down": "accordion-down 0.2s ease-out",
        "accordion-up": "accordion-up 0.2s ease-out",
        "pulse-glow": "pulse-glow 2s cubic-bezier(0.4, 0, 0.6, 1) infinite",
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
} satisfies Config;
