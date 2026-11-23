import type { Metadata } from "next";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { getActor } from "@/lib/auth/session";
import { listVolunteerOpportunities } from "@/lib/events/events";
import {
  getMemberStanding,
  isPaidMembershipStatus,
} from "@/lib/membership/access";
import { VolunteerRegisterForm } from "./register-form";

export const metadata: Metadata = {
  title: "Volunteer Opportunities",
  robots: { index: false, follow: false },
};

export const dynamic = "force-dynamic";

export default async function VolunteerPage() {
  const actor = await getActor();
  const standing = actor ? await getMemberStanding(actor.userId) : null;
  if (!standing || !isPaidMembershipStatus(standing.status)) {
    return (
      <div className="grid gap-6">
        <div>
          <p className="text-xs font-bold uppercase tracking-[0.2em] text-red-700">
            Volunteer
          </p>
          <h1 className="mt-3 text-3xl font-semibold">Standard membership required</h1>
        </div>
        <Card>
          <CardContent className="grid gap-4 p-6">
            <p className="text-sm leading-6 text-slate-600">
              Volunteer roles require Standard membership or higher. Free
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

  const opportunities = await listVolunteerOpportunities();

  return (
    <div className="grid gap-6">
      <div>
        <p className="text-xs font-bold uppercase tracking-[0.2em] text-red-700">
          Volunteer
        </p>
        <h1 className="mt-3 text-3xl font-semibold">Volunteer opportunities</h1>
        <p className="mt-2 text-sm leading-6 text-slate-600">
          Published opportunities from the founding chapter.
        </p>
      </div>

      {opportunities.length === 0 ? (
        <Card>
          <CardContent className="p-8 text-center">
            <h2 className="text-lg font-semibold">No published opportunities</h2>
            <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-slate-500">
              Volunteer opportunities will appear here when they are confirmed.
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {opportunities.map((opportunity) => (
            <Card key={opportunity.id}>
              <CardHeader>
                <CardTitle>{opportunity.title}</CardTitle>
                {opportunity.slots ? (
                  <p className="text-sm text-slate-500">{opportunity.slots} slots</p>
                ) : null}
              </CardHeader>
              <CardContent className="grid gap-4">
                <p className="text-sm leading-6 text-slate-600">
                  {opportunity.description}
                </p>
                {opportunity.skillsJson && opportunity.skillsJson !== "[]" ? (
                  <p className="text-xs text-slate-500">
                    Skills: {JSON.parse(opportunity.skillsJson).join(", ")}
                  </p>
                ) : null}
                {opportunity.availability ? (
                  <p className="text-xs text-slate-500">Availability: {opportunity.availability}</p>
                ) : null}
                {opportunity.isInstructorRole ? (
                  <p className="text-xs font-semibold text-red-700">Instructor / program-leader role</p>
                ) : null}
                <VolunteerRegisterForm opportunityId={opportunity.id} />
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
