export type AccountRole = "owner" | "admin" | "user";
export type AccountStatus =
  | "pending_activation"
  | "active"
  | "disabled"
  | "anonymized";
export type InvitationStatus = "pending" | "consumed" | "expired" | "revoked";

export type Page<T> = {
  items: T[];
  total: number;
  limit: number;
  offset: number;
};

export type IdentityQuery = {
  q: string;
  limit: number;
  offset: number;
};

export type ClientMetadata = {
  browser?: string;
  platform?: string;
  device?: string;
  language?: string;
  [key: string]: unknown;
};

export type LinkedAccount = {
  account_id: string;
  email: string;
  display_name: string;
  role: AccountRole;
  status: AccountStatus;
};

export type AccountRecord = LinkedAccount & {
  created_at: string;
  last_access_at: string | null;
  updated_at?: string;
};

export type AccountSummary = AccountRecord & {
  visitor_count: number;
  active_session_count: number;
  recent_ip: string | null;
  device_count: number;
};

export type VisitorSummary = {
  visitor_id: string;
  fingerprint_hmac: string;
  first_seen: string;
  last_seen: string;
  seen_count: number;
  client_meta: ClientMetadata;
  session_count: number;
  conversation_count: number;
  message_count: number;
  recent_ip: string | null;
  device_count: number;
  linked_account: LinkedAccount | null;
};

export type InvitationCreator = {
  account_id: string;
  email: string;
  display_name: string;
};

export type InvitationSummary = {
  invitation_id: string;
  account_id: string;
  email: string;
  intended_role: Exclude<AccountRole, "owner">;
  created_at: string;
  expires_at: string;
  consumed_at?: string | null;
  revoked_at?: string | null;
  status: InvitationStatus;
  delivery_status: string;
  delivery_error: string | null;
  creator?: InvitationCreator;
  activation_url?: string;
  delivery?: {
    delivered: boolean;
    provider_message_id: string | null;
    error: string | null;
  };
};

export type AccountInvitationHistory = {
  invitation_id: string;
  account_id: string;
  email: string;
  intended_role: Exclude<AccountRole, "owner">;
  created_by: string;
  created_at: string;
  expires_at: string;
  consumed_at: string | null;
  revoked_at: string | null;
  delivery_status: string;
  delivery_error: string | null;
};

export type AccountSession = {
  session_id: string;
  created_at: string;
  last_seen_at: string;
  expires_at: string;
  revoked_at: string | null;
};

export type LoginEvent = {
  event_id: string;
  outcome: string;
  created_at: string;
};

export type VisitorRecord = {
  visitor_id: string;
  fingerprint_hmac: string;
  first_seen: string;
  last_seen: string;
  seen_count: number;
  client_meta: ClientMetadata;
};

export type VisitorSession = {
  session_id: string;
  created_at: string;
  last_seen: string;
  client_meta: ClientMetadata;
};

export type ConnectionEvent = {
  connection_id: string;
  visitor_id: string;
  session_id: string;
  ip_address: string;
  user_agent: string;
  browser: string;
  platform: string;
  device: string;
  language: string;
  fingerprint_hmac: string;
  observed_at: string;
};

export type ConversationSummary = {
  conversation_id: string;
  title?: string;
  created_at?: string;
  updated_at?: string;
  message_count?: number;
  [key: string]: unknown;
};

export type UsageEvent = {
  event_id: string;
  visitor_id: string;
  conversation_id: string | null;
  request_id: string | null;
  event_type: string;
  route: string | null;
  model: string | null;
  research_status: string | null;
  evidence_count: number | null;
  status: string | null;
  created_at: string;
  metadata: Record<string, unknown>;
};

export type VisitorDetail = {
  visitor: VisitorRecord;
  sessions: VisitorSession[];
  connections: ConnectionEvent[];
  conversations: ConversationSummary[];
  usage_events: UsageEvent[];
  linked_account: LinkedAccount | null;
};

export type AccountLinkedVisitorDetail = {
  visitor_id: string;
  linked_at: string;
  last_seen_at: string;
  visitor: VisitorRecord | null;
  sessions: VisitorSession[];
  connections: ConnectionEvent[];
  conversations: ConversationSummary[];
  usage_events: UsageEvent[];
  telemetry: {
    recent_ip: string | null;
    device_count: number;
  };
};

export type AccountDetail = {
  account: AccountRecord;
  sessions: AccountSession[];
  login_events: LoginEvent[];
  invitations: AccountInvitationHistory[];
  linked_visitors: AccountLinkedVisitorDetail[];
};

export type ConversationMessage = {
  message_id: string;
  seq: number;
  role: string;
  content: string;
  created_at: string;
};

export type VisitorConversation = {
  visitor_id: string;
  conversation_id: string;
  messages: ConversationMessage[];
};

export type CreateAccountInput = {
  email: string;
  display_name: string;
  role: Exclude<AccountRole, "owner">;
};

export type UpdateAccountInput = {
  display_name?: string;
  role?: Exclude<AccountRole, "owner">;
  status?: "active" | "disabled";
};

export type AccountMutationResponse = {
  account: AccountRecord;
};

export type InvitationMutationResponse = {
  invitation: InvitationSummary;
};

export type CreateAccountResponse = AccountMutationResponse &
  InvitationMutationResponse;

const API_BASE = (process.env.NEXT_PUBLIC_DEFEND_API_BASE ?? "").replace(
  /\/$/,
  "",
);

export class IdentityApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "IdentityApiError";
    this.status = status;
  }
}

function encodePath(value: string): string {
  return encodeURIComponent(value);
}

function pagePath(path: string, query: IdentityQuery): string {
  const params = new URLSearchParams({
    q: query.q,
    limit: String(query.limit),
    offset: String(query.offset),
  });
  return `${path}?${params}`;
}

function safeErrorMessage(status: number, text: string): string {
  try {
    const parsed = JSON.parse(text) as { detail?: unknown };
    if (typeof parsed.detail === "string" && parsed.detail.trim()) {
      return parsed.detail.trim().slice(0, 240);
    }
  } catch {
    // Non-JSON upstream error bodies may contain internal details.
  }
  return `Request failed (${status})`;
}

async function identityJson<T>(
  path: string,
  token: string,
  init: RequestInit = {},
): Promise<T> {
  const headers: Record<string, string> = {
    Accept: "application/json",
    Authorization: `Bearer ${token}`,
  };
  if (init.body !== undefined) {
    headers["Content-Type"] = "application/json";
  }

  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers,
  });
  const text = await response.text();

  if (!response.ok) {
    throw new IdentityApiError(
      response.status,
      safeErrorMessage(response.status, text),
    );
  }
  if (response.status === 204 || text.length === 0) {
    return undefined as T;
  }
  try {
    return JSON.parse(text) as T;
  } catch {
    throw new IdentityApiError(
      response.status,
      "Identity service returned an invalid response",
    );
  }
}

export function listAccounts(
  token: string,
  query: IdentityQuery,
): Promise<Page<AccountSummary>> {
  return identityJson(pagePath("/api/admin/accounts", query), token);
}

export function getAccount(
  token: string,
  accountId: string,
): Promise<AccountDetail> {
  return identityJson(`/api/admin/accounts/${encodePath(accountId)}`, token);
}

export function createAccount(
  token: string,
  input: CreateAccountInput,
): Promise<CreateAccountResponse> {
  return identityJson("/api/admin/accounts", token, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function updateAccount(
  token: string,
  accountId: string,
  input: UpdateAccountInput,
): Promise<AccountMutationResponse> {
  return identityJson(`/api/admin/accounts/${encodePath(accountId)}`, token, {
    method: "PATCH",
    body: JSON.stringify(input),
  });
}

export function listVisitors(
  token: string,
  query: IdentityQuery,
): Promise<Page<VisitorSummary>> {
  return identityJson(pagePath("/api/admin/visitors", query), token);
}

export function getVisitor(
  token: string,
  visitorId: string,
): Promise<VisitorDetail> {
  return identityJson(`/api/admin/visitors/${encodePath(visitorId)}`, token);
}

export function getVisitorConversation(
  token: string,
  visitorId: string,
  conversationId: string,
): Promise<VisitorConversation> {
  return identityJson(
    `/api/admin/visitors/${encodePath(visitorId)}/conversations/${encodePath(conversationId)}`,
    token,
  );
}

export function listInvitations(
  token: string,
  query: IdentityQuery,
): Promise<Page<InvitationSummary>> {
  return identityJson(pagePath("/api/admin/invitations", query), token);
}

export function resendInvitation(
  token: string,
  invitationId: string,
): Promise<InvitationMutationResponse> {
  return identityJson(
    `/api/admin/invitations/${encodePath(invitationId)}/resend`,
    token,
    { method: "POST" },
  );
}

export function revokeInvitation(
  token: string,
  invitationId: string,
): Promise<InvitationMutationResponse> {
  return identityJson(
    `/api/admin/invitations/${encodePath(invitationId)}/revoke`,
    token,
    { method: "POST" },
  );
}

export function regenerateInvitation(
  token: string,
  invitationId: string,
): Promise<InvitationMutationResponse> {
  return resendInvitation(token, invitationId);
}
