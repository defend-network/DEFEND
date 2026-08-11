<!-- DEFEND-AI-INGEST: EXCLUDE -->

# DEFEND Admin Identity UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Users & Roles placeholder with searchable Accounts, Visitors, and Invitations tools, add role-safe management actions, and apply the approved Prominent admin background.

**Architecture:** Keep the existing `AdminWorkstation` as navigation/composition only. A focused `components/admin/identity/` feature owns tab state, typed API queries, tables, detail views, and invitation actions; shared types and fetch functions live in a dedicated client module.

**Tech Stack:** Next.js 14 App Router, React 18, TypeScript, CSS, Lucide React, Vitest, React Testing Library.

## Global Constraints

- Use top tabs in this order: Accounts, Visitors, Invitations.
- Admins create/manage end users only; owner-only administrator actions are hidden and still enforced by the API.
- Accounts and Visitors have separate datasets and detail experiences.
- Search includes identity fields, visitor IDs, IP, browser/platform/device, status, and linked account where applicable.
- Conversation content is visible to admins and owner through audited API calls.
- The admin/owner background uses the approved Prominent treatment while content surfaces preserve readable contrast.
- Do not expose raw passwords, invitation hashes, session hashes, reusable tokens, or raw authentication cookies.
- Complete both earlier implementation plans first.

---

## File map

- Create `defend-ui-v2/lib/identityApi.ts`: types and API functions.
- Create `defend-ui-v2/components/admin/identity/UsersRolesPanel.tsx`: tab composition and shared toolbar.
- Create `AccountsTab.tsx`, `VisitorsTab.tsx`, and `InvitationsTab.tsx`: bounded lists and states.
- Create `IdentityDetailDrawer.tsx`: selected account/visitor detail and conversation inspection.
- Create `InviteAccountModal.tsx`: role-safe account/invitation creation.
- Modify `AdminWorkstation.tsx`: render the feature and pass `AdminSession`.
- Modify `globals.css`: identity workspace styles and Prominent background.
- Modify `package.json`/lock: add Vitest, jsdom, and React Testing Library.
- Create frontend tests under `defend-ui-v2/components/admin/identity/__tests__/`.

### Task 1: Add typed identity API client and test harness

**Files:**
- Create: `defend-ui-v2/lib/identityApi.ts`
- Modify: `defend-ui-v2/package.json`
- Modify: `defend-ui-v2/package-lock.json`
- Create: `defend-ui-v2/vitest.config.ts`
- Test: `defend-ui-v2/lib/identityApi.test.ts`

**Interfaces:**
- Produces: `AccountSummary`, `VisitorSummary`, `InvitationSummary`, `AccountDetail`, `VisitorDetail`, `Page<T>`.
- Produces: `listAccounts`, `getAccount`, `createAccount`, `updateAccount`, `listVisitors`, `getVisitor`, `getVisitorConversation`, `listInvitations`, `resendInvitation`, `revokeInvitation`, and `regenerateInvitation`.

- [ ] **Step 1: Add Vitest dependencies and write a failing URL/authorization test**

```ts
const fetchMock = vi.fn();
vi.stubGlobal("fetch", fetchMock);
const ok = (body: unknown) => new Response(JSON.stringify(body), {status: 200, headers: {"Content-Type":"application/json"}});

it("encodes account search and sends the bearer token", async () => {
  fetchMock.mockResolvedValue(ok({items: [], total: 0}));
  await listAccounts("admin-token", {q: "jane+ops@example.com", limit: 25, offset: 0});
  expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("q=jane%2Bops%40example.com"), expect.objectContaining({headers: expect.objectContaining({Authorization: "Bearer admin-token"})}));
});
```

- [ ] **Step 2: Run test and verify RED**

Run: `C:\Program Files\nodejs\npm.cmd test --prefix defend-ui-v2 -- --run lib/identityApi.test.ts`
Expected: FAIL because the client module/test script does not exist.

- [ ] **Step 3: Implement shared typed request helpers and API functions**

```ts
export type Page<T> = { items: T[]; total: number; limit: number; offset: number };
export type IdentityQuery = { q: string; limit: number; offset: number };

export async function listAccounts(token: string, query: IdentityQuery): Promise<Page<AccountSummary>> {
  return identityJson(`/api/admin/accounts?${new URLSearchParams({q: query.q, limit: String(query.limit), offset: String(query.offset)})}`, token);
}
```

- [ ] **Step 4: Run client tests and type check**

Run: `C:\Program Files\nodejs\npm.cmd test --prefix defend-ui-v2 -- --run lib/identityApi.test.ts`
Run: `C:\Program Files\nodejs\npx.cmd tsc --noEmit -p defend-ui-v2/tsconfig.json`
Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add defend-ui-v2/lib/identityApi.ts defend-ui-v2/lib/identityApi.test.ts defend-ui-v2/package.json defend-ui-v2/package-lock.json defend-ui-v2/vitest.config.ts
git commit -m "Add typed identity admin client"
```

### Task 2: Build Accounts, Visitors, and Invitations tabs

**Files:**
- Create: `defend-ui-v2/components/admin/identity/UsersRolesPanel.tsx`
- Create: `defend-ui-v2/components/admin/identity/AccountsTab.tsx`
- Create: `defend-ui-v2/components/admin/identity/VisitorsTab.tsx`
- Create: `defend-ui-v2/components/admin/identity/InvitationsTab.tsx`
- Modify: `defend-ui-v2/components/AdminWorkstation.tsx`
- Test: `defend-ui-v2/components/admin/identity/__tests__/UsersRolesPanel.test.tsx`

**Interfaces:**
- Consumes: `AdminSession` and identity API list functions.
- Produces: `<UsersRolesPanel session={session} />` with tabs, debounced search, loading, error, empty, pagination, refresh, and selection callbacks.

- [ ] **Step 1: Write failing tab/search rendering tests**

```tsx
import * as identityApi from "@/lib/identityApi";

const ownerSession = {username:"chairman@defend-network.org", role:"owner" as const, token:"owner-token", loggedInAt:new Date().toISOString(), expiresAt:new Date(Date.now()+60_000).toISOString()};
const user = userEvent.setup();
vi.mock("@/lib/identityApi", () => ({listAccounts: vi.fn().mockResolvedValue({items:[],total:0,limit:50,offset:0}), listVisitors: vi.fn().mockResolvedValue({items:[],total:0,limit:50,offset:0}), listInvitations: vi.fn().mockResolvedValue({items:[],total:0,limit:50,offset:0})}));

it("keeps Accounts and Visitors separate and searches only the active tab", async () => {
  render(<UsersRolesPanel session={ownerSession} />);
  expect(screen.getByRole("tab", {name: /Accounts/})).toHaveAttribute("aria-selected", "true");
  await user.click(screen.getByRole("tab", {name: /Visitors/}));
  await user.type(screen.getByRole("searchbox"), "203.0.113.8");
  await waitFor(() => expect(identityApi.listVisitors).toHaveBeenCalledWith(ownerSession.token, expect.objectContaining({q:"203.0.113.8"})));
});
```

- [ ] **Step 2: Run component test and verify RED**

Run: `C:\Program Files\nodejs\npm.cmd test --prefix defend-ui-v2 -- --run components/admin/identity/__tests__/UsersRolesPanel.test.tsx`
Expected: FAIL because the components do not exist.

- [ ] **Step 3: Implement accessible top-tab workspace and tables**

Use native tab semantics, one searchbox, 300 ms debounce, `AbortController` or request generation guards, 50-row pages, and quiet semantic tables. Accounts columns: account, role, status, created, last access, recent IP, devices, sessions. Visitors columns: visitor ID, linked account, client, recent IP, first seen, last seen, visits, sessions/activity. Invitations columns: recipient, role, creator, delivery, status, created, expires.

- [ ] **Step 4: Run component tests and type check**

Run: `C:\Program Files\nodejs\npm.cmd test --prefix defend-ui-v2 -- --run components/admin/identity/__tests__/UsersRolesPanel.test.tsx`
Run: `C:\Program Files\nodejs\npx.cmd tsc --noEmit -p defend-ui-v2/tsconfig.json`
Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add defend-ui-v2/components/admin/identity defend-ui-v2/components/AdminWorkstation.tsx
git commit -m "Add identity administration tabs"
```

### Task 3: Add invitation actions and audited detail views

**Files:**
- Create: `defend-ui-v2/components/admin/identity/IdentityDetailDrawer.tsx`
- Create: `defend-ui-v2/components/admin/identity/InviteAccountModal.tsx`
- Modify: `defend-ui-v2/components/admin/identity/UsersRolesPanel.tsx`
- Modify: `defend-ui-v2/components/admin/identity/AccountsTab.tsx`
- Modify: `defend-ui-v2/components/admin/identity/VisitorsTab.tsx`
- Modify: `defend-ui-v2/components/admin/identity/InvitationsTab.tsx`
- Test: `defend-ui-v2/components/admin/identity/__tests__/IdentityActions.test.tsx`

**Interfaces:**
- Consumes: account/visitor detail and invitation mutation API functions.
- Produces: account creation modal, owner-only admin-role option, disable actions, copy/resend/revoke/regenerate actions, and audited conversation loading on explicit click.

- [ ] **Step 1: Write failing role and explicit-content-access tests**

```tsx
const adminSession = {username:"admin@defend-network.org", role:"admin" as const, token:"admin-token", loggedInAt:new Date().toISOString(), expiresAt:new Date(Date.now()+60_000).toISOString()};
const user = userEvent.setup();

it("does not offer administrator role to an admin", async () => {
  render(<InviteAccountModal session={adminSession} onClose={vi.fn()} onCreated={vi.fn()} />);
  expect(screen.queryByRole("option", {name:"Administrator"})).not.toBeInTheDocument();
});

it("loads conversation content only after explicit selection", async () => {
  render(<IdentityDetailDrawer session={adminSession} visitorId="vis_1" />);
  expect(identityApi.getVisitorConversation).not.toHaveBeenCalled();
  await user.click(await screen.findByRole("button", {name:/Open conversation/}));
  expect(identityApi.getVisitorConversation).toHaveBeenCalledTimes(1);
});
```

- [ ] **Step 2: Run action tests and verify RED**

Run: `C:\Program Files\nodejs\npm.cmd test --prefix defend-ui-v2 -- --run components/admin/identity/__tests__/IdentityActions.test.tsx`
Expected: FAIL because detail/action components do not exist.

- [ ] **Step 3: Implement actions, disclosure, and feedback states**

Show raw invitation links only immediately after creation/regeneration and label them sensitive. Use the Clipboard API only after a user click. Require confirmation text for disable, revoke, anonymize, and delete actions; owner-only actions render only for `session.role === "owner"`. Conversation content appears in a bounded modal/drawer after the audited endpoint returns.

- [ ] **Step 4: Run all identity component tests**

Run: `C:\Program Files\nodejs\npm.cmd test --prefix defend-ui-v2 -- --run components/admin/identity`
Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add defend-ui-v2/components/admin/identity
git commit -m "Add role-safe identity management actions"
```

### Task 4: Apply Prominent background and complete integration verification

**Files:**
- Modify: `defend-ui-v2/app/globals.css`
- Modify: `defend-ui-v2/components/AdminWorkstation.tsx`
- Test: `defend-ui-v2/components/admin/identity/__tests__/AdminWorkstationIdentity.test.tsx`

**Interfaces:**
- Consumes: complete `UsersRolesPanel` feature.
- Produces: approved Prominent background and responsive identity workspace at desktop and mobile widths.

- [ ] **Step 1: Write failing integration test**

```tsx
vi.mock("@/lib/adminAuth", async () => {
  const actual = await vi.importActual<typeof import("@/lib/adminAuth")>("@/lib/adminAuth");
  return {...actual, loadAdminSession: () => ({username:"chairman@defend-network.org", role:"owner", token:"owner-token", loggedInAt:new Date().toISOString(), expiresAt:new Date(Date.now()+60_000).toISOString()})};
});

const user = userEvent.setup();

it("renders the identity workspace instead of the placeholder", async () => {
  render(<AdminWorkstation />);
  await user.click(screen.getByRole("button", {name:"Users & Roles"}));
  expect(await screen.findByRole("tab", {name:/Accounts/})).toBeVisible();
  expect(screen.queryByText(/Single-operator mode/)).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run integration test and verify RED**

Run: `C:\Program Files\nodejs\npm.cmd test --prefix defend-ui-v2 -- --run components/admin/identity/__tests__/AdminWorkstationIdentity.test.tsx`
Expected: FAIL until integration replaces the placeholder.

- [ ] **Step 3: Implement the Prominent CSS and responsive identity styles**

Change `.admin-flag-bg` to the approved stronger treatment: reduce the image veil to approximately `rgba(6,10,18,0.25)` at the top and `rgba(6,10,18,0.48)` at the bottom, use layer opacity approximately `0.85`, and restore image saturation to approximately `0.95`. Keep nav/card/table surfaces at or above their current dark translucency and verify readable text contrast.

- [ ] **Step 4: Run complete verification**

Run: `C:\Program Files\nodejs\npm.cmd test --prefix defend-ui-v2 -- --run`
Run: `C:\Program Files\nodejs\npm.cmd run build --prefix defend-ui-v2`
Run: `python -m pytest tests -v`
Run: `python -m compileall -q .`
Run: `git diff --check`
Expected: all tests PASS, production build exits 0, Python compilation exits 0, and no diff errors.

- [ ] **Step 5: Commit**

```powershell
git add defend-ui-v2/app/globals.css defend-ui-v2/components/AdminWorkstation.tsx defend-ui-v2/components/admin/identity/__tests__/AdminWorkstationIdentity.test.tsx
git commit -m "Complete admin identity workstation"
```
