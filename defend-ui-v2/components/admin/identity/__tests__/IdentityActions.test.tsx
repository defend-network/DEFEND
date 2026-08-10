import { useState } from "react";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AdminSession } from "@/lib/adminAuth";
import type {
  AccountDetail,
  InvitationSummary,
  VisitorDetail,
} from "@/lib/identityApi";
import * as identityApi from "@/lib/identityApi";
import { IdentityDetailDrawer } from "../IdentityDetailDrawer";
import { InvitationsTab } from "../InvitationsTab";
import { InviteAccountModal } from "../InviteAccountModal";
import { UsersRolesPanel } from "../UsersRolesPanel";

vi.mock("@/lib/identityApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/identityApi")>(
    "@/lib/identityApi",
  );
  return {
    ...actual,
    anonymizeAccount: vi.fn(),
    createAccount: vi.fn(),
    deleteAccount: vi.fn(),
    getAccount: vi.fn(),
    getVisitor: vi.fn(),
    getVisitorConversation: vi.fn(),
    listAccounts: vi.fn(),
    listInvitations: vi.fn(),
    listVisitors: vi.fn(),
    regenerateInvitation: vi.fn(),
    resendInvitation: vi.fn(),
    revokeInvitation: vi.fn(),
    updateAccount: vi.fn(),
  };
});

const adminSession: AdminSession = {
  username: "admin@defend-network.org",
  role: "admin",
  token: "admin-token",
  loggedInAt: "2026-08-10T12:00:00.000Z",
  expiresAt: "2026-08-10T13:00:00.000Z",
};

const ownerSession: AdminSession = {
  ...adminSession,
  username: "chairman@defend-network.org",
  role: "owner",
  token: "owner-token",
};

const invitation: InvitationSummary = {
  invitation_id: "inv-1",
  account_id: "acct-1",
  email: "member@example.com",
  intended_role: "user",
  created_at: "2026-08-10T12:00:00.000Z",
  expires_at: "2026-08-12T12:00:00.000Z",
  status: "pending",
  delivery_status: "sent",
  delivery_error: null,
  activation_url: "https://should-not-render.example/raw-list-token",
};

const accountDetail: AccountDetail = {
  account: {
    account_id: "acct-1",
    email: "member@example.com",
    display_name: "Member",
    role: "user",
    status: "active",
    created_at: "2026-08-01T12:00:00.000Z",
    last_access_at: "2026-08-10T11:00:00.000Z",
  },
  sessions: [],
  login_events: [],
  invitations: [],
  linked_visitors: [],
};

const visitorDetail: VisitorDetail = {
  visitor: {
    visitor_id: "vis-1",
    fingerprint_hmac: "bounded-fingerprint-hash",
    first_seen: "2026-08-01T12:00:00.000Z",
    last_seen: "2026-08-10T11:00:00.000Z",
    seen_count: 5,
    client_meta: { browser: "Firefox", platform: "Windows", device: "Desktop" },
  },
  sessions: [],
  connections: [],
  conversations: [
    {
      conversation_id: "conv-1",
      title: "Private support conversation",
      message_count: 2,
    },
  ],
  usage_events: [],
  linked_account: null,
};

const activationUrl = "https://ai.defend-network.org/activate/one-time-token";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

describe("identity management actions", () => {
  beforeEach(() => {
    vi.mocked(identityApi.createAccount).mockReset().mockResolvedValue({
      account: accountDetail.account,
      invitation: { ...invitation, activation_url: activationUrl },
    });
    vi.mocked(identityApi.getAccount).mockReset().mockResolvedValue(accountDetail);
    vi.mocked(identityApi.getVisitor).mockReset().mockResolvedValue(visitorDetail);
    vi.mocked(identityApi.getVisitorConversation).mockReset().mockResolvedValue({
      visitor_id: "vis-1",
      conversation_id: "conv-1",
      messages: [
        {
          message_id: "msg-1",
          seq: 1,
          role: "user",
          content: "Audited message content",
          created_at: "2026-08-10T10:00:00.000Z",
        },
      ],
    });
    vi.mocked(identityApi.updateAccount).mockReset().mockResolvedValue({
      account: { ...accountDetail.account, status: "disabled" },
    });
    vi.mocked(identityApi.anonymizeAccount).mockReset().mockResolvedValue({
      account: { ...accountDetail.account, status: "anonymized" },
    });
    vi.mocked(identityApi.deleteAccount).mockReset().mockResolvedValue(undefined);
    vi.mocked(identityApi.resendInvitation).mockReset().mockResolvedValue({
      invitation: { ...invitation, invitation_id: "inv-resend", activation_url: activationUrl },
    });
    vi.mocked(identityApi.regenerateInvitation).mockReset().mockResolvedValue({
      invitation: { ...invitation, invitation_id: "inv-regenerated", activation_url: activationUrl },
    });
    vi.mocked(identityApi.revokeInvitation).mockReset().mockResolvedValue({
      invitation: { ...invitation, status: "revoked" },
    });
    vi.mocked(identityApi.listAccounts).mockReset().mockResolvedValue({
      items: [], total: 0, limit: 50, offset: 0,
    });
    vi.mocked(identityApi.listVisitors).mockReset().mockResolvedValue({
      items: [], total: 0, limit: 50, offset: 0,
    });
    vi.mocked(identityApi.listInvitations).mockReset().mockResolvedValue({
      items: [invitation], total: 1, limit: 50, offset: 0,
    });
  });

  it("offers only end-user creation to admins and reveals the one-time link after creation", async () => {
    const user = userEvent.setup();
    render(
      <InviteAccountModal
        session={adminSession}
        onClose={vi.fn()}
        onCreated={vi.fn()}
      />,
    );

    expect(screen.queryByRole("option", { name: "Administrator" })).not.toBeInTheDocument();
    expect(screen.queryByText(activationUrl)).not.toBeInTheDocument();
    await user.type(screen.getByLabelText("Display name"), "Member");
    await user.type(screen.getByLabelText("Email address"), "member@example.com");
    await user.click(screen.getByRole("button", { name: "Create account and invitation" }));

    expect(await screen.findByText("Sensitive one-time activation link")).toBeVisible();
    expect(screen.getByText(activationUrl)).toBeVisible();
    expect(screen.getByRole("button", { name: "Copy activation link" })).toHaveFocus();
    expect(screen.queryByLabelText("Password")).not.toBeInTheDocument();
  });

  it("offers administrator creation only to the owner", () => {
    render(
      <InviteAccountModal
        session={ownerSession}
        onClose={vi.fn()}
        onCreated={vi.fn()}
      />,
    );

    expect(screen.getByRole("option", { name: "Administrator" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "Owner" })).not.toBeInTheDocument();
  });

  it("traps modal focus, closes on Escape, and restores the opener", async () => {
    const user = userEvent.setup();
    function Harness() {
      const [open, setOpen] = useState(false);
      return (
        <>
          <button type="button" onClick={() => setOpen(true)}>Open account modal</button>
          {open && (
            <InviteAccountModal
              session={adminSession}
              onClose={() => setOpen(false)}
              onCreated={vi.fn()}
            />
          )}
        </>
      );
    }
    render(<Harness />);
    const opener = screen.getByRole("button", { name: "Open account modal" });
    await user.click(opener);
    const displayName = screen.getByLabelText("Display name");
    expect(displayName).toHaveFocus();
    await user.click(opener);
    expect(displayName).toHaveFocus();

    const close = screen.getByRole("button", { name: "Close" });
    close.focus();
    await user.tab({ shift: true });
    expect(screen.getByRole("button", { name: "Create account and invitation" })).toHaveFocus();
    await user.tab();
    expect(close).toHaveFocus();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "Create account" })).not.toBeInTheDocument();
    expect(opener).toHaveFocus();
  });

  it("loads audited conversation content only after an explicit click", async () => {
    const user = userEvent.setup();
    render(
      <IdentityDetailDrawer
        session={adminSession}
        visitorId="vis-1"
        onClose={vi.fn()}
      />,
    );

    expect(identityApi.getVisitorConversation).not.toHaveBeenCalled();
    const open = await screen.findByRole("button", {
      name: "Open conversation Private support conversation",
    });
    expect(screen.queryByText("Audited message content")).not.toBeInTheDocument();
    await user.click(open);

    expect(await screen.findByText("Audited message content")).toBeVisible();
    expect(identityApi.getVisitorConversation).toHaveBeenCalledWith(
      adminSession.token,
      "vis-1",
      "conv-1",
    );
  });

  it("paginates every returned conversation message in bounded 50-message windows", async () => {
    const user = userEvent.setup();
    vi.mocked(identityApi.getVisitorConversation).mockResolvedValueOnce({
      visitor_id: "vis-1",
      conversation_id: "conv-1",
      messages: Array.from({ length: 120 }, (_, index) => ({
        message_id: `msg-${index + 1}`,
        seq: index + 1,
        role: index % 2 === 0 ? "user" : "assistant",
        content: `Audited message ${index + 1}`,
        created_at: "2026-08-10T10:00:00.000Z",
      })),
    });
    render(
      <IdentityDetailDrawer
        session={adminSession}
        visitorId="vis-1"
        onClose={vi.fn()}
      />,
    );

    await user.click(await screen.findByRole("button", {
      name: "Open conversation Private support conversation",
    }));
    expect(await screen.findByText("Audited message 1")).toBeVisible();
    expect(screen.getByText("Showing messages 1-50 of 120")).toBeVisible();
    expect(screen.queryByText("Audited message 51")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Show next messages" }));
    expect(screen.getByText("Showing messages 51-100 of 120")).toBeVisible();
    expect(screen.getByText("Audited message 51")).toBeVisible();
    expect(screen.queryByText("Audited message 1")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Show next messages" }));
    expect(screen.getByText("Showing messages 101-120 of 120")).toBeVisible();
    expect(screen.getByText("Audited message 120")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Show next messages" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Show previous messages" }));
    expect(screen.getByText("Showing messages 51-100 of 120")).toBeVisible();
  });

  it("ignores stale out-of-order conversation responses", async () => {
    const user = userEvent.setup();
    vi.mocked(identityApi.getVisitor).mockResolvedValueOnce({
      ...visitorDetail,
      conversations: [
        { conversation_id: "conv-first", title: "First conversation" },
        { conversation_id: "conv-second", title: "Second conversation" },
      ],
    });
    const first = deferred<Awaited<ReturnType<typeof identityApi.getVisitorConversation>>>();
    const second = deferred<Awaited<ReturnType<typeof identityApi.getVisitorConversation>>>();
    vi.mocked(identityApi.getVisitorConversation)
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise);
    render(
      <IdentityDetailDrawer session={adminSession} visitorId="vis-1" onClose={vi.fn()} />,
    );

    await user.click(await screen.findByRole("button", { name: "Open conversation First conversation" }));
    await user.click(screen.getByRole("button", { name: "Open conversation Second conversation" }));
    second.resolve({
      visitor_id: "vis-1",
      conversation_id: "conv-second",
      messages: [{ message_id: "second", seq: 1, role: "user", content: "Second result", created_at: "2026-08-10T12:00:00Z" }],
    });
    expect(await screen.findByText("Second result")).toBeVisible();
    first.resolve({
      visitor_id: "vis-1",
      conversation_id: "conv-first",
      messages: [{ message_id: "first", seq: 1, role: "user", content: "Stale first result", created_at: "2026-08-10T12:00:00Z" }],
    });
    await waitFor(() => expect(screen.queryByText("Stale first result")).not.toBeInTheDocument());
    expect(screen.getByText("Second result")).toBeVisible();
  });

  it("closing a loading conversation invalidates its response and restores focus", async () => {
    const user = userEvent.setup();
    const pending = deferred<Awaited<ReturnType<typeof identityApi.getVisitorConversation>>>();
    vi.mocked(identityApi.getVisitorConversation).mockReturnValueOnce(pending.promise);
    render(
      <IdentityDetailDrawer session={adminSession} visitorId="vis-1" onClose={vi.fn()} />,
    );
    const opener = await screen.findByRole("button", {
      name: "Open conversation Private support conversation",
    });
    await user.click(opener);
    expect(screen.getByRole("button", { name: "Close conversation" })).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "Audited conversation content" })).not.toBeInTheDocument();
    expect(opener).toHaveFocus();

    pending.resolve({
      visitor_id: "vis-1",
      conversation_id: "conv-1",
      messages: [{ message_id: "late", seq: 1, role: "user", content: "Late response", created_at: "2026-08-10T12:00:00Z" }],
    });
    await waitFor(() => expect(screen.queryByText("Late response")).not.toBeInTheDocument());
    expect(screen.queryByText("Loading conversation...")).not.toBeInTheDocument();
  });

  it("shows bounded visitor client metadata without loading conversation content", async () => {
    render(
      <IdentityDetailDrawer
        session={adminSession}
        visitorId="vis-1"
        onClose={vi.fn()}
      />,
    );

    expect(await screen.findByText("Firefox / Windows / Desktop")).toBeVisible();
    expect(screen.getByText("bounded-fingerprint-hash")).toBeVisible();
    expect(identityApi.getVisitorConversation).not.toHaveBeenCalled();
  });

  it("renders bounded visitor session and safe usage-event timelines", async () => {
    vi.mocked(identityApi.getVisitor).mockResolvedValueOnce({
      ...visitorDetail,
      sessions: [
        {
          session_id: "visitor-session-1",
          created_at: "2026-08-09T10:00:00Z",
          last_seen: "2026-08-09T11:00:00Z",
          client_meta: { browser: "Edge", platform: "Windows", device: "Desktop" },
        },
      ],
      usage_events: [
        {
          event_id: "usage-safe-1",
          visitor_id: "vis-1",
          conversation_id: "conv-1",
          request_id: "request-1",
          event_type: "research.completed",
          route: "/api/research",
          model: "defend-ai",
          research_status: "complete",
          evidence_count: 4,
          status: "ok",
          created_at: "2026-08-09T11:01:00Z",
          metadata: { feature: "research", auth_token: "must-not-render" },
        },
      ],
    });
    render(
      <IdentityDetailDrawer session={adminSession} visitorId="vis-1" onClose={vi.fn()} />,
    );

    expect(await screen.findByText("visitor-session-1")).toBeVisible();
    expect(screen.getByText("Edge / Windows / Desktop")).toBeVisible();
    expect(screen.getByText("research.completed")).toBeVisible();
    expect(screen.getByText("feature: research")).toBeVisible();
    expect(screen.queryByText(/must-not-render/)).not.toBeInTheDocument();
  });

  it("shows linked visitor IP and usage history in account detail", async () => {
    vi.mocked(identityApi.getAccount).mockResolvedValueOnce({
      ...accountDetail,
      linked_visitors: [
        {
          visitor_id: "vis-linked",
          linked_at: "2026-08-02T12:00:00.000Z",
          last_seen_at: "2026-08-10T11:00:00.000Z",
          visitor: { ...visitorDetail.visitor, visitor_id: "vis-linked" },
          sessions: [],
          connections: [
            {
              connection_id: "connection-1",
              visitor_id: "vis-linked",
              session_id: "session-1",
              ip_address: "192.0.2.44",
              user_agent: "bounded user agent",
              browser: "Firefox",
              platform: "Windows",
              device: "Desktop",
              language: "en-US",
              fingerprint_hmac: "bounded-fingerprint-hash",
              observed_at: "2026-08-09T12:00:00.000Z",
            },
          ],
          conversations: [],
          usage_events: [
            {
              event_id: "usage-1",
              visitor_id: "vis-linked",
              conversation_id: null,
              request_id: null,
              event_type: "chat.request",
              route: "/api/chat",
              model: "defend-ai",
              research_status: null,
              evidence_count: null,
              status: "ok",
              created_at: "2026-08-09T12:01:00.000Z",
              metadata: {},
            },
          ],
          telemetry: { recent_ip: "203.0.113.8", device_count: 1 },
        },
      ],
    });
    render(
      <IdentityDetailDrawer
        session={adminSession}
        accountId="acct-1"
        onClose={vi.fn()}
      />,
    );

    expect(await screen.findByText("192.0.2.44")).toBeVisible();
    expect(screen.getByText("chat.request")).toBeVisible();
  });

  it("requires typed confirmation to disable and keeps destructive controls owner-only", async () => {
    const user = userEvent.setup();
    render(
      <IdentityDetailDrawer
        session={adminSession}
        accountId="acct-1"
        onClose={vi.fn()}
      />,
    );

    await screen.findByText("member@example.com");
    expect(screen.queryByRole("button", { name: "Anonymize account" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Delete account" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Disable account" }));
    const confirm = screen.getByLabelText("Type DISABLE to confirm");
    await user.type(confirm, "disable");
    expect(screen.getByRole("button", { name: "Confirm disable" })).toBeDisabled();
    await user.clear(confirm);
    await user.type(confirm, "DISABLE");
    await user.click(screen.getByRole("button", { name: "Confirm disable" }));

    expect(await screen.findByRole("status")).toHaveTextContent("Account disabled");
    expect(identityApi.updateAccount).toHaveBeenCalledWith(
      adminSession.token,
      "acct-1",
      { status: "disabled" },
    );
  });

  it("edits an end-user display name and refreshes the account list", async () => {
    const user = userEvent.setup();
    const onChanged = vi.fn();
    vi.mocked(identityApi.getAccount)
      .mockResolvedValueOnce(accountDetail)
      .mockResolvedValueOnce({
        ...accountDetail,
        account: { ...accountDetail.account, display_name: "Renamed member" },
      });
    vi.mocked(identityApi.updateAccount).mockResolvedValueOnce({
      account: { ...accountDetail.account, display_name: "Renamed member" },
    });
    render(
      <IdentityDetailDrawer
        session={adminSession}
        accountId="acct-1"
        onClose={vi.fn()}
        onChanged={onChanged}
      />,
    );

    const displayName = await screen.findByLabelText("Display name");
    await user.clear(displayName);
    await user.type(displayName, "Renamed member");
    await user.click(screen.getByRole("button", { name: "Save display name" }));

    expect(identityApi.updateAccount).toHaveBeenCalledWith(
      adminSession.token,
      "acct-1",
      { display_name: "Renamed member" },
    );
    expect(await screen.findByRole("status")).toHaveTextContent("Display name updated");
    expect(screen.getByRole("heading", { name: "Renamed member" })).toBeVisible();
    expect(identityApi.getAccount).toHaveBeenCalledTimes(2);
    expect(onChanged).toHaveBeenCalledTimes(1);
  });

  it("requires explicit confirmation to reactivate a disabled end user", async () => {
    const user = userEvent.setup();
    const onChanged = vi.fn();
    vi.mocked(identityApi.getAccount).mockResolvedValueOnce({
      ...accountDetail,
      account: { ...accountDetail.account, status: "disabled" },
    });
    vi.mocked(identityApi.updateAccount).mockResolvedValueOnce({
      account: { ...accountDetail.account, status: "active" },
    });
    render(
      <IdentityDetailDrawer
        session={adminSession}
        accountId="acct-1"
        onClose={vi.fn()}
        onChanged={onChanged}
      />,
    );

    await user.click(await screen.findByRole("button", { name: "Reactivate account" }));
    expect(screen.getByRole("button", { name: "Confirm reactivate" })).toBeDisabled();
    await user.type(screen.getByLabelText("Type REACTIVATE to confirm"), "REACTIVATE");
    await user.click(screen.getByRole("button", { name: "Confirm reactivate" }));

    expect(identityApi.updateAccount).toHaveBeenCalledWith(
      adminSession.token,
      "acct-1",
      { status: "active" },
    );
    expect(await screen.findByRole("status")).toHaveTextContent("Account reactivated");
    expect(onChanged).toHaveBeenCalledTimes(1);
  });

  it("keeps pending end-user accounts available for disabling", async () => {
    vi.mocked(identityApi.getAccount).mockResolvedValueOnce({
      ...accountDetail,
      account: { ...accountDetail.account, status: "pending_activation" },
    });
    render(
      <IdentityDetailDrawer
        session={adminSession}
        accountId="acct-1"
        onClose={vi.fn()}
      />,
    );

    expect(await screen.findByRole("button", { name: "Disable account" })).toBeVisible();
  });

  it("lets the owner promote a user with confirmation and refreshes the result", async () => {
    const user = userEvent.setup();
    const onChanged = vi.fn();
    vi.mocked(identityApi.getAccount)
      .mockResolvedValueOnce(accountDetail)
      .mockResolvedValueOnce({
        ...accountDetail,
        account: { ...accountDetail.account, role: "admin" },
      });
    vi.mocked(identityApi.updateAccount).mockResolvedValueOnce({
      account: { ...accountDetail.account, role: "admin" },
    });
    render(
      <IdentityDetailDrawer
        session={ownerSession}
        accountId="acct-1"
        onClose={vi.fn()}
        onChanged={onChanged}
      />,
    );

    await user.click(await screen.findByRole("button", { name: "Promote to administrator" }));
    await user.type(screen.getByLabelText("Type PROMOTE to confirm"), "PROMOTE");
    await user.click(screen.getByRole("button", { name: "Confirm promote" }));
    expect(identityApi.updateAccount).toHaveBeenLastCalledWith(
      ownerSession.token,
      "acct-1",
      { role: "admin" },
    );
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Account promoted to administrator",
    );
    expect(screen.getByRole("button", { name: "Demote to user" })).toBeVisible();
    expect(onChanged).toHaveBeenCalledTimes(1);
  });

  it("lets the owner demote an administrator with confirmation and refreshes the result", async () => {
    const user = userEvent.setup();
    const onChanged = vi.fn();
    vi.mocked(identityApi.getAccount)
      .mockResolvedValueOnce({
        ...accountDetail,
        account: { ...accountDetail.account, role: "admin" },
      })
      .mockResolvedValueOnce(accountDetail);
    vi.mocked(identityApi.updateAccount).mockResolvedValueOnce({
      account: { ...accountDetail.account, role: "user" },
    });
    render(
      <IdentityDetailDrawer
        session={ownerSession}
        accountId="acct-admin"
        onClose={vi.fn()}
        onChanged={onChanged}
      />,
    );
    await user.click(await screen.findByRole("button", { name: "Demote to user" }));
    await user.type(screen.getByLabelText("Type DEMOTE to confirm"), "DEMOTE");
    await user.click(screen.getByRole("button", { name: "Confirm demote" }));
    expect(identityApi.updateAccount).toHaveBeenLastCalledWith(
      ownerSession.token,
      "acct-admin",
      { role: "user" },
    );
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Administrator demoted to user",
    );
    expect(screen.getByRole("button", { name: "Promote to administrator" })).toBeVisible();
    expect(onChanged).toHaveBeenCalledTimes(1);
  });

  it("does not expose administrator management controls to an admin", async () => {
    vi.mocked(identityApi.getAccount).mockResolvedValueOnce({
      ...accountDetail,
      account: {
        ...accountDetail.account,
        account_id: "acct-admin",
        email: adminSession.username,
        role: "admin",
      },
    });
    render(
      <IdentityDetailDrawer
        session={adminSession}
        accountId="acct-admin"
        onClose={vi.fn()}
      />,
    );

    await screen.findByText(adminSession.username);
    expect(screen.queryByLabelText("Display name")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Disable account" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Promote|Demote|Reactivate/ })).not.toBeInTheDocument();
  });

  it("does not let a completed mutation overwrite a newly selected account", async () => {
    const user = userEvent.setup();
    const onChanged = vi.fn();
    const mutation = deferred<Awaited<ReturnType<typeof identityApi.updateAccount>>>();
    const accountB: AccountDetail = {
      ...accountDetail,
      account: {
        ...accountDetail.account,
        account_id: "acct-2",
        email: "second@example.com",
        display_name: "Second member",
      },
    };
    vi.mocked(identityApi.getAccount)
      .mockResolvedValueOnce(accountDetail)
      .mockResolvedValueOnce(accountB);
    vi.mocked(identityApi.updateAccount).mockReturnValueOnce(mutation.promise);
    const { rerender } = render(
      <IdentityDetailDrawer
        session={adminSession}
        accountId="acct-1"
        onClose={vi.fn()}
        onChanged={onChanged}
      />,
    );

    const displayName = await screen.findByLabelText("Display name");
    await user.clear(displayName);
    await user.type(displayName, "Stale renamed member");
    await user.click(screen.getByRole("button", { name: "Save display name" }));
    rerender(
      <IdentityDetailDrawer
        session={adminSession}
        accountId="acct-2"
        onClose={vi.fn()}
        onChanged={onChanged}
      />,
    );
    expect(await screen.findByRole("heading", { name: "Second member" })).toBeVisible();

    mutation.resolve({
      account: { ...accountDetail.account, display_name: "Stale renamed member" },
    });
    await waitFor(() => expect(identityApi.updateAccount).toHaveBeenCalledTimes(1));
    expect(screen.getByRole("heading", { name: "Second member" })).toBeVisible();
    expect(screen.queryByRole("heading", { name: "Stale renamed member" })).not.toBeInTheDocument();
    expect(screen.queryByText("Display name updated")).not.toBeInTheDocument();
    expect(identityApi.getAccount).toHaveBeenCalledTimes(2);
    expect(onChanged).not.toHaveBeenCalled();
  });

  it("does not show a stale mutation failure on a newly selected account", async () => {
    const user = userEvent.setup();
    const mutation = deferred<Awaited<ReturnType<typeof identityApi.updateAccount>>>();
    const accountB: AccountDetail = {
      ...accountDetail,
      account: {
        ...accountDetail.account,
        account_id: "acct-2",
        email: "second@example.com",
        display_name: "Second member",
      },
    };
    vi.mocked(identityApi.getAccount)
      .mockResolvedValueOnce(accountDetail)
      .mockResolvedValueOnce(accountB);
    vi.mocked(identityApi.updateAccount).mockReturnValueOnce(mutation.promise);
    const { rerender } = render(
      <IdentityDetailDrawer session={adminSession} accountId="acct-1" onClose={vi.fn()} />,
    );

    const displayName = await screen.findByLabelText("Display name");
    await user.clear(displayName);
    await user.type(displayName, "Rejected stale name");
    await user.click(screen.getByRole("button", { name: "Save display name" }));
    rerender(
      <IdentityDetailDrawer session={adminSession} accountId="acct-2" onClose={vi.fn()} />,
    );
    expect(await screen.findByRole("heading", { name: "Second member" })).toBeVisible();

    await act(async () => {
      mutation.reject(new Error("Stale account action failed"));
      await mutation.promise.catch(() => undefined);
    });
    expect(screen.queryByText("Stale account action failed")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Second member" })).toBeVisible();
  });

  it("focuses account confirmation, closes its layer on Escape, and restores the action", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(
      <IdentityDetailDrawer session={adminSession} accountId="acct-1" onClose={onClose} />,
    );
    const disable = await screen.findByRole("button", { name: "Disable account" });
    await user.click(disable);
    expect(screen.getByLabelText("Type DISABLE to confirm")).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("alertdialog", { name: "Confirm disable" })).not.toBeInTheDocument();
    expect(disable).toHaveFocus();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("traps drawer focus, closes on Escape, and restores the opener", async () => {
    const user = userEvent.setup();
    function Harness() {
      const [open, setOpen] = useState(false);
      return (
        <>
          <button type="button" onClick={() => setOpen(true)}>Open account detail</button>
          {open && (
            <IdentityDetailDrawer
              session={adminSession}
              accountId="acct-1"
              onClose={() => setOpen(false)}
            />
          )}
        </>
      );
    }
    render(<Harness />);
    const opener = screen.getByRole("button", { name: "Open account detail" });
    await user.click(opener);
    const close = screen.getByRole("button", { name: "Close details" });
    await waitFor(() => expect(close).toHaveFocus());
    await screen.findByRole("button", { name: "Disable account" });
    close.focus();
    await user.tab({ shift: true });
    expect(screen.getByRole("button", { name: "Disable account" })).toHaveFocus();
    await user.tab();
    expect(close).toHaveFocus();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "Account detail" })).not.toBeInTheDocument();
    expect(opener).toHaveFocus();
  });

  it("shows one safe failure message when an account action is rejected", async () => {
    const user = userEvent.setup();
    vi.mocked(identityApi.updateAccount).mockRejectedValueOnce(
      new Error("Account action is not permitted"),
    );
    render(
      <IdentityDetailDrawer
        session={adminSession}
        accountId="acct-1"
        onClose={vi.fn()}
      />,
    );
    await screen.findByText("member@example.com");
    await user.click(screen.getByRole("button", { name: "Disable account" }));
    await user.type(screen.getByLabelText("Type DISABLE to confirm"), "DISABLE");
    await user.click(screen.getByRole("button", { name: "Confirm disable" }));

    expect(await screen.findAllByRole("alert")).toHaveLength(1);
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Account action is not permitted",
    );
  });

  it("never exposes a stored invitation link and copies a regenerated link only on click", async () => {
    const user = userEvent.setup();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    render(
      <InvitationsTab
        invitations={[invitation]}
        session={ownerSession}
        onChanged={vi.fn()}
      />,
    );

    expect(screen.queryByText("https://should-not-render.example/raw-list-token")).not.toBeInTheDocument();
    expect(writeText).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Regenerate link for member@example.com" }));
    expect(await screen.findByText("Sensitive one-time activation link")).toBeVisible();
    expect(writeText).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Copy activation link" }));
    expect(writeText).toHaveBeenCalledWith(activationUrl);
    expect(
      screen.getByRole("button", { name: "Revoke invitation for member@example.com" }),
    ).toBeDisabled();
  });

  it("keeps a failed-resend activation fallback transient until explicitly hidden", async () => {
    const user = userEvent.setup();
    const onChanged = vi.fn();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    vi.mocked(identityApi.resendInvitation).mockResolvedValueOnce({
      invitation: {
        ...invitation,
        invitation_id: "inv-resend-failed",
        delivery_status: "failed",
        delivery_error: "Delivery failed",
        activation_url: activationUrl,
        delivery: {
          delivered: false,
          provider_message_id: null,
          error: "Delivery failed",
        },
      },
    });
    render(
      <InvitationsTab
        invitations={[invitation]}
        session={ownerSession}
        onChanged={onChanged}
      />,
    );

    const resendButton = screen.getByRole("button", {
      name: "Resend invitation to member@example.com",
    });
    await user.click(resendButton);

    expect(await screen.findByText("Sensitive one-time activation link")).toBeVisible();
    expect(screen.getByText(activationUrl)).toBeVisible();
    expect(screen.getByText(/Email delivery failed/i)).toBeVisible();
    expect(screen.getByRole("button", { name: "Copy activation link" })).toHaveFocus();
    expect(writeText).not.toHaveBeenCalled();
    expect(onChanged).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Copy activation link" }));
    expect(writeText).toHaveBeenCalledWith(activationUrl);
    await user.click(screen.getByRole("button", { name: "Hide activation link" }));
    expect(onChanged).toHaveBeenCalledTimes(1);
    expect(screen.queryByText(activationUrl)).not.toBeInTheDocument();
    expect(resendButton).toHaveFocus();
  });

  it("requires typed confirmation before revoking an invitation", async () => {
    const user = userEvent.setup();
    render(
      <InvitationsTab
        invitations={[invitation]}
        session={ownerSession}
        onChanged={vi.fn()}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Revoke invitation for member@example.com" }));
    expect(screen.getByRole("button", { name: "Confirm revoke" })).toBeDisabled();
    await user.type(screen.getByLabelText("Type REVOKE to confirm"), "REVOKE");
    await user.click(screen.getByRole("button", { name: "Confirm revoke" }));
    await waitFor(() =>
      expect(identityApi.revokeInvitation).toHaveBeenCalledWith(ownerSession.token, "inv-1"),
    );
  });

  it("hides administrator invitation actions from non-owner admins", () => {
    render(
      <InvitationsTab
        invitations={[{ ...invitation, intended_role: "admin" }]}
        session={adminSession}
      />,
    );

    expect(screen.queryByRole("button", { name: /Resend invitation/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Regenerate link/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Revoke invitation/ })).not.toBeInTheDocument();
  });

  it("keeps a regenerated one-time link visible until dismissal before refreshing", async () => {
    const user = userEvent.setup();
    render(<UsersRolesPanel session={ownerSession} />);
    await user.click(screen.getByRole("tab", { name: "Invitations" }));
    await user.click(
      await screen.findByRole("button", {
        name: "Regenerate link for member@example.com",
      }),
    );

    expect(await screen.findByText(activationUrl)).toBeVisible();
    expect(identityApi.listInvitations).toHaveBeenCalledTimes(1);
    await user.click(screen.getByRole("button", { name: "Hide activation link" }));
    await waitFor(() => expect(identityApi.listInvitations).toHaveBeenCalledTimes(2));
    expect(screen.queryByText(activationUrl)).not.toBeInTheDocument();
  });
});
