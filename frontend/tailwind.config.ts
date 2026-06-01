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
        // Status palette
        "status-online": "#34D399",
        "status-offline": "#F43F5E",
        "status-warning": "#FBBF24",
        brand: "#A8C5C0",
        // v4 semantic badge text colors (pre-defined for arbitrary-value-free usage)
        "badge-new":       "#C8E0DC",
        "badge-contacted": "#A5D8F8",
        "badge-qualified": "#86EFAC",
        "badge-rejected":  "#FDA4AF",
        "badge-source":    "#FCD34D",
        // v4 elevation-aware surface tints
        "surface-1": "rgba(15,16,20,0.72)",
        "surface-2": "rgba(15,16,20,0.88)",
        "surface-3": "rgba(12,13,16,0.96)",

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
        // 24px is the hero radius for glass cards; 20px xl; 16px content; 12px compact.
        lg: "1rem",          // 16px
        md: "0.75rem",       // 12px
        sm: "0.5rem",        // 8px
        xl: "1.25rem",       // 20px
        "2xl": "1.5rem",     // 24px
        "3xl": "1.5rem",     // 24px — hero glass
        // v4 additions — match --r-* CSS vars
        xs: "0.375rem",      // 6px  --r-xs
      },
      boxShadow: {
        // Inset highlights on glass — top-edge "lit" feel
        "glass-inset": "inset 0 1px 0 0 rgba(255, 255, 255, 0.08)",
        "glass-inset-strong": "inset 0 1px 0 0 rgba(255, 255, 255, 0.14)",
        // Status glows
        "glow-online": "0 0 8px rgba(52, 211, 153, 0.7)",
        "glow-offline": "0 0 8px rgba(244, 63, 94, 0.6)",
        "glow-warning": "0 0 8px rgba(251, 191, 36, 0.6)",
        // v4 elevation scale — mirrors --elev-1/2/3 CSS vars
        "elev-1":
          "inset 0 1px 0 rgba(255,255,255,0.055), 0 1px 2px rgba(0,0,0,0.30), 0 8px 24px -12px rgba(0,0,0,0.55)",
        "elev-2":
          "inset 0 1px 0 rgba(255,255,255,0.08), 0 2px 4px rgba(0,0,0,0.35), 0 20px 48px -16px rgba(0,0,0,0.70), 0 0 0 1px rgba(168,197,192,0.10)",
        "elev-3":
          "inset 0 1px 0 rgba(255,255,255,0.07), 0 4px 8px rgba(0,0,0,0.40), 0 40px 80px -24px rgba(0,0,0,0.85), 0 0 0 1px rgba(255,255,255,0.05)",
        // Mint glow ring for hover/focus
        "ring-mint": "0 0 0 2px rgba(168,197,192,0.55)",
        "mint-glow":
          "0 0 0 1px rgba(168,197,192,0.28), 0 18px 60px -18px rgba(168,197,192,0.35)",
      },
      backdropBlur: {
        "3xl": "40px",
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
        shimmer: {
          from: { backgroundPosition: "200% center" },
          to: { backgroundPosition: "-200% center" },
        },
        // v4 additions
        "fade-in": {
          from: { opacity: "0" },
          to:   { opacity: "1" },
        },
        "slide-in-right": {
          from: { transform: "translateX(100%)" },
          to:   { transform: "translateX(0)" },
        },
        "slide-out-right": {
          from: { transform: "translateX(0)" },
          to:   { transform: "translateX(100%)" },
        },
        "lift-in": {
          from: { opacity: "0", transform: "translateY(6px)" },
          to:   { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: {
        "accordion-down": "accordion-down 200ms ease-out",
        "accordion-up": "accordion-up 200ms ease-out",
        shimmer: "shimmer 1.5s linear infinite",
        // v4 additions
        "fade-in":         "fade-in 180ms ease-out",
        "slide-in-right":  "slide-in-right 240ms cubic-bezier(0.2,0.7,0.2,1)",
        "slide-out-right": "slide-out-right 200ms cubic-bezier(0.4,0,1,1)",
        "lift-in":         "lift-in 200ms cubic-bezier(0.2,0.7,0.2,1)",
      },
    },
  },
  plugins: [tailwindAnimate],
};

export default config;
