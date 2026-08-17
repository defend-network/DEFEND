import { cookies } from "next/headers";

import WorkspaceShell from "@/components/WorkspaceShell";
import { loadWorkspaceData } from "@/app/workspace/load-workspace";


export default async function WorkspacePage() {
  const cookieStore = await cookies();
  const cookieHeader = cookieStore.toString() || null;

  const base =
    process.env.DEFENDCODER_INTERNAL_API_URL ??
    "http://127.0.0.1:8301";

  const data = await loadWorkspaceData(fetch, cookieHeader, base);

  if (!data) {
    return (
      <main className="workspace-auth-fallback">
        <h1>Session required</h1>
        <a href="/">Return to login</a>
      </main>
    );
  }

  return (
    <WorkspaceShell
      account={data.account}
      runtime={data.runtime}
      workspaces={data.workspaces}
    />
  );
}