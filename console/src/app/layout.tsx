import type { Metadata, Viewport } from "next";
import "./globals.css";

/**
 * No `next/font/google` here, for two reasons:
 *
 *  1. It fetches font files at BUILD time. A teammate building offline (or on
 *     conference wifi the morning of a demo) would fail the build.
 *  2. Geist has no Bengali coverage. Our corpus is Bangla and Banglish, so
 *     forcing a Latin-only webfont would render Sylhet place names as tofu
 *     boxes. Falling through to the system stack lets the OS pick a
 *     Bengali-capable font.
 *
 * The monospace stack is set in globals.css via --font-mono.
 */

export const metadata: Metadata = {
  title: "GroundTruth — Disaster Triage Console",
  description:
    "First-72-hours flood triage console for Sylhet: fuses satellite building damage, imagery findings, and verified citizen signals into one ranked map.",
};

export const viewport: Viewport = {
  themeColor: "#04060c",
  colorScheme: "dark",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="min-h-full">{children}</body>
    </html>
  );
}
