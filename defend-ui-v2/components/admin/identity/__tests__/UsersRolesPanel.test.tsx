import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  AccountSummary,
  InvitationSummary,
  Page,
  VisitorSummary,
} from "@/lib/identityApi";
import * as identityApi from "@/lib/identityApi";
import { UsersRolesPanel } from "../UsersRolesPanel";

vi.mock("@/lib/identityApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/identityApi")>(
    "@/lib/identityApi",
  );
  return {
    ...actual,
    listAccounts: vi.fn(),
    listVisitors: vi.fn(),
    listInvitations: vi.fn(),
  };
});

const ownerSession = {
  username: "chairman@defend-network.org",
  role: "owner" as const,
  token: "owner-token",
  loggedInAt: "2026-08-10T12:00:00.000Z",
  expiresAt: "2026-08-10T13:00:00.000Z",
};

const account: AccountSummary = {
  account_id: "account-1",
  email: "jane@example.com",
  display_name: "Jane Operator",
  role: "admin",
  status: "active",
  created_at: "2026-08-01T10:00:00.000Z",
  last_access_at: "2026-08-10T11:30:00.000Z",
  visitor_count: 2,
  active_session_count: 3,
  recent_ip: "203.0.113.8",
  device_count: 2,
};

const visitor: VisitorSummary = {
  visitor_id: "visitor-7",
  fingerprint_hmac: "fingerprint-hmac",
  first_seen: "2026-08-01T10:00:00.000Z",
  last_seen: "2026-08-10T11:30:00.000Z",
  seen_count: 11,
  client_meta: {
    browser: "Firefox",
    platform: "Windows",
    device: "Desktop",
    language: "en-US",
  },
  session_count: 4,
  conversation_count: 5,
  message_count: 23,
  recent_ip: "198.51.100.4",
  device_count: 1,
  linked_account: {
    account_id: "account-1",
    email: "jane@example.com",
    display_name: "Jane Operator",
    role: "admin",
    status: "active",
  },
};

const invitation: InvitationSummary = {
  invitation_id: "invitation-4",
  account_id: "account-2",
  email: "new.user@example.com",
  intended_role: "user",
  created_at: "2026-08-10T10:00:00.000Z",
  expires_at: "2026-08-12T10:00:00.000Z",
  status: "pending",
  delivery_status: "sent",
  delivery_error: null,
  creator: {
    account_id: "owner-1",
    email: "chairman@defend-network.org",
    display_name: "Chairman",
  },
};

function page<T>(items: T[], total = items.length, offset = 0): Page<T> {
  return { items, total, limit: 50, offset };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

const listAccounts = vi.mocked(identityApi.listAccounts);
const listVisitors = vi.mocked(identityApi.listVisitors);
const listInvitations = vi.mocked(identityApi.listInvitations);

describe("UsersRolesPanel", () => {
  beforeEach(() => {
    listAccounts.mockReset().mockResolvedValue(page([account]));
    listVisitors.mockReset().mockResolvedValue(page([visitor]));
    listInvitations.mockReset().mockResolvedValue(page([invitation]));
  });

  it("renders Accounts, Visitors, and Invitations in order with separate tables and selection callbacks", async () => {
    const user = userEvent.setup();
    const onSelectAccount = vi.fn();
    const onSelectVisitor = vi.fn();
    const onSelectInvitation = vi.fn();

    render(
      <UsersRolesPanel
        session={ownerSession}
        onSelectAccount={onSelectAccount}
        onSelectVisitor={onSelectVisitor}
        onSelectInvitation={onSelectInvitation}
      />,
    );

    const tabs = screen.getAllByRole("tab");
    expect(tabs.map((tab) => tab.textContent)).toEqual([
      "Accounts",
      "Visitors",
      "Invitations",
    ]);
    expect(tabs[0]).toHaveAttribute("aria-selected", "true");

    const accountsTable = await screen.findByRole("table", {
      name: "Accounts",
    });
    expect(
      within(accountsTable)
        .getAllByRole("columnheader")
        .map((header) => header.textContent),
    ).toEqual([
      "Account",
      "Role",
      "Status",
      "Created",
      "Last access",
      "Recent IP",
      "Devices",
      "Sessions",
    ]);
    await user.click(within(accountsTable).getByRole("button", { name: /Jane Operator/ }));
    expect(onSelectAccount).toHaveBeenCalledWith(account);

    await user.click(screen.getByRole("tab", { name: "Visitors" }));
    const visitorsTable = await screen.findByRole("table", {
      name: "Visitors",
    });
    expect(screen.queryByRole("table", { name: "Accounts" })).not.toBeInTheDocument();
    expect(within(visitorsTable).getByText("Firefox / Windows / Desktop")).toBeVisible();
    expect(within(visitorsTable).getByText("Jane Operator")).toBeVisible();
    await user.click(within(visitorsTable).getByRole("button", { name: "visitor-7" }));
    expect(onSelectVisitor).toHaveBeenCalledWith(visitor);

    await user.click(screen.getByRole("tab", { name: "Invitations" }));
    const invitationsTable = await screen.findByRole("table", {
      name: "Invitations",
    });
    expect(
      within(invitationsTable)
        .getAllByRole("columnheader")
        .map((header) => header.textContent),
    ).toEqual([
      "Recipient",
      "Role",
      "Creator",
      "Delivery",
      "Status",
      "Created",
      "Expires",
    ]);
    await user.click(
      within(invitationsTable).getByRole("button", {
        name: "new.user@example.com",
      }),
    );
    expect(onSelectInvitation).toHaveBeenCalledWith(invitation);
  });

  it("debounces one searchbox and sends its value only to the active tab", async () => {
    const user = userEvent.setup();
    render(<UsersRolesPanel session={ownerSession} />);
    await screen.findByRole("table", { name: "Accounts" });

    await user.click(screen.getByRole("tab", { name: "Visitors" }));
    await screen.findByRole("table", { name: "Visitors" });
    listAccounts.mockClear();
    listVisitors.mockClear();

    await user.type(screen.getByRole("searchbox"), "203.0.113.8");
    expect(listVisitors).not.toHaveBeenCalled();

    await waitFor(
      () =>
        expect(listVisitors).toHaveBeenCalledWith(ownerSession.token, {
          q: "203.0.113.8",
          limit: 50,
          offset: 0,
        }),
      { timeout: 1000 },
    );
    expect(listAccounts).not.toHaveBeenCalled();
  });

  it("shows loading and empty states, then recovers from an error when refreshed", async () => {
    const user = userEvent.setup();
    const initial = deferred<Page<AccountSummary>>();
    listAccounts.mockReset().mockReturnValueOnce(initial.promise);

    render(<UsersRolesPanel session={ownerSession} />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading accounts");

    initial.resolve(page([]));
    expect(await screen.findByText("No accounts found.")).toBeVisible();

    listAccounts
      .mockRejectedValueOnce(new Error("Identity service unavailable"))
      .mockResolvedValueOnce(page([account]));
    await user.click(screen.getByRole("button", { name: "Refresh accounts" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Identity service unavailable",
    );

    await user.click(screen.getByRole("button", { name: "Refresh accounts" }));
    expect(await screen.findByText("jane@example.com")).toBeVisible();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("uses bounded 50-row pages and prevents navigation past the result set", async () => {
    const user = userEvent.setup();
    listAccounts
      .mockResolvedValueOnce(page([account], 51, 0))
      .mockResolvedValueOnce(page([{ ...account, account_id: "account-51", display_name: "Last Account" }], 51, 50));

    render(<UsersRolesPanel session={ownerSession} />);
    expect(await screen.findByText("1-50 of 51")).toBeVisible();
    expect(screen.getByRole("button", { name: "Previous page" })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Next page" }));
    await waitFor(() =>
      expect(listAccounts).toHaveBeenLastCalledWith(ownerSession.token, {
        q: "",
        limit: 50,
        offset: 50,
      }),
    );
    expect(await screen.findByText("Last Account")).toBeVisible();
    expect(screen.getByText("51-51 of 51")).toBeVisible();
    expect(screen.getByRole("button", { name: "Next page" })).toBeDisabled();
  });

  it("does not let a stale response replace newer refreshed results", async () => {
    const user = userEvent.setup();
    const stale = deferred<Page<AccountSummary>>();
    listAccounts
      .mockReset()
      .mockReturnValueOnce(stale.promise)
      .mockResolvedValueOnce(
        page([{ ...account, account_id: "account-new", display_name: "Fresh Account" }]),
      );

    render(<UsersRolesPanel session={ownerSession} />);
    await user.click(screen.getByRole("button", { name: "Refresh accounts" }));
    expect(await screen.findByText("Fresh Account")).toBeVisible();

    await act(async () => {
      stale.resolve(page([{ ...account, display_name: "Stale Account" }]));
      await stale.promise;
    });
    expect(screen.queryByText("Stale Account")).not.toBeInTheDocument();
    expect(screen.getByText("Fresh Account")).toBeVisible();
  });
});
