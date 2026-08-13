const API = process.env.NEXT_PUBLIC_SCS_API_ORIGIN ?? "http://localhost:8100";
export async function api<T>(path:string,init?:RequestInit):Promise<T>{const response=await fetch(`${API}${path}`,{...init,credentials:"include",headers:{"Content-Type":"application/json",...init?.headers}});if(!response.ok)throw new Error("SCS request failed");return response.json() as Promise<T>}
