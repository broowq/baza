import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import type { CollectionJob } from "@/lib/types";

type Props = {
  jobs: CollectionJob[];
  loading?: boolean;
};

const KIND_LABELS: Record<string, string> = { collect: "Сбор лидов", enrich: "Обогащение" };
const STATUS_LABELS: Record<string, string> = { queued: "В очереди", running: "В работе", done: "Завершено", failed: "Ошибка" };
const STATUS_VARIANTS: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  queued: "outline",
  running: "secondary",
  done: "default",
  failed: "destructive",
};

const BAR_COLORS: Record<string, string> = {
  failed: "bg-destructive",
  running: "bg-primary",
  done: "bg-emerald-500",
  queued: "bg-muted-foreground",
};

export function JobHistory({ jobs, loading = false }: Props) {
  const safeJobs = Array.isArray(jobs) ? jobs : [];

  if (loading) {
    return <div className="h-48 animate-pulse rounded-xl bg-muted" />;
  }

  if (safeJobs.length === 0) {
    return (
      <div className="rounded-xl border border-dashed p-8 text-center">
        <h3 className="text-base font-semibold">История задач пуста</h3>
        <p className="mt-1 text-sm text-muted-foreground">Запустите сбор или обогащение, чтобы увидеть прогресс.</p>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {safeJobs.map((job) => {
        const requested = typeof job.requested_limit === "number" ? job.requested_limit : 0;
        const progressValue = job.kind === "collect" ? job.found_count : job.enriched_count;
        const progress = job.status === "done"
          ? 100
          : job.status === "failed"
            ? 0
            : requested > 0
              ? Math.min(99, Math.round((progressValue / requested) * 100))
              : 0;

        return (
          <Card key={job.id} size="sm">
            <CardContent className="space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-medium">{KIND_LABELS[job.kind] ?? job.kind}</span>
                <Badge variant={STATUS_VARIANTS[job.status] ?? "secondary"}>
                  {STATUS_LABELS[job.status] ?? job.status}
                </Badge>
                {job.status !== "queued" && (
                  <span className="text-xs text-muted-foreground tabular-nums">{progress}%</span>
                )}
              </div>

              <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
                <div
                  className={`h-full rounded-full transition-[width] duration-700 ease-out ${BAR_COLORS[job.status] ?? BAR_COLORS.queued}`}
                  style={{ width: `${progress}%` }}
                />
              </div>

              <div className="flex flex-wrap gap-3 text-xs text-muted-foreground">
                {job.kind === "collect" && (
                  <>
                    <span>Найдено: <strong className="text-foreground">{job.found_count}</strong></span>
                    <span>Добавлено: <strong className="text-foreground">{job.added_count}</strong></span>
                  </>
                )}
                {job.kind === "enrich" && (
                  <span>Обогащено: <strong className="text-foreground">{job.enriched_count}</strong></span>
                )}
                {requested > 0 && (
                  <span>Лимит: <strong className="text-foreground">{requested}</strong></span>
                )}
              </div>

              {job.error && (
                <p
                  className="rounded-md bg-destructive/10 px-2 py-1 text-xs text-destructive"
                  title={job.error}
                >
                  {job.error.length > 200 ? `${job.error.slice(0, 200)}…` : job.error}
                </p>
              )}
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}
