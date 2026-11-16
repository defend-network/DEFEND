import type { EmailMessage } from "./send";

function appUrl(path = ""): string {
  const base = (process.env.APP_URL ?? "http://localhost:3000").replace(/\/$/, "");
  return `${base}${path}`;
}

function escapeHtml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function wrap(title: string, body: string, action?: { label: string; url: string }) {
  return `<!doctype html><html><body style="font-family:Segoe UI,Arial,sans-serif;color:#3f4f66;background:#f7f8fa;padding:24px">
  <div style="max-width:560px;margin:0 auto;background:#fff;border:1px solid #d8dee7;border-radius:8px;padding:28px">
    <p style="margin:0 0 8px;font-size:11px;letter-spacing:.16em;text-transform:uppercase;color:#b62639;font-weight:700">DEFEND</p>
    <h1 style="margin:0 0 16px;font-family:Georgia,serif;color:#101f38;font-size:24px">${escapeHtml(title)}</h1>
    ${body}
    ${
      action
        ? `<p style="margin:24px 0 0"><a href="${escapeHtml(action.url)}" style="display:inline-block;background:#b62639;color:#fff;text-decoration:none;padding:12px 18px;border-radius:4px;font-weight:700">${escapeHtml(action.label)}</a></p>`
        : ""
    }
    <p style="margin:24px 0 0;font-size:12px;color:#718198">DEFEND is not yet incorporated and has not received IRS recognition of tax-exempt status. Online dues and donations are not active.</p>
  </div>
</body></html>`;
}

function paragraph(value: string): string {
  return `<p style="margin:0 0 14px;line-height:1.6">${escapeHtml(value)}</p>`;
}

export function applicationReceivedEmail(input: {
  to: string;
  name: string;
  applicationNumber: string;
}): EmailMessage {
  const text = `Hello ${input.name},

Your DEFEND membership application has been received.

Application number: ${input.applicationNumber}

An administrator will review it manually. If DEFEND needs more information, you will receive a secure update link. Submitting an application does not create an account or authorize a payment.

DEFEND is not yet incorporated and has not received IRS recognition of tax-exempt status. Online dues and donations are not active.`;

  return {
    to: input.to,
    subject: "DEFEND application received",
    text,
    html: wrap(
      "Application received",
      paragraph(`Hello ${input.name},`) +
        paragraph("Your DEFEND membership application has been received.") +
        paragraph(`Application number: ${input.applicationNumber}`) +
        paragraph(
          "An administrator will review it manually. If DEFEND needs more information, you will receive a secure update link. Submitting an application does not create an account or authorize a payment.",
        ),
    ),
    templateKey: "application_received",
  };
}

export function applicationNeedsInfoEmail(input: {
  to: string;
  name: string;
  message: string;
  updateUrl: string;
}): EmailMessage {
  const text = `Hello ${input.name},

DEFEND needs more information about your membership application.

Administrator message: ${input.message}

Update your application: ${input.updateUrl}

This link expires in 72 hours and can be used once.`;

  return {
    to: input.to,
    subject: "DEFEND application: more information requested",
    text,
    html: wrap(
      "More information requested",
      paragraph(`Hello ${input.name},`) +
        paragraph("DEFEND needs more information about your membership application.") +
        paragraph(`Administrator message: ${input.message}`) +
        paragraph("This secure link expires in 72 hours and can be used once."),
      { label: "Update application", url: input.updateUrl },
    ),
    templateKey: "application_needs_info",
  };
}

export function applicationApprovedEmail(input: {
  to: string;
  name: string;
  activationUrl: string;
  expiresAt: Date;
}): EmailMessage {
  const text = `Hello ${input.name},

Your DEFEND membership application has been approved.

Activate your account: ${input.activationUrl}

This invitation expires at ${input.expiresAt.toISOString()}.

Approved founding members may access the member portal before live billing is enabled. Membership standing and payment status are separate. No payment is authorized by this email.`;

  return {
    to: input.to,
    subject: "DEFEND application approved",
    text,
    html: wrap(
      "Application approved",
      paragraph(`Hello ${input.name},`) +
        paragraph("Your DEFEND membership application has been approved.") +
        paragraph(
          `This invitation expires at ${input.expiresAt.toISOString()}. Approved founding members may access the member portal before live billing is enabled. No payment is authorized by this email.`,
        ),
      { label: "Activate account", url: input.activationUrl },
    ),
    templateKey: "application_approved",
  };
}

export function applicationDeniedEmail(input: {
  to: string;
  name: string;
}): EmailMessage {
  const text = `Hello ${input.name},

DEFEND has completed its review of your membership application. The application was not approved at this time.

You may contact DEFEND if you have questions about the decision.

No payment has been requested or collected.`;

  return {
    to: input.to,
    subject: "DEFEND application decision",
    text,
    html: wrap(
      "Application decision",
      paragraph(`Hello ${input.name},`) +
        paragraph(
          "DEFEND has completed its review of your membership application. The application was not approved at this time.",
        ) +
        paragraph(
          "You may contact DEFEND if you have questions about the decision. No payment has been requested or collected.",
        ),
    ),
    templateKey: "application_denied",
  };
}

export function membershipActivatedEmail(input: {
  to: string;
  name: string;
  memberNumber: string;
  chapterName: string;
}): EmailMessage {
  const text = `Hello ${input.name},

Your DEFEND member portal account is active.

Member number: ${input.memberNumber}
Chapter: ${input.chapterName}

You can sign in at ${appUrl("/login")}.

Online dues are not active. Approved founding members may use the portal before live billing is enabled.`;

  return {
    to: input.to,
    subject: "Your DEFEND account is active",
    text,
    html: wrap(
      "Account active",
      paragraph(`Hello ${input.name},`) +
        paragraph("Your DEFEND member portal account is active.") +
        paragraph(`Member number: ${input.memberNumber}`) +
        paragraph(`Chapter: ${input.chapterName}`) +
        paragraph(
          "Online dues are not active. Approved founding members may use the portal before live billing is enabled.",
        ),
      { label: "Sign in", url: appUrl("/login") },
    ),
    templateKey: "membership_activated",
  };
}

export function passwordResetEmail(input: {
  to: string;
  name: string;
  resetUrl: string;
}): EmailMessage {
  const text = `Hello ${input.name},

A password reset was requested for your DEFEND account.

Reset your password: ${input.resetUrl}

If you did not request this, you can ignore this message. The link expires according to the authentication system's policy and can be used once.`;

  return {
    to: input.to,
    subject: "Reset your DEFEND password",
    text,
    html: wrap(
      "Reset your password",
      paragraph(`Hello ${input.name},`) +
        paragraph("A password reset was requested for your DEFEND account.") +
        paragraph("If you did not request this, you can ignore this message."),
      { label: "Reset password", url: input.resetUrl },
    ),
    templateKey: "password_reset",
  };
}

export function emailVerificationEmail(input: {
  to: string;
  name: string;
  verifyUrl: string;
}): EmailMessage {
  const text = `Hello ${input.name},

Verify your DEFEND email address: ${input.verifyUrl}

If you did not request this, you can ignore this message.`;

  return {
    to: input.to,
    subject: "Verify your DEFEND email",
    text,
    html: wrap(
      "Verify your email",
      paragraph(`Hello ${input.name},`) +
        paragraph("Verify the email address associated with your DEFEND account."),
      { label: "Verify email", url: input.verifyUrl },
    ),
    templateKey: "email_verification",
  };
}

export function eventRegistrationEmail(input: {
  to: string;
  name: string;
  eventTitle: string;
  startsAt: Date;
  status: string;
}): EmailMessage {
  const text = `Hello ${input.name},

Your registration for ${input.eventTitle} is recorded as: ${input.status}.

Event time: ${input.startsAt.toISOString()}

You can view your member dashboard at ${appUrl("/members")}.`;

  return {
    to: input.to,
    subject: `DEFEND event registration: ${input.eventTitle}`,
    text,
    html: wrap(
      "Event registration",
      paragraph(`Hello ${input.name},`) +
        paragraph(`Your registration for ${input.eventTitle} is recorded as: ${input.status}.`) +
        paragraph(`Event time: ${input.startsAt.toISOString()}`),
      { label: "Member dashboard", url: appUrl("/members") },
    ),
    templateKey: "event_registration",
  };
}

export function volunteerRegistrationEmail(input: {
  to: string;
  name: string;
  opportunityTitle: string;
}): EmailMessage {
  const text = `Hello ${input.name},

Your volunteer registration for ${input.opportunityTitle} has been recorded.

You can view your member dashboard at ${appUrl("/members")}.`;

  return {
    to: input.to,
    subject: `DEFEND volunteer registration: ${input.opportunityTitle}`,
    text,
    html: wrap(
      "Volunteer registration",
      paragraph(`Hello ${input.name},`) +
        paragraph(`Your volunteer registration for ${input.opportunityTitle} has been recorded.`),
      { label: "Member dashboard", url: appUrl("/members") },
    ),
    templateKey: "volunteer_registration",
  };
}
