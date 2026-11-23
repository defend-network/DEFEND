import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { getActor } from "@/lib/auth/session";
import { getMemberAccount } from "@/lib/membership/profile";
import { CardQr } from "./card-qr";

export const metadata: Metadata = {
  title: "Membership Card",
  robots: { index: false, follow: false },
};

export const dynamic = "force-dynamic";

export default async function CardPage() {
  const actor = await getActor();
  if (!actor) redirect("/login?next=/members/card");
  const account = await getMemberAccount(actor.userId);

  if (!account.membership) {
    return (
      <div className="grid gap-6">
        <div>
          <p className="text-xs font-bold uppercase tracking-[0.2em] text-red-700">
            Member card
          </p>
          <h1 className="mt-3 text-3xl font-semibold">Membership card</h1>
        </div>
        <Alert tone="warning">
          A membership card is available after your membership record is
          activated. Contact DEFEND if you believe this is an error.
        </Alert>
      </div>
    );
  }

  if (account.membership.status === "free_access") {
    return (
      <div className="grid gap-6">
        <div>
          <p className="text-xs font-bold uppercase tracking-[0.2em] text-red-700">
            Member card
          </p>
          <h1 className="mt-3 text-3xl font-semibold">Paid membership required</h1>
        </div>
        <Card>
          <CardContent className="grid gap-4 p-6">
            <p className="text-sm leading-6 text-slate-600">
              Digital check-in cards are available to paid members. Free
              accounts can view announcements and eligible public events.
            </p>
            <Button asChild>
              <Link href="/membership">Compare membership tiers</Link>
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="grid gap-6">
      <div>
        <p className="text-xs font-bold uppercase tracking-[0.2em] text-red-700">
          Member card
        </p>
        <h1 className="mt-3 text-3xl font-semibold">Digital membership card</h1>
        <p className="mt-2 text-sm leading-6 text-slate-600">
          Present this card for authorized event check-in. The QR code is
          short-lived and refreshes automatically.
        </p>
      </div>
      <Card>
        <CardHeader>
          <CardTitle>Secure check-in code</CardTitle>
        </CardHeader>
        <CardContent>
          <CardQr initialName={actor.displayName} />
        </CardContent>
      </Card>
    </div>
  );
}
