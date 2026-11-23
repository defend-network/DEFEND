import { afterEach, describe, expect, it } from "vitest";

import {
  isDeployedEnvironment,
  isLocalEnvironment,
  requireSecret,
  resolveSecret,
  runtimeEnvironment,
  secureCookiesRequired,
} from "./env";

const originalEnv = process.env.APP_ENV;

afterEach(() => {
  if (originalEnv === undefined) delete process.env.APP_ENV;
  else process.env.APP_ENV = originalEnv;
  delete process.env.DEFEND_TEST_SECRET;
});

describe("runtime environment configuration", () => {
  it("treats test and development as local environments", () => {
    process.env.APP_ENV = "test";
    expect(runtimeEnvironment()).toBe("test");
    expect(isLocalEnvironment()).toBe(true);
    expect(isDeployedEnvironment()).toBe(false);
    expect(secureCookiesRequired()).toBe(false);
  });

  it("treats staging and production as deployed environments", () => {
    process.env.APP_ENV = "staging";
    expect(isDeployedEnvironment()).toBe(true);
    expect(secureCookiesRequired()).toBe(true);

    process.env.APP_ENV = "production";
    expect(isDeployedEnvironment()).toBe(true);
    expect(secureCookiesRequired()).toBe(true);
  });

  it("rejects unknown environments", () => {
    process.env.APP_ENV = "preview";
    expect(() => runtimeEnvironment()).toThrow("Unsupported APP_ENV");
  });

  it("allows the local fallback only in local environments", () => {
    process.env.APP_ENV = "test";
    expect(resolveSecret("DEFEND_TEST_SECRET", "local-fallback")).toBe(
      "local-fallback",
    );

    process.env.APP_ENV = "staging";
    expect(() => resolveSecret("DEFEND_TEST_SECRET", "local-fallback")).toThrow(
      "DEFEND_TEST_SECRET is required in staging",
    );

    process.env.DEFEND_TEST_SECRET = "configured-value";
    expect(resolveSecret("DEFEND_TEST_SECRET", "local-fallback")).toBe(
      "configured-value",
    );
  });

  it("requires explicit secrets in deployed environments", () => {
    process.env.APP_ENV = "production";
    expect(() => requireSecret("DEFEND_MISSING_SECRET")).toThrow(
      "DEFEND_MISSING_SECRET is required in production",
    );
  });
});
