import type { Metadata, Viewport } from "next";
import "./globals.css";

import { AppShell } from "@/components/AppShell";
import { SessionProvider } from "@/components/SessionProvider";

export const metadata: Metadata = {
  title: "Matchly — your football highlights",
  description:
    "Play your match, get your highlights. Automatic recording and highlight clips for small football pitches.",
  applicationName: "Matchly",
};

export const viewport: Viewport = {
  themeColor: "#0a0d10",
  width: "device-width",
  initialScale: 1,
  // Players watch video on phones; let them pinch-zoom rather than locking it.
  maximumScale: 5,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <SessionProvider>
          <AppShell>{children}</AppShell>
        </SessionProvider>
      </body>
    </html>
  );
}
