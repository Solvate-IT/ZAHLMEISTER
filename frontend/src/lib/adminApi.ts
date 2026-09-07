"use client";

import {readToken} from "@/lib/session";
import type {PlatformAdminSummary,PlatformCustomer} from "@/lib/types";

function base():string{
  const configured=process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/,"");
  if(configured)return configured;
  return typeof window!=="undefined"&&["localhost","127.0.0.1"].includes(window.location.hostname)
    ?"http://localhost:8003/api/v1"
    :`${window.location.origin}/api/v1`;
}

async function request<T>(path:string,init:RequestInit={}):Promise<T>{
  const token=await readToken();
  if(!token)throw new Error("Authentication required");
  const headers=new Headers(init.headers);
  headers.set("Authorization",`Bearer ${token}`);
  if(init.body!==undefined)headers.set("Content-Type","application/json");
  const response=await fetch(`${base()}${path}`,{...init,headers});
  if(!response.ok)throw new Error(String(response.status));
  return response.status===204?undefined as T:response.json() as Promise<T>;
}

export const adminApi={
  summary:()=>request<PlatformAdminSummary>("/admin/summary"),
  customers:()=>request<PlatformCustomer[]>("/admin/customers"),
  updateCustomer:(id:string,payload:{organization_name?:string;api_enabled?:boolean})=>request<PlatformCustomer>(`/admin/customers/${id}`,{method:"PATCH",body:JSON.stringify(payload)}),
  grantPro:(id:string,expires_at:string|null=null)=>request<PlatformCustomer>(`/admin/customers/${id}/grant-pro`,{method:"POST",body:JSON.stringify({expires_at})}),
  revokeAdminPro:(id:string)=>request<PlatformCustomer>(`/admin/customers/${id}/revoke-admin-pro`,{method:"POST"}),
};
