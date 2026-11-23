import { betterAuth } from "better-auth";
import { drizzleAdapter } from "better-auth/adapters/drizzle";

import { resolveSecret, secureCookiesRequired } from "@/lib/config/env";
import { getDb } from "@/lib/db/client";
import { sendEmail } from "@/lib/email/send";
import { emailVerificationEmail } from "@/lib/email/templates";
import { account, rateLimit, session, user, verification } from "@/db/schema";

type SignupAuth = ReturnType<typeof createSignupAuth>;

let signupAuthInstance: SignupAuth | null = null;

function createSignupAuth(db: Awaited<ReturnType<typeof getDb>>) {
  const baseURL = process.env.APP_URL?.trim() || "http://localhost:3000";

  return betterAuth({
    appName: "DEFEND Free Registration",
    baseURL,
    secret: resolveSecret(
      "BETTER_AUTH_SECRET",
      "defend-local-development-secret-change-before-deploying",
    ),
    database: drizzleAdapter(db, {
      provider: "sqlite",
      schema: {
        user,
        session,
        account,
        verification,
        rateLimit,
      },
    }),
    trustedOrigins: [baseURL],
    emailAndPassword: {
      enabled: true,
      disableSignUp: false,
      minPasswordLength: 12,
      maxPasswordLength: 512,
      requireEmailVerification: true,
    },
    emailVerification: {
      sendOnSignUp: true,
      sendVerificationEmail: async ({
        user: createdUser,
        url,
      }: {
        user: { email: string; name: string };
        url: string;
      }) => {
        await sendEmail(
          emailVerificationEmail({
            to: createdUser.email,
            name: createdUser.name,
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
      max: 20,
    },
    advanced: {
      cookiePrefix: "defend-signup",
      useSecureCookies: secureCookiesRequired(),
      ipAddress: {
        ipAddressHeaders: ["cf-connecting-ip"],
      },
    },
  });
}

export async function getSignupAuth(): Promise<SignupAuth> {
  if (signupAuthInstance) return signupAuthInstance;
  const instance = createSignupAuth(await getDb());
  signupAuthInstance = instance;
  return instance;
}
