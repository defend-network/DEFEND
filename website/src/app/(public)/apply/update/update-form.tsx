"use client";

import { useEffect, useRef, useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input, Textarea } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

type Application = {
  applicationNumber: string;
  legalName: string;
  preferredName: string | null;
  email: string;
  city: string | null;
  state: string | null;
  postalCode: string | null;
  status: string;
  infoRequest: string | null;
};

const interestOptions = [
  "Cultural heritage",
  "Fraternal fellowship",
  "Economic development",
  "Entrepreneurship",
  "Trades education",
  "Mentorship",
  "Fitness and boxing",
  "Community service",
  "Volunteer work",
  "Local chapter leadership",
];

const volunteerOptions = [
  "Events",
  "Community service",
  "Mentoring",
  "Trades education",
  "Administrative support",
  "Fundraising and sponsorship",
  "Property or facility search",
];

const programOptions = [
  "Trades & Entrepreneurship",
  "Mentorship",
  "Fitness & Boxing",
  "Cultural Education",
  "Community Service",
];

function CheckboxGroup({
  legend,
  name,
  options,
  selected,
}: {
  legend: string;
  name: string;
  options: string[];
  selected: string[];
}) {
  return (
    <fieldset className="grid gap-2">
      <legend className="text-sm font-semibold text-navy-800">{legend}</legend>
      <div className="grid gap-2 sm:grid-cols-2">
        {options.map((option) => (
          <label key={option} className="flex items-start gap-3 text-sm text-slate-700">
            <input
              type="checkbox"
              name={name}
              value={option}
              defaultChecked={selected.includes(option)}
              className="mt-1 size-4 rounded border-slate-300 accent-red-600"
            />
            <span>{option}</span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

export function ApplicationUpdateForm() {
  const tokenRef = useRef("");
  const [application, setApplication] = useState<Application | null>(null);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState(false);
  const [pending, setPending] = useState(false);

  useEffect(() => {
    const fragment = new URLSearchParams(window.location.hash.slice(1));
    tokenRef.current = fragment.get("token") ?? "";
    window.history.replaceState(
      window.history.state,
      "",
      `${window.location.pathname}${window.location.search}`,
    );

    if (!tokenRef.current) {
      setError("This update link is unavailable.");
      return;
    }

    fetch("/api/applications/update/status", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token: tokenRef.current }),
    })
      .then(async (response) => {
        const data = (await response.json()) as {
          application?: Application;
          error?: string;
        };
        if (!response.ok || !data.application) {
          setError(data.error || "This update link is unavailable.");
          return;
        }
        setApplication(data.application);
      })
      .catch(() => setError("This update link is unavailable."));
  }, []);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!application) return;
    const formData = new FormData(event.currentTarget);
    setError("");
    setPending(true);
    try {
      const response = await fetch("/api/applications/update", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          token: tokenRef.current,
          email: formData.get("email"),
          preferredName: formData.get("preferredName"),
          city: formData.get("city"),
          state: formData.get("state"),
          postalCode: formData.get("postalCode"),
          interests: formData.getAll("interests").map(String),
          skills: formData.get("skills"),
          volunteerInterests: formData.getAll("volunteerInterests").map(String),
          programInterests: formData.getAll("programInterests").map(String),
        }),
      });
      const data = (await response.json()) as { error?: string };
      if (!response.ok) {
        setError(data.error || "Unable to update the application.");
        return;
      }
      tokenRef.current = "";
      setSuccess(true);
    } catch {
      setError("Unable to update the application.");
    } finally {
      setPending(false);
    }
  }

  if (success) {
    return (
      <Alert tone="success" role="status">
        Your application has been updated and returned to administrative review.
      </Alert>
    );
  }

  if (error && !application) {
    return <Alert tone="error">{error}</Alert>;
  }

  if (!application) {
    return <p className="text-sm text-slate-500">Checking your update linkâ€¦</p>;
  }

  return (
    <form method="post" onSubmit={submit} className="grid gap-6">
      {error ? <Alert tone="error">{error}</Alert> : null}
      <Alert tone="info">
        <strong>Application {application.applicationNumber}</strong>
        {application.infoRequest ? (
          <span className="mt-2 block">Administrator message: {application.infoRequest}</span>
        ) : null}
      </Alert>
      <div className="grid gap-2">
        <Label htmlFor="preferredName">Preferred name</Label>
        <Input id="preferredName" name="preferredName" defaultValue={application.preferredName ?? ""} />
      </div>
      <div className="grid gap-2">
        <Label htmlFor="email">Email</Label>
        <Input id="email" name="email" type="email" defaultValue={application.email} required />
      </div>
      <div className="grid gap-2 sm:grid-cols-3">
        <div className="grid gap-2 sm:col-span-1">
          <Label htmlFor="city">City</Label>
          <Input id="city" name="city" defaultValue={application.city ?? ""} required />
        </div>
        <div className="grid gap-2">
          <Label htmlFor="state">State</Label>
          <Input id="state" name="state" maxLength={2} defaultValue={application.state ?? "FL"} required />
        </div>
        <div className="grid gap-2">
          <Label htmlFor="postalCode">ZIP</Label>
          <Input id="postalCode" name="postalCode" defaultValue={application.postalCode ?? ""} />
        </div>
      </div>
      <div className="grid gap-2">
        <Label htmlFor="skills">Skills, trade, or expertise</Label>
        <Textarea id="skills" name="skills" />
      </div>
      <CheckboxGroup legend="Interests" name="interests" options={interestOptions} selected={[]} />
      <CheckboxGroup legend="Volunteer interests" name="volunteerInterests" options={volunteerOptions} selected={[]} />
      <CheckboxGroup legend="Program interests" name="programInterests" options={programOptions} selected={[]} />
      <Button type="submit" disabled={pending}>
        {pending ? "Updatingâ€¦" : "Submit updated application"}
      </Button>
    </form>
  );
}
