"use client";

import * as Dialog from "@radix-ui/react-dialog";
import { Menu, X } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Logo } from "@/components/ui/logo";
import { publicNavigation } from "@/lib/config/site";
import { cn } from "@/lib/utils";

function NavLink({
  href,
  label,
  active,
  onClick,
}: {
  href: string;
  label: string;
  active: boolean;
  onClick?: () => void;
}) {
  return (
    <Link
      href={href}
      onClick={onClick}
      className={cn(
        "rounded-[var(--radius-control)] px-3 py-2 text-sm font-semibold transition-colors",
        active
          ? "text-red-700"
          : "text-navy-800/80 hover:bg-slate-100 hover:text-navy-900",
      )}
      aria-current={active ? "page" : undefined}
    >
      {label}
    </Link>
  );
}

export function SiteHeader() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);

  return (
    <header className="sticky top-0 z-40 border-b border-slate-200/80 bg-paper/95 backdrop-blur">
      <div className="mx-auto flex h-[76px] w-full max-w-6xl items-center justify-between px-5 sm:px-8">
        <Logo />

        <nav aria-label="Primary" className="hidden items-center gap-1 lg:flex">
          {publicNavigation.map((item) => (
            <NavLink
              key={item.href}
              href={item.href}
              label={item.label}
              active={pathname === item.href || pathname.startsWith(`${item.href}/`)}
            />
          ))}
        </nav>

        <div className="hidden items-center gap-2 lg:flex">
          <Button asChild variant="ghost" size="sm">
            <Link href="/login">Member login</Link>
          </Button>
          <Button asChild size="sm">
            <Link href="/apply">Apply for Membership</Link>
          </Button>
        </div>

        <Dialog.Root open={open} onOpenChange={setOpen}>
          <Dialog.Trigger asChild>
            <button
              type="button"
              className="inline-flex size-11 items-center justify-center rounded-[var(--radius-control)] border border-slate-300 bg-white text-navy-800 lg:hidden"
              aria-label="Open navigation menu"
            >
              <Menu size={20} aria-hidden="true" />
            </button>
          </Dialog.Trigger>
          <Dialog.Portal>
            <Dialog.Overlay className="fixed inset-0 z-50 bg-navy-950/45 backdrop-blur-sm" />
            <Dialog.Content className="fixed inset-y-0 right-0 z-50 flex w-[min(22rem,90vw)] flex-col bg-paper p-6 shadow-2xl">
              <div className="flex items-center justify-between">
                <Dialog.Title className="sr-only">Site navigation</Dialog.Title>
                <Logo size={40} />
                <Dialog.Close asChild>
                  <button
                    type="button"
                    className="inline-flex size-10 items-center justify-center rounded-[var(--radius-control)] border border-slate-300 bg-white text-navy-800"
                    aria-label="Close navigation menu"
                  >
                    <X size={18} aria-hidden="true" />
                  </button>
                </Dialog.Close>
              </div>

              <nav aria-label="Mobile" className="mt-8 grid gap-1">
                {publicNavigation.map((item) => (
                  <Link
                    key={item.href}
                    href={item.href}
                    onClick={() => setOpen(false)}
                    className="rounded-[var(--radius-control)] px-3 py-3 text-base font-semibold text-navy-800 hover:bg-white"
                  >
                    {item.label}
                  </Link>
                ))}
              </nav>

              <div className="mt-auto grid gap-2 border-t border-slate-200 pt-6">
                <Button asChild variant="secondary">
                  <Link href="/login" onClick={() => setOpen(false)}>
                    Member login
                  </Link>
                </Button>
                <Button asChild>
                  <Link href="/apply" onClick={() => setOpen(false)}>
                    Apply for Membership
                  </Link>
                </Button>
              </div>
            </Dialog.Content>
          </Dialog.Portal>
        </Dialog.Root>
      </div>
    </header>
  );
}
