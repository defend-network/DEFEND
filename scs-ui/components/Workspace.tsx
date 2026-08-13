import {CustomerWorkspace} from "./CustomerWorkspace";
import {EmployeeAdmin} from "./EmployeeAdmin";
import {JobCreator,JobWorkspace} from "./JobWorkspace";
type Employee = {display_name:string;roles:string[];permissions:string[]};
type Job = {job_id:string;job_type:string;status:string;job_date:string;priority:string;customer_id:string;site_id:string};
type Metric = {state:string;value:number|null};

const jobNames:Record<string,string> = {"hvac-service":"HVAC service","preventive-maintenance":"Preventive maintenance","installation-replacement":"Installation / replacement","tab-testing":"TAB testing","tab-reporting":"TAB reporting"};

export function Workspace({employee,jobs,summary,onRefresh=()=>{}}:{employee:Employee;jobs:Job[];summary?:{total_spend:Metric;average_payment_days:Metric};onRefresh?:()=>void}) {
  const canManage = employee.permissions.includes("manage_employees");
  const canManageJobs = employee.permissions.includes("manage_jobs");
  return <div className="workspace">
    <header><div><p className="eyebrow">Sunshine Climate Solutions</p><h1>Good day, {employee.display_name}</h1></div><div className="status-dot">Secure workspace</div></header>
    <nav aria-label="Primary"><a href="#jobs">Assigned jobs</a><a href="#customers">Customers</a>{canManage && <a href="#employees">Employee admin</a>}</nav>
    <section id="jobs"><div className="section-title"><div><p className="eyebrow">Today & upcoming</p><h2>Assigned jobs</h2></div><span>{jobs.length} active</span></div>
      {canManageJobs&&<JobCreator onCreated={onRefresh}/>}
      <div className="job-grid">{jobs.length ? jobs.map(job=><article className="job-card" key={job.job_id}><span className="pill">{job.status}</span><h3>{jobNames[job.job_type] ?? job.job_type}</h3><p>{job.job_date} · {job.priority} priority</p><JobWorkspace jobId={job.job_id} onUpdated={onRefresh} canManage={canManageJobs}/></article>) : <div className="empty">No assigned work right now.</div>}</div>
    </section>
    {summary && <section className="metrics"><article><span>Total spend</span><strong>{summary.total_spend.state === "not_available" ? "Not available" : summary.total_spend.value}</strong></article><article><span>Average payment time</span><strong>{summary.average_payment_days.state === "not_available" ? "Not available" : summary.average_payment_days.value}</strong></article></section>}
    {employee.permissions.includes("view_customers")&&<CustomerWorkspace canEdit={employee.permissions.includes("edit_customers")}/>} {canManage&&<EmployeeAdmin/>}
  </div>;
}
