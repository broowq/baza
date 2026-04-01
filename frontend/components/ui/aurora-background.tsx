"use client";

export function AuroraBackground({ children, className = "" }: { children?: React.ReactNode; className?: string }) {
  return (
    <div className={`relative overflow-hidden ${className}`}>
      {/* Aurora blobs */}
      <div className="pointer-events-none absolute inset-0 -z-10 overflow-hidden" aria-hidden="true">
        <div className="absolute -top-1/2 -left-1/4 h-[800px] w-[800px] rounded-full bg-violet-500/20 blur-[120px] animate-aurora-1" />
        <div className="absolute -top-1/3 -right-1/4 h-[600px] w-[600px] rounded-full bg-sky-500/15 blur-[120px] animate-aurora-2" />
        <div className="absolute -bottom-1/4 left-1/3 h-[700px] w-[700px] rounded-full bg-emerald-500/10 blur-[120px] animate-aurora-3" />
      </div>
      {children}
    </div>
  );
}
