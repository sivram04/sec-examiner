import type { Metadata } from "next";
import Nav from "@/components/Nav";
import "./globals.css";

export const metadata: Metadata = {
  title: "AI Research Desk",
  description: "Cited equity research from SEC filings. Point-in-time. Not investment advice.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className="font-sans antialiased">
        <header className="flex flex-wrap items-baseline gap-4 px-4 pt-5 sm:px-6">
          <h1 className="text-lg font-semibold">AI Research Desk</h1>
          <p className="text-sm text-muted">
            Cited research from SEC filings. Point-in-time. Research only, not investment advice.
          </p>
        </header>
        <Nav />
        <main className="mx-auto max-w-5xl px-4 pt-5 pb-16 sm:px-6">{children}</main>
      </body>
    </html>
  );
}
