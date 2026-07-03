---
name: БАЗА — Cinematic Glass
colors:
  # ── Canvas (dark — the default/signature theme) ──
  bg: '#0A0A0C'
  bg-2: '#0E0F12'
  surface-1: '#16171B'        # white @3% over bg — panel resting
  surface-2: '#1A1B1F'        # white @5% — elevated card
  surface-3: '#1F2024'        # white @8% — chips / inset wells
  foreground: '#FFFFFF'
  foreground-muted: '#9A9A9C' # white @56% — secondary text
  foreground-faint: '#5C5C5E' # white @40% — meta / placeholder
  line: '#FFFFFF14'           # hairline border (white @8%)
  # ── Brand button (inverts per theme) ──
  brand-bg: '#FFFFFF'         # white pill on dark
  brand-fg: '#0A0A0C'         # ink label on the white pill
  # ── Signature accent ──
  mint: '#A8C5C0'             # THE accent (dark theme)
  mint-deep: '#4E8A7E'        # deepened mint for text/borders on light
  # ── Functional / status ──
  green: '#34D399'            # online / success / positive delta
  rose: '#F43F5E'             # offline / destructive / overdue
  amber: '#FBBF24'            # warning / mid-score
  sky: '#7DD3FC'              # info / contacted
  # ── Lead-status badge text (dark, all ≥4.5:1 on tinted bg) ──
  badge-new: '#C8E0DC'
  badge-contacted: '#A5D8F8'
  badge-qualified: '#86EFAC'
  badge-rejected: '#FDA4AF'
  badge-source: '#FCD34D'
  # ── Light theme canvas (manual/system toggle) ──
  light-bg: '#F5F6F8'
  light-surface: '#FFFFFF'
  light-ink: '#16181D'
typography:
  hero-h1:
    fontFamily: Geist
    fontSize: 56px
    fontWeight: '200'
    lineHeight: 0.94
    letterSpacing: -0.045em
  h2:
    fontFamily: Geist
    fontSize: 32px
    fontWeight: '200'
    lineHeight: '1'
    letterSpacing: -0.035em
  h3:
    fontFamily: Geist
    fontSize: 22px
    fontWeight: '300'
    lineHeight: 1.1
    letterSpacing: -0.025em
  stat-value:
    fontFamily: Geist
    fontSize: 28px
    fontWeight: '200'
    lineHeight: '1'
    letterSpacing: -0.04em
  body:
    fontFamily: Geist
    fontSize: 13px
    fontWeight: '400'
    lineHeight: 1.55
    letterSpacing: -0.01em
  body-medium:
    fontFamily: Geist
    fontSize: 13px
    fontWeight: '500'
    lineHeight: 1.5
    letterSpacing: -0.015em
  eyebrow:
    fontFamily: Geist
    fontSize: 11px
    fontWeight: '400'
    lineHeight: '1.2'
    letterSpacing: 0.18em
  mono-meta:
    fontFamily: Geist Mono
    fontSize: 10.5px
    fontWeight: '400'
    lineHeight: '1.4'
    letterSpacing: 0.06em
  serif-accent:
    fontFamily: Instrument Serif
    fontSize: 56px
    fontWeight: '400'
    lineHeight: 0.94
    letterSpacing: -0.02em
rounded:
  xs: 0.375rem      # 6px
  sm: 0.5rem        # 8px
  md: 0.75rem       # 12px
  lg: 1rem          # 16px
  xl: 1.25rem       # 20px — panels
  2xl: 1.5rem       # 24px — hero glass / cards
  full: 9999px      # pills, buttons, chips, dots
spacing:
  unit: 8px
  sub: 4px
  xs: 6px
  sm: 8px
  md: 12px
  lg: 16px
  xl: 20px
  2xl: 24px
  sidebar-width: 240px
  drawer-width: 420px
  tabrail-width: 220px
---

# Design System: БАЗА — Cinematic Glass

**Product:** БАЗА — Russian B2B lead-generation SaaS (lead discovery, enrichment,
CRM pipeline, outreach). **Stack:** Next.js 14 App Router · Tailwind 3.4 ·
`@base-ui/react` primitives · `class-variance-authority`. The system has accreted
in four waves (v2 cinematic → v3 product shell → v4 elevated components); the
through-line is **dark-first glassmorphism with a single mint accent**.

## 1. Visual Theme & Atmosphere

БАЗА feels like a **cinematic control room rendered in glass and graphite**. The
canvas is near-black (`#0A0A0C`) — not flat, but alive: faint mint and sky radial
glows bleed in from the corners, a 64px graticule of hairline grid-lines is masked
to a soft ellipse, a 2.5%-opacity film grain sits over everything, and a mint
cursor-spotlight follows the pointer in screen-blend. Marketing surfaces layer a
bioluminescent "ocean" backdrop and drifting mesh-gradient blobs; the product app
calms this to a quiet graphite field so data stays legible.

The mood is **restrained, expensive, and engineered**. Whitespace is generous,
type is set in **ultra-light weights (200–300)** with tight negative tracking, and
the only saturated color is the **mint `#A8C5C0`** — never orange. Surfaces are
semi-transparent panels with `backdrop-blur(16–24px)` and a single lit top-edge
highlight, so the UI reads as **panes of frosted glass floating over the dark
field**. It should feel less like a CRM and more like a precision instrument:
calm, deep, and quietly luminous.

## 2. Color Palette & Roles

### Primary Foundation (dark)
- **Abyss Black** (`#0A0A0C`) — root page canvas (`--bg`).
- **Graphite Black** (`#0E0F12`) — secondary canvas, topnav, drawer body (`--bg-2`).
- **Glass surfaces** — built as *white over the canvas at rising alpha*, never solid:
  `surface-1` 3% (panel resting), `surface-2` 5% (elevated card / sidebar),
  `surface-3` 8% (chips, wells), plus `hover` 6% and `active` 10% interaction tints.
- **Hairlines** — `--line` white @6%, `--line-2` @10%, `--line-3` @14%. Borders are
  whispers, never strokes.

### Accent & Interactive
- **Signature Mint** (`#A8C5C0`) — the one accent. Active-nav dot, focus rings, score
  fills, links, glows, chart primaries, progress gradient (mint→white). Used at full
  value for text/icons and at 10–28% alpha for tints, borders, and glows.
- **Brand White Pill** (`#FFFFFF` bg / `#0A0A0C` text) — THE primary action. A solid
  white pill on the dark field with a mint drop-glow (`0 8px 28px -10px mint@60%`).
  Inverts to an ink pill (`#16181D`/white) in light theme.

### Typography & Text Hierarchy
White at a fixed **alpha ladder**: `100%` (titles, key numbers) → `84%` (body) →
`72%` (labels, nav) → `56%` (captions) → `48%`/`40%` (meta, eyebrows) → `28%`
(disabled). This single ladder does all hierarchy work — color is rarely used to
rank text, only opacity.

### Functional States
- **Green** `#34D399` — online, success, upward delta.
- **Rose** `#F43F5E` — offline, destructive, overdue (also the rose nav-count tint).
- **Amber** `#FBBF24` — warning, mid-range score.
- **Sky** `#7DD3FC` — info, "contacted" lane.
Each ships with a matching `0 0 8px` glow and a haloed status-dot.

### Lead-Status Badge System
A pastel-on-tint chip family, each ≥4.5:1 contrast (WCAG AA), color paired with a
dot so hue is never the sole signal:
**Новый** mint `#C8E0DC` · **Контакт** sky `#A5D8F8` · **Квалифицирован** green
`#86EFAC` · **Отклонён** rose `#FDA4AF` · **КП/Источник** amber `#FCD34D`. In light
theme the text deepens (`#2F6B61`, `#1E6FA8`, `#1A7F4B`, `#C2334A`, `#8A5A00`).

## 3. Typography Rules

### Hierarchy & Weights
- **Geist** is the workhorse (sans) — body defaults to **weight 300** with `-0.01em`
  tracking. **Geist Mono** carries labels, table headers, metrics, IDs, and badge
  text. **Instrument Serif** (italic, 400) is a single decorative accent (e.g. one
  emphasized hero word).
- The signature is **thin display type**: `h1` 56px/**200**/‑0.045em/0.94lh,
  `h2` 32px/200/‑0.035em, `h3` 22px/300/‑0.025em, stat values 28px/**200**/‑0.04em
  with `tabular-nums`. Headlines feel airy and architectural, never bold.
- **Eyebrows / labels:** 10–11px, **uppercase**, `0.16–0.18em` letter-spacing, in
  Geist Mono or light Geist at `t-40/48`. These tiny tracked caps are everywhere
  (section kickers, table heads, stat labels, rail sections).
- **Medium (500)** is the only "heavy" weight — used for the white-pill label,
  active items, names, and emphasis. There is essentially no bold.

### Spacing Principles
Negative tracking scales with size (‑0.045em on hero down to ‑0.005em on small
body). Line-height is tight on display (0.94–1.1) and relaxed on body (1.5–1.55).
Numerics always use `tabular-nums` so counters and tables don't jitter.

## 4. Component Stylings

### Buttons
- **default / brand** — white pill (`rounded-full`), `h-11`, medium weight, mint
  drop-glow; `brand` adds a `-1px` hover lift. The hero CTA can pulse a mint ring.
- **secondary / outline** — glass pill: `surface-3` fill, `line-2` border,
  `backdrop-blur-xl`; hover → `surface-active` + `line-3`.
- **ghost** — text only (`t-72` → `t-100`), `rounded-lg`, faint hover fill. Toolbars,
  table actions.
- **destructive** — translucent rose (`rose/10` fill, `rose/20` border).
- Sizes `xs h-7 · sm h-9 · default h-11 · lg h-12`, plus square `icon` sizes.
- Transitions 150–200ms; **focus-visible = 2px mint outline, 2px offset**; disabled
  drops to ~45% opacity.

### Cards & Glass Surfaces
The core primitive is the **glass card**: `bg surface-input/2`, `1px line-2` border,
`backdrop-blur-xl`, and a single inset top highlight (`inset 0 1px 0 white@6%`).
Variants: **default** `rounded-2xl` `p-6` · **hero** `rounded-3xl` `p-8`
`backdrop-blur-2xl` (KPI strips, landing) · **compact** `rounded-xl` `p-4` (dense
data) · **warning** rose-tinted glass. `.panel` (20px, blur+saturate) is the
hand-CSS equivalent; `.panel-flat` and `.panel-glass` are lighter tiers.

### Navigation & Shells
- **Product sidebar** (`240px`, `sidebar-v3`): glass column, `backdrop-blur(20px)
  saturate(140%)`, right hairline. Nav items are `rounded-[10px]`, `t-72`→`t-100`
  on hover; the **active item gets a raised `surface-hover` fill + a glowing mint
  dot** on its left edge and a mono count-pill on the right (rose-tinted for overdue).
  Bottom: avatar + email (mono) + "Выйти →" + theme toggle.
- **Top rail / marketing nav** (`topnav`): sticky, `blur(14px)`, bottom hairline,
  pill `nav-link`s (`t-72`, hover fills `surface-input`, active `surface-hover`).
- **Segmented controls** (`seg`, `ptabs`): inset pill-groups; the active segment is a
  filled white pill (`ptabs`) or a raised `surface-3` chip (`seg`).
- **Detail drawer**: a `420px` right slide-over (`translateX` 240ms) over a blurred
  `scrim`, `elev-3` shadow, header/body/footer split.

### Inputs & Forms
Glass fields: `surface-input` bg, `1px line-2` border, `backdrop-blur-xl`,
placeholder at `t-40`. **Focus** lightens the fill to `surface-hover` and the border
to `line-3` (plus the 2px mint focus-ring on keyboard nav); **invalid** tints border
& bg rose. React `<Input>` is `h-11 rounded-2xl` (default) / `h-9 rounded-xl` (sm).
Checkboxes (`cbox`) are 16px, `rounded-[4px]`, and fill with the brand color when
checked.

### Domain Components
- **Lead card** — glass card with `elev-1`, hover lifts `-2px` to `elev-2` and tints
  the border mint; an optional 2px mint left-stripe flags hot leads; contacts pin to
  the bottom so every card in a row is equal height. Valid contacts turn mint.
- **Stat tile** — metric card with a mint radial glow in the bottom-right corner;
  value in 28px/200 tabular-nums; delta in mono, green up / rose down.
- **Score visualisers** — a thin `score-bar` (mint→amber→muted gradient, glow on high
  fills) and a circular `score-ring` (mint arc with drop-shadow). Both animate width/
  dash over 400–500ms on the signature easing.
- **Tables** (`lt` / `lt-v3`) — mono uppercase tracked headers on `surface-1`,
  hairline row borders, zebra `surface-1`, hover `surface-hover` (or a mint 3.5% wash).
- **Chips, pills, dots** — pill chips (mono caps) in mint/green/amber/rose/sky tints;
  status dots carry a soft radial **halo** and pulse when "live".

## 5. Layout Principles

### Grid & Structure
Product app = **fixed 240px glass sidebar + fluid `flex-1` scroll column**; settings
nests a 220px tab-rail; detail views slide a 420px drawer over a scrim. Marketing is
**full-bleed** single-column with a sticky blurred topnav and a desktop-proportioned
product mockup that scrolls horizontally on phones rather than crushing.

### Whitespace Strategy
Strict **8px base grid** (with a 4px sub-unit). Card padding `p-4/p-6/p-8` by
density; section gaps generous; hairlines (`section-divider`, `.hairline`) separate
zones instead of heavy boxes. The interface breathes — emptiness is a feature.

### Alignment & Visual Balance
Left-aligned data and forms; centered marketing heroes. Visual weight comes from
**luminance and glow**, not size or color blocks — the eye is pulled to the brightest
(white pill, mint dot, lit stat) element. Tabular numerics keep columns optically
flush.

### Responsive Behaviour & Touch
Desktop-first with a `lg` breakpoint flipping the sidebar to a slide-in drawer
(framer-motion, hamburger ≥44px). Touch targets ≥44px on interactive rows and
controls. All hovers degrade to focus/active on touch.

## 6. Elevation & Depth

Depth is **glass + a 3-tier shadow scale**, not heavy drop-shadows:
- **elev-1** — resting card: faint inset highlight + soft ambient.
- **elev-2** — hover/active: stronger highlight, deeper ambient, **+1px mint ring**.
- **elev-3** — drawers/modals: top-layer with a long 80px shadow + white inset edge.
Every glass surface also carries `inset 0 1px 0 white@6–8%` — a single "lit top edge"
that sells the frosted-pane illusion. Glows (status, mint, ring-mint) add the
luminous accent on top.

## 7. Light / Dark Theme Story

**Dark is the canonical, signature theme.** Light is a full token inversion
(`next-themes`, `class="theme-light"` on `<html>`; default = system, manual toggle):
- Canvas → soft off-white `#F5F6F8`, surfaces → pure `#FFFFFF`.
- Foreground → near-black ink `#16181D` at the same alpha ladder.
- Hairlines/surfaces flip to **black-at-low-alpha**; shadows drop the white insets
  for soft black ambient.
- **Mint deepens to `#4E8A7E`** so it reads as text/border on white; badge text
  deepens for contrast; the brand pill inverts to ink-on-white.
- Cinematic backdrops swap their dark gradient bases for light mint/sky tints; the
  dark readability scrim fades out.

## 8. Design System Notes for Stitch Generation

### Language to Use
"Cinematic dark glassmorphism." "Near-black graphite canvas with faint mint and sky
corner-glows, a masked hairline grid, and film grain." "Frosted-glass panels with a
lit top edge and whisper-thin white borders." "Ultra-light Geist display type, tight
negative tracking, mono tracked-caps labels." "A single mint `#A8C5C0` accent; the
primary button is a solid white pill with a mint glow." "Calm, expensive, engineered
— a precision instrument, not a busy CRM."

### Color References
Canvas `#0A0A0C` / `#0E0F12` · accent mint `#A8C5C0` · brand pill white `#FFFFFF` on
ink `#0A0A0C` · text = white at 100/84/72/56/48/40% · status green `#34D399` / rose
`#F43F5E` / amber `#FBBF24` / sky `#7DD3FC`.

### Component Prompts
1. *"A glass KPI stat tile on a near-black canvas: tiny uppercase mono label, a 28px
   ultra-light white number with tabular figures, a small green mono delta, and a
   faint mint radial glow in the bottom-right corner. 1px white@10% border, lit top
   edge, 24px radius."*
2. *"A lead row card: company name in medium white, muted sub-line, a pastel status
   badge with a colored dot, a thin mint→amber score bar, contacts pinned to the
   bottom. Hover lifts it 2px with a mint-tinted border."*
3. *"A 240px frosted-glass product sidebar: 'база' wordmark with a mint avatar tile,
   a search field + notification bell, pill nav items where the active one shows a
   glowing mint dot on its left edge and a mono count pill on the right."*

### Incremental Iteration
Build dark first, then verify the light inversion. Keep accent usage to mint only —
reach for green/rose/amber/sky strictly for status. Prefer opacity over new colors
for hierarchy. Lean on `backdrop-blur` + the elev-1/2/3 scale rather than solid fills
or hard shadows. Animate transform/opacity only, 150–250ms, easing
`cubic-bezier(0.2, 0.7, 0.2, 1)`, and always gate motion behind
`prefers-reduced-motion`.

## 9. Known Issues / Inconsistencies (redesign targets)

1. **Two parallel component systems.** React primitives (`components/ui/*.tsx`,
   base-ui + cva + Tailwind arbitrary values) coexist with a large hand-written CSS
   class layer in `globals.css` (`.btn`, `.input`, `.chip`, `.panel`, `table.lt*`).
   They drift: e.g. the React `<Input>` is `h-11 rounded-2xl (24px)` while the CSS
   `.input` is `h-44 rounded-[14px]`; React `<Button>` default is `h-11` vs `.btn`
   `h-9`. A redesign should pick one source of truth.
2. **Badge variants aren't all theme-aware.** The React `Badge` default/outline/ghost
   variants hardcode `white/[0.05]` etc., so they won't flip in light theme — only
   the `.badge--*` CSS classes use theme tokens. Unify on the CSS-var tokens.
3. **Radius scale collisions.** Tailwind maps **both** `2xl` and `3xl` to `1.5rem`
   (24px), so "hero" `rounded-3xl` looks identical to default `rounded-2xl`. The
   `--r-*` CSS vars (6/8/12/16/20/24) are the cleaner scale to standardize on.
4. **Dual border systems.** Tailwind `border = hsl(var(--border)/0.08)` (white) vs the
   global `* { border-color: var(--line-2) }` override vs per-component `--line-*`.
   Most borders resolve via `--line-*`; the shadcn `--border` token is largely vestigial.
5. **Static Tailwind color tokens don't theme.** `brand`, `status-*`, and `badge-*`
   hexes in `tailwind.config.ts` are fixed — anything styled with `text-brand` /
   `bg-status-*` keeps its dark value in light theme (only the CSS-var path inverts).
6. **Four accreted token waves with legacy keep-alives.** `globals.css` carries v1–v4
   plus "legacy helpers (kept for inherited components)" (`aurora-bg`, `.reveal` vs
   `.srv-*`, two table classes). Ripe for a dead-utility audit during the redesign.

---
*Generated by the Stitch `extract-design-md` skill from frontend source
(`tailwind.config.ts`, `app/globals.css`, `components/ui/*`, layout shells) — no
build required. This DESIGN.md is the input for `manage-design-system` (push to a
Stitch project) once the Stitch MCP tools are loaded.*
