/**
 * Organization roles as the UI uses them (API_SPECIFICATION §24, backend `permissions.py`).
 *
 * For usability only (PHASE_01C_PLAN §4.7): these decide which buttons are shown. The API
 * authorizes every action itself; a hidden button is never the protection.
 */

export const ROLES = ["owner", "admin", "manager", "analyst", "viewer"] as const;
export type Role = (typeof ROLES)[number];

const RANK: Readonly<Record<Role, number>> = {
  owner: 5,
  admin: 4,
  manager: 3,
  analyst: 2,
  viewer: 1,
};

export const ROLE_LABELS: Readonly<Record<Role, string>> = {
  owner: "Owner",
  admin: "Admin",
  manager: "Manager",
  analyst: "Analyst",
  viewer: "Viewer",
};

export const ROLE_DESCRIPTIONS: Readonly<Record<Role, string>> = {
  owner: "Full control, including other owners.",
  admin: "Manages members, invitations, settings and connections.",
  manager: "Manages connections and linked accounts, and plans campaign strategies.",
  analyst: "Views data and plans campaign strategies.",
  viewer: "Views data.",
};

export function isRole(value: string): value is Role {
  return (ROLES as readonly string[]).includes(value);
}

/** A readable label; unknown values (a newer API) are shown as they are. */
export function roleLabel(role: string): string {
  return isRole(role) ? ROLE_LABELS[role] : role;
}

/** Owners and admins manage members and invitations (`members.manage`). */
export function canManageMembers(role: string): boolean {
  return role === "owner" || role === "admin";
}

/** Owners and admins change organization settings (`organization.update`). */
export function canUpdateOrganization(role: string): boolean {
  return role === "owner" || role === "admin";
}

/** Only owners grant or remove the owner role; nobody assigns a role above their own. */
export function canAssign(actorRole: string, targetRole: string): boolean {
  if (!isRole(actorRole) || !isRole(targetRole)) return false;
  if (targetRole === "owner") return actorRole === "owner";
  return RANK[actorRole] >= RANK[targetRole];
}

/** Roles the actor may give to someone (in invitations and role changes), highest first. */
export function assignableRoles(actorRole: string): Role[] {
  if (!canManageMembers(actorRole)) return [];
  return ROLES.filter((role) => canAssign(actorRole, role));
}

/** Whether the actor may change or remove a member who currently has `memberRole`. */
export function canManageMember(actorRole: string, memberRole: string): boolean {
  return canManageMembers(actorRole) && canAssign(actorRole, memberRole);
}

/** Owners, admins and managers connect platforms and link accounts (`connections.manage`). */
export function canManageConnections(role: string): boolean {
  return role === "owner" || role === "admin" || role === "manager";
}

/** Everyone but viewers creates and changes campaign strategies (`strategies.manage`, Q-8-7). */
export function canManageStrategies(role: string): boolean {
  return isRole(role) && role !== "viewer";
}

/** Everyone but viewers drafts and edits creatives and uploads images (`creatives.manage`). */
export function canManageCreatives(role: string): boolean {
  return canManageStrategies(role);
}

/** Owners, admins and managers approve, reject and archive creatives (`creatives.approve`). */
export function canApproveCreatives(role: string): boolean {
  return role === "owner" || role === "admin" || role === "manager";
}

/** Owners, admins and managers request changes to campaigns (`actions.request`, Q-10A-3). */
export function canRequestChanges(role: string): boolean {
  return role === "owner" || role === "admin" || role === "manager";
}

/** Owners and admins approve or reject changes (`actions.approve`, Q-10A-3). */
export function canApproveChanges(role: string): boolean {
  return role === "owner" || role === "admin";
}

/** Owners and admins pause all changes, set the rules and allow changes per connection. */
export function canManageChangeSettings(role: string): boolean {
  return canApproveChanges(role);
}

/** Phase 12: only owners switch autopilot on and set its policy; anyone who may request
 * changes can stop it. */
export function canManageAutopilot(role: string): boolean {
  return role === "owner";
}
