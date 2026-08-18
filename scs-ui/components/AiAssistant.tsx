"use client";
import {FormEvent,useEffect,useRef,useState} from "react";
import {AiTurn,ChatResult,chat} from "@/lib/aiApi";
export function AiAssistant({jobContext}:{jobContext?:string}){
  const [turns,setTurns]=useState<AiTurn[]>([]);
  const [draft,setDraft]=useState("");
  const [busy,setBusy]=useState(false);
  const [outcome,setOutcome]=useState<ChatResult|null>(null);
  const bottom=useRef<HTMLDivElement|null>(null);
  useEffect(()=>{bottom.current?.scrollIntoView?.({behavior:"smooth"})},[turns,outcome]);
  async function send(e:FormEvent){
    e.preventDefault();
    if(!draft.trim()||busy)return;
    const message=draft.trim();
    const next=[...turns,{role:"user" as const,content:message}];
    setTurns(next);setDraft("");setBusy(true);setOutcome(null);
    const result=await chat(message,turns,jobContext);
    setBusy(false);
    if(result.state==="answered"&&result.reply){setTurns([...next,{role:"assistant",content:result.reply}])}
    else{setOutcome(result)}
  }
  return <div className="assistant-panel">
    <div className="chat-log">
      {turns.length===0&&<p className="chat-placeholder">Ask about HVAC service, TAB workflows, or equipment guidance. Answers come from the configured SCS model — it never guesses at customer, job, or reading facts.</p>}
      {turns.map((turn,index)=><div className={`chat-bubble ${turn.role}`} key={index}><p>{turn.content}</p></div>)}
      {busy&&<div className="chat-bubble assistant"><p>Thinking…</p></div>}
      <div ref={bottom}/>
    </div>
    {outcome&&<div className="model-banner" role="status"><strong>Model {outcome.state.replace("_"," ")}</strong><span>{outcome.detail ?? (outcome.model?`${outcome.model} is configured but not answering`:"No model is configured")}</span></div>}
    <form className="chat-form" onSubmit={send}><label>Ask the SCS assistant<input value={draft} onChange={e=>setDraft(e.target.value)} disabled={busy} placeholder="e.g. What readings should I take on a TAB traverse?"/></label><button disabled={busy||!draft.trim()}>Send</button></form>
  </div>;
}