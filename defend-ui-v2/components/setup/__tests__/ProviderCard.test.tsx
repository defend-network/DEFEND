import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";

import ProviderCard from "../ProviderCard";
import type { ProviderView } from "@/lib/setupApi";
import * as setupApi from "@/lib/setupApi";

vi.mock("@/lib/setupApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/setupApi")>(
    "@/lib/setupApi",
  );
  return {
    ...actual,
    saveSetupSecret: vi.fn(),
    removeSetupSecret: vi.fn(),
    saveSetupConfig: vi.fn(),
    testSetupProvider: vi.fn(),
  };
});

function makeProvider(overrides: Partial<ProviderView> = {}): ProviderView {
  return {
    provider_id: "fred",
    display_name: "FRED",
    purpose: "Macro series",
    category: "macro",
    auth_type: "api_key",
    adapter_kind: "real",
    state: "READY_TO_TEST",
    health_badge: "NOT_TESTED",
    enabled: true,
    requires_credentials: true,
    credentials_configured: true,
    credentials: [
      { name: "FRED_API_KEY", configured: true, masked: "****-key" },
    ],
    config: {},
    detected: {},
    optional_config: ["host"],
    products: ["defend_ai"],
    docs_url: null,
    rate_limits: { requests_per_day: 1000 },
    license: {},
    tested_at: null,
    last_success_at: null,
    last_test_detail: null,
    last_status_code: null,
    last_latency_ms: null,
    remaining_quota: null,
    quota_reset_at: null,
    notes: null,
    ...overrides,
  };
}

beforeEach(() => {
  vi.mocked(setupApi.saveSetupSecret).mockReset();
  vi.mocked(setupApi.removeSetupSecret).mockReset();
  vi.mocked(setupApi.saveSetupConfig).mockReset();
  vi.mocked(setupApi.testSetupProvider).mockReset();
});

it("shows the masked credential and updates it without echoing the value", async () => {
  vi.mocked(setupApi.saveSetupSecret).mockResolvedValue({
    ok: true,
    provider_id: "fred",
    secret_name: "FRED_API_KEY",
    configured: true,
    masked: "****new",
  });
  const onChanged = vi.fn();
  const user = userEvent.setup();
  render(<ProviderCard provider={makeProvider()} token="t" onChanged={onChanged} />);

  expect(screen.getByText("****-key")).toBeVisible();
  await user.type(screen.getByLabelText("FRED_API_KEY value"), "brand-new-key-99");
  await user.click(screen.getByRole("button", { name: "Update" }));

  await waitFor(() =>
    expect(setupApi.saveSetupSecret).toHaveBeenCalledWith(
      "t",
      "fred",
      "FRED_API_KEY",
      "brand-new-key-99",
    ),
  );
  expect(await screen.findByRole("status")).toHaveTextContent("Saved.");
  expect(screen.getByLabelText("FRED_API_KEY value")).toHaveValue("");
  expect(screen.queryByText("brand-new-key-99")).not.toBeInTheDocument();
  expect(onChanged).toHaveBeenCalled();
});

it("removes a configured credential", async () => {
  vi.mocked(setupApi.removeSetupSecret).mockResolvedValue({
    ok: true,
    provider_id: "fred",
    secret_name: "FRED_API_KEY",
    configured: false,
    masked: null,
  });
  const user = userEvent.setup();
  render(<ProviderCard provider={makeProvider()} token="t" onChanged={vi.fn()} />);
  await user.click(screen.getByRole("button", { name: "Remove" }));
  await waitFor(() =>
    expect(setupApi.removeSetupSecret).toHaveBeenCalledWith(
      "t",
      "fred",
      "FRED_API_KEY",
    ),
  );
});

it("runs a health test and surfaces the backend detail", async () => {
  vi.mocked(setupApi.testSetupProvider).mockResolvedValue({
    provider_id: "fred",
    ok: true,
    badge: "HEALTHY",
    detail: "200 in 41ms",
    status_code: 200,
    latency_ms: 41,
    tested_at: "2026-08-17T10:00:00Z",
  });
  const user = userEvent.setup();
  render(<ProviderCard provider={makeProvider()} token="t" onChanged={vi.fn()} />);
  await user.click(screen.getByRole("button", { name: "Test" }));
  expect(await screen.findByRole("status")).toHaveTextContent("200 in 41ms");
});

it("surfaces a failing test as an error message", async () => {
  vi.mocked(setupApi.testSetupProvider).mockResolvedValue({
    provider_id: "fred",
    ok: false,
    badge: "AUTH_FAILED",
    detail: "HTTP 401 — invalid key",
    status_code: 401,
    tested_at: "2026-08-17T10:00:00Z",
  });
  const user = userEvent.setup();
  render(<ProviderCard provider={makeProvider()} token="t" onChanged={vi.fn()} />);
  await user.click(screen.getByRole("button", { name: "Test" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "HTTP 401 — invalid key",
  );
});

it("labels placeholders as planned and disables their test button", () => {
  render(
    <ProviderCard
      provider={makeProvider({
        adapter_kind: "placeholder",
        state: "PLANNED",
        health_badge: "NOT_TESTED",
      })}
      token="t"
      onChanged={vi.fn()}
    />,
  );
  expect(screen.getByText("Planned")).toBeVisible();
  expect(screen.getByText("ADAPTER NOT IMPLEMENTED")).toBeVisible();
  expect(screen.getByRole("button", { name: "Test" })).toBeDisabled();
  expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  expect(screen.getByText(/PLANNED/)).toBeVisible();
});

it("keeps placeholder credentials savable even when credentials exist", async () => {
  vi.mocked(setupApi.saveSetupSecret).mockResolvedValue({
    ok: true,
    provider_id: "api_sports",
    secret_name: "API_SPORTS_API_KEY",
    configured: true,
    masked: "****new",
  });
  const user = userEvent.setup();
  render(
    <ProviderCard
      provider={makeProvider({
        provider_id: "api_sports",
        display_name: "API-Sports",
        adapter_kind: "placeholder",
        state: "PLANNED",
        credentials: [
          { name: "API_SPORTS_API_KEY", configured: true, masked: "****key" },
        ],
      })}
      token="t"
      onChanged={vi.fn()}
    />,
  );
  expect(
    screen.getByText(/saved in advance/i),
  ).toBeVisible();
  const input = screen.getByLabelText("API_SPORTS_API_KEY value");
  expect(input).not.toBeDisabled();
  await user.type(input, "preloaded-key-77");
  await user.click(screen.getByRole("button", { name: "Update" }));
  await waitFor(() =>
    expect(setupApi.saveSetupSecret).toHaveBeenCalledWith(
      "t",
      "api_sports",
      "API_SPORTS_API_KEY",
      "preloaded-key-77",
    ),
  );
});

it("shows the state progression labels", () => {
  const states: [ProviderView["state"], string][] = [
    ["NEEDS_CREDENTIAL", "Needs credential"],
    ["READY_TO_TEST", "Ready to test"],
    ["HEALTHY", "Healthy"],
    ["RATE_LIMITED", "Rate limited"],
    ["AUTH_FAILED", "Auth failed"],
    ["UNAVAILABLE", "Unavailable"],
  ];
  for (const [state, label] of states) {
    const { unmount } = render(
      <ProviderCard provider={makeProvider({ state })} token="t" onChanged={vi.fn()} />,
    );
    expect(screen.getByText(label)).toBeVisible();
    unmount();
  }
});

it("shows detected runtime values as read-only context", () => {
  render(
    <ProviderCard
      provider={makeProvider({
        provider_id: "origin_defend_ai",
        display_name: "DEFEND AI origin",
        auth_type: "none",
        credentials: [],
        detected: {
          public_origin: "https://ai.defend-network.org",
          api_port: "8000",
          web_port: "3000",
        },
        optional_config: ["public_origin", "api_port", "web_port"],
        config: {},
      })}
      token="t"
      onChanged={vi.fn()}
    />,
  );
  expect(screen.getByText("Detected (runtime)")).toBeVisible();
  expect(screen.getByText("https://ai.defend-network.org")).toBeVisible();
  const apiInput = screen.getByLabelText("api_port value") as HTMLInputElement;
  expect(apiInput.placeholder).toBe("Detected: 8000");
});

it("omits the credentials section for auth-free providers", () => {
  render(
    <ProviderCard
      provider={makeProvider({ auth_type: "none", credentials: [] })}
      token="t"
      onChanged={vi.fn()}
    />,
  );
  expect(screen.queryByText("Credentials")).not.toBeInTheDocument();
});

it("saves optional config values", async () => {
  vi.mocked(setupApi.saveSetupConfig).mockResolvedValue(makeProvider());
  const user = userEvent.setup();
  render(<ProviderCard provider={makeProvider()} token="t" onChanged={vi.fn()} />);
  await user.type(screen.getByLabelText("host value"), "stats.example.test");
  await user.click(screen.getByRole("button", { name: "Save config" }));
  await waitFor(() =>
    expect(setupApi.saveSetupConfig).toHaveBeenCalledWith("t", "fred", {
      enabled: true,
      config: { host: "stats.example.test" },
    }),
  );
});

it("toggles the enabled state", async () => {
  vi.mocked(setupApi.saveSetupConfig).mockResolvedValue(
    makeProvider({ enabled: false }),
  );
  const user = userEvent.setup();
  render(<ProviderCard provider={makeProvider()} token="t" onChanged={vi.fn()} />);
  await user.click(screen.getByLabelText("Enable FRED"));
  await waitFor(() =>
    expect(setupApi.saveSetupConfig).toHaveBeenCalledWith("t", "fred", {
      enabled: false,
      config: {},
    }),
  );
});

it("shows rate limit details when quota metadata exists", async () => {
  const user = userEvent.setup();
  render(
    <ProviderCard
      provider={makeProvider({ remaining_quota: 87, quota_reset_at: "2026-08-18T00:00:00Z" })}
      token="t"
      onChanged={vi.fn()}
    />,
  );
  await user.click(screen.getByText("Rate limits & quota"));
  expect(screen.getByText("87")).toBeVisible();
  expect(screen.getByText("2026-08-18T00:00:00Z")).toBeVisible();
});
