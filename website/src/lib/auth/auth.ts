import { betterAuth } from "better-auth";
import { drizzleAdapter } from "better-auth/adapters/drizzle";
import { nextCookies } from "better-auth/next-js";
import { twoFactor } from "better-auth/plugins";

import { getDb } from "@/lib/db/client";
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
  const secret = process.env.BETTER_AUTH_SECRET?.trim();
  if (secret) return secret;
  if (process.env.APP_ENV === "production") {
    throw new Error("BETTER_AUTH_SECRET is required in production.");
  }
  return "defend-local-development-secret-change-before-deploying";
}

function createAuth(db: Awaited<ReturnType<typeof getDb>>) {
  const baseURL = process.env.APP_URL?.trim() || "http://localhost:3000";

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
    },
    emailVerification: {
      sendOnSignUp: false,
      sendVerificationEmail: async () => {
        throw new Error("Email transport is not configured.");
      },
    },
    sendResetPassword: async () => {
      throw new Error("Email transport is not configured.");
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
      useSecureCookies: process.env.APP_ENV === "production",
      ipAddress: {
        ipAddressHeaders: ["cf-connecting-ip"],
      },
    },
    plugins: [
      twoFactor({
        issuer: "DEFEND",
      }),
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
