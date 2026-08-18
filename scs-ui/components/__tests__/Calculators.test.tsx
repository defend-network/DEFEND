import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { Calculators } from "../Calculators";

const schema = {
  ok: true,
  items: [
    {
      name: "cfm_from_velocity_area",
      formula: "CFM = velocity (ft/min) × area (ft²)",
      inputs: { velocity_fpm: "number > 0", area_sqft: "number > 0" },
    },
    {
      name: "pressure_convert",
      formula: "1 in. w.c. = 248.84 Pa",
      inputs: { value: "number ≥ 0", from_unit: "'inwc' or 'pa'" },
    },
  ],
};

function jsonResponse(body: unknown, status = 200) {
  return { ok: status < 400, status, json: async () => body };
}

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        const payload = JSON.parse(String(init.body));
        if (payload.calculation === "cfm_from_velocity_area")
          return jsonResponse({
            ok: true,
            calculation: "cfm_from_velocity_area",
            formula: "CFM = velocity (ft/min) × area (ft²)",
            result: { cfm: 1200, velocity_fpm: 400, area_sqft: 3 },
            errors: [],
          });
        return jsonResponse({
          ok: false,
          calculation: payload.calculation,
          result: null,
          errors: ["value must be ≥ 0"],
        });
      }
      return jsonResponse(schema);
    }),
  );
});

test("runs a real calculation and shows the computed values", async () => {
  render(<Calculators />);
  const velocity = await screen.findByLabelText(/velocity fpm/);
  fireEvent.change(velocity, { target: { value: "400" } });
  fireEvent.change(screen.getByLabelText(/area sqft/), { target: { value: "3" } });
  fireEvent.click(screen.getByRole("button", { name: /calculate/i }));
  await waitFor(() => expect(screen.getByText("1200")).toBeInTheDocument());
  expect(screen.getByText(/CFM = velocity/)).toBeInTheDocument();
});

test("surfaces input errors instead of inventing a result", async () => {
  render(<Calculators />);
  const select = await screen.findByLabelText(/^calculation$/i);
  fireEvent.change(select, { target: { value: "pressure_convert" } });
  fireEvent.change(await screen.findByLabelText(/value/), {
    target: { value: "-5" },
  });
  fireEvent.change(screen.getByLabelText(/from unit/), {
    target: { value: "inwc" },
  });
  fireEvent.click(screen.getByRole("button", { name: /calculate/i }));
  await waitFor(() =>
    expect(screen.getByRole("status")).toHaveTextContent(/value must be ≥ 0/i),
  );
});