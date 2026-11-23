export const PERMISSIONS = [
  "applications.view",
  "applications.review",
  "members.view",
  "members.manage",
  "members.roles",
  "chapters.view",
  "chapters.manage",
  "crm.view",
  "crm.manage",
  "facilities.view",
  "facilities.manage",
  "events.view",
  "events.manage",
  "events.checkin",
  "volunteers.view",
  "volunteers.manage",
  "documents.view",
  "documents.manage",
  "documents.download_sensitive",
  "cms.edit",
  "cms.publish",
  "communications.view",
  "communications.send",
  "programs.view",
  "finance.view",
  "finance.manage",
  "system.users",
  "system.audit",
  "system.settings",
  "exports.run",
] as const;

export type Permission = (typeof PERMISSIONS)[number];

export const ROLE_KEYS = [
  "owner",
  "national_admin",
  "chapter_admin",
  "staff",
  "volunteer_coordinator",
  "member",
] as const;

export type RoleKey = (typeof ROLE_KEYS)[number];

export type ScopeType = "global" | "chapter" | "self";

export type RoleAssignment = {
  roleKey: RoleKey;
  scopeType: ScopeType;
  scopeId: string | null;
};

export type ActorContext = {
  userId: string;
  displayName: string;
  email: string;
  roles: RoleAssignment[];
  mfaVerified: boolean;
};

export type ResourceScope = {
  chapterId?: string | null;
  ownerUserId?: string | null;
};

const GLOBAL_ROLES: RoleKey[] = ["owner", "national_admin"];

const ADMIN_PERMISSIONS: Permission[] = [
  "applications.view",
  "applications.review",
  "members.view",
  "members.manage",
  "members.roles",
  "chapters.view",
  "chapters.manage",
  "crm.view",
  "crm.manage",
  "facilities.view",
  "facilities.manage",
  "events.view",
  "events.manage",
  "events.checkin",
  "volunteers.view",
  "volunteers.manage",
  "documents.view",
  "documents.manage",
  "documents.download_sensitive",
  "cms.edit",
  "cms.publish",
  "communications.view",
  "communications.send",
  "programs.view",
  "finance.view",
  "finance.manage",
  "system.users",
  "system.audit",
  "system.settings",
  "exports.run",
];

export const ROLE_PERMISSIONS: Record<RoleKey, ReadonlySet<Permission>> = {
  owner: new Set(ADMIN_PERMISSIONS),
  national_admin: new Set(
    ADMIN_PERMISSIONS.filter(
      (permission) =>
        permission !== "system.users" && permission !== "system.settings",
    ),
  ),
  chapter_admin: new Set<Permission>([
    "applications.view",
    "applications.review",
    "members.view",
    "members.manage",
    "chapters.view",
    "events.view",
    "events.manage",
    "events.checkin",
    "volunteers.view",
    "volunteers.manage",
    "documents.view",
    "documents.manage",
  ]),
  staff: new Set<Permission>([
    "members.view",
    "chapters.view",
    "crm.view",
    "crm.manage",
    "events.view",
    "events.manage",
    "events.checkin",
    "volunteers.view",
    "volunteers.manage",
    "documents.view",
    "documents.manage",
    "communications.view",
    "programs.view",
  ]),
  volunteer_coordinator: new Set<Permission>([
    "members.view",
    "chapters.view",
    "events.view",
    "events.manage",
    "events.checkin",
    "volunteers.view",
    "volunteers.manage",
  ]),
  member: new Set<Permission>([]),
};

const MFA_REQUIRED_PERMISSIONS = new Set<Permission>([
  "applications.review",
  "members.manage",
  "members.roles",
  "chapters.manage",
  "crm.manage",
  "facilities.manage",
  "events.manage",
  "documents.manage",
  "documents.download_sensitive",
  "cms.publish",
  "communications.send",
  "finance.manage",
  "system.users",
  "system.settings",
  "exports.run",
]);

export class AuthorizationError extends Error {
  constructor(
    message = "You do not have permission to perform this action.",
    public readonly reason: "unauthenticated" | "forbidden" | "mfa_required" =
      "forbidden",
  ) {
    super(message);
    this.name = "AuthorizationError";
  }
}

export function isRoleKey(value: string): value is RoleKey {
  return (ROLE_KEYS as readonly string[]).includes(value);
}

export function roleRequiresMfa(roleKey: RoleKey): boolean {
  return roleKey !== "member";
}

export function actorRequiresMfa(actor: ActorContext): boolean {
  return actor.roles.some(
    (assignment) =>
      assignment.scopeType !== "self" && roleRequiresMfa(assignment.roleKey),
  );
}

export function hasGlobalRole(actor: ActorContext): boolean {
  return actor.roles.some(
    (assignment) =>
      assignment.scopeType === "global" &&
      GLOBAL_ROLES.includes(assignment.roleKey),
  );
}

export function hasAnyAdminPermission(actor: ActorContext): boolean {
  return actor.roles.some((assignment) => {
    if (assignment.scopeType === "self") return false;
    const permissions = ROLE_PERMISSIONS[assignment.roleKey];
    if (!permissions) return false;
    return ADMIN_PERMISSIONS.some((permission) => permissions.has(permission));
  });
}

export function chapterIdsForPermission(
  actor: ActorContext,
  permission: Permission,
): "all" | string[] {
  const chapterIds = new Set<string>();
  for (const assignment of actor.roles) {
    if (!ROLE_PERMISSIONS[assignment.roleKey]?.has(permission)) continue;
    if (assignment.scopeType === "global") return "all";
    if (assignment.scopeType === "chapter" && assignment.scopeId) {
      chapterIds.add(assignment.scopeId);
    }
  }
  return [...chapterIds];
}

export function canAccessModule(
  actor: ActorContext,
  permission: Permission,
): boolean {
  if (can(actor, permission)) return true;
  const chapterIds = chapterIdsForPermission(actor, permission);
  return chapterIds === "all" || chapterIds.length > 0;
}

export function scopedChapterIds(actor: ActorContext): "all" | string[] {
  if (hasGlobalRole(actor)) return "all";
  const ids = new Set<string>();
  for (const assignment of actor.roles) {
    if (assignment.scopeType === "chapter" && assignment.scopeId) {
      ids.add(assignment.scopeId);
    }
  }
  return [...ids];
}

export function canAccessChapter(
  actor: ActorContext,
  chapterId: string,
): boolean {
  const scope = scopedChapterIds(actor);
  return scope === "all" || scope.includes(chapterId);
}

export function can(
  actor: ActorContext | null,
  permission: Permission,
  resource?: ResourceScope,
): boolean {
  if (!actor) return false;

  if (MFA_REQUIRED_PERMISSIONS.has(permission) && !actor.mfaVerified) {
    return false;
  }

  for (const assignment of actor.roles) {
    const allowed = ROLE_PERMISSIONS[assignment.roleKey]?.has(permission);
    if (!allowed) continue;

    if (assignment.scopeType === "global") return true;

    if (assignment.scopeType === "chapter") {
      if (!assignment.scopeId) continue;
      if (!resource?.chapterId) continue;
      if (resource.chapterId === assignment.scopeId) return true;
    }

    if (assignment.scopeType === "self") {
      if (resource?.ownerUserId && resource.ownerUserId === actor.userId) {
        return true;
      }
    }
  }

  return false;
}

export function assertCan(
  actor: ActorContext | null,
  permission: Permission,
  resource?: ResourceScope,
): asserts actor is ActorContext {
  if (!actor) {
    throw new AuthorizationError("Sign in to continue.", "unauthenticated");
  }
  if (MFA_REQUIRED_PERMISSIONS.has(permission) && !actor.mfaVerified) {
    throw new AuthorizationError(
      "Multi-factor authentication is required for this action.",
      "mfa_required",
    );
  }
  if (!can(actor, permission, resource)) {
    throw new AuthorizationError();
  }
}
