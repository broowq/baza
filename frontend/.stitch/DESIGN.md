# БАЗА — Design System v2.0

> Premium B2B SaaS for lead generation. Dark-first, glassmorphic, motion-rich.

---

## Color Tokens

### Brand

| Role | Name | Hex | HSL | Usage |
|------|------|-----|-----|-------|
| Background | Void | `#07070A` | 228 15% 3% | Page bg, depth layer |
| Surface | Onyx | `#0F1117` | 228 15% 7% | Cards, panels |
| Surface Elevated | Slate | `#161822` | 228 14% 11% | Hover states, active cards |
| Border | Frost | `#1E2030` | 228 14% 15% | Default borders |
| Border Subtle | Ghost | `#ffffff0d` | — | Subtle divisions |
| Text Primary | Snow | `#F0F2F5` | 215 20% 95% | Headlines, body |
| Text Secondary | Ash | `#8B8FA3` | 230 10% 59% | Descriptions, labels |
| Text Tertiary | Mist | `#565A6E` | 230 12% 38% | Placeholders, hints |

### Accent Spectrum

| Role | Name | Hex | Glow | Usage |
|------|------|-----|------|-------|
| Primary Action | Violet | `#8B5CF6` | `rgba(139,92,246,0.15)` | CTAs, active states, links |
| Success | Emerald | `#10B981` | `rgba(16,185,129,0.12)` | Positive metrics, completion |
| Warning | Amber | `#F59E0B` | `rgba(245,158,11,0.12)` | Cautions, limits approaching |
| Danger | Rose | `#EF4444` | `rgba(239,68,68,0.12)` | Errors, destructive actions |
| Info | Sky | `#38BDF8` | `rgba(56,189,248,0.10)` | Links, informational |
| Premium | Fuchsia | `#D946EF` | `rgba(217,70,239,0.10)` | Pro badges, upsell |

---

## Typography

| Style | Font | Size | Weight | Tracking | Line Height |
|-------|------|------|--------|----------|-------------|
| Display | Inter | 48px / 3rem | 700 | -0.025em | 1.1 |
| H1 | Inter | 36px / 2.25rem | 700 | -0.02em | 1.2 |
| H2 | Inter | 28px / 1.75rem | 600 | -0.015em | 1.25 |
| H3 | Inter | 20px / 1.25rem | 600 | -0.01em | 1.35 |
| Body | Inter | 15px / 0.9375rem | 400 | 0 | 1.6 |
| Body Small | Inter | 13px / 0.8125rem | 400 | 0.01em | 1.5 |
| Caption | Inter | 11px / 0.6875rem | 500 | 0.05em | 1.4 |
| Label | Inter | 12px / 0.75rem | 600 | 0.06em | 1 |

**Rules:**
- Headlines: `text-balance` for even line breaks
- Body: max-width 65ch for readability
- Numbers: `tabular-nums` for alignment in tables/stats
- Russian text: `hyphens: auto` for long words

---

## Spacing & Layout

| Token | Value | Usage |
|-------|-------|-------|
| page-x | 24px mobile / 48px desktop | Page horizontal padding |
| section-gap | 80px / 5rem | Between major sections |
| card-pad | 24px / 1.5rem | Inside cards |
| card-pad-sm | 16px / 1rem | Compact cards |
| grid-gap | 16px / 1rem | Between grid items |
| stack-gap | 8px / 0.5rem | Between stacked elements |

**Max Widths:**
- Content: 1200px
- Narrow: 720px (forms, text-heavy)
- Wide: 1400px (dashboards)

---

## Border Radius

| Token | Value | Usage |
|-------|-------|-------|
| xs | 6px | Badges, chips |
| sm | 8px | Inputs, small buttons |
| md | 10px | Default components |
| lg | 12px | Buttons, cards |
| xl | 16px | Featured cards, modals |
| 2xl | 20px | Hero sections |
| full | 9999px | Pills, avatars |

---

## Shadows & Depth

```css
/* Ambient — default card elevation */
--shadow-ambient: 0 1px 3px rgba(0,0,0,0.12), 0 0 1px rgba(0,0,0,0.08);

/* Raised — hover, modals */
--shadow-raised: 0 8px 30px rgba(0,0,0,0.24), 0 0 1px rgba(0,0,0,0.12);

/* Glow — accent elements */
--shadow-glow-violet: 0 0 20px rgba(139,92,246,0.2), 0 0 60px rgba(139,92,246,0.08);
--shadow-glow-emerald: 0 0 20px rgba(16,185,129,0.15);

/* Glass — frosted surfaces */
--glass-bg: rgba(15,17,23,0.7);
--glass-border: rgba(255,255,255,0.06);
--glass-blur: 20px;
```

---

## Motion

| Pattern | Duration | Easing | Usage |
|---------|----------|--------|-------|
| Micro | 150ms | ease-out | Button hover, toggles |
| Enter | 300ms | cubic-bezier(0.16, 1, 0.3, 1) | Cards, modals appearing |
| Exit | 200ms | ease-in | Dismissing elements |
| Stagger | +50ms per item | — | Lists, grid items |
| Float | 3-5s infinite | ease-in-out | Ambient decoration |
| Pulse | 2s infinite | ease-in-out | Loading, attention |

**Rules:**
- All interactive elements: `transition-all duration-200`
- Hover lift: `hover:-translate-y-0.5 hover:shadow-raised`
- Active press: `active:translate-y-0 active:shadow-ambient`
- Scroll reveal: fade-up with 20px offset, `once: true`
- Prefer `will-change: transform` for animated elements

---

## Component Patterns

### Glass Card
```
bg-white/[0.04] backdrop-blur-xl border border-white/[0.06]
rounded-xl shadow-ambient
hover:bg-white/[0.06] hover:border-white/[0.10] hover:shadow-raised
transition-all duration-200
```

### Stat Card
```
bg-gradient-to-br from-white/[0.05] to-white/[0.02]
backdrop-blur-xl border border-white/[0.06] rounded-xl p-6
```

### Primary Button
```
bg-violet-600 text-white font-medium rounded-xl px-5 h-10
shadow-sm shadow-violet-600/25
hover:bg-violet-500 hover:-translate-y-0.5 hover:shadow-lg hover:shadow-violet-600/20
active:translate-y-0
transition-all duration-200
```

### Input Field
```
bg-white/[0.04] border border-white/[0.08] rounded-lg px-3.5 h-10
text-sm text-foreground placeholder:text-muted-foreground/50
focus:border-violet-500/50 focus:ring-2 focus:ring-violet-500/20
transition-colors duration-200
```

### Badge / Chip
```
inline-flex items-center rounded-full px-2.5 py-0.5
text-xs font-medium
bg-violet-500/10 text-violet-400 ring-1 ring-violet-500/20
```

---

## Page Templates

### Landing
1. **Nav**: Sticky, glass bg, logo left, links center, CTA right
2. **Hero**: Display heading + gradient text, subtitle, dual CTAs, ambient glow orbs
3. **Social Proof**: Logo bar or metric counters
4. **Features**: 3-col bento grid with glass cards, icons
5. **How It Works**: Numbered steps with connecting line
6. **Pricing**: 3 cards, center highlighted with violet glow border
7. **FAQ**: Accordion with clean borders
8. **CTA Section**: Full-width gradient bg, centered text + button
9. **Footer**: 4-col links grid, copyright

### Dashboard
1. **Header**: Org name, plan badge, usage bar, notifications
2. **Project Grid**: Cards with name, niche tags, last activity, quick actions
3. **Empty State**: Illustration, heading, CTA button

### Project Detail
1. **Header**: Project name, prompt tags, action buttons
2. **Stats Row**: 4 stat cards (total, enriched, with email, avg score)
3. **Leads Table**: Sortable, filterable, with row actions
4. **Job History**: Timeline/list of collection runs

---

## Atmosphere Keywords

`premium`, `elevated`, `calm-tech`, `dark-luxury`, `glassmorphism`,
`ambient-glow`, `perpetual-motion`, `editorial-precision`, `deep-depth`,
`monochromatic-with-accent`, `silicon-valley`, `data-rich`
