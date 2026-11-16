import type { Metadata } from "next";
import { Public_Sans, Source_Serif_4 } from "next/font/google";

import "./globals.css";

const publicSans = Public_Sans({
  variable: "--font-public-sans",
  subsets: ["latin"],
  display: "swap",
});

const sourceSerif = Source_Serif_4({
  variable: "--font-source-serif",
  subsets: ["latin"],
  display: "swap",
});

export const metadata: Metadata = {
  metadataBase: new URL("https://defend-network.org"),
  title: {
    default: "DEFEND — Fraternal Economic Network for Development",
    template: "%s | DEFEND",
  },
  description:
    "DEFEND is a fraternal, cultural, and economic network being organized in Pasco County, Florida.",
  applicationName: "DEFEND",
  icons: {
    icon: "/defend-logo.png",
    apple: "/defend-logo.png",
  },
  openGraph: {
    type: "website",
    siteName: "DEFEND",
    title: "DEFEND — Fraternal Economic Network for Development",
    description:
      "A fraternal, cultural, and economic network being organized in Pasco County, Florida.",
    url: "https://defend-network.org",
  },
  twitter: {
    card: "summary",
    title: "DEFEND — Fraternal Economic Network for Development",
    description:
      "A fraternal, cultural, and economic network being organized in Pasco County, Florida.",
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html
      lang="en"
      className={`${publicSans.variable} ${sourceSerif.variable} h-full`}
    >
      <body className="min-h-full bg-paper text-slate-700 antialiased">
        {children}
      </body>
    </html>
  );
}
