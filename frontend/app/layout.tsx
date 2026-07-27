import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";
import { ThemeProvider } from "next-themes";

import { ThemeToggle } from "@/components/theme-toggle";

import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Agentic Market Explainer",
  description:
    "Ask why a stock moved and get a real investigation — live data, ranked hypotheses, traceable sources.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="flex min-h-screen flex-col">
        <ThemeProvider attribute="class" defaultTheme="light" enableSystem={false}>
          <header className="sticky top-0 z-10 border-b bg-background/80 backdrop-blur">
            <div className="mx-auto flex h-14 max-w-5xl items-center justify-between px-4">
              <Link href="/" className="text-sm font-semibold tracking-tight">
                Agentic <span className="text-primary">Market Explainer</span>
              </Link>
              <nav className="flex items-center gap-1">
                <Link
                  href="/about"
                  className="rounded-md px-3 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
                >
                  About
                </Link>
                <ThemeToggle />
              </nav>
            </div>
          </header>
          <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-6">{children}</main>
          <footer className="border-t">
            <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-3 text-xs text-muted-foreground">
              <span>Not investment advice. Data can be delayed or wrong.</span>
              <a
                href="https://buymeacoffee.com/sakthibats"
                target="_blank"
                rel="noopener noreferrer"
                className="transition-colors hover:text-primary"
              >
                ☕ Support this project
              </a>
            </div>
          </footer>
        </ThemeProvider>
      </body>
    </html>
  );
}
