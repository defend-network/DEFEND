import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";

import SetupIntegrationsPanel from "../SetupIntegrationsPanel";
import type { SetupCategory, SetupSummary } from "@/lib/setupApi";
import * as setupApi from "@/lib/setupApi";

vi.mock("@/lib/setupApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/setupApi")>(
    "@/lib/setupApi",
  );
  return {
    ...actual,
    getSetupSummary: vi.fn(),
    getSetupDiagnostics: vi.fn(),
    testAllSetupProviders: vi.fn(),
  };
});

vi.mock("../ProviderCard", () => ({
  default: ({ provider }: { provider: { provider_id: string; display_name: string } }) => (
    <div data-testid={`card-${provider.provider_id}`}>{provider.display_name}</div>
  ),
}));

const session = {
  username: "chairman@defend-network.org",
  role: "owner" as const,
  token: "owner-token",
  loggedInAt: "2026-08-10T12:00:00.000Z",
  expiresAt: "2026-08-10T13:00:00.000Z",
};

const category: SetupCategory = {
  category_id: "core",
  display_name: "Core",
  description: null,
  providers: [
    {
      provider_id: "local_model",
      display_name: "Local model",
      purpose: "Inference",
      category: "core",
      auth_type: "api_key",
      adapter_kind: "real",
      state: "CONFIGURED",
      health_badge: "NOT_TESTED",
      enabled: true,
      credentials: [],
      config: {},
      optional_config: ["image"],
      products: ["defend_ai"],
      docs_url: null,
      rate_limits: {},
      license: {},
      tested_at: null,
      last_success_at: null,
      last_test_detail: null,
      last_status_code: null,
      last_latency_ms: null,
      remaining_quota: null,
      quota_reset_at: null,
      notes: null,
    },
  ],
};

const summary: SetupSummary = {
  categories: [
    category,
    { category_id: "diagnostics", display_name: "Diagnostics", description: null, providers: [] },
  ],
  products: [{ product_id: "defend_ai", display_name: "DEFEND AI" }],
  product_providers: { defend_ai: ["local_model"] },
  legacy_secret_names: ["VLLM_API_KEY"],
  registry_secret_names: ["VLLM_API_KEY"],
};

beforeEach(() => {
  vi.mocked(setupApi.getSetupSummary).mockReset();
  vi.mocked(setupApi.getSetupDiagnostics).mockReset();
  vi.mocked(setupApi.testAllSetupProviders).mockReset();
  vi.mocked(setupApi.getSetupSummary).mockResolvedValue(summary);
});

it("renders category tabs with providers and the summary data", async () => {
  render(<SetupIntegrationsPanel session={session} />);
  expect(await screen.findByText("Setup & Integrations")).toBeVisible();
  const tab = screen.getByRole("tab", { name: "Core" });
  expect(tab).toBeVisible();
  expect(tab).toHaveAttribute("aria-selected", "true");
  expect(screen.getByTestId("card-local_model")).toBeVisible();
});

it("keeps the panel shell scroll-hostile and the body scrollable", async () => {
  const { container } = render(<SetupIntegrationsPanel session={session} />);
  await screen.findByRole("tab", { name: "Core" });
  const shell = container.querySelector("[data-setup-shell]");
  expect(shell).not.toBeNull();
  expect(shell).toHaveStyle({ overflowY: "hidden" });
  expect(screen.getByRole("tabpanel")).toHaveStyle({ overflowY: "auto" });
});

it("switches to the select when measured under the compact width", async () => {
  Object.defineProperty(HTMLElement.prototype, "clientWidth", {
    configurable: true,
    get: () => 500,
  });
  try {
    const user = userEvent.setup();
    render(<SetupIntegrationsPanel session={session} />);
    const select = await screen.findByRole("combobox", { name: "Category" });
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
    await user.selectOptions(select, "core");
    expect(select).toHaveValue("core");
    expect(screen.getByTestId("card-local_model")).toBeVisible();
  } finally {
    delete (HTMLElement.prototype as { clientWidth?: number }).clientWidth;
  }
});

it("shows an error banner when the summary request fails", async () => {
  vi.mocked(setupApi.getSetupSummary).mockRejectedValue(
    new Error("registry unavailable"),
  );
  render(<SetupIntegrationsPanel session={session} />);
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "registry unavailable",
  );
});

it("renders diagnostics rows when the diagnostics tab is active", async () => {
  vi.mocked(setupApi.getSetupDiagnostics).mockResolvedValue({
    rows: [
      {
        provider_id: "fred",
        display_name: "FRED",
        category: "macro",
        products: ["defend_ai"],
        auth_type: "api_key",
        adapter_kind: "real",
        enabled: true,
        configured: false,
        health_badge: "NOT_CONFIGURED",
        detail: null,
      },
    ],
  });
  const user = userEvent.setup();
  render(<SetupIntegrationsPanel session={session} />);
  await screen.findByRole("tab", { name: "Core" });
  await user.click(screen.getByRole("tab", { name: "Diagnostics" }));
  await screen.findByRole("tabpanel");
  expect(await screen.findByText("FRED")).toBeVisible();
  expect(screen.getByText("Not configured")).toBeVisible();
  expect(screen.getByText("macro")).toBeVisible();
});

it("runs TEST ALL, reports the outcome, and refreshes the summary", async () => {
  vi.mocked(setupApi.testAllSetupProviders).mockResolvedValue({
    tested: 1,
    results: [
      {
        provider_id: "local_model",
        ok: true,
        badge: "HEALTHY",
        detail: "200 in 42ms",
        tested_at: "2026-08-17T10:00:00Z",
      },
    ],
    skipped: [{ provider_id: "api_sports", reason: "adapter not implemented" }],
  });
  const user = userEvent.setup();
  render(<SetupIntegrationsPanel session={session} />);
  await screen.findByRole("tab", { name: "Core" });
  await user.click(screen.getByRole("button", { name: "TEST ALL CONFIGURED" }));
  expect(await screen.findByRole("status")).toHaveTextContent(
    "Tested 1 provider(s)",
  );
  await waitFor(() =>
    expect(setupApi.getSetupSummary).toHaveBeenCalledTimes(2),
  );
});
