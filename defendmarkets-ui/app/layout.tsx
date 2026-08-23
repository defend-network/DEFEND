import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "DEFENDmarkets",
  description: "Cross-market research, ranking, and decision engine. Real data only.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
