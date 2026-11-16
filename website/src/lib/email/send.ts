import { getDb } from "@/lib/db/client";
import { emailDeliveryEvents, emailOutbox } from "@/db/schema";

export type EmailMessage = {
  to: string;
  subject: string;
  text: string;
  html?: string;
  templateKey: string;
};

export type EmailResult = {
  status: "sent" | "outbox" | "not_configured" | "failed";
  providerMessageId?: string | null;
  error?: string | null;
};

function transport(): "resend" | "outbox" | "not_configured" {
  const configured = process.env.EMAIL_TRANSPORT?.trim().toLowerCase();
  if (configured === "resend") return "resend";
  if (configured === "outbox") return "outbox";
  if (!configured && process.env.APP_ENV !== "production") return "outbox";
  return "not_configured";
}

async function recordDelivery(
  message: EmailMessage,
  provider: string,
  status: string,
  providerMessageId?: string | null,
  errorCode?: string | null,
) {
  const db = await getDb();
  await db.insert(emailDeliveryEvents).values({
    id: `email_${crypto.randomUUID()}`,
    recipient: message.to.toLowerCase(),
    templateKey: message.templateKey,
    provider,
    providerMessageId: providerMessageId ?? null,
    status,
    errorCode: errorCode ?? null,
    createdAt: new Date(),
  });
}

export async function sendEmail(message: EmailMessage): Promise<EmailResult> {
  const mode = transport();

  if (mode === "not_configured") {
    await recordDelivery(
      message,
      "none",
      "not_configured",
      null,
      "EMAIL_TRANSPORT_NOT_CONFIGURED",
    );
    return { status: "not_configured", error: "Email transport is not configured." };
  }

  if (mode === "outbox") {
    if (process.env.APP_ENV === "production") {
      return {
        status: "not_configured",
        error: "Development outbox is disabled in production.",
      };
    }
    const db = await getDb();
    await db.insert(emailOutbox).values({
      id: `outbox_${crypto.randomUUID()}`,
      recipient: message.to.toLowerCase(),
      subject: message.subject,
      textBody: message.text,
      htmlBody: message.html ?? null,
      templateKey: message.templateKey,
      createdAt: new Date(),
    });
    await recordDelivery(message, "outbox", "outbox");
    return { status: "outbox" };
  }

  const apiKey = process.env.RESEND_API_KEY?.trim();
  const from = process.env.EMAIL_FROM?.trim();
  if (!apiKey || !from) {
    await recordDelivery(
      message,
      "resend",
      "not_configured",
      null,
      "RESEND_NOT_CONFIGURED",
    );
    return {
      status: "not_configured",
      error: "Resend is not configured.",
    };
  }

  try {
    const response = await fetch("https://api.resend.com/emails", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${apiKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        from,
        to: [message.to],
        subject: message.subject,
        text: message.text,
        html: message.html,
      }),
    });

    const data = (await response.json().catch(() => ({}))) as {
      id?: string;
      message?: string;
    };

    if (!response.ok) {
      await recordDelivery(
        message,
        "resend",
        "failed",
        null,
        `RESEND_${response.status}`,
      );
      return {
        status: "failed",
        error: "Email provider rejected the message.",
      };
    }

    await recordDelivery(message, "resend", "sent", data.id ?? null);
    return { status: "sent", providerMessageId: data.id ?? null };
  } catch {
    await recordDelivery(message, "resend", "failed", null, "RESEND_NETWORK_ERROR");
    return { status: "failed", error: "Email provider is unreachable." };
  }
}
