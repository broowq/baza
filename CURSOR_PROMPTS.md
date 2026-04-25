# БАЗА — Cursor Redesign Prompt Pack

> Use these prompts ONE AT A TIME in Cursor IDE. Always paste `@DESIGN.md` first, then the specific brief below. Don't ask Cursor to "redo everything" — it will hallucinate inconsistencies.

## Prerequisites in Cursor

1. Open `/Users/mark/lid` as workspace
2. Add to context: `@DESIGN.md`
3. Set Cursor to use Sonnet 4.5 or higher (these prompts assume strong model)
4. After each prompt, run dev server (`pnpm --filter frontend dev`) and visually QA before moving on
5. Commit after each successful page so you can roll back

---

## Order of operations (do NOT skip)

```
1. Foundation (already done — globals.css, tailwind.config.ts, layout.tsx)
2. Primitives:    Button → Card → Input → Badge → glass-card
3. Pages:         Landing → Dashboard home → Project detail → Leads table → Settings
4. Polish:        Empty states, loading skeletons, error toasts
```

---

# 1. PRIMITIVE: Button

```
@DESIGN.md @/Users/mark/lid/frontend/components/ui/button.tsx

Rewrite this Button component for the Cinematic Glass system.

VARIANTS (replace existing):
- default: pure-white pill on dark canvas. bg-white, text-black, rounded-full,
  hover:bg-white/90. The ONE primary action per view.
- secondary: glass pill. bg-white/8, border-white/12, backdrop-blur-xl,
  text-white, rounded-full, hover:bg-white/12, hover:border-white/16.
- ghost: text-only. text-white/72, hover:text-white, hover:bg-white/5,
  rounded-lg.
- brand: orange pill — bg-[#FF6A00], text-black, rounded-full,
  hover:bg-[#FF7A1A], shadow-[0_0_24px_rgba(255,106,0,0.35)].
  Use ONLY when something needs to scream "do this now" (e.g., "Собрать
  лиды" on project page, "Начать бесплатно" on landing CTA).
- destructive: text-status-offline, bg-status-offline/10, border-status-offline/20,
  rounded-full, hover:bg-status-offline/15.
- link: text-white/80, underline on hover. No background.
- outline: REMOVE this variant. Use secondary instead.

SIZES: xs (h-7), sm (h-9), default (h-11), lg (h-12), icon (size-11), icon-sm (size-9).
All button text-sm font-medium.

INTERACTIONS:
- Hover: opacity / bg shift only. NO -translate-y. NO shadow lift on default
  variant (white pill is already maximum contrast).
- Focus: ring-2 ring-white/30 ring-offset-2 ring-offset-canvas.
- Disabled: opacity-50, pointer-events-none.

Drop the cva pattern's heavy `aria-expanded` styles — replace with simple
`data-state=open:bg-white/10` on glass variants.

Keep the export shape (Button + buttonVariants + ButtonProps).
```

---

# 2. PRIMITIVE: Card

```
@DESIGN.md @/Users/mark/lid/frontend/components/ui/card.tsx

Rewrite Card to be the Cinematic Glass primitive.

DEFAULT (replace current card):
- rounded-2xl (16px) for content cards
- bg-white/[0.04]
- border border-white/10
- backdrop-blur-xl
- p-6
- shadow-[inset_0_1px_0_0_rgba(255,255,255,0.06)]
- text-white/[0.92]

ADD VARIANTS via data-attr or a `variant` prop:
- hero: rounded-3xl (24px), p-8, bg-white/[0.05], backdrop-blur-2xl,
  shadow-[inset_0_1px_0_0_rgba(255,255,255,0.08)]. Use this for KPI strips
  and the hero card on landing.
- compact: rounded-xl (12px), p-4. For dense data containers.

KEEP slots: CardHeader, CardTitle, CardDescription, CardContent, CardFooter.
- CardTitle: text-base font-medium tracking-tight
- CardDescription: text-sm text-white/[0.56]
- CardHeader: pb-4 mb-4 border-b border-white/[0.06] (only if variant === "default")

DROP: shadcn's `border-border` and `bg-card` references — use direct
white/[0.X] tokens.
```

---

# 3. PRIMITIVE: Input

```
@DESIGN.md @/Users/mark/lid/frontend/components/ui/input.tsx

Rewrite Input for glass system.

DEFAULT:
- h-11 (was h-8 — too cramped for premium feel; reduce only inside table cells)
- w-full
- rounded-2xl
- border border-white/10
- bg-white/[0.04]
- backdrop-blur-xl
- px-4 text-base text-white
- placeholder:text-white/40
- focus: border-white/24 bg-white/[0.07], no external ring
- disabled: opacity-50 cursor-not-allowed
- invalid: border-status-offline/40 bg-status-offline/[0.05]

Also create a SIZES variant via prop:
- sm (h-9 px-3 text-sm) for table-cell editing
- default (h-11 px-4 text-base)

NO box-shadow, NO ring on focus — depth is from bg/border opacity bumps only.
```

---

# 4. PRIMITIVE: Badge

```
@DESIGN.md @/Users/mark/lid/frontend/components/ui/badge.tsx

Rewrite Badge as a glass pill with optional status dot.

DEFAULT:
- inline-flex items-center gap-1.5
- rounded-full
- bg-white/[0.05] border border-white/10
- px-2.5 py-0.5 text-xs text-white/[0.72]
- backdrop-blur-xl

VARIANTS:
- status-online: bg-status-online/10, border-status-online/20, text-status-online
- status-offline: bg-status-offline/10, border-status-offline/20, text-status-offline
- status-warning: bg-status-warning/10, border-status-warning/20, text-status-warning

PROP: `dot?: "online" | "offline" | "warning"` — when set, prepend a
size-1.5 colored circle with appropriate box-shadow glow. Use the
.status-dot[data-state="..."] CSS already in globals.css.

Drop variant: secondary, destructive, outline (legacy filled pills).
```

---

# 5. PRIMITIVE: GlassCard (canonical)

```
@DESIGN.md @/Users/mark/lid/frontend/components/ui/glass-card.tsx

This is the CANONICAL hero glass primitive. Other components should
compose this when they need depth.

Rewrite as:

export function GlassCard({
  className,
  variant = "default",  // "default" | "hero" | "warning"
  children,
  ...props
}: GlassCardProps) {
  // default: rounded-2xl bg-white/[0.04] border-white/10 backdrop-blur-xl p-5
  //          shadow-[inset_0_1px_0_0_rgba(255,255,255,0.06)]
  // hero:    rounded-3xl bg-white/[0.05] border-white/10 backdrop-blur-2xl p-8
  //          shadow-[inset_0_1px_0_0_rgba(255,255,255,0.08)]
  // warning: rounded-2xl bg-[rgba(40,28,28,0.65)] border-status-offline/18 backdrop-blur-xl p-5
}

Add a `floating` prop (boolean): when true, wraps in a parent that adds
a subtle 3D rotateX(-2deg) tilt and a soft drop-shadow at the bottom edge
to simulate the screenshots' "tilted card" feel.

Export GlassCardHeader, GlassCardTitle, GlassCardEyebrow as small
sub-components matching the typography scale in DESIGN.md §3.
```

---

# 6. PAGE: Landing

```
@DESIGN.md @/Users/mark/lid/search_tuning/new_landing_copy.md
@/Users/mark/lid/frontend/app/page.tsx

Rewrite the landing page from scratch using the Cinematic Glass system.

LAYOUT (sections, top → bottom):

1. Sticky navbar (glass pill, max-w-6xl mx-auto, my-4):
   logo "БАЗА" left | nav center (Тарифы, Как работает, FAQ) | "Войти" + brand CTA "Начать бесплатно" right

2. HERO (full-bleed, .aurora-bg backdrop, py-32):
   - Eyebrow pill "× ИИ для B2B-продаж" centered
   - Display XL headline (use exact copy from new_landing_copy.md hero):
     "Найди 100 B2B-клиентов за минуту — по одному промпту"
     Style: text-white font-extralight tracking-tight leading-[1.05]
     md:text-7xl lg:text-8xl
   - Subheadline (max-w-2xl mx-auto): "Опиши свой бизнес одной фразой —
     ИИ соберёт базу компаний с проверенными email, телефонами и данными ФНС."
     Style: text-lg text-white/72
   - CTAs row: brand pill ("Попробовать бесплатно — 10 лидов за минуту"),
     secondary glass pill ("Смотреть демо")
   - Below CTAs: scattered floating glass cards (3 of them) showing example
     leads with source-glyphs, email-status badges, score numbers. Each
     tilted at slight angle (rotate-1, -rotate-2, rotate-3). Use real
     example data: "Птицефабрика Юг", "Агрохолдинг СТЕПЬ", etc.

3. SOCIAL PROOF STRIP (mt-24, py-12):
   - Eyebrow "Уже используют" centered
   - 4-column grid of logo placeholders (text-only mock company names in
     muted white). Real logos to be added later. Below them: row of stats
     "850K+ компаний в базе", "94% доставляемость email", "<60 сек первый
     результат", "16 источников данных"

4. PROBLEM (3-paragraph copy from new_landing_copy.md, max-w-3xl mx-auto):
   - Eyebrow "Проблема"
   - Display L title: "Найти B2B-клиентов в России — это боль"
   - 3 paragraphs body (text-white/72)

5. HOW IT WORKS (3 steps, large glass cards in grid):
   - Eyebrow "Как работает"
   - Title "Три шага до первой сделки"
   - 3 glass cards (rounded-3xl, p-8) with number "01" / "02" / "03" in
     Display M extralight, then step title, then 2-sentence description.

6. FEATURE GRID (6 blocks, 2-col grid):
   - Each: glass card with lucide icon (size-6, text-white/64) at top,
     headline (text-base font-medium), 2-sentence description (text-sm text-white/64)
   - Features (use copy from new_landing_copy.md): AI-driven search,
     Verified emails, ФНС data, 2GIS integration, CRM webhooks,
     Workflow & reminders

7. PRICING (4 tiers, glass cards in horizontal scroll on mobile, 4-col grid on desktop):
   - Free / Starter 1490₽ / Pro 4990₽ / Team 12990₽
   - Pro tier has brand glow ring (ring-1 ring-brand/40, shadow-glow-brand)
   - Each card: tier name, price (Display M extralight), 5-7 feature bullets,
     CTA button (default white pill for Pro, secondary glass for others)

8. TESTIMONIALS (3 cards, alternating card sizes):
   - 3 fake-but-realistic Russian B2B quotes from new_landing_copy.md
   - Avatar (initials only on glass circle), role, quote in italic

9. FAQ (single column, max-w-3xl mx-auto):
   - Use Radix Accordion or a custom expand/collapse glass row
   - 6 questions from new_landing_copy.md
   - Open state: rotate chevron, expand answer with fade-in 200ms

10. FINAL CTA (full-bleed, .aurora-bg, py-24):
    - Display L "Начни первую рассылку сегодня"
    - Brand pill button + secondary glass pill

11. FOOTER (py-12 border-t border-white/8):
    - 4-col grid: Продукт / Компания / Юр / Контакты
    - Bottom row: copyright, social icons (lucide)

REQUIREMENTS:
- Every section has internal max-w-6xl mx-auto px-6
- Vertical rhythm: py-24 between major sections
- Use motion.div from framer-motion for slide-up + fade on enter
  (already installed). Keep it subtle — 400ms, 8px Y offset.
- Hero floating example cards: use real data shape from frontend/lib/types.ts
  (Lead type) so it looks authentic.
- DROP all current Hero / smart-cta / faq-accordion components and rebuild
  them as colocated within app/page.tsx OR as new files in
  components/landing/. Don't keep the old code.
```

---

# 7. PAGE: Dashboard Home

```
@DESIGN.md @/Users/mark/lid/frontend/app/dashboard/page.tsx

Rewrite the dashboard home as a Cinematic Glass cockpit.

LAYOUT:

1. Top bar (sticky, glass pill containing search):
   Search input (⌘+K, h-11 glass) | notifications icon-button | avatar

2. KPI strip (grid grid-cols-2 md:grid-cols-4 gap-4):
   4 hero glass cards. Each:
   - Eyebrow (kpi-eyebrow class): "ВСЕГО ЛИДОВ" / "ОБОГАЩЕНО" / "С EMAIL" / "СРЕДНИЙ SCORE"
   - Number (kpi-number class): big thin numeral
   - Caption (kpi-caption class): trend (e.g., "+12% за 7 дней", "—")
   - Top-right: tiny chart sparkline (recharts LineChart, 60×24, stroke-1
     white/40, 1 highlighted segment in brand color)

3. Recent projects (horizontally scrollable card row OR 3-col grid):
   Each project card:
   - GlassCard variant="default", p-5
   - Top: project name (font-medium) + status dot (online if cron enabled)
   - Middle: niche · geography · segments (3-5 chips)
   - Bottom-left: 3 mini stats (leads / enriched / score)
   - Bottom-right: chevron-right indicating click-through
   - Click → /dashboard/projects/[id]

4. Quick actions row:
   Brand button "Создать проект" (links to /dashboard/projects/new) +
   secondary glass buttons: "Импортировать из Excel", "Подключить CRM"

5. Empty state (when 0 projects):
   Centered glass card max-w-md mx-auto p-12 text-center
   - Lucide icon (Sparkles size-12 text-brand opacity-40)
   - Title "Создайте первый проект"
   - Description "Опишите свой бизнес одной фразой — мы найдём первых клиентов за минуту."
   - Brand CTA button

6. Activity feed (right rail or below, depending on width):
   Stream of "lead added", "project completed", etc. Each row:
   timestamp / event type icon / message / lead-link.

REQUIREMENTS:
- Sidebar (separate file: components/layout/sidebar.tsx) is already
  rendered by parent layout — DO NOT rebuild it here.
- Use real /api endpoints already wired in lib/api.ts.
- Loading state: skeleton shimmer per KPI card and per project card
  (use Skeleton primitive — restyle if needed).
- Error state: glass card with Lucide AlertTriangle, message in Russian,
  retry button.
```

---

# 8. PAGE: Project Detail

```
@DESIGN.md @/Users/mark/lid/frontend/app/dashboard/projects/[projectId]/page.tsx

Rewrite the project detail page. The current version has good content
but cramped layout — apply Cinematic Glass.

LAYOUT:

1. Page header (no map backdrop — too noisy. Just plain canvas):
   - Breadcrumb back-link "← Назад в дашборд"
   - Project name (Display L, font-light)
   - Below: row of metadata pills (niche / geography / segments[:5])
   - Below that: ОКВЭД chips row (already exists in current code — restyle
     to match badge spec)
   - Right side: action cluster — Brand button "Собрать лиды",
     secondary glass "Обогатить", secondary glass icon-buttons for
     CSV / Excel / Webhook / Settings.

2. Auto-collection bar (the schedule toggle, currently below header):
   GlassCard variant="default" p-4. Toggle (use Switch primitive),
   schedule preset dropdown, status text "Следующий сбор: завтра 09:00".

3. KPI strip (4 cards — same pattern as dashboard home):
   "Всего" / "Обогащено" / "С email" / "Средний score"

4. Leads table (full-width):
   - Wrapped in a hero glass card (rounded-3xl, p-2 — minimal padding so
     table edge-touches the card border).
   - Filter bar above table: search input, status dropdown, sort dropdown.
   - Table itself: see prompt #9 below.

5. Job history (collapsed by default, expand on click):
   A small disclosure section "История задач (12)" that opens to show
   recent collect/enrich jobs.

REQUIREMENTS:
- Existing logic (queueJob, fetchAll, exporting) MUST be preserved.
- Existing AutoCollectionBar logic stays; just restyle.
- Existing OkvedChips already shipped — don't break the data shape.
```

---

# 9. COMPONENT: Leads Table

```
@DESIGN.md @/Users/mark/lid/frontend/components/dashboard/leads-table.tsx

Rewrite the leads table for Cinematic Glass.

DESKTOP (md and up):
- Wrap table in: `rounded-2xl border border-white/8 bg-white/[0.03] overflow-hidden`
- Header row: bg-white/[0.04] border-b border-white/8 h-11 px-4
  text-[11px] uppercase tracking-wider text-white/[0.48]
- Body rows: border-b border-white/[0.06] hover:bg-white/[0.04]
  transition-colors duration-150
- Cell padding: px-4 py-3.5
- First column "Компания": company name (text-sm font-medium) +
  source-badge glyph (already shipped) + email-status (already shipped) +
  small subline below with score-bar
- Other columns: city, email, phone, address, status, score
- Status: render as Badge with dot (use new Badge variant="status-online"
  for "Связались", etc.)
- Score: render as a horizontal bar 80px wide with brand fill proportional
  to score/100, score number to the right.

MOBILE (<md): card layout — already exists, restyle it:
- Each lead is a GlassCard variant="default" p-4 mb-2
- Top row: company + source-badge + score
- Middle: city · status (with dot)
- Bottom: email + phone + address (small, wrappable)
- Tap to open detail drawer (Sheet primitive)

LEAD ROW DRAWER (Sheet from right, w-[480px]):
- All fields editable
- Status dropdown
- Tags input (chip-style)
- Notes textarea
- Reminder date-picker
- Action buttons: "Связаться" (brand), "Отметить как qualified" (secondary)

KEEP all existing semantics:
- email_status badge → already shipped, restyle
- source badge → already shipped, restyle
- ОКВЭД chips on lead row — NEW: small text under company name showing
  matched ОКВЭД codes (text-[10px] font-mono text-white/[0.32]).

DROP filled colored badges for status → use the new Badge with dots.
```

---

# 10. POLISH: Empty States, Skeletons, Errors

```
@DESIGN.md

Audit all pages and replace these patterns:

EMPTY STATES (when 0 results):
Use the .empty-state utility from globals.css. Compose:
- Lucide icon (size-12, text-white/[0.24])
- Title (text-lg font-medium text-white)
- Description (text-sm text-white/[0.56])
- Optional CTA button

Files to fix: app/dashboard/page.tsx (no projects), app/dashboard/projects/[id]/
(no leads), settings (no team members).

SKELETONS:
For loading lists: use `animate-pulse bg-white/[0.04] rounded-2xl`
matching the actual content row size. NO spinners except inside buttons
during async actions.

ERROR TOASTS:
Wrap all api() calls so Russian-language messages surface, not
"Failed to fetch":
- 401: "Сессия истекла, войдите снова"
- 402: "Превышен лимит тарифа — обновите подписку"
- 403: "Недостаточно прав"
- 429: "Слишком много запросов, подождите минуту"
- 500: "Сервер не отвечает — попробуйте через минуту"
- network error: "Проверьте интернет-соединение"

FOCUS RING:
Add globally to <body>: focus-visible:outline-none focus-visible:ring-2
focus-visible:ring-white/30 focus-visible:ring-offset-2
focus-visible:ring-offset-canvas — applied via @layer base rule.
```

---

# Verification checklist after each prompt

After Cursor finishes a prompt, verify in browser at 1920×1080 DARK MODE:

- [ ] Black canvas everywhere — no white slabs
- [ ] One BIG thin number per view (the KPI)
- [ ] Glass cards floating with backdrop-blur visible
- [ ] Status dots glow (online/offline/warning)
- [ ] No more than 2 distinct accent colors per view
- [ ] All radii ≥ 12px
- [ ] No hard drop shadows
- [ ] Buttons: white pill primary, glass secondary, brand only when needed
- [ ] Hover: subtle opacity shift, no -translate-y on cards/buttons
- [ ] Russian copy throughout (no English leaks)

If any check fails — stop, point at the problem spot, ask Cursor to fix
that specific element only. Don't regenerate the whole page.

---

# When stuck

If Cursor keeps producing stuff that doesn't match: paste DESIGN.md §11
("Quality Gate") into the conversation and ask "what specifically is
violating these rules in your last output?" — it will self-correct better
than vague "make it nicer".
