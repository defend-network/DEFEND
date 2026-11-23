"use client";

import { useActionState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input, Textarea } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type {
  DirectoryPreferences,
  NotificationPreferences,
} from "@/lib/membership/profile";
import { updateAccountAction } from "./actions";
import {
  initialAccountActionState,
  type AccountActionState,
} from "./action-state";

const volunteerOptions = [
  "Events",
  "Community service",
  "Mentoring",
  "Trades education",
  "Administrative support",
  "Fundraising and sponsorship",
  "Property or facility search",
];

function Checkbox({
  name,
  label,
  defaultChecked,
}: {
  name: string;
  label: string;
  defaultChecked: boolean;
}) {
  return (
    <label className="flex items-start gap-3 text-sm leading-6 text-slate-700">
      <input
        type="checkbox"
        name={name}
        defaultChecked={defaultChecked}
        className="mt-1 size-4 rounded border-slate-300 accent-red-600"
      />
      <span>{label}</span>
    </label>
  );
}

export function AccountForm({
  profile,
  phone,
  directory,
  directoryPreferences,
  notificationPreferences,
}: {
  profile: {
    preferredName: string | null;
    city: string | null;
    state: string | null;
    postalCode: string | null;
    legalFirstName: string;
    legalLastName: string;
    familyParticipation: boolean;
  };
  phone: string | null;
  directory: {
    visible: boolean;
    profession: string | null;
    businessName: string | null;
    skillsJson: string;
  } | null;
  directoryPreferences: DirectoryPreferences;
  notificationPreferences: NotificationPreferences;
}) {
  const [state, action, pending] = useActionState(
    updateAccountAction,
    initialAccountActionState,
  ) as [AccountActionState, (formData: FormData) => void, boolean];

  let skills = "";
  try {
    const parsed = JSON.parse(directory?.skillsJson ?? "[]");
    if (Array.isArray(parsed)) skills = parsed.join(", ");
  } catch {
    skills = "";
  }

  return (
    <form action={action} className="grid gap-8">
      {state.status === "success" ? <Alert tone="success">{state.message}</Alert> : null}
      {state.status === "error" ? <Alert tone="error">{state.message}</Alert> : null}

      <fieldset className="grid gap-5">
        <legend className="text-lg font-semibold text-navy-900">Profile</legend>
        <div className="grid gap-2">
          <Label htmlFor="preferredName">Preferred name</Label>
          <Input
            id="preferredName"
            name="preferredName"
            defaultValue={profile.preferredName ?? ""}
            autoComplete="nickname"
          />
        </div>
        <div className="grid gap-5 sm:grid-cols-2">
          <div className="grid gap-2">
            <Label htmlFor="phone">Phone (optional)</Label>
            <Input
              id="phone"
              name="phone"
              type="tel"
              autoComplete="tel"
              defaultValue={phone ?? ""}
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="city">City</Label>
            <Input id="city" name="city" defaultValue={profile.city ?? ""} />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="state">State</Label>
            <Input id="state" name="state" maxLength={2} defaultValue={profile.state ?? ""} />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="postalCode">ZIP</Label>
            <Input
              id="postalCode"
              name="postalCode"
              defaultValue={profile.postalCode ?? ""}
            />
          </div>
        </div>
        <div className="grid gap-2">
          <Label htmlFor="profession">Profession or trade</Label>
          <Input
            id="profession"
            name="profession"
            defaultValue={directory?.profession ?? ""}
          />
        </div>
        <div className="grid gap-2">
          <Label htmlFor="businessName">Business name (optional)</Label>
          <Input
            id="businessName"
            name="businessName"
            defaultValue={directory?.businessName ?? ""}
          />
        </div>
        <div className="grid gap-2">
          <Label htmlFor="skills">Skills (comma separated)</Label>
          <Textarea id="skills" name="skills" defaultValue={skills} />
        </div>
        <fieldset className="grid gap-2">
          <legend className="text-sm font-semibold text-navy-800">
            Volunteer interests
          </legend>
          <div className="grid gap-2 sm:grid-cols-2">
            {volunteerOptions.map((option) => (
              <label key={option} className="flex items-start gap-3 text-sm text-slate-700">
                <input
                  type="checkbox"
                  name="volunteerInterests"
                  value={option}
                  className="mt-1 size-4 rounded border-slate-300 accent-red-600"
                />
                <span>{option}</span>
              </label>
            ))}
          </div>
        </fieldset>
        <Checkbox
          name="familyParticipation"
          label="My household is interested in family participation and family-friendly community events."
          defaultChecked={profile.familyParticipation}
        />
        <p className="text-xs leading-5 text-slate-500">
          Family participation does not change your membership tier.
          Program fees, capacity, and eligibility are configured separately for
          each program or event.
        </p>
      </fieldset>

      <fieldset className="grid gap-4 rounded-[var(--radius-card)] border border-slate-200 bg-paper p-5">
        <legend className="px-1 text-lg font-semibold text-navy-900">Directory</legend>
        <Checkbox
          name="directoryVisible"
          label="Include me in the opt-in member directory."
          defaultChecked={directory?.visible ?? false}
        />
        <p className="text-xs leading-5 text-slate-500">
          If visible, only the fields you select below are shown to other signed-in members.
        </p>
        <div className="grid gap-2 sm:grid-cols-2">
          <Checkbox name="showChapter" label="Show chapter" defaultChecked={directoryPreferences.showChapter} />
          <Checkbox name="showProfession" label="Show profession" defaultChecked={directoryPreferences.showProfession} />
          <Checkbox name="showBusiness" label="Show business name" defaultChecked={directoryPreferences.showBusiness} />
          <Checkbox name="showSkills" label="Show skills" defaultChecked={directoryPreferences.showSkills} />
          <Checkbox name="showVolunteerInterests" label="Show volunteer interests" defaultChecked={directoryPreferences.showVolunteerInterests} />
          <Checkbox name="showEmail" label="Show email address" defaultChecked={directoryPreferences.showEmail} />
          <Checkbox name="showPhone" label="Show phone number" defaultChecked={directoryPreferences.showPhone} />
        </div>
      </fieldset>

      <fieldset className="grid gap-3 rounded-[var(--radius-card)] border border-slate-200 bg-white p-5">
        <legend className="px-1 text-lg font-semibold text-navy-900">Notifications</legend>
        <Checkbox name="notifyMembership" label="Membership and account notices" defaultChecked={notificationPreferences.membership} />
        <Checkbox name="notifyEvents" label="Event and volunteer notices" defaultChecked={notificationPreferences.events} />
        <Checkbox name="notifyNewsletter" label="Organizational newsletter (optional)" defaultChecked={notificationPreferences.newsletter} />
      </fieldset>

      <div>
        <Button type="submit" disabled={pending}>
          {pending ? "Saving…" : "Save profile and preferences"}
        </Button>
      </div>
    </form>
  );
}
