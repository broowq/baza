"use client";

import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { getToken } from "@/lib/auth";

export function SmartCTA() {
  const [loggedIn, setLoggedIn] = useState(false);

  useEffect(() => {
    setLoggedIn(Boolean(getToken()));
  }, []);

  const href = loggedIn ? "/dashboard" : "/register";
  const label = loggedIn ? "Перейти в дашборд" : "Попробовать бесплатно";

  return (
    <Link href={href}>
      <Button
        size="lg"
        className="h-12 rounded-full bg-[#191C1F] px-8 text-base font-semibold text-white shadow-none hover:bg-[#2C2F33] dark:bg-white dark:text-[#191C1F] dark:hover:bg-gray-100"
      >
        {label}
        <ArrowRight className="ml-2" size={16} />
      </Button>
    </Link>
  );
}

/** Smart link that goes to /dashboard if logged in, otherwise fallback */
export function SmartLink({ fallback = "/register", children, className }: { fallback?: string; children: React.ReactNode; className?: string }) {
  const [loggedIn, setLoggedIn] = useState(false);

  useEffect(() => {
    setLoggedIn(Boolean(getToken()));
  }, []);

  const href = loggedIn ? "/dashboard" : fallback;

  return (
    <Link href={href as "/dashboard"} className={className}>
      {children}
    </Link>
  );
}
