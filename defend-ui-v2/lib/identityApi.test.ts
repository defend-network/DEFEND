import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  anonymizeAccount,
  type AccountDetail,
  createAccount,
  deleteAccount,
  getAccount,
  getVisitor,
  getVisitorConversation,
  listAccounts,
  listInvitations,
  listVisitors,
  regenerateInvitation,
  resendInvitation,
  revokeInvitation,
  updateAccount,
} from "./identityApi";

const accountDetailContract = {
  account: {
    account_id: "acct_1",
    email: "member@example.com",
    display_name: "Member",
    role: "user",
    status: "active",
    created_at: "2026-08-10T12:00:00+00:00",
    updated_at: "2026-08-10T12:00:00+00:00",
    last_access_at: null,
  },
  sessions: [],
  login_events: [],
  invitations: [
    {
      invitation_id: "inv_1",
      account_id: "acct_1",
      email: "member@example.com",
      intended_role: "user",
      created_by: "acct_owner",
      created_at: "2026-08-10T12:00:00+00:00",
      expires_at: "2026-08-12T12:00:00+00:00",
      consumed_at: null,
      revoked_at: null,
      delivery_status: "sent",
      delivery_error: null,
    },
  ],
  linked_visitors: [
    {
      visitor_id: "vis_missing",
      linked_at: "2026-08-10T12:00:00+00:00",
      last_seen_at: "2026-08-10T12:00:00+00:00",
      visitor: null,
      sessions: [],
      connections: [],
      conversations: [],
      usage_events: [],
      telemetry: { recent_ip: null, device_count: 0 },
    },
  ],
} satisfies AccountDetail;

const fetchMock = vi.fn<typeof fetch>();

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("identity admin API client", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
    fetchMock.mockReset();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    document.body.replaceChildren();
  });

  it("loads jest-dom matchers for identity component tests", () => {
    const marker = document.createElement("div");
    marker.setAttribute("data-testid", "identity-test-harness");
    document.body.append(marker);

    expect(marker).toBeInTheDocument();
    expect(accountDetailContract.linked_visitors[0]?.visitor).toBeNull();
  });

  it("encodes account search and sends the bearer token", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ items: [], total: 0, limit: 25, offset: 0 }),
    );

    await listAccounts("admin-token", {
      q: "jane+ops@example.com",
      limit: 25,
      offset: 0,
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/admin/accounts?q=jane%2Bops%40example.com&limit=25&offset=0",
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: "Bearer admin-token",
        }),
      }),
    );
  });

  it("encodes identifiers in all detail and invitation paths", async () => {
    fetchMock.mockImplementation(async () => jsonResponse({}));
    const unsafeId = "id/with spaces?#";

    await getAccount("admin-token", unsafeId);
    await updateAccount("admin-token", unsafeId, { display_name: "Jane" });
    await anonymizeAccount("admin-token", unsafeId);
    await deleteAccount("admin-token", unsafeId);
    await getVisitor("admin-token", unsafeId);
    await getVisitorConversation("admin-token", unsafeId, unsafeId);
    await resendInvitation("admin-token", unsafeId);
    await revokeInvitation("admin-token", unsafeId);
    await regenerateInvitation("admin-token", unsafeId);

    const paths = fetchMock.mock.calls.map(([url]) => String(url));
    expect(paths).toEqual([
      "/api/admin/accounts/id%2Fwith%20spaces%3F%23",
      "/api/admin/accounts/id%2Fwith%20spaces%3F%23",
      "/api/admin/accounts/id%2Fwith%20spaces%3F%23/anonymize",
      "/api/admin/accounts/id%2Fwith%20spaces%3F%23",
      "/api/admin/visitors/id%2Fwith%20spaces%3F%23",
      "/api/admin/visitors/id%2Fwith%20spaces%3F%23/conversations/id%2Fwith%20spaces%3F%23",
      "/api/admin/invitations/id%2Fwith%20spaces%3F%23/resend",
      "/api/admin/invitations/id%2Fwith%20spaces%3F%23/revoke",
      "/api/admin/invitations/id%2Fwith%20spaces%3F%23/resend",
    ]);
    expect(fetchMock.mock.calls[2]?.[1]).toEqual(
      expect.objectContaining({ method: "POST" }),
    );
    expect(fetchMock.mock.calls[3]?.[1]).toEqual(
      expect.objectContaining({ method: "DELETE" }),
    );
  });

  it("serializes list queries and account mutation bodies", async () => {
    fetchMock.mockImplementation(async () =>
      jsonResponse({ items: [], total: 0, limit: 50, offset: 100 }),
    );
    const query = { q: "desktop & edge", limit: 50, offset: 100 };

    await listVisitors("admin-token", query);
    await listInvitations("admin-token", query);
    await createAccount("admin-token", {
      email: "member@example.com",
      display_name: "Member",
      role: "user",
    });

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      "/api/admin/visitors?q=desktop+%26+edge&limit=50&offset=100",
    );
    expect(fetchMock.mock.calls[1]?.[0]).toBe(
      "/api/admin/invitations?q=desktop+%26+edge&limit=50&offset=100",
    );
    expect(fetchMock.mock.calls[2]?.[1]).toEqual(
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          email: "member@example.com",
          display_name: "Member",
          role: "user",
        }),
      }),
    );
  });

  it("returns undefined for successful no-content responses", async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));

    await expect(
      revokeInvitation("admin-token", "invitation-id"),
    ).resolves.toBeUndefined();
  });

  it("uses a safe API error message and preserves the response status", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ detail: "Account action is not permitted" }, 403),
    );

    await expect(getAccount("admin-token", "account-id")).rejects.toMatchObject({
      name: "IdentityApiError",
      message: "Account action is not permitted",
      status: 403,
    });
  });

  it("does not leak non-JSON error bodies", async () => {
    fetchMock.mockResolvedValue(
      new Response("upstream stack trace with internal data", { status: 502 }),
    );

    await expect(getAccount("admin-token", "account-id")).rejects.toMatchObject({
      message: "Request failed (502)",
      status: 502,
    });
  });
});
