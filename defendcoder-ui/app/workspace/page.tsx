import WorkspaceShell from "@/components/WorkspaceShell";


type SessionResponse = {
  account: {
    username: string;
    role: "admin" | "consumer";
  };
};

type WorkspaceResponse = {
  workspaces: Array<{
    workspace_id: string;
    name: string;
    repository_url?: string | null;
    default_branch?: string | null;
  }>;
};


async function loadWorkspaceData() {
  const base =
    process.env.DEFENDCODER_INTERNAL_API_URL ??
    "http://127.0.0.1:8301";

  const sessionResponse = await fetch(
    `${base}/v1/auth/session`,
    {
      cache: "no-store",
    }
  );

  if (!sessionResponse.ok) {
    return null;
  }

  const session =
    (await sessionResponse.json()) as SessionResponse;

  const workspaceResponse = await fetch(
    `${base}/v1/workspaces`,
    {
      cache: "no-store",
    }
  );

  const workspaces =
    workspaceResponse.ok
      ? ((await workspaceResponse.json()) as WorkspaceResponse).workspaces
      : [];

  return {
    account: session.account,
    workspaces,
  };
}


export default async function WorkspacePage() {
  const data = await loadWorkspaceData();

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
      runtime={null}
      workspaces={data.workspaces}
    />
  );
}
