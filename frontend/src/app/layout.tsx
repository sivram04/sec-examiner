import type { Metadata } from "next";
import { Archivo, Source_Serif_4 } from "next/font/google";
import Nav from "@/components/Nav";
import "./globals.css";

const display = Archivo({ subsets: ["latin"], axes: ["wdth"], variable: "--font-display", display: "swap" });
const body = Source_Serif_4({ subsets: ["latin"], variable: "--font-body", display: "swap" });

export const metadata: Metadata = {
  title: "SEC Examiner: what will the SEC ask about your 10-K?",
  description:
    "Predicts the topics SEC staff are likely to raise in a comment letter, and the disclosures they will find missing. Graded on 5,107 real SEC comment letters.",
};

const CONTRACT = ` THESIS: the product is set like an official government document (a dated issue, numbered sections, rulings with citations); refuses the SaaS hero with a floating dashboard mock.
 OWN-WORLD: Federal Register print. Government stock #fbfaf7, black ink, hairline and heavy rules, agency blue #1c3d8c heads, one red stamp #b3261e for findings only; condensed Archivo caps over Source Serif text.
 STORY: a reporting team (or recruiter) learns in seconds what it predicts, sees a real ruling, believes the honest numbers on a ruled scale, and examines a filing.
 FIRST VIEWPORT: masthead strip; poster-scale two-line question left with the ticker input and examples under it; a printed Alibaba ruling right with red NOT FOUND stamps.
 FORM: Federal Register page, 6th of 7 on the ordered list; seed de1977c0. Raises: combo-sheet hierarchy, brick-instructions numbered steps, oscilloscope ruled scale.
 FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance `;

function Contract() {
  // first child of <body>: an HTML comment that survives the static export
  return <div hidden dangerouslySetInnerHTML={{ __html: `<!--${CONTRACT}-->` }} />;
}

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`${display.variable} ${body.variable}`}>
      <body className="font-serif antialiased">
        <Contract />
        <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-2 focus:z-50 focus:bg-accent focus:px-3 focus:py-2 focus:text-accent-ink">
          Skip to content
        </a>
        <Nav />
        <main id="main" className="mx-auto max-w-6xl px-4 pb-20 sm:px-6">{children}</main>
        <footer className="mx-auto max-w-6xl px-4 pb-10 sm:px-6">
          <div className="rule-double pt-4 text-[13px] leading-relaxed text-muted sm:flex sm:justify-between sm:gap-8">
            <p className="max-w-2xl">
              SEC Examiner ranks likely comment topics from public SEC data. It is not legal or accounting
              advice and is not affiliated with or endorsed by the U.S. Securities and Exchange Commission.
            </p>
            <p className="mt-3 shrink-0 sm:mt-0">
              <a className="underline hover:text-ink" href="https://github.com/sivram04/sec-examiner">Source on GitHub</a>
              {" · "}Apache-2.0
            </p>
          </div>
        </footer>
      </body>
    </html>
  );
}
