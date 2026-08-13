import type { Metadata } from "next";
import "./globals.css";
export const metadata:Metadata={title:"SCS Operations",description:"Sunshine Climate Solutions employee operations"};
export default function RootLayout({children}:{children:React.ReactNode}){return <html lang="en"><body>{children}</body></html>}
