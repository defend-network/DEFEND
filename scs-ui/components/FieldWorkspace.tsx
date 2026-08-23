"use client";
import {FormEvent,useEffect,useState} from "react";
import {ChatAnswer,FieldConceptContract,HistoryEntry,JobReadiness,chatHistory,fieldConcepts,jobChat,jobReadiness,jobTruth,recordReading} from "@/lib/fieldApi";

type FieldJob = {job_id:string};
type Turn = {role:"user"|"assistant";content:string};

export function FieldWorkspace(){
  const [jobs,setJobs]=useState<FieldJob[]>([]);
  const [jobId,setJobId]=useState<string>("");
  const [truth,setTruth]=useState<Record<string,unknown>|null>(null);
  const [readiness,setReadiness]=useState<JobReadiness|null>(null);
  const [turns,setTurns]=useState<Turn[]>([]);
  const [draft,setDraft]=useState("");
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState<string|null>(null);
  const [contract,setContract]=useState<FieldConceptContract|null>(null);
  const [reading,setReading]=useState({equipment_id:"",concept:"FIELD_SUPPLY_CFM",value:"",unit:"CFM",stage:"FINAL"});
  async function loadJobs(){try{const body=await jobTruthList();setJobs(body.jobs)}catch{setJobs([])}}
  async function loadContract(){try{setContract(await fieldConcepts())}catch{setContract(null)}}
  async function refresh(id:string){try{const[t,r,h]=await Promise.all([jobTruth(id),jobReadiness(id),chatHistory(id)]);setTruth(t);setReadiness(r);setTurns(historyToTurns(h.history))}catch(e){setError(e instanceof Error?e.message:"Failed to load field job")}}
  async function loadJob(id:string){setJobId(id);setError(null);await refresh(id)}
  useEffect(()=>{loadJobs();loadContract()},[]);
  const selectedConcept = contract?.concepts.find(c=>c.concept===reading.concept);
  function selectConcept(concept:string){const c=contract?.concepts.find(x=>x.concept===concept);setReading({...reading,concept,unit:c?.accepted_units[0]??"",equipment_id:c?.scope==="JOB"?"":reading.equipment_id})}
  async function send(e:FormEvent){e.preventDefault();if(!draft.trim()||!jobId||busy)return;const message=draft.trim();setTurns(prev=>[...prev,{role:"user",content:message}]);setDraft("");setBusy(true);try{const answer=await jobChat(jobId,message);setTurns(prev=>[...prev,{role:"assistant",content:answer.visible_answer||`Blocked: ${answer.blocked_claims.count} claim(s) — ${answer.blocked_claims.reasons.join("; ")||"no evidence"}`}]);await refresh(jobId)}catch(e){setError(e instanceof Error?e.message:"SCS AI request failed")}finally{setBusy(false)}}
  async function submitReading(e:FormEvent){e.preventDefault();if(!jobId||!reading.value)return;if(selectedConcept?.scope==="EQUIPMENT"&&!reading.equipment_id)return;try{await recordReading(jobId,{equipment_id:selectedConcept?.scope==="EQUIPMENT"?reading.equipment_id:null,concept:reading.concept,value:Number(reading.value),unit:reading.unit||null,stage:reading.stage});setReading({equipment_id:"",concept:"FIELD_SUPPLY_CFM",value:"",unit:"CFM",stage:"FINAL"});await refresh(jobId)}catch(e){setError(e instanceof Error?e.message:"Reading write failed")}}
  return <section className="field-workspace">
    <div className="section-title"><div><p className="eyebrow">Active job</p><h2>Field workstation</h2></div><select value={jobId} onChange={e=>loadJob(e.target.value)}><option value="">Select a field job</option>{jobs.map(job=><option key={job.job_id} value={job.job_id}>{job.job_id}</option>)}</select></div>
    {error&&<div className="model-banner" role="status"><strong>Error</strong><span>{error}</span></div>}
    {truth&&<div className="truth-grid">
      <article className="card"><h3>Equipment</h3><ul>{Array.isArray(truth.equipment)&&truth.equipment.map((item,index)=><li key={index}>{String((item as Record<string,unknown>).id||"UNKNOWN")} — {String((item as Record<string,unknown>).manufacturer||"UNKNOWN")} {String((item as Record<string,unknown>).model||"")} <span className="pill">{String((item as Record<string,unknown>).knowledge_coverage||"NO_OEM_SOURCE")}</span></li>)}{(!truth.equipment||(truth.equipment as unknown[]).length===0)&&<li>No equipment recorded</li>}</ul></article>
      <article className="card"><h3>Readings</h3><ul>{Object.entries((truth.readings as Record<string,unknown[]>)||{}).map(([key,entries])=><li key={key}>{key}: {entries.map(e=>`${String((e as Record<string,unknown>).value)} ${String((e as Record<string,unknown>).unit||"")} (${String((e as Record<string,unknown>).stage)})`).join(", ")}</li>)}{(!truth.readings||Object.keys(truth.readings as object).length===0)&&<li>No field readings recorded</li>}</ul></article>
    </div>}
    {jobId&&<article className="card"><h3>Record reading</h3>{contract?<form className="inline-form" onSubmit={submitReading}><label>Concept<select value={reading.concept} onChange={e=>selectConcept(e.target.value)}>{contract.concepts.map(c=><option key={c.concept} value={c.concept}>{c.concept}{c.scope==="JOB"?" (job)":""}</option>)}</select></label>{selectedConcept?.scope==="EQUIPMENT"&&<label>Equipment<input value={reading.equipment_id} onChange={e=>setReading({...reading,equipment_id:e.target.value})} placeholder="RTU-1"/></label>}<label>Value<input value={reading.value} onChange={e=>setReading({...reading,value:e.target.value})}/></label><label>Unit<select value={reading.unit} onChange={e=>setReading({...reading,unit:e.target.value})}>{(selectedConcept?.accepted_units??[]).map(u=><option key={u} value={u}>{u}</option>)}</select></label><label>Stage<select value={reading.stage} onChange={e=>setReading({...reading,stage:e.target.value})}><option>AS_FOUND</option><option>INTERMEDIATE</option><option>FINAL</option></select></label><button disabled={selectedConcept?.scope==="EQUIPMENT"&&!reading.equipment_id}>Save reading</button></form>:<p className="chat-placeholder">Reading entry unavailable — the server measurement contract could not be loaded.</p>}</article>}
    {readiness&&<div className="truth-grid">
      <article className="card"><h3>Ready to leave? <span className="pill">{readiness.ready_to_leave.readiness}</span></h3><ul>{readiness.ready_to_leave.reasons.map(r=><li key={r.key}><strong>{r.severity}</strong> {r.label}{r.action&&<span> → {r.action}</span>}</li>)}{readiness.ready_to_leave.reasons.length===0&&<li>No outstanding items.</li>}</ul></article>
      <article className="card"><h3>Report readiness <span className="pill">{readiness.report_readiness.readiness}</span></h3><ul>{Object.entries(readiness.report_readiness.summary).map(([k,v])=><li key={k}>{k}: {v}</li>)}</ul></article>
    </div>}
    {jobId&&<div className="assistant-panel">
      <div className="chat-log">{turns.map((turn,index)=><div className={`chat-bubble ${turn.role}`} key={index}><p>{turn.content}</p></div>)}{busy&&<div className="chat-bubble assistant"><p>Thinking…</p></div>}</div>
      <form className="chat-form" onSubmit={send}><label>Ask SCS AI about this job<input value={draft} onChange={e=>setDraft(e.target.value)} disabled={busy} placeholder="e.g. What do I measure next?"/></label><button disabled={busy||!draft.trim()}>Send</button></form>
    </div>}
  </section>;
}

function historyToTurns(history:HistoryEntry[]):Turn[]{
  const turns:Turn[]=[];
  for(const entry of history){turns.push({role:"user",content:entry.question});if(entry.answer)turns.push({role:"assistant",content:entry.answer})}
  return turns;
}

async function jobTruthList():Promise<{jobs:FieldJob[]}>{const {api}=await import("@/lib/api");return api<{jobs:FieldJob[]}>("/api/scs/field/jobs")}
