import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "DEFEND AI",
  description: "Intelligence for European-heritage Americans",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
