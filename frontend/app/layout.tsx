import type { Metadata } from "next";
import { Inter } from "next/font/google";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import { Toaster } from "sonner";

import "@/app/globals.css";
import Analytics from "@/components/analytics";
import { CookieConsent } from "@/components/cookie-consent";
import { ErrorBoundary } from "@/components/error-boundary";
import { Navbar } from "@/components/layout/navbar";

// Inter kept as Cyrillic fallback; Geist is the primary display + body face.
const inter = Inter({ subsets: ["latin", "cyrillic"], variable: "--font-inter" });

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
    <html lang="ru" className={`dark ${GeistSans.variable} ${GeistMono.variable} ${inter.variable}`}>
      <body className={`${GeistSans.className} font-sans overflow-x-hidden antialiased`}>
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
