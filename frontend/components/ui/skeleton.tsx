export function Skeleton({ className = "" }: { className?: string }) {
  return (
    <div
      className={`animate-shimmer rounded-xl bg-slate-200 bg-[length:200%_100%] bg-[linear-gradient(90deg,transparent,rgba(0,0,0,0.04),transparent)] dark:bg-white/[0.06] dark:bg-[linear-gradient(90deg,transparent,rgba(255,255,255,0.04),transparent)] ${className}`}
    />
  );
}
