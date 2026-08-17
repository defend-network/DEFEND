"use client";
import {useEffect,useState} from "react";
import {Login} from "@/components/Login";
import {Workspace} from "@/components/Workspace";
import {api} from "@/lib/api";
type Employee={display_name:string;roles:string[];permissions:string[]};
type Job={job_id:string;job_type:string;status:string;job_date:string;priority:string;customer_id:string;site_id:string};
export default function Page(){
  const[employee,setEmployee]=useState<Employee|null>(null);
  const[jobs,setJobs]=useState<Job[]>([]);
  const[restoring,setRestoring]=useState(true);
  async function loadJobs(){setJobs((await api<{jobs:Job[]}>("/api/scs/jobs")).jobs)}
  async function login(identifier:string,password:string){const value=await api<{employee:Employee}>("/api/scs/auth/login",{method:"POST",body:JSON.stringify({identifier,password})});setEmployee(value.employee);await loadJobs()}
  useEffect(()=>{api<{employee:Employee}>("/api/scs/auth/session").then(async value=>{setEmployee(value.employee);await loadJobs()}).catch(()=>{}).finally(()=>setRestoring(false))},[]);
  if(restoring&&employee===null)return <div className="workspace"><p className="chat-placeholder">Restoring session…</p></div>;
  return employee?<Workspace employee={employee} jobs={jobs} onRefresh={loadJobs}/>:<Login onLogin={login}/>;
}