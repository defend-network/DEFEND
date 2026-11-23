import Link from "next/link";

import { Logo } from "@/components/ui/logo";

export default function AuthLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="flex min-h-screen flex-col bg-paper">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex h-20 w-full max-w-6xl items-center justify-between px-5 sm:px-8">
          <Logo />
          <Link
            href="/"
            className="text-sm font-semibold text-slate-600 underline-offset-4 hover:text-navy-900 hover:underline"
          >
            Return home
          </Link>
        </div>
      </header>
      <main className="flex flex-1 items-center justify-center px-5 py-12">
        {children}
      </main>
    </div>
  );
}
