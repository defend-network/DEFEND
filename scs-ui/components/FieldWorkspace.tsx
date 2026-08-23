"use client";
import {FormEvent,useEffect,useState} from "react";
import {ChatAnswer,ReadinessResult,jobChat,jobReadiness,jobTruth} from "@/lib/fieldApi";

type FieldJob = {job_id:string};

export function FieldWorkspace(){
  const [jobs,setJobs]=useState<FieldJob[]>([]);
  const [jobId,setJobId]=useState<string>("");
  const [truth,setTruth]=useState<Record<string,unknown>|null>(null);
  const [readiness,setReadiness]=useState<ReadinessResult|null>(null);
  const [turns,setTurns]=useState<Array<{role:"user"|"assistant";content:string}>>([]);
  const [draft,setDraft]=useState("");
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState<string|null>(null);
  async function loadJobs(){try{const body=await jobTruthList();setJobs(body.jobs)}catch{setJobs([])}}
  async function loadJob(id:string){setJobId(id);setError(null);try{const[t,r]=await Promise.all([jobTruth(id),jobReadiness(id)]);setTruth(t);setReadiness(r);setTurns([])}catch(e){setError(e instanceof Error?e.message:"Failed to load field job")}}
  useEffect(()=>{loadJobs()},[]);
  async function send(e:FormEvent){e.preventDefault();if(!draft.trim()||!jobId||busy)return;const message=draft.trim();const next=[...turns,{role:"user" as const,content:message}];setTurns(next);setDraft("");setBusy(true);try{const answer=await jobChat(jobId,message);setTurns([...next,{role:"assistant" as const,content:answer.visible_answer||`Blocked: ${answer.blocked_claims.count} claim(s) — ${answer.blocked_claims.reasons.join("; ")||"no evidence"}`}]);await loadJob(jobId)}catch(e){setError(e instanceof Error?e.message:"SCS AI request failed")}finally{setBusy(false)}}
  return <section className="field-workspace">
    <div className="section-title"><div><p className="eyebrow">Active job</p><h2>Field workstation</h2></div><select value={jobId} onChange={e=>loadJob(e.target.value)}><option value="">Select a field job</option>{jobs.map(job=><option key={job.job_id} value={job.job_id}>{job.job_id}</option>)}</select></div>
    {error&&<div className="model-banner" role="status"><strong>Error</strong><span>{error}</span></div>}
    {truth&&<div className="truth-grid">
      <article className="card"><h3>Equipment</h3><ul>{Array.isArray(truth.equipment)&&truth.equipment.map((item,index)=><li key={index}>{String((item as Record<string,unknown>).id||"UNKNOWN")} — {String((item as Record<string,unknown>).manufacturer||"UNKNOWN")} {String((item as Record<string,unknown>).model||"")}</li>)}{(!truth.equipment||(truth.equipment as unknown[]).length===0)&&<li>No equipment recorded</li>}</ul></article>
      <article className="card"><h3>Readings</h3><ul>{Object.entries((truth.readings as Record<string,unknown[]>)||{}).map(([key,entries])=><li key={key}>{key}: {entries.map(e=>`${(e as Record<string,unknown>).value} (${(e as Record<string,unknown>).stage})`).join(", ")}</li>)}{(!truth.readings||Object.keys(truth.readings as object).length===0)&&<li>No field readings recorded</li>}</ul></article>
    </div>}
    {readiness&&<article className="card"><h3>Ready to leave? <span className="pill">{readiness.readiness}</span></h3><ul>{readiness.reasons.map(r=><li key={r.key}><strong>{r.severity}</strong> {r.label}{r.action&&<span> → {r.action}</span>}</li>)}{readiness.reasons.length===0&&<li>No outstanding items.</li>}</ul></article>}
    {jobId&&<div className="assistant-panel">
      <div className="chat-log">{turns.map((turn,index)=><div className={`chat-bubble ${turn.role}`} key={index}><p>{turn.content}</p></div>)}{busy&&<div className="chat-bubble assistant"><p>Thinking…</p></div>}</div>
      <form className="chat-form" onSubmit={send}><label>Ask SCS AI about this job<input value={draft} onChange={e=>setDraft(e.target.value)} disabled={busy} placeholder="e.g. What do I measure next?"/></label><button disabled={busy||!draft.trim()}>Send</button></form>
    </div>}
  </section>;
}

async function jobTruthList():Promise<{jobs:FieldJob[]}>{const {api}=await import("@/lib/api");return api<{jobs:FieldJob[]}>("/api/scs/field/jobs")}
