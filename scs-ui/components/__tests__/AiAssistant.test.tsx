import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { AiAssistant } from "../AiAssistant";

function jsonResponse(body: unknown, status = 200) {
  return { ok: status < 400, status, json: async () => body };
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({})));
});

test("shows an honest not-configured banner instead of a fake answer", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      jsonResponse(
        {
          state: "not_configured",
          reply: null,
          model: null,
          provider: null,
          detail: "Model not configured",
        },
        503,
      ),
    ),
  );
  render(<AiAssistant />);
  fireEvent.change(screen.getByPlaceholderText(/what readings/i), {
    target: { value: "What is a traverse?" },
  });
  fireEvent.click(screen.getByRole("button", { name: /send/i }));
  await waitFor(() =>
    expect(screen.getByRole("status")).toHaveTextContent(/model not configured/i),
  );
  expect(screen.queryByText(/traverse.*answer/i)).not.toBeInTheDocument();
  expect(screen.queryByText(/you should/i)).not.toBeInTheDocument();
});

test("renders the model reply when the model answers", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      jsonResponse({
        state: "answered",
        reply: "Take velocity readings across the duct.",
        model: "Qwen3",
        provider: "openai_compatible",
        detail: null,
      }),
    ),
  );
  render(<AiAssistant />);
  fireEvent.change(screen.getByPlaceholderText(/what readings/i), {
    target: { value: "Traverse steps?" },
  });
  fireEvent.click(screen.getByRole("button", { name: /send/i }));
  await waitFor(() =>
    expect(screen.getByText(/Take velocity readings across the duct\./)).toBeInTheDocument(),
  );
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
});

test("offers no send button state when the service is unreachable", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => {
      throw new TypeError("Failed to fetch");
    }),
  );
  render(<AiAssistant />);
  fireEvent.change(screen.getByPlaceholderText(/what readings/i), {
    target: { value: "hello" },
  });
  fireEvent.click(screen.getByRole("button", { name: /send/i }));
  await waitFor(() =>
    expect(screen.getByRole("status")).toHaveTextContent(/unreachable/i),
  );
});