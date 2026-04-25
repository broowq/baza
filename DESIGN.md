# Design System: БАЗА — "Cinematic Glass"

> **Visual reference:** [@rondesignlab](https://www.instagram.com/rondesignlab/) Public Transit OS series (March 2026) — satellite-map dashboards with floating glass widgets, thin display typography, ambient depth.
>
> **Positioning:** premium B2B Russian SaaS (Apollo.io × Linear × Vercel). Audience: serious sales operators willing to pay ₽5000+/mo. Tone: confident, spatial, almost-cinematic. The product looks like a cockpit, not a CRM.

This is the **source of truth** for any UI work. Cursor (or any IDE) MUST read this file before touching components or pages. When a prompt conflicts with this doc, this doc wins.

---

## 1. Visual Theme & Atmosphere

**Mood:** ambient, spatial, cinematic. Black canvas with photographic / satellite-map texture leaking through translucent glass surfaces. Information hierarchy through **depth and weight**, not color saturation.

**Aesthetic philosophy:**
- **Dark-only by default.** Light mode is a deferred feature. Every component is designed black-first — accent colors are calibrated to glow on black.
- **Floating glass over a real-world canvas.** UI is layered on top of a backdrop that always carries information (a map, a satellite image, a vehicle photo, an aurora gradient). Glass cards refract that backdrop via heavy `backdrop-blur-2xl`/`3xl`. Never solid panels.
- **Thin display typography for numbers.** Big stats (78.3%, 142,580, 87%) are rendered at `font-extralight` / `font-light` — communicates calm precision. Body text is regular.
- **Color is a status-only language.** Brand neutral is monochrome. Color appears ONLY for status (green/red dots), warnings (amber), and one brand accent for CTAs.
- **Generous radii, generous space.** `rounded-3xl` (24px) for hero glass cards, `rounded-2xl` (16px) for content surfaces, `rounded-full` for pills. Padding never below `p-5`.
- **Live, but slow.** Pulse on status dots, aurora drift on hero (15-25s loops), 200ms transitions. Never flashy.

---

## 2. Color Palette & Roles

### Canvas — pure dark layered

| Role | Hex | HSL | Used for |
|---|---|---|---|
| **Canvas root** | `#0A0A0B` | `240 5% 4%` | Page background, deepest layer |
| **Canvas raised** | `#0F0F11` | `240 5% 6%` | Section backgrounds when no image is used |
| **Glass tint A** (8% white) | `rgba(255,255,255,0.05)` | — | Default glass card fill |
| **Glass tint B** (4% white) | `rgba(255,255,255,0.03)` | — | Subtle nested cards |
| **Glass tint warm** | `rgba(40,28,28,0.65)` | — | Warning panel (see screenshot 3 — "Capacity Issues") |
| **Border whisper** | `rgba(255,255,255,0.08)` | — | Hairline glass border |
| **Border strong** | `rgba(255,255,255,0.14)` | — | Active / focused glass border |

### Foreground

| Role | Hex | Used for |
|---|---|---|
| **Foreground primary** | `#F5F5F7` | Headlines, big numerals |
| **Foreground secondary** | `rgba(245,245,247,0.72)` | Body text |
| **Foreground muted** | `rgba(245,245,247,0.48)` | Labels, eyebrows, sublabels (`Operational Efficiency`, `Target:`) |
| **Foreground faint** | `rgba(245,245,247,0.28)` | Chart axis labels, timestamps |

### Status & accent (USE SPARINGLY)

| Role | Hex | Used for |
|---|---|---|
| **Status online** | `#34D399` (emerald-400) | Online dot, MX-valid checkmark |
| **Status offline** | `#F43F5E` (rose-500) | Offline triangle, MX-bounce |
| **Status warning** | `#FBBF24` (amber-400) | Schedule deviation, capacity warning |
| **Brand accent** | `#FF6A00` (orange) | Primary CTA only, KPI highlight on chart |
| **Live indicator** | `#34D399 + 60% glow` | Pulsing dot for live data |

> **Rule:** if you're about to use blue/purple/pink "decoratively" — don't. The whole UI's chromatic intensity must come from the backdrop image, not the chrome.

---

## 3. Typography

**Stack** (in priority order):
1. **Geist** (display + body, primary) — Vercel's modern grotesque, clean numerics, perfect for thin weights
2. **Inter** (fallback if Geist unavailable)
3. **system-ui**

Add Geist via `@next/font` or `geist/font` package.

### Scale

| Token | Spec | Use |
|---|---|---|
| **Display XL** | 64-96px / `font-extralight` (200) / `tracking-tight` / `leading-[0.95]` | Hero KPI numbers, hero headline |
| **Display L** | 40-56px / `font-light` (300) / `tracking-tight` | Section hero, large stats |
| **Display M** | 28-32px / `font-light` (300) | Card-level KPI numbers |
| **Title** | 18-22px / `font-medium` (500) / `tracking-tight` | Card titles ("Traffic Management", "Schedule Offset") |
| **Body** | 14-15px / `font-normal` (400) | Default body |
| **Label** | 11-12px / `font-medium` (500) / `tracking-wider` / uppercase | Eyebrow labels above sections |
| **Caption** | 11px / `font-normal` (400) / `text-foreground-muted` | Timestamps, supporting copy |
| **Mono** | `Geist Mono` 12-13px | Codes (ОКВЭД, IDs, ИНН) |

**Critical**: numerical displays (KPIs, prices, percentages) ALWAYS use `font-light` or `font-extralight`. Body text stays at regular weight. This is the single highest-leverage typographic decision.

---

## 4. Component Specs

### Glass Card (the hero primitive)

```tsx
<div className="rounded-3xl border border-white/10 bg-white/5 backdrop-blur-2xl p-6
                shadow-[inset_0_1px_0_0_rgba(255,255,255,0.08)]">
  ...
</div>
```

- **Radius:** 24px (`rounded-3xl`) for hero/feature cards, 16px (`rounded-2xl`) for content, 12px (`rounded-xl`) for compact data cells.
- **Backdrop blur:** `backdrop-blur-2xl` minimum (24px). Hero glass uses `backdrop-blur-3xl` (40px).
- **Border:** `border-white/10` default, `border-white/14` on hover/focus.
- **Inset highlight:** `shadow-[inset_0_1px_0_0_rgba(255,255,255,0.08)]` — gives the top edge that subtle "lit" feel.
- **Padding:** `p-5` minimum, `p-6` standard, `p-8` for hero KPI cards.
- **NO drop shadow.** The depth comes from blur + transparency, not from `shadow-lg`.

### KPI Display

```tsx
<div className="flex flex-col gap-1">
  <span className="text-[11px] font-medium uppercase tracking-wider text-white/48">
    Operational Efficiency
  </span>
  <span className="text-5xl font-extralight tracking-tight text-white">
    78.3<span className="text-2xl text-white/48">%</span>
  </span>
  <span className="text-[11px] text-white/48">Target: 75%</span>
</div>
```

The "tiny label → huge thin number → tiny supporting" sandwich is the signature pattern.

### Pill Tabs (top of dashboards)

```tsx
<nav className="inline-flex items-center gap-1 rounded-full border border-white/10 bg-white/5 p-1 backdrop-blur-xl">
  <button className="rounded-full px-4 py-1.5 text-sm font-medium text-white/56 hover:text-white">
    Routes
  </button>
  <button className="rounded-full bg-white/10 px-4 py-1.5 text-sm font-medium text-white">
    Live Map
  </button>
</nav>
```

- Inactive: `text-white/56`, no background.
- Active: `bg-white/10`, `text-white`. NO heavy color fill.
- Hover: bump opacity on text, no other change.

### Status Chip

```tsx
<span className="inline-flex items-center gap-1.5 rounded-full bg-white/5 border border-white/10 px-2.5 py-0.5 text-xs text-white/72">
  <span className="size-1.5 rounded-full bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.7)]" />
  Online
</span>
```

The colored dot has a glow shadow that matches its hue. Status text stays neutral white.

### Buttons

- **Primary:** `bg-white text-black rounded-full h-11 px-6 font-medium hover:bg-white/90` — pure-white pill on dark canvas. Maximum contrast for the ONE primary action per view.
- **Secondary (glass):** `bg-white/8 border border-white/12 backdrop-blur-xl text-white rounded-full h-11 px-6 hover:bg-white/12`.
- **Ghost:** `text-white/72 hover:text-white hover:bg-white/5 rounded-lg h-9 px-3`.
- **Brand accent (rare):** `bg-[#FF6A00] text-black rounded-full h-11 px-6 font-medium hover:bg-[#FF7A1A]` — only when something needs to scream "do this now" (e.g., "Собрать лиды", "Начать бесплатно").
- **Sizes:** prefer `h-11` (default), `h-9` (sm), `h-12` (xl hero CTA).

### Inputs

```tsx
<input className="h-11 w-full rounded-2xl border border-white/10 bg-white/5 px-4
                  text-white placeholder:text-white/40
                  focus:border-white/24 focus:bg-white/8 focus:outline-none
                  backdrop-blur-xl" />
```

- Always glassy. Match the surrounding card surface.
- Focus: bump border opacity, bump bg. No external ring (would look out of place on glass).

### Tables

- Container: `rounded-2xl border border-white/8 bg-white/3 overflow-hidden`.
- Header: `bg-white/4 border-b border-white/8 px-4 h-10 text-[11px] uppercase tracking-wider text-white/48`.
- Row: hover `bg-white/3`. Border between rows `border-white/6`.
- Cell padding: `px-4 py-3.5`. Comfortable but not loose.

### Charts (line charts, like the Operational Efficiency on screen 1)

- Stroke `1px`, color `white/40` for primary line.
- Highlighted segment (e.g., today): `#FF6A00` or `#FBBF24`, stroke `1px`.
- Gridlines: `white/4`, dashed `2 4`.
- Axis labels: 11px, `text-white/40`. No box around the chart.
- No fills under lines unless the chart specifically calls for area emphasis.

### Maps (when present)

- **Use a real map or satellite tile** as the backdrop wherever possible. Mapbox / Maplibre with a custom dark style.
- Overlay glass cards float on top of the map at strategic anchor points.
- Map markers: simple white circles or pin-glyphs, never branded shapes.

---

## 5. Layout Patterns

### Hero (landing)

- Full-bleed dark canvas.
- Optional: subtle aurora-blur backdrop (3 slow-drifting blobs) OR a real screenshot of the dashboard tilted in 3D, blurred.
- Center column max-width `max-w-3xl`. Headline (Display XL), subheadline (body), 2 CTAs (primary white pill + secondary glass pill).
- Below the fold: floating dashboard mockup at -8° rotation, framed in a glass bezel.

### Dashboard home

- Left rail (sidebar): `w-60`, `bg-black/40 backdrop-blur-xl`, `border-r border-white/8`. Icon + label per item, active state `bg-white/8` + left accent bar.
- Top bar: search command (`⌘+K`) glass pill, notifications, avatar.
- Content: 12-col grid, `gap-4`. KPIs on row 1 (4 glass cards), main panel on row 2 (large glass card with chart + map), recent activity below.

### Project detail / Leads table

- Above table: header card with project metadata + ОКВЭД chips + ATTRIBUTION (3 stat KPIs in a glass strip).
- Table itself: as above. First column = company + source-glyph + email-status, last column = score.
- Row click → side-drawer (sheet) with detailed view.

### Settings / Billing

- Tabs as glass pill nav at top.
- Content: stacked glass cards, `gap-4`. Each section gets its own card.

---

## 6. Motion

- **Standard transition:** 200ms ease-out, applied to color/opacity/border.
- **Hover lift on cards:** `hover:bg-white/7 hover:border-white/14` — opacity shifts only, no transform.
- **Page enter:** `opacity 0 → 1` over 300ms, optional `translate-y-2 → 0`.
- **Aurora blobs:** 15s/20s/25s loops, very slow.
- **Live status pulse:** dot scales `1 → 1.15 → 1` over 2s, infinite. Glow shadow synced.
- **Chart line draw:** stroke-dashoffset animation 800ms on first paint.
- NO bouncy spring physics. Everything ease-out, calm.

---

## 7. Iconography

- **Lucide React** at `strokeWidth={1.5}` (default). Never bold.
- Icon size matches text line-height: 14px in body, 16px in titles, 20px in card hero icons.
- Always inherits text color (`currentColor`).
- Status icons (online dot, warning triangle) are NOT lucide — they're custom SVG matched to the screenshot palette.

---

## 8. Backdrop Layer (the most underused tool)

The reference designs all have **something** behind the glass — that's where 50% of the visual identity lives.

| Surface | Backdrop |
|---|---|
| Landing hero | Real dashboard screenshot, blurred + tilted in 3D, OR aurora blobs |
| Dashboard home | Subtle dotted-grid pattern + aurora at 30% opacity |
| Project detail | Faded map tile of the project's geography (Москва, Томск, etc.) — DIY via Mapbox static API |
| Leads table | None (data density is its own texture) |
| Settings | Plain canvas (settings are a low-attention surface) |

For the project page, fetch a static Mapbox image:
`https://api.mapbox.com/styles/v1/mapbox/dark-v11/static/[lng,lat,zoom,0,0]/1200x300@2x` — paint at 30% opacity behind the header card.

---

## 9. Migration Checklist (from current codebase)

These are the files where the new system has to land:

| File | Change |
|---|---|
| `app/globals.css` | Replace HSL token block with new dark canvas + glass utility classes |
| `tailwind.config.ts` | Add `font-display`, fontWeights 200/300, tweak `colors` to use the canvas/foreground/border tokens, drop the chunky `boxShadow.soft` |
| `app/layout.tsx` | Add `<GeistSans>` and `<GeistMono>` fonts |
| `components/ui/button.tsx` | Variants → `default` (white pill), `secondary` (glass), `ghost` (text), `brand` (orange). Heights 9/11/12. Drop the `aria-expanded` heavy variants. |
| `components/ui/card.tsx` | New base: glass surface. Drop the dropshadow variants. |
| `components/ui/input.tsx` | Glass background, no fill, focus by border opacity. |
| `components/ui/badge.tsx` | Pill with glass surface + colored dot. Drop the heavy filled variants. |
| `components/ui/glass-card.tsx` | Reauthor as the canonical glass primitive. Other components compose this. |
| `app/page.tsx` (landing) | Full rewrite. Hero + How it works + Features (3-col with glass) + Pricing + FAQ + Footer. Use `search_tuning/new_landing_copy.md` as copy spec. |
| `app/dashboard/page.tsx` | Full rewrite. KPI strip (4 cards), main panel (recent project activity), CTA empty state. |
| `app/dashboard/projects/[projectId]/page.tsx` | Header glass card + metadata strip + leads table. |
| `components/dashboard/leads-table.tsx` | New table styles. Existing source-glyph + email-status badges already shipped — keep their semantics, restyle their look. |
| `components/landing/*` | Rebuild from scratch under new system. |

**Do NOT touch the backend** during this redesign. Schemas are stable.

---

## 10. Out-of-Scope Anti-Patterns

When in doubt, AVOID:

- ❌ Soft pastel gradients on cards (no purple/pink fills)
- ❌ Heavy drop shadows (`shadow-2xl`, etc.)
- ❌ Bold display weights (700+) for numbers
- ❌ Multiple competing accent colors in one view
- ❌ Solid white panels in dark mode
- ❌ Bouncy animations (spring with overshoot)
- ❌ Emoji as decoration (only as functional source-glyphs in tables)
- ❌ Rounded-md / rounded-lg on hero surfaces (too tight; use 2xl/3xl)
- ❌ Solid borders > 1px
- ❌ Filled icons / dual-tone icons

---

## 11. Quality Gate (the "smell test")

After any redesign change, scroll to the page in dark mode at 1920×1080. If you see:
- ✅ Black canvas with one or more glass cards floating
- ✅ One BIG thin number per view (the KPI)
- ✅ Status dot(s) with subtle glow
- ✅ Generous breathing room around every element
- ✅ No more than 2 distinct accent colors visible
- ✅ All radii ≥ 12px

then the design is correct.

If you see filled blue gradient cards, multiple bright fills, dense uppercase headers, or boxy elements with sharp 4px radii — back out. Read this doc again.

---

## 12. Companion Files

- `search_tuning/new_landing_copy.md` — landing page copy spec (use verbatim, just restyle visually)
- `search_tuning/ux_polish_list.md` — pre-existing UX issues to resolve during redesign
- This file — the visual law

When prompting Cursor, paste THIS file as `@DESIGN.md`, the relevant target file as `@components/ui/...`, and one specific brief. Don't ask for "redo the whole app" in one shot.
