import type { Metadata } from "next";
import { Inter } from "next/font/google";
import { Toaster } from "sonner";

import "@/app/globals.css";
import Analytics from "@/components/analytics";
import { CookieConsent } from "@/components/cookie-consent";
import { ErrorBoundary } from "@/components/error-boundary";
import { Navbar } from "@/components/layout/navbar";

const inter = Inter({ subsets: ["latin", "cyrillic"], variable: "--font-sans" });

const appUrl = process.env.NEXT_PUBLIC_APP_URL || "https://baza.io";

export const metadata: Metadata = {
  metadataBase: new URL(appUrl),
  title: "БАЗА - B2B SaaS для лидогенерации",
  description: "Мультитенантная платформа для поиска и обогащения B2B-лидов",
  icons: {
    icon: "/favicon.svg",
  },
  openGraph: {
    title: "БАЗА - B2B SaaS для лидогенерации",
    description: "Мультитенантная платформа для поиска и обогащения B2B-лидов",
    url: appUrl,
    siteName: "БАЗА",
    locale: "ru_RU",
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "БАЗА - B2B SaaS для лидогенерации",
    description: "Мультитенантная платформа для поиска и обогащения B2B-лидов",
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ru" className={`dark ${inter.variable}`}>
      <body className={`${inter.className} font-sans overflow-x-hidden`}>
        <div className="page-shell">
          <Navbar />
          <ErrorBoundary>
            {children}
          </ErrorBoundary>
          <Toaster richColors position="top-right" />
          <CookieConsent />
        </div>
        <Analytics />
      </body>
    </html>
  );
}
