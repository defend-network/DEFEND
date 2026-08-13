import { fireEvent, render, screen } from "@testing-library/react";
import { vi } from "vitest";
import { expect, test } from "vitest";
import { Login } from "../Login";

test("shows the employee-only Sunshine login and submits credentials", () => {
  const submit = vi.fn();
  render(<Login onLogin={submit} />);
  expect(screen.getByRole("heading", {name:/Sunshine Climate Solutions/i})).toBeInTheDocument();
  expect(screen.queryByText(/create account|customer login/i)).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText(/email or username/i), {target:{value:"tech"}});
  fireEvent.change(screen.getByLabelText(/password/i), {target:{value:"secret"}});
  fireEvent.click(screen.getByRole("button", {name:/sign in/i}));
  expect(submit).toHaveBeenCalledWith("tech", "secret");
});
