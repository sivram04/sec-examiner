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
        <header className="flex flex-wrap items-baseline gap-4 px-4 pt-5 sm:px-6">
          <h1 className="text-lg font-semibold">SEC Examiner</h1>
          <p className="text-sm text-muted">
            Predicts what SEC staff will question in a 10-K, 10-Q or 20-F. Graded against real
            comment letters. Not legal advice.
          </p>
        </header>
        <Nav />
        <main className="mx-auto max-w-5xl px-4 pt-5 pb-16 sm:px-6">{children}</main>
      </body>
    </html>
  );
}
