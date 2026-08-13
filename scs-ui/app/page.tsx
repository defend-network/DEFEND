"use client";
import {useState} from "react";
import {Login} from "@/components/Login";
import {Workspace} from "@/components/Workspace";
import {api} from "@/lib/api";
type Employee={display_name:string;roles:string[];permissions:string[]};
export default function Page(){const [employee,setEmployee]=useState<Employee|null>(null);async function login(identifier:string,password:string){const value=await api<{employee:Employee}>("/api/scs/auth/login",{method:"POST",body:JSON.stringify({identifier,password})});setEmployee(value.employee)}return employee?<Workspace employee={employee} jobs={[]}/>:<Login onLogin={login}/>}
