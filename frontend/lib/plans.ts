// Казус имён: enum-значение `team` исторически занято тиром Business,
// поэтому средний тир «Team» живёт под значением `growth` (см. бэкенд PlanType).
export const PLAN_LABELS: Record<string, string> = { free: "Free", starter: "Starter", growth: "Team", pro: "Pro", team: "Business" };
export const formatPlan = (p?: string | null): string => (p ? (PLAN_LABELS[p] ?? p) : "");
