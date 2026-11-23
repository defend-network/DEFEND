import { eq } from "drizzle-orm";
import { betterAuth } from "better-auth";
import { drizzleAdapter } from "better-auth/adapters/drizzle";
import { nextCookies } from "better-auth/next-js";
import { emailOTP, twoFactor } from "better-auth/plugins";
import { createAuthMiddleware } from "better-auth/api";

import { getDb } from "@/lib/db/client";
import { resolveSecret, secureCookiesRequired } from "@/lib/config/env";
import { sendEmail } from "@/lib/email/send";
import {
  emailOtpEmail,
  emailVerificationEmail,
  passwordResetEmail,
} from "@/lib/email/templates";
import {
  account,
  rateLimit,
  session,
  twoFactor as twoFactorTable,
  user,
  verification,
} from "@/db/schema";

type AuthInstance = ReturnType<typeof createAuth>;

let authInstance: AuthInstance | null = null;

function authSecret(): string {
  return resolveSecret(
    "BETTER_AUTH_SECRET",
    "defend-local-development-secret-change-before-deploying",
  );
}

function createAuth(db: Awaited<ReturnType<typeof getDb>>) {
  const baseURL = process.env.APP_URL?.trim() || "http://localhost:3000";
  const mfaSessionMarker = {
    id: "mfa-session-marker",
    hooks: {
      after: [
        {
          matcher: (context: { path?: string }) =>
            Boolean(context.path?.startsWith("/two-factor/verify-")),
          handler: createAuthMiddleware(async (ctx) => {
            const context = ctx.context as {
              newSession?: { session?: { id?: string } };
              session?: { session?: { id?: string } };
            };
            const sessionId =
              context.newSession?.session?.id ?? context.session?.session?.id;
            if (!sessionId) return;
            await db
              .update(session)
              .set({ mfaVerifiedAt: new Date() })
              .where(eq(session.id, sessionId));
          }),
        },
      ],
    },
  };

  return betterAuth({
    appName: "DEFEND",
    baseURL,
    secret: authSecret(),
    database: drizzleAdapter(db, {
      provider: "sqlite",
      schema: {
        user,
        session,
        account,
        verification,
        twoFactor: twoFactorTable,
        rateLimit,
      },
    }),
    trustedOrigins: [baseURL],
    emailAndPassword: {
      enabled: true,
      disableSignUp: true,
      minPasswordLength: 12,
      maxPasswordLength: 512,
      requireEmailVerification: true,
      revokeSessionsOnPasswordReset: true,
      sendResetPassword: async ({
        user,
        url,
      }: {
        user: { email: string; name: string };
        url: string;
      }) => {
        await sendEmail(
          passwordResetEmail({
            to: user.email,
            name: user.name,
            resetUrl: url,
          }),
        );
      },
    },
    emailVerification: {
      sendOnSignUp: false,
      sendVerificationEmail: async ({
        user,
        url,
      }: {
        user: { email: string; name: string };
        url: string;
      }) => {
        await sendEmail(
          emailVerificationEmail({
            to: user.email,
            name: user.name,
            verifyUrl: url,
          }),
        );
      },
    },
    session: {
      expiresIn: 60 * 60 * 24 * 7,
      updateAge: 60 * 60 * 24,
    },
    rateLimit: {
      enabled: true,
      storage: "database",
      modelName: "rateLimit",
      window: 60,
      max: 100,
    },
    advanced: {
      cookiePrefix: "defend",
      useSecureCookies: secureCookiesRequired(),
      ipAddress: {
        ipAddressHeaders: ["cf-connecting-ip"],
      },
    },
    databaseHooks: {
      user: {
        update: {
          after: async (updatedUser) => {
            const rows = await db
              .select({
                twoFactorEnabled: user.twoFactorEnabled,
                twoFactorEnabledAt: user.twoFactorEnabledAt,
              })
              .from(user)
              .where(eq(user.id, updatedUser.id))
              .limit(1);
            const current = rows[0];
            if (!current) return;
            if (current.twoFactorEnabled && !current.twoFactorEnabledAt) {
              await db
                .update(user)
                .set({ twoFactorEnabledAt: new Date() })
                .where(eq(user.id, updatedUser.id));
            } else if (
              !current.twoFactorEnabled &&
              current.twoFactorEnabledAt
            ) {
              await db
                .update(user)
                .set({ twoFactorEnabledAt: null })
                .where(eq(user.id, updatedUser.id));
            }
          },
        },
      },
    },
    plugins: [
      emailOTP({
        otpLength: 6,
        expiresIn: 300,
        allowedAttempts: 5,
        storeOTP: "hashed",
        disableSignUp: true,
        rateLimit: {
          window: 60,
          max: 3,
        },
        sendVerificationOTP: async ({ email, otp, type }) => {
          const normalizedEmail = email.trim().toLowerCase();
          const rows = await db
            .select({ id: user.id, name: user.name })
            .from(user)
            .where(eq(user.email, normalizedEmail))
            .limit(1);
          const recipient = rows[0];
          if (!recipient) return;
          await sendEmail(
            emailOtpEmail({
              to: normalizedEmail,
              name: recipient.name,
              code: otp,
              purpose: type,
            }),
          );
        },
      }),
      twoFactor({
        issuer: "DEFEND",
      }),
      mfaSessionMarker,
      nextCookies(),
    ],
  });
}

export async function getAuth(): Promise<AuthInstance> {
  if (authInstance) return authInstance;
  const instance = createAuth(await getDb());
  authInstance = instance;
  return instance;
}
