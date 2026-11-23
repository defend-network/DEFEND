// @vitest-environment jsdom

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/ui/badge";

describe("design system primitives", () => {
  it("renders a primary button with accessible text", () => {
    render(<Button>Apply</Button>);
    const button = screen.getByRole("button", { name: "Apply" });
    expect(button).toBeInTheDocument();
    expect(button).toHaveClass("bg-red-600");
  });

  it("renders as a link when asChild is used", () => {
    render(
      <Button asChild>
        <a href="/apply">Apply</a>
      </Button>,
    );
    const link = screen.getByRole("link", { name: "Apply" });
    expect(link).toHaveAttribute("href", "/apply");
  });

  it("shows truthful status labels", () => {
    render(<StatusBadge status="in_development" />);
    expect(screen.getByText("In development")).toBeInTheDocument();
  });
});
