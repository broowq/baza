import { Sidebar } from "@/components/layout/sidebar";
import { SessionWarning } from "@/components/session-warning";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen">
      <Sidebar />
      <main className="flex-1 overflow-y-auto overflow-x-hidden min-w-0">
        {children}
      </main>
      <SessionWarning />
    </div>
  );
}
