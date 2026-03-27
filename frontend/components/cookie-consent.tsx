"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { motion, AnimatePresence } from "framer-motion";
import { Button } from "@/components/ui/button";

const COOKIE_CONSENT_KEY = "baza_cookie_consent";

export function CookieConsent() {
  const [visible, setVisible] = useState(false);
  const [exiting, setExiting] = useState(false);

  useEffect(() => {
    const consent = localStorage.getItem(COOKIE_CONSENT_KEY);
    if (!consent) {
      setVisible(true);
    }
  }, []);

  function dismiss(value: "accepted" | "declined") {
    localStorage.setItem(COOKIE_CONSENT_KEY, value);
    setExiting(true);
  }

  function handleExitComplete() {
    if (exiting) setVisible(false);
  }

  if (!visible) return null;

  return (
    <AnimatePresence onExitComplete={handleExitComplete}>
      {!exiting && (
        <motion.div
          initial={{ opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: 24 }}
          transition={{ duration: 0.3, ease: "easeOut" }}
          className="fixed bottom-4 right-4 z-50 max-w-md rounded-2xl border border-border/50 bg-background/90 p-4 shadow-lg backdrop-blur-lg"
        >
          <p className="mb-3 text-sm text-muted-foreground">
            Мы используем файлы cookie для работы сервиса и аналитики.{" "}
            <Link
              href="/privacy"
              className="underline transition-colors hover:text-foreground"
            >
              Подробнее
            </Link>
          </p>
          <div className="flex items-center justify-end gap-2">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => dismiss("declined")}
            >
              Отклонить
            </Button>
            <Button
              variant="default"
              size="sm"
              onClick={() => dismiss("accepted")}
            >
              Принять
            </Button>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
