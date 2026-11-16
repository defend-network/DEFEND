"use client";

import { useActionState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { FieldError, Label } from "@/components/ui/label";
import { Input, Textarea } from "@/components/ui/input";
import { initialContactState, type ContactFormState } from "./form-state";
import { submitContact } from "./actions";

function fieldError(state: ContactFormState, name: string) {
  return state.fieldErrors?.[name];
}

export function ContactForm() {
  const [state, action, pending] = useActionState(
    submitContact,
    initialContactState,
  );

  return (
    <form action={action} className="grid gap-5">
      <input
        type="text"
        name="website"
        tabIndex={-1}
        autoComplete="off"
        className="hidden"
        aria-hidden="true"
      />

      {state.status === "success" ? (
        <Alert tone="success" role="status">
          {state.message}
        </Alert>
      ) : null}
      {state.status === "error" ? (
        <Alert tone="error" role="alert">
          {state.message}
        </Alert>
      ) : null}

      <div className="grid gap-2">
        <Label htmlFor="name">Name</Label>
        <Input
          id="name"
          name="name"
          autoComplete="name"
          required
          aria-invalid={Boolean(fieldError(state, "name"))}
        />
        <FieldError>{fieldError(state, "name")}</FieldError>
      </div>

      <div className="grid gap-2">
        <Label htmlFor="email">Email</Label>
        <Input
          id="email"
          name="email"
          type="email"
          autoComplete="email"
          required
          aria-invalid={Boolean(fieldError(state, "email"))}
        />
        <FieldError>{fieldError(state, "email")}</FieldError>
      </div>

      <div className="grid gap-2">
        <Label htmlFor="subject">Subject</Label>
        <Input
          id="subject"
          name="subject"
          required
          aria-invalid={Boolean(fieldError(state, "subject"))}
        />
        <FieldError>{fieldError(state, "subject")}</FieldError>
      </div>

      <div className="grid gap-2">
        <Label htmlFor="message">Message</Label>
        <Textarea
          id="message"
          name="message"
          required
          aria-invalid={Boolean(fieldError(state, "message"))}
        />
        <FieldError>{fieldError(state, "message")}</FieldError>
      </div>

      <div>
        <Button type="submit" disabled={pending}>
          {pending ? "Sending…" : "Send message"}
        </Button>
      </div>
    </form>
  );
}
