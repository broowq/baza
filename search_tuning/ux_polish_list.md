# БАЗА — UX Polish Audit

Prioritized list of concrete UX rough edges that break the "premium ₽5000+/mo" feel. Each row has a file:line anchor, problem, target state, and effort vs impact.

Legend: **Effort** XS (<30 min) · S (<2 h) · M (<1 day) · L (>1 day) · **Impact** low / med / high

---

## P0 — User-facing polish (ship first)

### 1. Landing hero uses fake dashboard domain `app.baza.io`
- File: `frontend/components/landing/hero-section.tsx:125`
- Wrong: The mock browser chrome shows `app.baza.io/dashboard` while the real product is `usebaza.ru`. Immediately reads as an unfinished template.
- Should: Show `usebaza.ru/dashboard` (or drop the URL bar entirely).
- **Effort: XS · Impact: high**

### 2. Landing "Documentation" footer link points to `#` (dead link)
- File: `frontend/app/page.tsx:443`
- Wrong: `<Link href="#">Документация</Link>` — a visibly broken nav on a paid-product homepage.
- Should: Either remove the link, disable-style it until docs exist, or link to a real docs page / knowledge base.
- **Effort: XS · Impact: high**

### 3. Stats bar claim "50 000+ лидов в месяц" is unverifiable / marketing puff
- File: `frontend/app/page.tsx:138`
- Wrong: Hardcoded "50 000+" hero stat with no source or caveat looks like placeholder copy from a template.
- Should: Replace with a concrete, sourceable stat (e.g. "5 источников · 221 город · до 25k лидов/мес на Pro"), or turn the card into something verifiable like "99.9% uptime SLA".
- **Effort: S · Impact: med**

### 4. Admin page loading state is a bare grey line of Russian text
- File: `frontend/app/dashboard/admin/page.tsx:84`
- Wrong: `<p className="text-muted-foreground">Загрузка...</p>` on an otherwise-empty page — every other page uses skeletons or the shared `<Loader />`.
- Should: Use the same skeleton pattern as `settings/page.tsx` (lines 290–312) or the shared `<Loader />`.
- **Effort: XS · Impact: med**

### 5. Admin "удалить пользователя" uses native `confirm()` dialog
- File: `frontend/app/dashboard/admin/page.tsx:93`
- Wrong: `if (!confirm(...))` — the app already uses `<AlertDialog>` everywhere else for destructive actions; a browser confirm popup feels amateurish and non-themed.
- Should: Reuse `<AlertDialog>` with a proper description and destructive action button, matching `dashboard/page.tsx:524`.
- **Effort: S · Impact: high**

### 6. Mobile breakpoint: admin tables overflow without mobile card fallback
- File: `frontend/app/dashboard/admin/page.tsx:197` (Users), `:289` (Jobs)
- Wrong: On <=768px, tables rely only on `overflow-x-auto` — users must horizontally scroll an 8-column table. `leads-table.tsx` has a proper mobile card view (`md:hidden`) that should be the pattern.
- Should: Add a `md:hidden` card list fallback for mobile, like `leads-table.tsx:416`.
- **Effort: M · Impact: high**

### 7. Members list role-select shows lowercase English: "member", "admin", "owner"
- File: `frontend/app/dashboard/settings/page.tsx:577-579, 588`
- Wrong: In a Russian B2B UI, dropping `member` / `admin` / `owner` in lowercase English next to otherwise-Russian copy feels like untranslated placeholder text.
- Should: Map to Russian labels (`Владелец` / `Админ` / `Участник`) consistent with dashboard role labels (`dashboard/page.tsx:259`).
- **Effort: XS · Impact: high**

### 8. Plan shown as lowercase raw key (`pro`, `starter`)
- File: `frontend/app/dashboard/settings/page.tsx:455`
- Wrong: `<p className="capitalize">{organization?.plan ?? "---"}</p>` prints `Starter` / `Pro` / `Team` (internal key) instead of the Russian marketing name ("Business" for `team`). Inconsistent with `dashboard/page.tsx:253` which has a proper planLabel map.
- Should: Use the same label map. Also note the admin plan dropdown calls it "Business" but value is `team` — confusing.
- **Effort: XS · Impact: med**

### 9. Empty-state on `/dashboard/projects` is dead-end
- File: `frontend/app/dashboard/projects/page.tsx:39-52`
- Wrong: If you land on `/dashboard/projects` with 0 projects, the CTA says "Перейти в дашборд" — not "Создать первый проект". Users get shuffled between two empty pages.
- Should: Primary CTA should trigger the project-creation flow directly (or link to `/dashboard` deep-linking `?new=1` that opens the dialog). Alternatively, remove this page since `/dashboard` already lists projects.
- **Effort: S · Impact: med**

### 10. "Search returns nothing" state is weak vs. the real empty state
- File: `frontend/components/dashboard/leads-table.tsx:417-421`
- Wrong: When filters exclude everything, mobile shows *only* a muted text line; desktop shows *nothing at all* inside the table body (just an empty `<tbody>`).
- Should: Add a proper empty-filter state with a "Сбросить фильтры" button. Distinguish "0 leads total" vs "0 match filters".
- **Effort: S · Impact: high**

### 11. Project detail page has no skeleton — whole page is blank during load
- File: `frontend/app/dashboard/projects/[projectId]/page.tsx:208`
- Wrong: Returns just `<Loader />` on a max-w-7xl container — a huge empty page that flashes on every refresh. Stats, tabs, filters all blink.
- Should: Skeleton loaders for the 4 stat cards + filter bar + table (pattern already exists in settings and projects/page).
- **Effort: S · Impact: med**

### 12. Dashboard-level error handler is a silent swallow
- File: `frontend/app/dashboard/page.tsx:126-127`
- Wrong: `} catch { /* Silently handle */ }` — if `/organizations/my-list` or `/projects` fails for any reason other than auth, the user sees a blank dashboard with no toast, no retry button.
- Should: Show a toast + inline "Не удалось загрузить данные. [Повторить]" card so users aren't stuck.
- **Effort: S · Impact: high**

### 13. Filter bar has 8 fields on one row, no reset / collapse
- File: `frontend/app/dashboard/projects/[projectId]/page.tsx:325-403`
- Wrong: Eight filter controls wrap awkwardly on laptop widths (~1280px), and there's no "Сбросить все фильтры" button once a user has applied a combination.
- Should: Collapse advanced filters behind a "Фильтры (3)" popover, always show a "Сбросить" link when any filter is non-default.
- **Effort: M · Impact: med**

### 14. Icon-only buttons on project cards lack aria-label / tooltip
- File: `frontend/app/dashboard/page.tsx:716-739`
- Wrong: The Pencil (edit) and Trash (delete) icon buttons have no `aria-label`, no `title`, no Tooltip. Screen readers announce "button" only, and the buttons are only visible on hover on desktop.
- Should: Add `aria-label="Редактировать"` / `aria-label="Удалить"` + `<Tooltip>` wrappers (the Tooltip component is already imported in `leads-table.tsx`).
- **Effort: XS · Impact: med**

### 15. `leads-table.tsx` uses emoji prefixes (📞 ✉️ 📍 🌐) in mobile cards
- File: `frontend/components/dashboard/leads-table.tsx:448, 453, 457, 461`
- Wrong: Emoji icons mixed with Lucide SVG icons elsewhere — inconsistent visual language. Looks "hackathon-y" vs. the polished desktop design.
- Should: Use the Phone / Mail / MapPin / Globe Lucide icons (already imported in neighbouring files) to match.
- **Effort: XS · Impact: med**

### 16. Tag-remove UX uses inline "✕" in a Badge; no clear affordance
- File: `frontend/components/dashboard/leads-table.tsx:207-209`
- Wrong: `<Badge ... onClick={removeTag}>{t} ✕</Badge>` — the whole badge is clickable but there's no hover state or confirmation; users will delete tags accidentally.
- Should: Make the `✕` a real `<button>` with hover state, separated from the label, and use `XIcon` from lucide instead of unicode ×.
- **Effort: S · Impact: low**

### 17. CTA eyebrow badge says "Новая версия" with no version indicator
- File: `frontend/components/landing/hero-section.tsx:37`
- Wrong: Sparkle + "Новая версия" + chevron implies a clickable "what's new" link, but it does nothing (no `<Link>`).
- Should: Either remove it, link it to a changelog, or change copy to something meaningful like "v2 · 221 городов".
- **Effort: XS · Impact: low**

### 18. Job error messages can dump 200-char stack-trace-like text into UI
- File: `frontend/components/dashboard/job-history.tsx:90-95`
- Wrong: `{job.error.slice(0, 200)}…` renders raw backend error strings verbatim. Users see things like "Failed to fetch" or Python exception text.
- Should: Map known error codes to friendly Russian ("Превышен лимит лидов — обновите тариф", "Источник 2ГИС временно недоступен, попробуйте позже") with a "Подробнее" toggle for the raw text.
- **Effort: M · Impact: high**

### 19. Generic toast error fallbacks leak English / unhelpful messages
- Files: `app/dashboard/projects/[projectId]/page.tsx:96, 163, 185, 203`, `settings/page.tsx:166, 185, 209, 225, 240, 251, 266, 284, 854`
- Wrong: When the error has no message, toasts fall back to "Не удалось загрузить проект" / "Ошибка экспорта" without actionable guidance. Worse, any raw API string (e.g. `"Failed to fetch"`) is passed straight to `toast.error`.
- Should: Wrap the error formatter in a helper that (a) translates known English API fragments, (b) appends an actionable hint ("Проверьте соединение и попробуйте снова"), (c) logs the raw text to console for debugging.
- **Effort: M · Impact: high**

### 20. Settings webhook has no format validation or test button
- File: `frontend/app/dashboard/settings/page.tsx:840-876`
- Wrong: `type="url"` only; no "Проверить webhook" button that POSTs a sample payload. Users save a bad URL and silently fail on real leads.
- Should: Add "Проверить" button → `POST /organizations/me/webhook/test` and show success/failure + response code.
- **Effort: M · Impact: high** (saves support tickets)

### 21. Onboarding: empty-state is a static checklist, not an interactive tour
- File: `frontend/app/dashboard/page.tsx:613-644`
- Wrong: The 3-step list is informational only — nothing pre-fills the "describe your business" form with an example or offers "Запустить демо-сбор" to see results with zero effort.
- Should: Either (a) add an "Заполнить примером" button that pre-populates the prompt with a B2B example and opens the dialog, or (b) a "Демо-проект" that shows sample leads so new users see value before spending quota.
- **Effort: M · Impact: high**

### 22. Landing page has no footer contact / support info
- File: `frontend/app/page.tsx:428-455`
- Wrong: Footer has no email, phone, company legal name (ИП / ООО), or support link. For a Russian B2B product asking ₽3900+/mo, the absence of "Реквизиты" / contact is a trust killer.
- Should: Add at least support email and legal entity line (e.g. "ИП Иванов · ИНН xxxxx") to the footer.
- **Effort: XS · Impact: high**

### 23. Sidebar layout pushes content below fixed mobile header with magic padding
- File: `frontend/app/dashboard/layout.tsx:8`
- Wrong: `pt-14 lg:pt-0` hard-codes a 56px gap for the mobile sidebar header; if the sidebar ever changes height, the dashboard content tucks under it. No aria-landmark for the `<main>`.
- Should: Let the sidebar component own its own spacer / use CSS grid with `[hamburger][main]` rows; add `aria-label="Основное содержимое"` to `<main>`.
- **Effort: S · Impact: low**

### 24. Register page has no real-time email format feedback
- File: `frontend/app/register/page.tsx:157-167`
- Wrong: Only `type="email"` browser validation — no inline "Email уже используется" check until after submit, and no "looks good" state for password length (only the negative "минимум 8" warning shows when short).
- Should: Add positive inline validation (green check) for password once ≥8 chars; consider `/auth/check-email` debounced call for duplicate email.
- **Effort: M · Impact: med**

### 25. "Забыли пароль?" link points to `/forgot-password` — route existence not guaranteed
- File: `frontend/app/login/page.tsx:120`
- Wrong: If `/forgot-password` doesn't exist, user hits a 404 from the login page. Worth verifying the page exists and is wired to a backend endpoint.
- Should: Confirm the route exists; if not, either implement it or remove the link.
- **Effort: XS (to verify) · Impact: high** (if broken)

### 26. Lead-row status badge is clickable but looks like a plain badge
- File: `frontend/components/dashboard/leads-table.tsx:591-613`
- Wrong: Status badge opens a dropdown but has no chevron / hover ring / cursor hint beyond `cursor-pointer`. Users won't discover they can change status.
- Should: Add a tiny chevron icon on hover, or a subtle border/underline, so the interaction is discoverable.
- **Effort: XS · Impact: med**

### 27. Export "CSV" / "Excel" buttons lack visual distinction from ghost nav
- File: `frontend/app/dashboard/projects/[projectId]/page.tsx:257-270`
- Wrong: Both use `variant="ghost"` with tiny 12px icons — look like tertiary nav instead of primary actions users will want often.
- Should: Use `variant="outline"` with "Экспорт ▾" dropdown → CSV / Excel, so primary action is discoverable.
- **Effort: S · Impact: med**

### 28. Quota progress bar colors don't reach colorblind accessibility
- File: `frontend/app/dashboard/page.tsx:343`
- Wrong: Quota indicator relies purely on red / amber / emerald gradient to signal state. Colorblind users can't distinguish them.
- Should: Add an icon (⚠ / ✓) or explicit text label ("Критично") alongside color.
- **Effort: XS · Impact: low**

### 29. Admin plan dropdown label mismatch: value `team`, display `Business`
- File: `frontend/app/dashboard/admin/page.tsx:255`
- Wrong: `<SelectItem value="team">Business</SelectItem>` — admins pick "Business" but the data model calls it `team`. If anything surfaces the raw value, it'll confuse.
- Should: Either rename backend enum to `business`, or display "Team (Business)" consistently.
- **Effort: M · Impact: low** (tech-debt)

### 30. "Следующий запуск: {preset label toLowerCase()}" reads awkward
- File: `frontend/app/dashboard/projects/[projectId]/page.tsx:521-523`
- Wrong: The preset label ("Каждый день 9:00") becomes "каждый день 9:00" inside the sentence but the label was already formatted as a Russian phrase. Reads slightly off ("Следующий запуск: каждый день 9:00. Получите email когда готово.").
- Should: Use a separate short label field per preset, e.g. "ежедневно 9:00" / "понедельники 9:00" / "1 и 15 числа 9:00", and say "Расписание: …".
- **Effort: XS · Impact: low**

---

## Summary

| Priority | Count | Combined effort |
|---|---|---|
| High-impact quick wins (XS/S) | #1, #2, #4, #5, #7, #8, #14, #15, #22, #25, #26 | ~half a day |
| High-impact deeper work (M/L) | #6, #12, #18, #19, #20, #21 | ~3–5 days |
| Nice-to-have polish | #3, #9, #10, #11, #13, #16, #17, #23, #24, #27, #28, #29, #30 | ~2–3 days |

Top recommendation: address #1, #2, #7, #5, #14, #22 in a single "landing + admin polish" PR — <2 hours, and each one removes a visible "this is a template / side-project" tell.
