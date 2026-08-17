import { render, screen } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { Workspace } from "../Workspace";

const employee = {display_name:"Taylor", roles:["read_only"], permissions:[]};

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(async () => ({ok:false,status:503,json:async()=>({})})));
});

test("ordinary employee sees assigned work on a compact workspace without technician levels", () => {
  render(<Workspace employee={employee} jobs={[{job_id:"scs_job_1",job_type:"hvac-service",status:"scheduled",job_date:"2026-08-13",priority:"normal",customer_id:"c",site_id:"s"}]} />);
  expect(screen.getByText("HVAC service")).toBeInTheDocument();
  expect(screen.getByText(/scheduled/i)).toBeInTheDocument();
  expect(screen.queryByText(/technician level/i)).not.toBeInTheDocument();
  expect(screen.queryByRole("link", {name:/employee admin/i})).not.toBeInTheDocument();
  expect(screen.queryByRole("button", {name:/add customer/i})).not.toBeInTheDocument();
});

test("authorized navigation and unavailable financial metrics are explicit", () => {
  render(<Workspace employee={{...employee,roles:["owner"],permissions:["manage_employees","manage_jobs","view_customers","edit_customers","view_financials","view_technician_level"]}} jobs={[]} summary={{total_spend:{state:"not_available",value:null},average_payment_days:{state:"not_available",value:null}}} />);
  expect(screen.getByRole("link", {name:/employee admin/i})).toBeInTheDocument();
  expect(screen.getByRole("button", {name:/create service job/i})).toBeInTheDocument();
  expect(screen.getByRole("button", {name:/load employees/i})).toBeInTheDocument();
  expect(screen.getByRole("button", {name:/send invitation/i})).toBeInTheDocument();
  expect(screen.getByRole("button", {name:/add equipment/i})).toBeInTheDocument();
  expect(screen.getByRole("heading", {name:/customers/i})).toBeInTheDocument();
  expect(screen.getAllByText("Not available")).toHaveLength(2);
});
