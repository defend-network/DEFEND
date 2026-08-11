import { expect, it, vi } from "vitest";

import { activateAccount, activationStatus } from "@/lib/api";

it("sends activation credentials only in JSON bodies on fixed API paths", async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(new Response(JSON.stringify({ status: "invalid" }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ account: { status: "active" } }), { status: 200 }));
  vi.stubGlobal("fetch", fetchMock);
  const token = "invite_body-only-secret";

  await activationStatus(token);
  await activateAccount(token, "a sufficiently long password");

  expect(fetchMock).toHaveBeenNthCalledWith(
    1,
    "/api/activate/status",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ token }),
    }),
  );
  expect(fetchMock).toHaveBeenNthCalledWith(
    2,
    "/api/activate",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ token, password: "a sufficiently long password" }),
    }),
  );
  for (const [url] of fetchMock.mock.calls) {
    expect(url).not.toContain(token);
  }
});
