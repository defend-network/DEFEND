import { afterEach, expect, it, vi } from "vitest";

import { adminRagIngest, adminRagJob } from "@/lib/api";

afterEach(() => vi.unstubAllGlobals());

it("uploads permanent RAG files as authenticated multipart", async () => {
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(JSON.stringify({ job_id: "ragjob_1", status: "queued", total: 1, indexed: 0, skipped: 0, failed: 0, files: [] }), {
      status: 202,
      headers: { "Content-Type": "application/json" },
    }),
  );
  vi.stubGlobal("fetch", fetchMock);

  await adminRagIngest("owner-token", [new File(["%PDF"], "a.pdf", { type: "application/pdf" })]);

  const [, init] = fetchMock.mock.calls[0];
  expect(init.headers).toEqual({ Authorization: "Bearer owner-token" });
  expect(init.body).toBeInstanceOf(FormData);
  expect(init.credentials).toBe("include");
});

it("encodes a permanent RAG job id", async () => {
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(JSON.stringify({ job_id: "job/one", status: "complete", total: 0, indexed: 0, skipped: 0, failed: 0, files: [] }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }),
  );
  vi.stubGlobal("fetch", fetchMock);

  await adminRagJob("owner-token", "job/one");

  expect(fetchMock.mock.calls[0][0]).toContain("job%2Fone");
});
