import type { Metadata } from "next";
import localFont from "next/font/local";
import "./globals.css";

// Fonts are committed to the repo (SIL OFL 1.1). Nothing is fetched at runtime.
const barlow = localFont({
  src: [
    { path: "./fonts/barlow-semi-condensed-latin-500-normal.woff2", weight: "500" },
    { path: "./fonts/barlow-semi-condensed-latin-600-normal.woff2", weight: "600" },
  ],
  variable: "--font-barlow",
  display: "swap",
});
const plex = localFont({
  src: [
    { path: "./fonts/ibm-plex-sans-latin-400-normal.woff2", weight: "400" },
    { path: "./fonts/ibm-plex-sans-latin-500-normal.woff2", weight: "500" },
    { path: "./fonts/ibm-plex-sans-latin-600-normal.woff2", weight: "600" },
  ],
  variable: "--font-plex",
  display: "swap",
});
const plexMono = localFont({
  src: [
    { path: "./fonts/ibm-plex-mono-latin-400-normal.woff2", weight: "400" },
    { path: "./fonts/ibm-plex-mono-latin-500-normal.woff2", weight: "500" },
  ],
  variable: "--font-plex-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "KILA",
  description: "Sovereign, air-gapped AI workbench",
  robots: { index: false, follow: false },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${barlow.variable} ${plex.variable} ${plexMono.variable}`}>
      {/* Browser extensions inject attributes into <body>; ignore those mismatches only. */}
      <body suppressHydrationWarning>{children}</body>
    </html>
  );
}
