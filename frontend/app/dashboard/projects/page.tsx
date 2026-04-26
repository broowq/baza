"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

// /dashboard/projects was a duplicate of /dashboard — both showed the same
// project list. The «Проекты» nav item now points at /dashboard. This redirect
// keeps any stale bookmarks landing somewhere meaningful.
export default function ProjectsRedirect() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/dashboard");
  }, [router]);
  return null;
}
