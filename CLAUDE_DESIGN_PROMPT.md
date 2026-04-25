# Claude Design Prompt — БАЗА (cinematic glass)

> Скопируй блок ниже целиком и вставь в Claude (claude.ai). Он должен отрендерить полный HTML-артефакт с дизайном.
> Если артефакт получится частичным — попроси «продолжи остальные экраны в том же стиле».

---

```
Сделай в одном HTML-артефакте дизайн-макеты для БАЗА — российской B2B SaaS-платформы для лидогенерации (usebaza.ru).

## ВИЗУАЛЬНЫЙ ЯЗЫК — обязательно следуй

Стиль референса — rondesignlab Public Transit OS (cinematic glass, dark-only, ambient computing). Скриншоты, которые я показал, — операторская панель общественного транспорта со следующими признаками:

1. **Канвас:** чисто-чёрный (#0A0A0B) или фотография техники / спутниковая карта на фоне. UI — стеклянные карточки поверх. Никаких белых/серых блоков.

2. **Стекло (glass):**
   - bg: rgba(255,255,255,0.04-0.06)
   - border: 1px rgba(255,255,255,0.08-0.12)
   - backdrop-filter: blur(24-40px)
   - shadow: inset 0 1px 0 0 rgba(255,255,255,0.08) — едва заметное свечение по верхнему ребру
   - НЕТ внешних drop-shadow. Глубина — только через blur и прозрачность.

3. **Радиусы — крупные:**
   - rounded-3xl (24px) для hero/feature cards
   - rounded-2xl (16px) для content
   - rounded-full для pills/buttons

4. **Типографика — Geist (или Inter fallback):**
   - HUGE цифры (KPI, цены, проценты): font-weight 200 (extralight), 48-96px, tracking-tight, leading-[0.95]. Это подпись стиля.
   - Заголовки секций: font-weight 300 (light), 32-56px, tracking-tight
   - Тело: font-weight 400 (normal), 14-15px
   - Eyebrow-метки над секциями: 11px uppercase tracking-wider text-white/[0.48]
   - Все цифры используют tabular-nums

5. **Цвет — почти монохром, акценты ТОЛЬКО:**
   - Online/доставляемо: #34D399 (emerald-400) с свечением box-shadow 0 0 8px rgba(52,211,153,0.7)
   - Offline/ошибка: #F43F5E (rose-500)
   - Warning: #FBBF24 (amber-400)
   - Brand CTA: #FF6A00 (orange) — ОДНА кнопка на экран
   - Всё остальное — белый с прозрачностью: text-white, text-white/[0.72] (body), text-white/[0.48] (muted), text-white/[0.28] (faint)

6. **Status dots:** 1.5×1.5 px кружочек цвета статуса, с glow shadow того же цвета, с пульсацией (scale 1↔1.15, 2s ease-in-out infinite).

7. **Pill-tabs (как «Live Map / Fleet / Routes / Analytics» в скрине 1):**
   - inline-flex в стеклянном контейнере rounded-full bg-white/[0.05] border-white/[0.10] p-1
   - неактивная: text-white/[0.56] hover:text-white
   - активная: bg-white/[0.10] text-white (БЕЗ цветного фона)

8. **Charts (как «Operational Efficiency 78.3%»):**
   - Линии stroke-1 white/40, выделенный сегмент — orange #FF6A00 stroke-1
   - Ось/метки 11px text-white/[0.40], gridlines white/[0.04] dashed
   - Без рамок, без заливки под линией

9. **Animation:** плавно (200-400ms ease-out). Никаких bouncy-springs, никаких больших translate. Только opacity и slow drift.

10. **Карта/спутник как фон** где уместно — через mapbox static API (можешь имитировать через темную текстуру с зелёными/коричневыми пятнами и тонкими белыми линиями дорог).

## ПРОДУКТ — что показывать

БАЗА — премиум B2B-инструмент для русских продаж: пишешь промпт «Продаю кормовые добавки в Томске» → ИИ выдаёт 100+ птицефабрик/ферм/агрохолдингов с email и телефонами. Конкуренты: Контур.Компас (доминирующий), Apollo.io. Цена ₽5000+/мес. Аудитория: sales-операторы, маркетинговые агентства, B2B-фаундеры.

Все строки — на русском. Realistic данные: реальные русские названия компаний, города, ОКВЭД-коды.

## ЭКРАНЫ — отрисуй ВСЕ четыре в одном артефакте, секциями сверху вниз

### 1. ЛЕНДИНГ (Hero + ниже)

- Глобальный navbar pill (sticky top, max-w-6xl mx-auto): logo «БАЗА» слева | nav (Тарифы, Как работает, FAQ) центр | «Войти» + brand-pill «Начать бесплатно» справа
- Hero: full-bleed аврора-blobs за стеклом, eyebrow pill «✨ ИИ-поиск B2B-клиентов», headline 60-72px font-light: «Найди 100 клиентов за минуту — по одному промпту» (где «100 клиентов» курсивом extralight тонким), subheadline до 600px, две CTA — orange brand pill «Попробовать бесплатно →» и стеклянная secondary pill «Как это работает»
- Под hero: 3 floating glass cards с tilt -1°/0°/+1° показывающие реальный лид: «Птицефабрика "Юг"» Томск, «Агрохолдинг СТЕПЬ» Ростов-на-Дону, «Юрьевецкая п/ф» Иваново. Каждая карточка: source-badge сверху (2GIS/ЕГРЮЛ/Я.Карты), имя, город, score 92/87/78 в extralight 32px, email с зелёным dot
- Stats strip: 850K+ компаний / 94% доставляемость / <60 секунд / 16 источников — все extralight 4xl
- Pricing: 4 тарифа (Free 0₽ / Starter 1490₽ / Pro 4990₽ выделен оранжевым ring + glow / Team 12990₽). Каждый стеклянный rounded-3xl, цена extralight 4xl, фичи с зелёными чек-маркерами

### 2. ДАШБОРД (Cockpit)

- Sidebar слева (w-60, bg-black/40 backdrop-blur-xl, border-r white/[0.08]): logo + nav items (Дашборд, Проекты, Лиды, Настройки)
- Top bar: search command pill «⌘K Поиск...» + notif icon + avatar
- KPI strip — 4 hero glass cards в grid:
  - «ВСЕГО ЛИДОВ» 2,847 (extralight 5xl) +12% за 7 дней
  - «ОБОГАЩЕНО» 1,923 / 67%
  - «С EMAIL» 1,456 + зелёный online dot
  - «СРЕДНИЙ SCORE» 72 / 100
  - В углу каждой — мини-sparkline (60×24, stroke-1 white/[0.40], последний сегмент orange)
- Recent projects — 3 glass cards: «Кормовые добавки Томск», «HoReCa оборудование Москва», «Стройматериалы СПб». Каждая: имя + online status dot, ниша·гео, чипы сегментов, мини-stats внизу (134 лидов · 89 enriched · 71 score)

### 3. СТРАНИЦА ПРОЕКТА (Project detail)

- Header: breadcrumb «← Назад», название проекта 5xl light, ниже row metadata pills (агропром · Томская область · 23 сегмента), под ним ОКВЭД-чипы (01.47 Птицеводство, 01.46 Свиноводство, 01.41 КРС — каждый стеклянный rounded-md font-mono blue-tint)
- Action cluster справа: brand pill «Собрать лиды», secondary glass «Обогатить», icon-buttons CSV/Excel/Webhook
- Auto-collection bar: glass-card с toggle (включён) + dropdown «Ежедневно 09:00» + текст «Следующий сбор: завтра 09:00»
- KPI strip — 4 cards (Всего/Обогащено/С email/Avg score)
- Главная панель: hero glass card rounded-3xl, заголовок «Лиды», под ним фильтры (search, status, sort), ниже таблица с колонками: Компания (с source-glyph эмоджи 🅉/②/📋 + email-status ✓/!) | Город | Email | Телефон | Адрес | Статус (badge с dot) | Score (горизонтальная brand-fill полоска 80px + число mono)
- 5-7 строк realистичных данных

### 4. ТАБЛИЦА ЛИДОВ (детальный вид + drawer)

- Та же таблица, но с открытым справа Sheet/drawer (w-[480px]) показывающим выбранного лида:
  - Шапка drawer: имя компании, address copy-button, close
  - Score visualization (большая horizontal bar)
  - Status dropdown
  - Tags input (chip-стиль с x для удаления)
  - Notes textarea (glass background)
  - Reminder date-picker
  - Action buttons: brand «Связаться», secondary «Отметить как qualified», ghost «Удалить»

## ТЕХНИЧЕСКИЕ ТРЕБОВАНИЯ

- Single HTML файл с inline styles или один <style> блок
- Tailwind CSS через CDN ОК (https://cdn.tailwindcss.com)
- Использовать font-feature-settings: "tnum" 1 для числовых блоков
- Все scrollable области с custom-scrollbar 8px shadow-white/[0.08]
- Lucide-иконки через CDN (или inline SVG в стиле stroke-1.5 currentColor)
- Mock-карта на фоне проекта = темная svg/canvas с зелёными blob-облаками + тонкие белые линии дорог
- Aurora-blobs = три абсолют-позиционированных div с radial-gradients и blur(120px) animation drift 18-25s

## ANTI-PATTERNS — не делай

- ❌ Любые цветные градиенты на чипах/кнопках кроме brand orange
- ❌ Heavy drop shadows
- ❌ font-bold (700+) на цифрах — только extralight 200 / light 300
- ❌ rounded-md / rounded-lg на hero surfaces
- ❌ Solid borders > 1px
- ❌ Bouncy-spring анимации
- ❌ Эмоджи как декорация (только функциональные source-glyphs в таблицах)
- ❌ Solid white panels — стекло обязательно

## QUALITY GATE — перед сдачей проверь

✅ Pure black canvas. Нигде не белый/светло-серый.
✅ Минимум одно ОГРОМНОЕ ТОНКОЕ число (KPI или цена) на каждом экране
✅ Все радиусы ≥ 12px
✅ Не больше 2 разных акцентных цветов в одном экране
✅ Status dots имеют glow shadow
✅ Текст на русском, цифры с tabular-nums
✅ Cohesive — все 4 экрана выглядят как один продукт

Начни с лендинга, потом дашборд, потом проект, потом таблица. Каждый экран — отдельная секция в артефакте, разделены тонкой линией white/[0.08]. Минимум 2000 строк HTML/CSS — без скупости на детали.
```

---

## Как пользоваться

1. Открой [claude.ai](https://claude.ai)
2. Создай новый чат, выбери Sonnet или Opus
3. Скопируй ВЕСЬ блок выше (между ``` и ```)
4. Вставь и отправь
5. Claude отрендерит HTML-артефакт со всеми 4 экранами
6. Если получилось 1-2 экрана — попроси «продолжи остальные в том же стиле»
7. Если стиль уехал — ткни в Anti-Patterns + Quality Gate и попроси переделать конкретный экран

Когда визуально устроит — скинь мне HTML, я перенесу в наш Next.js без потери стиля.
