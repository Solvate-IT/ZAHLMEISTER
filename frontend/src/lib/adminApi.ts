"use client";

import type {AccountUser,PlatformAdminSummary,PlatformCustomer,PlatformCustomerDetail} from "@/lib/types";

export class AdminApiError extends Error{
  constructor(message:string,public status:number){super(message)}
}

export interface PlatformSupportSession{
  access_token:string;
  expires_in:number;
  expires_at:string;
  user_id:string;
  user_name:string;
  user_email:string;
  organization_id:string;
  organization_name:string;
  read_only:true;
}

function base():string{
  const configured=process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/,"");
  if(configured)return configured;
  return typeof window!=="undefined"&&["localhost","127.0.0.1"].includes(window.location.hostname)
    ?"http://localhost:8003/api/v1"
    :`${window.location.origin}/api/v1`;
}

async function parseError(response:Response):Promise<AdminApiError>{
  let message="Request failed";
  try{const body=await response.json();message=String(body.detail??message)}catch{}
  return new AdminApiError(message,response.status);
}

async function request<T>(path:string,init:RequestInit={}):Promise<T>{
  const headers=new Headers(init.headers);
  headers.set("X-Admin-Request","1");
  if(init.body!==undefined)headers.set("Content-Type","application/json");
  const response=await fetch(`${base()}${path}`,{...init,headers,credentials:"include"});
  if(!response.ok)throw await parseError(response);
  return response.status===204?undefined as T:response.json() as Promise<T>;
}

async function login(email:string,password:string):Promise<AccountUser>{
  const response=await fetch(`${base()}/auth/admin-login`,{
    method:"POST",
    headers:{"Content-Type":"application/json"},
    credentials:"include",
    body:JSON.stringify({email,password}),
  });
  if(!response.ok)throw await parseError(response);
  return response.json() as Promise<AccountUser>;
}

export const adminApi={
  login,
  me:()=>request<AccountUser>("/auth/admin-me"),
  logout:()=>request<void>("/auth/admin-logout",{method:"POST"}),
  summary:()=>request<PlatformAdminSummary>("/admin/summary"),
  customers:()=>request<PlatformCustomer[]>("/admin/customers"),
  customer:(id:string)=>request<PlatformCustomerDetail>(`/admin/customers/${id}`),
  updateCustomer:(id:string,payload:{organization_name?:string;api_enabled?:boolean})=>request<PlatformCustomer>(`/admin/customers/${id}`,{method:"PATCH",body:JSON.stringify(payload)}),
  grantPro:(id:string,expires_at:string|null=null)=>request<PlatformCustomer>(`/admin/customers/${id}/grant-pro`,{method:"POST",body:JSON.stringify({expires_at})}),
  revokeAdminPro:(id:string)=>request<PlatformCustomer>(`/admin/customers/${id}/revoke-admin-pro`,{method:"POST"}),
  startSupport:(organizationId:string,userId:string,reason:string)=>request<PlatformSupportSession>(`/admin/customers/${organizationId}/users/${userId}/support-session`,{method:"POST",body:JSON.stringify({reason})}),
};
