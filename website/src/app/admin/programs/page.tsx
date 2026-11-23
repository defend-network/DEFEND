import type { Metadata } from "next";

import { AdminAccessDenied } from "@/components/admin/access-denied";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { adminPageActor } from "@/lib/auth/admin";
import { listPrograms } from "@/lib/programs/programs";
import { ProgramForm } from "./program-form";

export const metadata: Metadata = {
  title: "Programs",
  robots: { index: false, follow: false },
};

export const dynamic = "force-dynamic";

export default async function ProgramsAdminPage() {
  const { allowed } = await adminPageActor("programs.view");
  if (!allowed) return <AdminAccessDenied module="programs" />;
  const programs = await listPrograms();

  return (
    <div className="grid gap-6">
      <div>
        <p className="text-xs font-bold uppercase tracking-[0.2em] text-red-700">
          Programming
        </p>
        <h1 className="mt-3 text-3xl font-semibold">Programs</h1>
        <p className="mt-2 text-sm leading-6 text-slate-600">
          Capacity, fees, eligibility, family participation, and delivery status.
          The standard $7 membership does not automatically include free program
          or facility access.
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-[0.8fr_1.2fr]">
        <ProgramForm />
        <div className="grid gap-4">
          {programs.length === 0 ? (
            <Card><CardContent className="p-6 text-sm text-slate-500">No programs configured.</CardContent></Card>
          ) : (
            programs.map((program) => (
              <Card key={program.id}>
                <CardHeader>
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <CardTitle>{program.title}</CardTitle>
                    <Badge variant={program.status === "operating" ? "green" : program.status === "in_development" ? "amber" : "outline"}>
                      {program.status.replaceAll("_", " ")}
                    </Badge>
                  </div>
                  <p className="text-sm text-slate-500">{program.summary}</p>
                </CardHeader>
                <CardContent className="grid gap-2 text-xs text-slate-500">
                  <p>Capacity: {program.capacity ?? "not set"} · Fee: {program.feeCents ? `$${(program.feeCents / 100).toFixed(2)}` : "none"}</p>
                  <p>Eligibility: {program.eligibility || "not specified"}</p>
                  <p>Family-friendly: {program.familyFriendly ? "yes" : "no"}</p>
                </CardContent>
              </Card>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
