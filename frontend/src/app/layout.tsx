import type { Metadata } from "next";
import Nav from "@/components/Nav";
import "./globals.css";

export const metadata: Metadata = {
  title: "SEC Examiner",
  description: "Predicts which disclosures SEC staff will question, graded against real comment letters.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className="font-sans antialiased">
        <header className="border-b border-line bg-panel">
          <div className="mx-auto flex max-w-5xl flex-wrap items-end justify-between gap-x-6 px-4 pt-4 sm:px-6">
            <a href="/examiner" className="flex items-center gap-2 pb-3">
              <span className="grid h-7 w-7 place-items-center rounded-md bg-accent text-sm font-bold text-accent-ink">SE</span>
              <span className="text-base font-semibold">SEC Examiner</span>
            </a>
            <Nav />
          </div>
        </header>
        <main className="mx-auto max-w-5xl px-4 pt-6 pb-16 sm:px-6">{children}</main>
        <footer className="mx-auto max-w-5xl px-4 pb-8 text-[12px] text-muted sm:px-6">
          Predictions are statistical and graded against public SEC comment letters. Not legal or
          accounting advice.
        </footer>
      </body>
    </html>
  );
}
