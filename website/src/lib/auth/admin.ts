import { redirect } from "next/navigation";

import { getActor } from "@/lib/auth/session";
import {
  can,
  canAccessModule,
  hasAnyAdminPermission,
  type ActorContext,
  type Permission,
  type ResourceScope,
} from "@/lib/policy/permissions";

export async function adminPageActor(
  permission: Permission,
  resource?: ResourceScope,
): Promise<{ actor: ActorContext; allowed: boolean }> {
  const actor = await getActor();
  if (!actor) redirect("/login?next=/admin");
  return {
    actor,
    allowed: resource
      ? can(actor, permission, resource)
      : canAccessModule(actor, permission),
  };
}

export async function adminPageAnyPermission(): Promise<{
  actor: ActorContext;
  allowed: boolean;
}> {
  const actor = await getActor();
  if (!actor) redirect("/login?next=/admin");
  return { actor, allowed: hasAnyAdminPermission(actor) };
}
