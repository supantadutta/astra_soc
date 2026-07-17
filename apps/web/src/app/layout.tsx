import type { Metadata, Viewport } from "next";
import "@/styles/globals.css";
import { AppProvider } from "@/lib/store";

export const metadata: Metadata = {
  title: "ASTRASOC — Autonomous Security Operations",
  description:
    "Autonomous Security Operations & Cognitive Response Platform — an AI-native SOC command center.",
  manifest: "/manifest.webmanifest",
};

export const viewport: Viewport = {
  themeColor: "#05070d",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen antialiased">
        <AppProvider>{children}</AppProvider>
      </body>
    </html>
  );
}
