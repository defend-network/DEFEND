"use client";
import {FormEvent,useEffect,useState} from "react";
import {api} from "@/lib/api";
type Visit={visit_id:string;work_performed:string;findings:string|null;recommendations:string|null;readings_summary:string|null};
type Note={note_id:string;body:string;visibility:string;author_id:string;created_at:string};
export function JobWorkspace({jobId,onUpdated,canManage=false}:{jobId:string;onUpdated:()=>void;canManage?:boolean}){
  const[work,setWork]=useState("");const[note,setNote]=useState("");const[employee,setEmployee]=useState("");
  const[visits,setVisits]=useState<Visit[]>([]);const[notes,setNotes]=useState<Note[]>([]);
  async function loadReadback(){try{const[visitBody,noteBody]=await Promise.all([api<{visits:Visit[]}>(`/api/scs/jobs/${jobId}/visits`),api<{notes:Note[]}>(`/api/scs/jobs/${jobId}/notes`)]);setVisits(visitBody.visits);setNotes(noteBody.notes)}catch{}}
  useEffect(()=>{loadReadback()},[jobId]);
  async function status(value:string){await api(`/api/scs/jobs/${jobId}/status`,{method:"POST",body:JSON.stringify({status:value})});onUpdated()}
  async function visit(e:FormEvent){e.preventDefault();await api(`/api/scs/jobs/${jobId}/visits`,{method:"POST",body:JSON.stringify({work_performed:work})});setWork("");await loadReadback()}
  async function addNote(e:FormEvent){e.preventDefault();await api(`/api/scs/jobs/${jobId}/notes`,{method:"POST",body:JSON.stringify({body:note,visibility:"operational"})});setNote("");await loadReadback()}
  async function assign(){await api(`/api/scs/jobs/${jobId}/assignments`,{method:"POST",body:JSON.stringify({employee_id:employee,assignment_role:"technician"})});setEmployee("")}
  async function classify(){await api(`/api/scs/jobs/${jobId}/classifications`,{method:"POST",body:JSON.stringify({code:"potential-member",source:"manual"})})}
  return <section className="action-panel" aria-label="Job actions"><div><button onClick={()=>status("in-progress")}>Start work</button> <button onClick={()=>status("completed")}>Complete</button></div>
    {canManage&&<div className="inline-form"><label>Employee ID<input value={employee} onChange={e=>setEmployee(e.target.value)}/></label><button onClick={assign}>Assign technician</button><button onClick={classify}>Potential member</button></div>}
    <form onSubmit={visit}><label>Work performed<input value={work} onChange={e=>setWork(e.target.value)}/></label><button>Add visit</button></form>
    <form onSubmit={addNote}><label>Operational note<input value={note} onChange={e=>setNote(e.target.value)}/></label><button>Add note</button></form>
    {visits.length>0&&<div className="readback"><h4>Visits</h4><ul>{visits.map(visit=><li key={visit.visit_id}><strong>{visit.work_performed}</strong>{visit.findings&&<span> · {visit.findings}</span>}{visit.readings_summary&&<span> · readings: {visit.readings_summary}</span>}</li>)}</ul></div>}
    {notes.length>0&&<div className="readback"><h4>Notes</h4><ul>{notes.map(item=><li key={item.note_id}><strong>{item.body}</strong><span className="pill"> {item.visibility}</span></li>)}</ul></div>}
  </section>;
}

export function JobCreator({onCreated}:{onCreated:()=>void}){const[customer,setCustomer]=useState("");const[site,setSite]=useState("");async function create(e:FormEvent){e.preventDefault();await api("/api/scs/jobs",{method:"POST",body:JSON.stringify({customer_id:customer,site_id:site,job_type:"hvac-service",job_date:new Date().toISOString().slice(0,10)})});setCustomer("");setSite("");onCreated()}return <form className="inline-form" onSubmit={create}><label>Customer ID<input value={customer} onChange={e=>setCustomer(e.target.value)}/></label><label>Site ID<input value={site} onChange={e=>setSite(e.target.value)}/></label><button>Create service job</button></form>}