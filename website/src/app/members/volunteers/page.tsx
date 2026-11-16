import type { Metadata } from "next";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { listVolunteerOpportunities } from "@/lib/events/events";
import { VolunteerRegisterForm } from "./register-form";

export const metadata: Metadata = {
  title: "Volunteer Opportunities",
  robots: { index: false, follow: false },
};

export const dynamic = "force-dynamic";

export default async function VolunteerPage() {
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
                <VolunteerRegisterForm opportunityId={opportunity.id} />
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
