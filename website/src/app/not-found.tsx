import Link from "next/link";

import { Button } from "@/components/ui/button";
import { Container } from "@/components/ui/section";

export default function NotFound() {
  return (
    <Container className="flex min-h-[60vh] flex-col items-center justify-center py-20 text-center">
      <p className="text-xs font-bold uppercase tracking-[0.2em] text-red-700">
        404
      </p>
      <h1 className="mt-4 text-3xl font-semibold">Page not found</h1>
      <p className="mt-3 max-w-md text-sm leading-6 text-slate-600">
        The page you requested does not exist or has moved.
      </p>
      <div className="mt-7 flex flex-wrap justify-center gap-3">
        <Button asChild>
          <Link href="/">Return home</Link>
        </Button>
        <Button asChild variant="secondary">
          <Link href="/contact">Contact DEFEND</Link>
        </Button>
      </div>
    </Container>
  );
}
