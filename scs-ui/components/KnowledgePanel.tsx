"use client";
import {useEffect,useState} from "react";
import {KnowledgeStatus,knowledgeApproveIndex,knowledgeBlock,knowledgeClassify,knowledgeDiscover,knowledgeStatus} from "@/lib/fieldApi";

type Discovery = Record<string,unknown>;

export function KnowledgePanel(){
  const [status,setStatus]=useState<KnowledgeStatus|null>(null);
  const [error,setError]=useState<string|null>(null);
  const [edit,setEdit]=useState<Record<string,string>|null>(null);
  async function load(){try{setStatus(await knowledgeStatus())}catch{setError("Knowledge not available")}}
  async function discover(){try{await knowledgeDiscover();await load()}catch{setError("Discovery failed")}}
  async function classify(discoveryId:string){try{await knowledgeClassify(discoveryId,{source_type:edit?.source_type||undefined,manufacturer:edit?.manufacturer||undefined,model:edit?.model||undefined,model_series:edit?.model_series||undefined,edition:edit?.edition||undefined});setEdit(null);await load()}catch{setError("Classification failed")}}
  async function approve(discoveryId:string){try{await knowledgeApproveIndex(discoveryId,{source_type:edit?.source_type||undefined,manufacturer:edit?.manufacturer||undefined,model:edit?.model||undefined,model_series:edit?.model_series||undefined,edition:edit?.edition||undefined});setEdit(null);await load()}catch{setError("Approval failed")}}
  async function block(discoveryId:string){try{await knowledgeBlock(discoveryId);await load()}catch{setError("Block failed")}}
  useEffect(()=>{load()},[]);
  const discovery = (status?.discovery ?? []) as Discovery[];
  const blocked = status?.knowledge_authority_blocked ?? null;
  return <section className="knowledge-panel">
    <div className="section-title"><div><p className="eyebrow">Private library</p><h2>Knowledge</h2></div>{status&&<span className={`pill ${status.configured?"ok":""}`}>{status.state}</span>}</div>
    {blocked&&<div className="model-banner" role="status"><strong>Knowledge authority blocked</strong><span>{blocked}</span></div>}
    {error&&<div className="model-banner" role="status"><strong>Knowledge</strong><span>{error}</span></div>}
    <button onClick={discover}>Discover documents</button>
    {status&&<div className="truth-grid"><article className="card"><h3>Index</h3><ul><li>Discovered: {status.discovered}</li><li>Owner approved: {status.owner_approved}</li><li>Indexed: {status.indexed}</li><li>Blocked: {status.blocked}</li></ul></article></div>}
    {discovery.length>0&&<article className="card"><h3>Discovered candidates</h3><table className="data-table"><thead><tr><th>File</th><th>Type</th><th>SHA</th><th>State</th><th>Actions</th></tr></thead><tbody>{discovery.map(doc=>{const id=String(doc.discovery_id);const state=String(doc.state);return <tr key={id}><td>{String(doc.filename)}</td><td>{String(doc.candidate_source_type||"UNKNOWN")}</td><td>{String(doc.file_sha256||"").slice(0,10)}</td><td><span className="pill">{state}</span></td><td>{state==="DISCOVERED"&&<><button onClick={()=>setEdit(edit?.id===id?null:{id,source_type:String(doc.candidate_source_type||""),manufacturer:"",model:"",model_series:"",edition:""})}>Review / Classify</button> <button onClick={()=>block(id)}>Block</button></>}{state==="CLASSIFIED"&&<><button onClick={()=>setEdit(edit?.id===id?null:{id,source_type:String(doc.candidate_source_type||""),manufacturer:String(doc.manufacturer||""),model:String(doc.model||""),model_series:String(doc.model_series||""),edition:String(doc.edition||"")})}>Edit</button> <button onClick={()=>approve(id)}>Approve &amp; Index</button> <button onClick={()=>block(id)}>Block</button></>}{state==="STALE_CHANGED"&&<span>stale — re-discover required</span>}{state==="PARSE_FAILED"&&<button onClick={()=>setEdit(edit?.id===id?null:{id,source_type:String(doc.candidate_source_type||""),manufacturer:String(doc.manufacturer||""),model:String(doc.model||""),model_series:"",edition:""})}>Retry review</button>}</td></tr>})}</tbody></table></article>}
    {edit&&<article className="card"><h3>Classify candidate</h3><form className="inline-form" onSubmit={e=>{e.preventDefault();classify(edit.id)}}><label>Source type<input value={edit.source_type} onChange={e=>setEdit({...edit,source_type:e.target.value})}/></label><label>Manufacturer<input value={edit.manufacturer} onChange={e=>setEdit({...edit,manufacturer:e.target.value})}/></label><label>Model<input value={edit.model} onChange={e=>setEdit({...edit,model:e.target.value})}/></label><label>Model series<input value={edit.model_series} onChange={e=>setEdit({...edit,model_series:e.target.value})}/></label><label>Edition<input value={edit.edition} onChange={e=>setEdit({...edit,edition:e.target.value})}/></label><button>Save classification</button></form></article>}
    {status&&status.documents.length>0&&<article className="card"><h3>Indexed documents</h3><ul>{status.documents.map((doc,index)=><li key={index}>{String((doc as Record<string,unknown>).title||"UNKNOWN")} <span className="pill">{String((doc as Record<string,unknown>).source_type||"UNKNOWN")}</span></li>)}</ul></article>}
  </section>;
}
