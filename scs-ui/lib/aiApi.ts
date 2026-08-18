const AI = process.env.NEXT_PUBLIC_SCS_AI_API_ORIGIN ?? "http://127.0.0.1:8300";
export type AiTurn = {role:"user"|"assistant";content:string};
export type ChatState = "answered"|"model_unavailable"|"model_timeout"|"model_error"|"not_configured";
export type ChatResult = {state:ChatState;reply:string|null;model:string|null;provider:string|null;detail:string|null};
export type GatewayStatus = {state:string;ready:boolean;alias:string|null;provider:string|null;model_name:string|null};
export type CalculationItem = {name:string;formula:string;inputs:Record<string,string>};
export type CalculationResult = {ok:boolean;calculation:string;formula?:string;result:Record<string,number>|null;errors:string[]};

async function aiJson<T>(path:string,init?:RequestInit):Promise<T>{
  const response=await fetch(`${AI}${path}`,{...init,headers:{"Content-Type":"application/json",...init?.headers}});
  if(!response.ok)throw new Error("SCS AI request failed");
  return response.json() as Promise<T>;
}

export async function aiStatus():Promise<GatewayStatus|null>{
  try{const body=await aiJson<{model_gateway:GatewayStatus}>("/v1/system/status");return body.model_gateway}catch{return null}
}

export async function chat(message:string,history:AiTurn[],jobContext?:string):Promise<ChatResult>{
  try{
    const response=await fetch(`${AI}/v1/chat`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({message,history,job_context:jobContext})});
    const body=await response.json() as ChatResult;
    if(!response.ok&&response.status!==503)return {state:"model_unavailable",reply:null,model:null,provider:null,detail:"SCS AI request failed"};
    return body;
  }catch{return {state:"model_unavailable",reply:null,model:null,provider:null,detail:"SCS AI service unreachable"}}
}

export async function calculationSchema():Promise<CalculationItem[]>{try{const body=await aiJson<{items:CalculationItem[]}>("/v1/calculations");return body.items}catch{return []}}

export async function calculate(calculation:string,inputs:Record<string,unknown>):Promise<CalculationResult|null>{
  try{return await aiJson<CalculationResult>("/v1/calculations",{method:"POST",body:JSON.stringify({calculation,inputs})})}catch{return null}
}