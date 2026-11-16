"use client";

import { useActionState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { FieldError, Label } from "@/components/ui/label";
import { Input, Textarea } from "@/components/ui/input";
import {
  initialApplicationState,
  type ApplicationFormState,
} from "./form-state";
import { submitApplication } from "./actions";

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

function errorFor(state: ApplicationFormState, name: string) {
  return state.fieldErrors?.[name];
}

function CheckboxGroup({
  legend,
  name,
  options,
}: {
  legend: string;
  name: string;
  options: string[];
}) {
  return (
    <fieldset className="grid gap-3">
      <legend className="text-sm font-semibold text-navy-800">{legend}</legend>
      <div className="grid gap-2 sm:grid-cols-2">
        {options.map((option) => (
          <label
            key={option}
            className="flex items-start gap-3 rounded-[var(--radius-control)] border border-slate-200 bg-white px-3 py-2.5 text-sm text-slate-700"
          >
            <input
              type="checkbox"
              name={name}
              value={option}
              className="mt-1 size-4 rounded border-slate-300 accent-red-600"
            />
            <span>{option}</span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

export function ApplicationForm() {
  const [state, action, pending] = useActionState(
    submitApplication,
    initialApplicationState,
  );

  if (state.status === "success") {
    return (
      <div className="space-y-5">
        <Alert tone="success" role="status">
          {state.message}
        </Alert>
        {state.applicationNumber ? (
          <div className="rounded-[var(--radius-card)] border border-slate-200 bg-paper p-6">
            <p className="text-sm font-semibold text-navy-900">
              Application number
            </p>
            <p className="mt-1 font-mono text-lg text-red-700">
              {state.applicationNumber}
            </p>
            <p className="mt-3 text-sm leading-6 text-slate-600">
              Keep this number for your records. If your application is
              approved, DEFEND will send an invitation to the email address you
              provided.
            </p>
          </div>
        ) : null}
      </div>
    );
  }

  return (
    <form action={action} className="grid gap-8">
      <input
        type="text"
        name="website"
        tabIndex={-1}
        autoComplete="off"
        className="hidden"
        aria-hidden="true"
      />

      {state.status === "error" ? (
        <Alert tone="error" role="alert">
          {state.message}
        </Alert>
      ) : null}

      <fieldset className="grid gap-5">
        <legend className="text-lg font-semibold text-navy-900">
          Your information
        </legend>

        <div className="grid gap-2">
          <Label htmlFor="legalName">Legal name</Label>
          <Input
            id="legalName"
            name="legalName"
            autoComplete="name"
            required
            aria-invalid={Boolean(errorFor(state, "legalName"))}
          />
          <FieldError>{errorFor(state, "legalName")}</FieldError>
        </div>

        <div className="grid gap-2">
          <Label htmlFor="preferredName">Preferred name (optional)</Label>
          <Input id="preferredName" name="preferredName" autoComplete="nickname" />
        </div>

        <div className="grid gap-5 sm:grid-cols-2">
          <div className="grid gap-2">
            <Label htmlFor="email">Email</Label>
            <Input
              id="email"
              name="email"
              type="email"
              autoComplete="email"
              required
              aria-invalid={Boolean(errorFor(state, "email"))}
            />
            <FieldError>{errorFor(state, "email")}</FieldError>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="phone">Phone (optional)</Label>
            <Input id="phone" name="phone" type="tel" autoComplete="tel" />
          </div>
        </div>

        <div className="grid gap-5 sm:grid-cols-[1.4fr_0.5fr_0.7fr]">
          <div className="grid gap-2">
            <Label htmlFor="city">City</Label>
            <Input
              id="city"
              name="city"
              autoComplete="address-level2"
              required
              aria-invalid={Boolean(errorFor(state, "city"))}
            />
            <FieldError>{errorFor(state, "city")}</FieldError>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="state">State</Label>
            <Input
              id="state"
              name="state"
              autoComplete="address-level1"
              maxLength={2}
              required
              defaultValue="FL"
              aria-invalid={Boolean(errorFor(state, "state"))}
            />
            <FieldError>{errorFor(state, "state")}</FieldError>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="postalCode">ZIP (optional)</Label>
            <Input
              id="postalCode"
              name="postalCode"
              autoComplete="postal-code"
            />
          </div>
        </div>

        <div className="grid gap-2">
          <Label htmlFor="desiredChapterId">Chapter</Label>
          <select
            id="desiredChapterId"
            name="desiredChapterId"
            defaultValue="chapter_pasco"
            className="h-11 rounded-[var(--radius-control)] border border-slate-300 bg-white px-3 text-[15px] text-navy-900 shadow-sm outline-none focus:border-navy-700 focus:ring-2 focus:ring-navy-800/15"
          >
            <option value="chapter_pasco">
              Pasco County — founding chapter (in development)
            </option>
          </select>
          <p className="text-xs leading-5 text-slate-500">
            Only Pasco County is accepting membership applications. Planned
            chapters are not available for assignment.
          </p>
          <FieldError>{errorFor(state, "desiredChapterId")}</FieldError>
        </div>
      </fieldset>

      <fieldset className="grid gap-5">
        <legend className="text-lg font-semibold text-navy-900">
          Interests and experience
        </legend>
        <CheckboxGroup
          legend="Areas of interest"
          name="interests"
          options={interestOptions}
        />
        <div className="grid gap-2">
          <Label htmlFor="skills">
            Skills, trade, profession, or expertise (optional)
          </Label>
          <Textarea
            id="skills"
            name="skills"
            placeholder="For example: electrical, carpentry, accounting, software, teaching, fitness..."
          />
        </div>
        <CheckboxGroup
          legend="Volunteer interests"
          name="volunteerInterests"
          options={volunteerOptions}
        />
        <CheckboxGroup
          legend="Program interests"
          name="programInterests"
          options={programOptions}
        />
      </fieldset>

      <fieldset className="grid gap-4 rounded-[var(--radius-card)] border border-slate-200 bg-paper p-5">
        <legend className="px-1 text-lg font-semibold text-navy-900">
          Acknowledgements
        </legend>
        <label className="flex items-start gap-3 text-sm leading-6 text-slate-700">
          <input
            type="checkbox"
            name="policiesAccepted"
            required
            className="mt-1 size-4 rounded border-slate-300 accent-red-600"
          />
          <span>
            I have read the membership information and agree to follow DEFEND&apos;s
            written membership policies and code of conduct.
          </span>
        </label>
        <FieldError>{errorFor(state, "policiesAccepted")}</FieldError>
        <label className="flex items-start gap-3 text-sm leading-6 text-slate-700">
          <input
            type="checkbox"
            name="privacyAcknowledged"
            required
            className="mt-1 size-4 rounded border-slate-300 accent-red-600"
          />
          <span>
            I acknowledge that DEFEND will use the information in this
            application to review my membership request and will handle it
            according to its privacy notice.
          </span>
        </label>
        <FieldError>{errorFor(state, "privacyAcknowledged")}</FieldError>
      </fieldset>

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <Button type="submit" size="lg" disabled={pending}>
          {pending ? "Submitting…" : "Submit application"}
        </Button>
        <p className="text-xs leading-5 text-slate-500">
          Applications are reviewed manually. Submitting does not create an
          account or authorize any payment.
        </p>
      </div>
    </form>
  );
}
