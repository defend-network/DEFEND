"use client";

import { useActionState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input, Textarea } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { createEventAction, createVolunteerAction } from "./actions";
import {
  initialEventActionState,
  type EventActionState,
} from "./action-state";

function Result({ state }: { state: EventActionState }) {
  if (state.status === "idle") return null;
  return (
    <div className="mt-3">
      <Alert tone={state.status === "success" ? "success" : "error"}>
        {state.message}
      </Alert>
    </div>
  );
}

export function EventAdminForms() {
  const [eventState, eventAction, eventPending] = useActionState(
    createEventAction,
    initialEventActionState,
  );
  const [volunteerState, volunteerAction, volunteerPending] = useActionState(
    createVolunteerAction,
    initialEventActionState,
  );

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <form action={eventAction} className="grid gap-4 rounded-[var(--radius-card)] border border-slate-200 bg-white p-5">
        <h2 className="text-lg font-semibold">Create event</h2>
        <div className="grid gap-2">
          <Label htmlFor="title">Title</Label>
          <Input id="title" name="title" required />
        </div>
        <div className="grid gap-2">
          <Label htmlFor="summary">Summary</Label>
          <Input id="summary" name="summary" />
        </div>
        <div className="grid gap-2">
          <Label htmlFor="description">Description</Label>
          <Textarea id="description" name="description" />
        </div>
        <div className="grid gap-2">
          <Label htmlFor="startsAt">Starts at</Label>
          <Input id="startsAt" name="startsAt" type="datetime-local" required />
        </div>
        <div className="grid gap-2">
          <Label htmlFor="locationName">Location name</Label>
          <Input id="locationName" name="locationName" />
        </div>
        <div className="grid gap-2">
          <Label htmlFor="address">Address</Label>
          <Input id="address" name="address" />
        </div>
        <div className="grid gap-2">
          <Label htmlFor="capacity">Capacity (optional)</Label>
          <Input id="capacity" name="capacity" type="number" min={1} />
        </div>
        <div className="grid gap-2">
          <Label htmlFor="feeDollars">Program fee ($, optional)</Label>
          <Input id="feeDollars" name="feeDollars" type="number" min={0} step="0.01" />
        </div>
        <label className="flex items-center gap-2 text-sm text-slate-700">
          <input type="checkbox" name="familyFriendly" className="size-4 accent-red-600" />
          Family-friendly event
        </label>
        <div className="grid gap-2">
          <Label htmlFor="status">Publication</Label>
          <select id="status" name="status" className="h-11 rounded-[var(--radius-control)] border border-slate-300 bg-white px-3 text-sm">
            <option value="draft">Draft</option>
            <option value="published">Published</option>
          </select>
        </div>
        <Button type="submit" disabled={eventPending}>
          {eventPending ? "Creating…" : "Create event"}
        </Button>
        <Result state={eventState} />
      </form>

      <form action={volunteerAction} className="grid gap-4 rounded-[var(--radius-card)] border border-slate-200 bg-white p-5">
        <h2 className="text-lg font-semibold">Create volunteer opportunity</h2>
        <div className="grid gap-2">
          <Label htmlFor="vol-title">Title</Label>
          <Input id="vol-title" name="title" required />
        </div>
        <div className="grid gap-2">
          <Label htmlFor="vol-description">Description</Label>
          <Textarea id="vol-description" name="description" />
        </div>
        <div className="grid gap-2">
          <Label htmlFor="slots">Slots (optional)</Label>
          <Input id="slots" name="slots" type="number" min={1} />
        </div>
        <div className="grid gap-2">
          <Label htmlFor="vol-skills">Skills needed (comma separated)</Label>
          <Input id="vol-skills" name="skills" />
        </div>
        <div className="grid gap-2">
          <Label htmlFor="vol-availability">Availability</Label>
          <Input id="vol-availability" name="availability" placeholder="Weekends, evenings…" />
        </div>
        <label className="flex items-center gap-2 text-sm text-slate-700">
          <input type="checkbox" name="isInstructorRole" className="size-4 accent-red-600" />
          Instructor / program-leader role
        </label>
        <Button type="submit" variant="secondary" disabled={volunteerPending}>
          {volunteerPending ? "Creating…" : "Create opportunity"}
        </Button>
        <Result state={volunteerState} />
      </form>
    </div>
  );
}
