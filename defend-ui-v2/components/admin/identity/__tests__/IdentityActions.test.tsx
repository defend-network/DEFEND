import { render, screen, waitFor, within } from "@testing-library/react";
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
