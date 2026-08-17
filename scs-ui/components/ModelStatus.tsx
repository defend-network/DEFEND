"use client";
import {useEffect,useState} from "react";
import {GatewayStatus,aiStatus} from "@/lib/aiApi";
export function ModelStatus(){
  const [status,setStatus]=useState<GatewayStatus|null|undefined>(undefined);
  useEffect(()=>{
    let alive=true;
    async function refresh(){const value=await aiStatus();if(alive)setStatus(value)}
    refresh();
    const timer=setInterval(refresh,15000);
    return ()=>{alive=false;clearInterval(timer)};
  },[]);
  if(status===undefined)return <span className="model-chip pending" aria-label="Model status">Model checking…</span>;
  if(status===null)return <span className="model-chip offline" aria-label="Model status">SCS AI offline</span>;
  const label=status.state==="configured"?(status.model_name??"model ready"):status.state.replaceAll("_"," ");
  return <span className={`model-chip ${status.ready?"ready":"offline"}`} aria-label="Model status">{label}</span>;
}