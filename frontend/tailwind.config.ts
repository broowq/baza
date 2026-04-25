import type { Config } from "tailwindcss";
import tailwindAnimate from "tailwindcss-animate";

/**
 * БАЗА — Cinematic Glass theme.
 * See /DESIGN.md for full system spec (rondesignlab Public Transit OS reference).
 */
const config: Config = {
  darkMode: "class",
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./lib/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Geist", "Inter", "system-ui", "sans-serif"],
        mono: ["Geist Mono", "ui-monospace", "monospace"],
      },
      fontWeight: {
        // Geist exposes the full weight range; expose 200/300 for hero numerics.
        extralight: "200",
        light: "300",
      },
      colors: {
        // Canvas tokens — see DESIGN.md §2
        canvas: "hsl(var(--canvas))",
        "canvas-raised": "hsl(var(--canvas-raised))",
        fg: "hsl(var(--fg))",
        // Status palette
        "status-online": "#34D399",
        "status-offline": "#F43F5E",
        "status-warning": "#FBBF24",
        brand: "#FF6A00",

        // Shadcn-compat (for components that still reference these directly).
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
        popover: {
          DEFAULT: "hsl(var(--popover))",
          foreground: "hsl(var(--popover-foreground))",
        },
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))",
        },
        border: "hsl(var(--border) / 0.08)",
        input: "hsl(var(--input) / 0.08)",
        ring: "hsl(var(--ring) / 0.24)",
      },
      borderRadius: {
        // 24px is the hero radius for glass cards; 16px content; 12px compact.
        lg: "1rem",          // 16px
        md: "0.75rem",       // 12px
        sm: "0.5rem",        // 8px
        xl: "1rem",
        "2xl": "1rem",
        "3xl": "1.5rem",     // 24px — hero glass
      },
      boxShadow: {
        // Inset highlights on glass — top-edge "lit" feel
        "glass-inset": "inset 0 1px 0 0 rgba(255, 255, 255, 0.08)",
        "glass-inset-strong": "inset 0 1px 0 0 rgba(255, 255, 255, 0.14)",
        // Status glows
        "glow-online": "0 0 8px rgba(52, 211, 153, 0.7)",
        "glow-offline": "0 0 8px rgba(244, 63, 94, 0.6)",
        "glow-warning": "0 0 8px rgba(251, 191, 36, 0.6)",
        "glow-brand": "0 0 24px rgba(255, 106, 0, 0.35)",
      },
      backdropBlur: {
        "3xl": "40px",
      },
      keyframes: {
        "fade-in": {
          from: { opacity: "0" },
          to: { opacity: "1" },
        },
        "slide-up": {
          from: { opacity: "0", transform: "translateY(8px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        "pulse-glow": {
          "0%, 100%": { transform: "scale(1)", opacity: "1" },
          "50%": { transform: "scale(1.15)", opacity: "0.85" },
        },
        "draw-line": {
          from: { strokeDashoffset: "1000" },
          to: { strokeDashoffset: "0" },
        },
        "accordion-down": {
          from: { height: "0" },
          to: { height: "var(--radix-accordion-content-height)" },
        },
        "accordion-up": {
          from: { height: "var(--radix-accordion-content-height)" },
          to: { height: "0" },
        },
      },
      animation: {
        "fade-in": "fade-in 300ms ease-out",
        "slide-up": "slide-up 400ms ease-out",
        "pulse-glow": "pulse-glow 2s ease-in-out infinite",
        "draw-line": "draw-line 800ms ease-out forwards",
        "accordion-down": "accordion-down 200ms ease-out",
        "accordion-up": "accordion-up 200ms ease-out",
      },
    },
  },
  plugins: [tailwindAnimate],
};

export default config;
