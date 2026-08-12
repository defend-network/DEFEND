import { afterEach, expect, it, vi } from "vitest";

import { sendChat, uploadFiles } from "@/lib/api";

afterEach(() => {
  vi.unstubAllGlobals();
});

it("does not expose an upstream HTML error body in chat", async () => {
  const sentinel = "private-cloudflare-upstream-detail";
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(`<!DOCTYPE html><p>${sentinel}</p>`, {
        status: 502,
        headers: { "Content-Type": "text/html" },
      }),
    ),
  );

  const request = sendChat({
    message: "hello",
    conversation_id: "conversation-1",
    document_ids: [],
  });

  await expect(request).rejects.toThrow("Request failed (502)");
  await expect(request).rejects.not.toThrow(sentinel);
});

it("does not expose an upstream upload error body", async () => {
  const sentinel = "private-upload-proxy-detail";
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(sentinel, {
        status: 503,
        headers: { "Content-Type": "text/plain" },
      }),
    ),
  );

  const request = uploadFiles(
    [new File(["test"], "test.txt", { type: "text/plain" })],
    "conversation-1",
  );

  await expect(request).rejects.toThrow("Request failed (503)");
  await expect(request).rejects.not.toThrow(sentinel);
});
