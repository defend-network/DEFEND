"use client";
import {useEffect,useState} from "react";
import {KnowledgeStatus,knowledgeDiscover,knowledgeStatus} from "@/lib/fieldApi";

export function KnowledgePanel(){
  const [status,setStatus]=useState<KnowledgeStatus|null>(null);
  const [discovered,setDiscovered]=useState<Array<Record<string,unknown>>>([]);
  const [error,setError]=useState<string|null>(null);
  async function load(){try{setStatus(await knowledgeStatus())}catch{setError("Knowledge not available")}}
  async function discover(){try{const body=await knowledgeDiscover();setDiscovered(body.documents)}catch{setError("Discovery failed")}}
  useEffect(()=>{load()},[]);
  return <section className="knowledge-panel">
    <div className="section-title"><div><p className="eyebrow">Private library</p><h2>Knowledge</h2></div>{status&&<span className={`pill ${status.configured?"ok":""}`}>{status.state}</span>}</div>
    {error&&<div className="model-banner" role="status"><strong>Knowledge</strong><span>{error}</span></div>}
    {status&&<div className="truth-grid">
      <article className="card"><h3>Index</h3><ul><li>Discovered: {status.discovered}</li><li>Owner approved: {status.owner_approved}</li><li>Indexed: {status.indexed}</li><li>Blocked: {status.blocked}</li></ul></article>
      <article className="card"><h3>Documents</h3><ul>{status.documents.map((doc,index)=><li key={index}>{String((doc as Record<string,unknown>).title||"UNKNOWN")} <span className="pill">{String((doc as Record<string,unknown>).source_type||"UNKNOWN")}</span></li>)}{status.documents.length===0&&<li>No documents indexed</li>}</ul></article>
    </div>}
    <button onClick={discover}>Discover documents</button>
    {discovered.length>0&&<article className="card"><h3>Discovered</h3><ul>{discovered.map((doc,index)=><li key={index}>{String((doc as Record<string,unknown>).filename)} — {String((doc as Record<string,unknown>).source_type||"UNKNOWN")} <span className="pill">DISCOVERED</span></li>)}</ul></article>}
  </section>;
}
