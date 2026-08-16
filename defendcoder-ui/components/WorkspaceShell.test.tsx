import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import WorkspaceShell from "./WorkspaceShell";


describe("DEFENDcoder workspace shell", () => {
  it("renders the repo-agnostic workspace navigation", () => {
    render(
      <WorkspaceShell
        account={{
          username: "consumer",
          role: "consumer",
        }}
        runtime={null}
        workspaces={[]}
      />
    );

    expect(screen.getByText("Projects")).toBeInTheDocument();
    expect(screen.getByText("Git Repos")).toBeInTheDocument();
    expect(screen.getByText("Workspaces")).toBeInTheDocument();
  });

  it("renders execution and review panes", () => {
    render(
      <WorkspaceShell
        account={{
          username: "consumer",
          role: "consumer",
        }}
        runtime={null}
        workspaces={[]}
      />
    );

    expect(screen.getByText("Terminal")).toBeInTheDocument();
    expect(screen.getByText("Tests")).toBeInTheDocument();
    expect(screen.getByText("Diff")).toBeInTheDocument();
    expect(screen.getByText("Logs")).toBeInTheDocument();
  });

  it("does not fabricate unavailable runtime values", () => {
    render(
      <WorkspaceShell
        account={{
          username: "consumer",
          role: "consumer",
        }}
        runtime={null}
        workspaces={[]}
      />
    );

    expect(screen.getByText("Unavailable")).toBeInTheDocument();

    const emDashes = screen.getAllByText("?");
    expect(emDashes.length).toBeGreaterThan(0);
  });

  it("shows admin navigation only to admins", () => {
    const { rerender } = render(
      <WorkspaceShell
        account={{
          username: "consumer",
          role: "consumer",
        }}
        runtime={null}
        workspaces={[]}
      />
    );

    expect(
      screen.queryByRole("link", { name: /admin/i })
    ).not.toBeInTheDocument();

    rerender(
      <WorkspaceShell
        account={{
          username: "admin",
          role: "admin",
        }}
        runtime={null}
        workspaces={[]}
      />
    );

    expect(
      screen.getByRole("link", { name: /admin/i })
    ).toBeInTheDocument();
  });

  it("renders known runtime values when provided", () => {
    render(
      <WorkspaceShell
        account={{
          username: "admin",
          role: "admin",
        }}
        runtime={{
          state: "ready",
          model: "Qwen/Qwen3-Coder-30B-A3B-Instruct",
          provider: "Vast.ai",
          context_used: null,
          context_limit: 8192,
        }}
        workspaces={[]}
      />
    );

    expect(screen.getByText("ready")).toBeInTheDocument();
    expect(
      screen.getByText("Qwen/Qwen3-Coder-30B-A3B-Instruct")
    ).toBeInTheDocument();
    expect(screen.getByText("Vast.ai")).toBeInTheDocument();
    expect(screen.getByText(/8192/)).toBeInTheDocument();
  });

  it("renders workspace names without assuming DEFEND-specific repos", () => {
    render(
      <WorkspaceShell
        account={{
          username: "consumer",
          role: "consumer",
        }}
        runtime={null}
        workspaces={[
          {
            workspace_id: "1",
            name: "customer-portal",
            repository_url: "https://github.com/example/customer-portal.git",
            default_branch: "main",
          },
        ]}
      />
    );

    expect(screen.getByText("customer-portal")).toBeInTheDocument();
    expect(
      screen.getByText("https://github.com/example/customer-portal.git")
    ).toBeInTheDocument();
  });
});

