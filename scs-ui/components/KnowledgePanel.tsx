"use client";
import {useEffect,useState} from "react";
import {KnowledgeStatus,knowledgeApprove,knowledgeBlock,knowledgeDiscover,knowledgeStatus} from "@/lib/fieldApi";

type Discovery = Record<string,unknown>;

export function KnowledgePanel(){
  const [status,setStatus]=useState<KnowledgeStatus|null>(null);
  const [error,setError]=useState<string|null>(null);
  async function load(){try{setStatus(await knowledgeStatus())}catch{setError("Knowledge not available")}}
  async function discover(){try{await knowledgeDiscover();await load()}catch{setError("Discovery failed")}}
  async function approve(discoveryId:string){try{await knowledgeApprove({discovery_id:discoveryId});await load()}catch{setError("Approval failed")}}
  async function block(discoveryId:string){try{await knowledgeBlock(discoveryId);await load()}catch{setError("Block failed")}}
  useEffect(()=>{load()},[]);
  const discovery = (status?.discovery ?? []) as Discovery[];
  return <section className="knowledge-panel">
    <div className="section-title"><div><p className="eyebrow">Private library</p><h2>Knowledge</h2></div>{status&&<span className={`pill ${status.configured?"ok":""}`}>{status.state}</span>}</div>
    {error&&<div className="model-banner" role="status"><strong>Knowledge</strong><span>{error}</span></div>}
    <button onClick={discover}>Discover documents</button>
    {status&&<div className="truth-grid">
      <article className="card"><h3>Index</h3><ul><li>Discovered: {status.discovered}</li><li>Owner approved: {status.owner_approved}</li><li>Indexed: {status.indexed}</li><li>Blocked: {status.blocked}</li></ul></article>
    </div>}
    {discovery.length>0&&<article className="card"><h3>Discovered candidates</h3><table className="data-table"><thead><tr><th>File</th><th>Type</th><th>SHA</th><th>State</th><th>Actions</th></tr></thead><tbody>{discovery.map(doc=><tr key={String(doc.discovery_id)}><td>{String(doc.filename)}</td><td>{String(doc.candidate_source_type||"UNKNOWN")}</td><td>{String(doc.file_sha256||"").slice(0,10)}</td><td><span className="pill">{String(doc.state)}</span></td><td>{(doc.state==="DISCOVERED"||doc.state==="CLASSIFIED")&&<><button onClick={()=>approve(String(doc.discovery_id))}>Approve</button> <button onClick={()=>block(String(doc.discovery_id))}>Block</button></>}</td></tr>)}</tbody></table></article>}
    {status&&status.documents.length>0&&<article className="card"><h3>Indexed documents</h3><ul>{status.documents.map((doc,index)=><li key={index}>{String((doc as Record<string,unknown>).title||"UNKNOWN")} <span className="pill">{String((doc as Record<string,unknown>).source_type||"UNKNOWN")}</span></li>)}</ul></article>}
  </section>;
}
