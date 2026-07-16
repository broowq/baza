import type { Metadata } from "next";
import { Instrument_Serif } from "next/font/google";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import { Toaster } from "sonner";

import "@/app/globals.css";
import Analytics from "@/components/analytics";
import { ChunkReloadGuard } from "@/components/chunk-reload-guard";
import { CookieConsent } from "@/components/cookie-consent";
import { ErrorBoundary } from "@/components/error-boundary";
import { Navbar } from "@/components/layout/navbar";
import { SmoothScrollProvider } from "@/components/smooth-scroll-provider";
import { ThemeProvider } from "@/components/theme-provider";

// Instrument Serif italic — used for one decorative emphasis on the hero ("созревают").
const instrument = Instrument_Serif({
  weight: "400",
  style: "italic",
  subsets: ["latin"],
  variable: "--font-instrument",
  display: "swap",
});

const appUrl = process.env.NEXT_PUBLIC_APP_URL || "https://usebaza.ru";

const siteDescription =
  "Поиск B2B-клиентов с контактами за минуты: 2ГИС, Яндекс.Карты, Яндекс.Поиск. Опишите клиента своими словами — получите список компаний с email и телефонами.";

export const metadata: Metadata = {
  metadataBase: new URL(appUrl),
  title: "БАЗА - B2B SaaS для лидогенерации",
  description: siteDescription,
  icons: {
    icon: "/favicon.svg",
  },
  openGraph: {
    title: "БАЗА - B2B SaaS для лидогенерации",
    description: siteDescription,
    url: appUrl,
    siteName: "БАЗА",
    locale: "ru_RU",
    type: "website",
  },
  twitter: {
    card: "summary",
    title: "БАЗА - B2B SaaS для лидогенерации",
    description: siteDescription,
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="ru"
      suppressHydrationWarning
      className={`${GeistSans.variable} ${GeistMono.variable} ${instrument.variable}`}
    >
      <body className={`${GeistSans.className} font-sans overflow-x-hidden antialiased`}>
        {/* ThemeProvider sets the resolved theme class on <html> before paint
            (no flash); default = system, with a manual toggle in the UI. */}
        <ThemeProvider>
          {/* Устаревший бандл после деплоя → ChunkLoadError → тихая перезагрузка,
              чтобы почти любая кнопка не отдавала «Что-то пошло не так». */}
          <ChunkReloadGuard />
          {/* Top hairline that fills mint-to-white as the user scrolls.
              Driven by --scroll-progress emitted by SmoothScrollProvider. */}
          <div className="scroll-progress" aria-hidden />
          <SmoothScrollProvider>
            <div className="page-shell">
              <Navbar />
              <ErrorBoundary>
                {children}
              </ErrorBoundary>
              <Toaster richColors position="top-right" />
              <CookieConsent />
            </div>
          </SmoothScrollProvider>
          <Analytics />
        </ThemeProvider>
      </body>
    </html>
  );
}
