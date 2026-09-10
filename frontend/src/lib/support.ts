"use client";

import {readToken} from "@/lib/session";

function apiBase():string{
  const configured=process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/,"");
  if(configured)return configured;
  if(typeof window==="undefined")return "/api/v1";
  return ["localhost","127.0.0.1"].includes(window.location.hostname)
    ?"http://localhost:8000/api/v1"
    :`${window.location.origin}/api/v1`;
}

export async function endSupportSessionRemote():Promise<void>{
  const token=await readToken();
  if(!token)return;
  const response=await fetch(`${apiBase()}/auth/support-logout`,{
    method:"POST",
    headers:{Authorization:`Bearer ${token}`},
  });
  if(!response.ok&&response.status!==401)throw new Error("Support logout failed");
}
