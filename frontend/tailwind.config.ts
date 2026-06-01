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
      },
      boxShadow: {
        // Inset highlights on glass — top-edge "lit" feel
        "glass-inset": "inset 0 1px 0 0 rgba(255, 255, 255, 0.08)",
        "glass-inset-strong": "inset 0 1px 0 0 rgba(255, 255, 255, 0.14)",
        // Status glows
        "glow-online": "0 0 8px rgba(52, 211, 153, 0.7)",
        "glow-offline": "0 0 8px rgba(244, 63, 94, 0.6)",
        "glow-warning": "0 0 8px rgba(251, 191, 36, 0.6)",
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
      },
      animation: {
        "accordion-down": "accordion-down 200ms ease-out",
        "accordion-up": "accordion-up 200ms ease-out",
        shimmer: "shimmer 1.5s linear infinite",
      },
    },
  },
  plugins: [tailwindAnimate],
};

export default config;
