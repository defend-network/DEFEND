"use client";
import {FormEvent,useEffect,useState} from "react";
import {KnowledgeStatus,SetupStatus,knowledgeApproveIndex,knowledgeBlock,knowledgeClassify,knowledgeDiscover,knowledgeStatus,recoverLedger,setKnowledgeRoot,setupStatus} from "@/lib/fieldApi";

type Discovery = Record<string,unknown>;

export function SetupPanel(){
  const [setup,setSetup]=useState<SetupStatus|null>(null);
  const [knowledge,setKnowledge]=useState<KnowledgeStatus|null>(null);
  const [root,setRoot]=useState("");
  const [error,setError]=useState<string|null>(null);
  const [edit,setEdit]=useState<Record<string,string>|null>(null);
  const [recoverConfirm,setRecoverConfirm]=useState(false);
  async function load(){try{setSetup(await setupStatus());setKnowledge(await knowledgeStatus())}catch{setKnowledge(null)}}
  async function saveRoot(e:FormEvent){e.preventDefault();if(!root.trim())return;try{await setKnowledgeRoot(root.trim());setRoot("");await load()}catch(e2){setError(e2 instanceof Error?e2.message:"Could not set root")}}
  async function discover(){try{await knowledgeDiscover();await load()}catch{setError("Discovery failed")}}
  async function recover(){try{const r=await recoverLedger(recoverConfirm);if(r.requires_confirmation===true){setRecoverConfirm(true)}else{setRecoverConfirm(false)}await load()}catch{setError("Recovery failed")}}
  async function classify(id:string){try{await knowledgeClassify(id,{source_type:edit?.source_type||undefined,manufacturer:edit?.manufacturer||undefined,model:edit?.model||undefined,model_series:edit?.model_series||undefined,edition:edit?.edition||undefined});setEdit(null);await load()}catch{setError("Classification failed")}}
  async function approve(id:string){try{await knowledgeApproveIndex(id,{source_type:edit?.source_type||undefined,manufacturer:edit?.manufacturer||undefined,model:edit?.model||undefined,model_series:edit?.model_series||undefined,edition:edit?.edition||undefined});setEdit(null);await load()}catch{setError("Approval failed")}}
  async function block(id:string){try{await knowledgeBlock(id);await load()}catch{setError("Block failed")}}
  useEffect(()=>{load()},[]);
  const discovery = (knowledge?.discovery ?? []) as Discovery[];
  return <section className="setup-panel">
    <div className="section-title"><div><p className="eyebrow">SCS Setup</p><h2>Setup</h2></div>{setup&&<span className="pill">SCS-owned</span>}</div>
    {error&&<div className="model-banner" role="status"><strong>Setup</strong><span>{error}</span></div>}
    <div className="truth-grid">
      <article className="card"><h3>Knowledge Root</h3>
        <p>{setup?.knowledge_configured?<span className="pill ok">CONFIGURED</span>:<span className="pill">NOT_CONFIGURED</span>} · source: {setup?.knowledge_root_source||"n/a"}</p>
        {setup?.knowledge_root&&<p className="mono">{setup.knowledge_root}</p>}
        <form className="inline-form" onSubmit={saveRoot}><label>Local directory path<input value={root} onChange={e=>setRoot(e.target.value)} placeholder="C:\path\to\manuals"/></label><button disabled={!root.trim()}>Set root</button></form>
        <p className="chat-placeholder">Configuring the root does not scan or approve anything. Discovery is explicit.</p>
      </article>
      <article className="card"><h3>Discovery Ledger</h3>
        <p>State: <span className="pill">{setup?.discovery_ledger_state??"n/a"}</span></p>
        {(setup?.discovery_ledger_state==="INCOMPATIBLE"||setup?.discovery_ledger_state==="CORRUPT")&&<button onClick={recover}>{recoverConfirm?"Confirm reset (authority unknown)":"Archive & Recover"}</button>}
        {knowledge?.knowledge_authority_blocked&&<p className="chat-placeholder">{knowledge.knowledge_authority_blocked}</p>}
      </article>
    </div>
    <button onClick={discover}>Discover Documents</button>
    {discovery.length>0&&<article className="card"><h3>Documents</h3><table className="data-table"><thead><tr><th>File</th><th>Type</th><th>SHA</th><th>State</th><th>Actions</th></tr></thead><tbody>{discovery.map(doc=>{const id=String(doc.discovery_id);const state=String(doc.state);return <tr key={id}><td>{String(doc.filename)}</td><td>{String(doc.candidate_source_type||"UNKNOWN")}</td><td>{String(doc.file_sha256||"").slice(0,10)}</td><td><span className="pill">{state}</span></td><td>{state==="DISCOVERED"&&<><button onClick={()=>setEdit(edit?.id===id?null:{id,source_type:String(doc.candidate_source_type||""),manufacturer:"",model:"",model_series:"",edition:""})}>Review / Classify</button> <button onClick={()=>block(id)}>Block</button></>}{state==="CLASSIFIED"&&<><button onClick={()=>setEdit(edit?.id===id?null:{id,source_type:String(doc.candidate_source_type||""),manufacturer:String(doc.manufacturer||""),model:String(doc.model||""),model_series:String(doc.model_series||""),edition:String(doc.edition||"")})}>Edit</button> <button onClick={()=>approve(id)}>Approve &amp; Index</button> <button onClick={()=>block(id)}>Block</button></>}{state==="STALE_CHANGED"&&<span>stale — re-discover required</span>}{state==="PARSE_FAILED"&&<button onClick={()=>setEdit(edit?.id===id?null:{id,source_type:String(doc.candidate_source_type||""),manufacturer:String(doc.manufacturer||""),model:String(doc.model||""),model_series:"",edition:""})}>Retry review</button>}</td></tr>})}</tbody></table></article>}
    {edit&&<article className="card"><h3>Classify candidate</h3><form className="inline-form" onSubmit={e=>{e.preventDefault();classify(edit.id)}}><label>Source type<input value={edit.source_type} onChange={e=>setEdit({...edit,source_type:e.target.value})}/></label><label>Manufacturer<input value={edit.manufacturer} onChange={e=>setEdit({...edit,manufacturer:e.target.value})}/></label><label>Model<input value={edit.model} onChange={e=>setEdit({...edit,model:e.target.value})}/></label><label>Model series<input value={edit.model_series} onChange={e=>setEdit({...edit,model_series:e.target.value})}/></label><label>Edition<input value={edit.edition} onChange={e=>setEdit({...edit,edition:e.target.value})}/></label><button>Save classification</button></form></article>}
  </section>;
}
