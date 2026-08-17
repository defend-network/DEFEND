"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  AdminSession,
  loadAdminSession,
} from "@/lib/adminAuth";
import AdminLogin from "../../components/AdminLogin";
import SetupIntegrationsPanel from "../../components/setup/SetupIntegrationsPanel";

export default function SetupPage() {
  const [session, setSession] = useState<AdminSession | null>(null);
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    setSession(loadAdminSession());
    setChecking(false);
  }, []);

  if (checking) {
    return <p className="admin-loading">Checking access…</p>;
  }
  if (!session) {
    return <AdminLogin onSuccess={setSession} />;
  }
  return <SetupIntegrationsPanel session={session} />;
}