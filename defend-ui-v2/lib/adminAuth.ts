export type AdminRole = "admin" | "owner";

export type AdminSession = {
  username: string;
  role: AdminRole;
  token: string;
  loggedInAt: string;
  expiresAt: string;
};

const STORAGE_KEY = "defend_admin_session_v2";

export function loadAdminSession(): AdminSession | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as AdminSession;
    if (!parsed?.token || !parsed?.role || !parsed?.expiresAt) return null;
    if (Date.parse(parsed.expiresAt) <= Date.now()) {
      sessionStorage.removeItem(STORAGE_KEY);
      return null;
    }
    return parsed;
  } catch {
    return null;
  }
}

export function saveAdminSession(s: AdminSession) {
  sessionStorage.setItem(STORAGE_KEY, JSON.stringify(s));
}

export function clearAdminSession() {
  sessionStorage.removeItem(STORAGE_KEY);
}

export function isOwner(s: AdminSession | null): boolean {
  return s?.role === "owner";
}
