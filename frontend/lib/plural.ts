/**
 * Русские склонения по числу. Аудит 16.07 (перед стартом продаж) нашёл
 * «1 лидов», «3 мест», «остаток квоты: 1 проектов», «Найдена 2 раз» по всему
 * интерфейсу — каждая страница склоняла сама и по-своему. Единая точка.
 *
 * plural(n, "лид", "лида", "лидов") → строка БЕЗ числа
 * pluralN(...) → «21 лид», «2 лида», «5 лидов»
 */
export function plural(n: number, one: string, few: string, many: string): string {
  const m10 = Math.abs(n) % 10;
  const m100 = Math.abs(n) % 100;
  if (m10 === 1 && m100 !== 11) return one;
  if (m10 >= 2 && m10 <= 4 && (m100 < 10 || m100 >= 20)) return few;
  return many;
}

export function pluralN(n: number, one: string, few: string, many: string): string {
  return `${n.toLocaleString("ru-RU")} ${plural(n, one, few, many)}`;
}

export const leadsN = (n: number) => pluralN(n, "лид", "лида", "лидов");
export const projectsN = (n: number) => pluralN(n, "проект", "проекта", "проектов");
export const seatsN = (n: number) => pluralN(n, "место", "места", "мест");
export const companiesN = (n: number) => pluralN(n, "компания", "компании", "компаний");
