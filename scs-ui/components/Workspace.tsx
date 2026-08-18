import {AiAssistant} from "./AiAssistant";
import {Calculators} from "./Calculators";
import {CustomerWorkspace} from "./CustomerWorkspace";
import {EmployeeAdmin} from "./EmployeeAdmin";
import {JobCreator,JobWorkspace} from "./JobWorkspace";
import {ModelStatus} from "./ModelStatus";
type Employee = {display_name:string;roles:string[];permissions:string[]};
type Job = {job_id:string;job_type:string;status:string;job_date:string;priority:string;customer_id:string;site_id:string};
type Metric = {state:string;value:number|null};

const jobNames:Record<string,string> = {"hvac-service":"HVAC service","preventive-maintenance":"Preventive maintenance","installation-replacement":"Installation / replacement","tab-testing":"TAB testing","tab-reporting":"TAB reporting"};

export function Workspace({employee,jobs,summary,onRefresh=()=>{}}:{employee:Employee;jobs:Job[];summary?:{total_spend:Metric;average_payment_days:Metric};onRefresh?:()=>void}) {
  const canManage = employee.permissions.includes("manage_employees");
  const canManageJobs = employee.permissions.includes("manage_jobs");
  const jobContext = jobs.length ? `Assigned jobs: ${jobs.map(job=>`${job.job_type} on ${job.job_date} (${job.status})`).join("; ")}.` : "No jobs assigned to this employee right now.";
  return <div className="workspace">
    <header><div><p className="eyebrow">Sunshine Climate Solutions</p><h1>Good day, {employee.display_name}</h1></div><div className="header-right"><span className="status-dot">Secure workspace</span><ModelStatus/></div></header>
    <nav aria-label="Primary"><a href="#jobs">Assigned jobs</a><a href="#assistant">AI assistant</a><a href="#calculators">Calculators</a><a href="#customers">Customers</a>{canManage && <a href="#employees">Employee admin</a>}</nav>
    <section id="jobs"><div className="section-title"><div><p className="eyebrow">Today & upcoming</p><h2>Assigned jobs</h2></div><span>{jobs.length} active</span></div>
      {canManageJobs&&<JobCreator onCreated={onRefresh}/>}
      <div className="job-grid">{jobs.length ? jobs.map(job=><article className="job-card" key={job.job_id}><span className="pill">{job.status}</span><h3>{jobNames[job.job_type] ?? job.job_type}</h3><p>{job.job_date} · {job.priority} priority</p><JobWorkspace jobId={job.job_id} onUpdated={onRefresh} canManage={canManageJobs}/></article>) : <div className="empty">No assigned work right now.</div>}</div>
    </section>
    <section id="assistant"><div className="section-title"><div><p className="eyebrow">SCS AI</p><h2>AI assistant</h2></div><span>grounded in your assigned work</span></div><AiAssistant jobContext={jobContext}/></section>
    <section id="calculators"><div className="section-title"><div><p className="eyebrow">Field math</p><h2>Calculators</h2></div><span>no invented inputs</span></div><Calculators/></section>
    {summary && <section className="metrics"><article><span>Total spend</span><strong>{summary.total_spend.state === "not_available" ? "Not available" : summary.total_spend.value}</strong></article><article><span>Average payment time</span><strong>{summary.average_payment_days.state === "not_available" ? "Not available" : summary.average_payment_days.value}</strong></article></section>}
    {employee.permissions.includes("view_customers")&&<CustomerWorkspace canEdit={employee.permissions.includes("edit_customers")}/>} {canManage&&<EmployeeAdmin/>}
  </div>;
}