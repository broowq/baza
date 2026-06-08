export const PLAN_LABELS: Record<string, string> = { free: "Free", starter: "Starter", pro: "Pro", team: "Business" };
export const formatPlan = (p?: string | null): string => (p ? (PLAN_LABELS[p] ?? p) : "");
