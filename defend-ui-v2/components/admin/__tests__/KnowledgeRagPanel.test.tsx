import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";

import { KnowledgeRagPanel } from "../KnowledgeRagPanel";
import * as api from "@/lib/api";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, adminRagIngest: vi.fn(), adminRagJob: vi.fn(), adminRagStatus: vi.fn() };
});

beforeEach(() => {
  vi.mocked(api.adminRagIngest).mockReset();
  vi.mocked(api.adminRagJob).mockReset();
  vi.mocked(api.adminRagStatus).mockReset();
  vi.mocked(api.adminRagStatus).mockResolvedValue({ ready: true, provider: "vLLM - Qwen/Qwen3-Embedding-0.6B" });
});

it("shows the managed embedding provider and disables ingestion when unavailable", async () => {
  vi.mocked(api.adminRagStatus).mockResolvedValue({
    ready: false,
    provider: "vLLM - Qwen/Qwen3-Embedding-0.6B",
  });

  render(<KnowledgeRagPanel token="owner-token" documents={[]} onDocumentsChanged={vi.fn()} />);

  expect(await screen.findByText("vLLM - Qwen/Qwen3-Embedding-0.6B")).toBeVisible();
  expect(screen.getByText(/embedding service is unavailable/i)).toBeVisible();
  expect(screen.getByRole("button", { name: "Index 0 documents" })).toBeDisabled();
});

it("indexes selected documents, displays partial results, and refreshes corpus", async () => {
  const refresh = vi.fn().mockResolvedValue(undefined);
  vi.mocked(api.adminRagIngest).mockResolvedValue({
    job_id: "ragjob_1", status: "queued", total: 2, indexed: 0, skipped: 0, failed: 0, files: [],
  });
  vi.mocked(api.adminRagJob).mockResolvedValue({
    job_id: "ragjob_1", status: "complete", total: 2, indexed: 1, skipped: 0, failed: 1,
    files: [
      { name: "a.pdf", document_id: "doc_a", status: "indexed", chunks_added: 4, chunks_updated: 0 },
      { name: "b.docx", document_id: "doc_b", status: "failed", chunks_added: 0, chunks_updated: 0, error: "Could not extract text" },
    ],
  });
  const user = userEvent.setup();
  render(<KnowledgeRagPanel token="owner-token" documents={[]} onDocumentsChanged={refresh} pollIntervalMs={1} />);
  await screen.findByText("vLLM - Qwen/Qwen3-Embedding-0.6B");

  await user.upload(screen.getByLabelText("Choose PDF or DOCX files"), [
    new File(["%PDF"], "a.pdf", { type: "application/pdf" }),
    new File(["PK"], "b.docx", { type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document" }),
  ]);
  await user.click(screen.getByRole("button", { name: "Index 2 documents" }));

  expect(await screen.findByText("Could not extract text")).toBeVisible();
  expect(screen.getByText("1 indexed")).toBeVisible();
  expect(screen.getByText("1 failed")).toBeVisible();
  await waitFor(() => expect(refresh).toHaveBeenCalled());
});

it("rejects more than twenty files before calling the API", async () => {
  const user = userEvent.setup();
  render(<KnowledgeRagPanel token="owner-token" documents={[]} onDocumentsChanged={vi.fn()} />);
  await screen.findByText("vLLM - Qwen/Qwen3-Embedding-0.6B");
  const files = Array.from({ length: 21 }, (_, index) => new File(["%PDF"], `${index}.pdf`, { type: "application/pdf" }));

  await user.upload(screen.getByLabelText("Choose PDF or DOCX files"), files);

  expect(screen.getByText(/at most 20/i)).toBeVisible();
  expect(api.adminRagIngest).not.toHaveBeenCalled();
});
