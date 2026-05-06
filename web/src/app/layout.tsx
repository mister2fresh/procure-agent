import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";
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
  title: "procure-agent — quote reconciliation",
  description:
    "An AI agent that extracts supplier quotes, matches each line to the product master, surfaces divergence flags, and pauses for human approval before producing a PO.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>): React.ReactElement {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}>
      <body className="min-h-full flex flex-col bg-background text-foreground">
        <header className="border-b border-border">
          <div className="mx-auto max-w-6xl px-6 py-4 flex items-center justify-between">
            <Link href="/" className="font-semibold tracking-tight">
              procure-agent
            </Link>
            <span className="text-xs text-muted-foreground font-mono">
              quote reconciliation · HITL demo
            </span>
          </div>
        </header>
        <main className="flex-1">{children}</main>
        <footer className="border-t border-border">
          <div className="mx-auto max-w-6xl px-6 py-4 text-xs text-muted-foreground">
            Synthetic data only. No real supplier or buyer information shown.
          </div>
        </footer>
      </body>
    </html>
  );
}
