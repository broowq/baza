"use client";

import { useEffect, useState } from "react";

import { Sidebar } from "@/components/layout/sidebar";
import { getToken } from "@/lib/auth";

export default function PlansLayout({ children }: { children: React.ReactNode }) {
  const [authed, setAuthed] = useState<boolean | null>(null);

  useEffect(() => {
    setAuthed(Boolean(getToken()));
  }, []);

  // While mounting, render content alone — avoids flash of the sidebar
  // for guests and avoids flash of the public navbar for logged-in users.
  if (authed === null) {
    return <div className="min-h-screen">{children}</div>;
  }

  // Logged-in users get the product shell (sidebar + main).
  if (authed) {
    return (
      <div className="flex min-h-screen">
        <Sidebar />
        <main className="flex-1 overflow-y-auto overflow-x-hidden min-w-0 pt-14 lg:pt-0">
          {children}
        </main>
      </div>
    );
  }

  // Guests see the public Navbar (rendered by RootLayout) above the page.
  return <div className="min-h-screen">{children}</div>;
}
