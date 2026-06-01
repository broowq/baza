export function Loader() {
  return (
    <div role="status" aria-live="polite" className="flex items-center gap-2 text-sm text-white/56">
      <span className="inline-block h-5 w-5 animate-spin rounded-full border-2 border-white/10 border-t-[var(--mint)]" />
      Загрузка...
    </div>
  );
}
