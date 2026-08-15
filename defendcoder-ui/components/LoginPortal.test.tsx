import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import LoginPortal from "./LoginPortal";


describe("DEFENDcoder login portal", () => {
  beforeEach(() => {
    vi.restoreAllMocks();

    Object.defineProperty(window, "location", {
      writable: true,
      value: { href: "/" }
    });
  });

  it("renders admin and consumer login forms", () => {
    render(<LoginPortal />);

    expect(
      screen.getByRole("form", { name: /admin login/i })
    ).toBeInTheDocument();

    expect(
      screen.getByRole("form", { name: /consumer login/i })
    ).toBeInTheDocument();
  });

  it("uses real password inputs", () => {
    render(<LoginPortal />);

    const passwords = screen.getAllByLabelText(/password/i);

    expect(passwords).toHaveLength(2);
    expect(passwords[0]).toHaveAttribute("type", "password");
    expect(passwords[1]).toHaveAttribute("type", "password");
  });

  it("contains no crown decoration", () => {
    const { container } = render(<LoginPortal />);

    expect(container.querySelector("[data-crown]")).toBeNull();
  });

  it("submits the selected role to the login API", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        account: {
          username: "admin",
          role: "admin"
        },
        csrf_token: "csrf-test"
      })
    });

    vi.stubGlobal("fetch", fetchMock);

    render(<LoginPortal />);

    const adminForm = screen.getByRole(
      "form",
      { name: /admin login/i }
    );

    fireEvent.change(
      screen.getByLabelText("Admin username"),
      { target: { value: "admin" } }
    );

    fireEvent.change(
      screen.getByLabelText("Admin password"),
      { target: { value: "password" } }
    );

    fireEvent.submit(adminForm);

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(1);
    });

    const [, request] = fetchMock.mock.calls[0];

    expect(JSON.parse(request.body)).toEqual({
      username: "admin",
      password: "password",
      role: "admin"
    });
  });

  it("uses credentialed requests for server-side session cookies", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        account: {
          username: "consumer",
          role: "consumer"
        },
        csrf_token: "csrf-test"
      })
    });

    vi.stubGlobal("fetch", fetchMock);

    render(<LoginPortal />);

    fireEvent.change(
      screen.getByLabelText("Consumer username"),
      { target: { value: "consumer" } }
    );

    fireEvent.change(
      screen.getByLabelText("Consumer password"),
      { target: { value: "password" } }
    );

    fireEvent.submit(
      screen.getByRole(
        "form",
        { name: /consumer login/i }
      )
    );

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalled();
    });

    const [, request] = fetchMock.mock.calls[0];

    expect(request.credentials).toBe("include");
  });

  it("shows the same generic error for failed authentication", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        json: async () => ({
          detail: "invalid credentials"
        })
      })
    );

    render(<LoginPortal />);

    fireEvent.change(
      screen.getByLabelText("Consumer username"),
      { target: { value: "someone" } }
    );

    fireEvent.change(
      screen.getByLabelText("Consumer password"),
      { target: { value: "wrong" } }
    );

    fireEvent.submit(
      screen.getByRole(
        "form",
        { name: /consumer login/i }
      )
    );

    expect(
      await screen.findByRole("alert")
    ).toHaveTextContent("Invalid username or password.");
  });
});
