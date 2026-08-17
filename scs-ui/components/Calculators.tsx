"use client";
import {FormEvent,useEffect,useState} from "react";
import {CalculationItem,CalculationResult,calculate,calculationSchema} from "@/lib/aiApi";
export function Calculators(){
  const [items,setItems]=useState<CalculationItem[]>([]);
  const [selected,setSelected]=useState<CalculationItem|null>(null);
  const [values,setValues]=useState<Record<string,string>>({});
  const [result,setResult]=useState<CalculationResult|null>(null);
  useEffect(()=>{calculationSchema().then(items=>{setItems(items);if(items.length)select(items[0])})},[]);
  function select(item:CalculationItem){setSelected(item);setValues({});setResult(null)}
  const listInputs=Object.entries(selected?.inputs??{});
  function parse():Record<string,unknown>{
    const inputs:Record<string,unknown>={};
    for(const [name,spec] of listInputs){
      const raw=values[name]??"";
      if(spec.startsWith("list"))inputs[name]=raw.split(",").map(part=>part.trim()).filter(Boolean).map(Number);
      else inputs[name]=Number(raw);
    }
    return inputs;
  }
  async function run(e:FormEvent){
    e.preventDefault();
    if(!selected)return;
    setResult(await calculate(selected.name,parse()));
  }
  return <div className="calc-panel">
    <div className="calc-toolbar"><label>Calculation<select aria-label="Calculation" value={selected?.name??""} onChange={e=>{const item=items.find(candidate=>candidate.name===e.target.value);if(item)select(item)}}>{items.map(item=><option key={item.name} value={item.name}>{item.name.replaceAll("_"," ")}</option>)}</select></label>{selected&&<p className="calc-formula">{selected.formula}</p>}</div>
    <form className="calc-form" onSubmit={run}>
      {selected&&listInputs.map(([name,spec])=><label key={name}>{name.replaceAll("_"," ")}{spec.startsWith("list")&&<span className="hint">comma separated</span>}<input value={values[name]??""} onChange={e=>setValues({...values,[name]:e.target.value})} placeholder={spec}/></label>)}
      <button disabled={!selected}>Calculate</button>
    </form>
    {result&&(result.ok&&result.result?<div className="calc-result" role="status">{Object.entries(result.result).map(([name,value])=><span key={name}><strong>{value}</strong>{name.replaceAll("_"," ")}</span>)}</div>:<div className="model-banner" role="status"><strong>Calculation rejected</strong><span>{(result.errors??[]).join(" · ")}</span></div>)}
    {!result&&items.length===0&&<p className="chat-placeholder">The calculation service is not reachable right now.</p>}
  </div>;
}