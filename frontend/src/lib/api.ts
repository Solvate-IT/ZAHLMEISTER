"use client";

import {clearToken, readToken, storeToken} from "@/lib/session";
import {Capacitor} from "@capacitor/core";
import {Directory,Filesystem} from "@capacitor/filesystem";
import {Share} from "@capacitor/share";
import type * as T from "@/lib/types";

export class ApiError extends Error { constructor(message: string, public status: number) { super(message); } }

function apiBase(): string {
  const configured = process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "");
  if (configured) return configured;
  if (typeof window === "undefined") return "/api/v1";
  if (Capacitor.isNativePlatform()) {
    throw new Error("NEXT_PUBLIC_API_BASE_URL is required for native builds");
  }
  if (["localhost","127.0.0.1"].includes(window.location.hostname)) return "http://localhost:8000/api/v1";
  return `${window.location.origin}/api/v1`;
}

async function request<T>(path: string, init: RequestInit = {}, auth = true): Promise<T> {
  const token = auth ? await readToken() : null;
  const headers = new Headers(init.headers);
  if (!(init.body instanceof FormData) && init.body !== undefined) headers.set("Content-Type", "application/json");
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(`${apiBase()}${path}`, {...init, headers});
  if (response.status === 401 && auth) await clearToken();
  if (!response.ok) {
    let message = "Request failed";
    try { const body = await response.json(); message = String(body.detail ?? message); } catch {}
    throw new ApiError(message, response.status);
  }
  if (response.status === 204) return undefined as T;
  const type = response.headers.get("content-type") ?? "";
  if (type.includes("application/json")) return response.json() as Promise<T>;
  return response as unknown as T;
}

async function download(path: string): Promise<{blob: Blob; filename: string}> {
  const token = await readToken();
  const response = await fetch(`${apiBase()}${path}`, {headers: token ? {Authorization:`Bearer ${token}`} : {}});
  if (!response.ok) throw new ApiError("Request failed", response.status);
  const disposition = response.headers.get("content-disposition") ?? "";
  const filename = /filename="?([^";]+)/i.exec(disposition)?.[1] ?? "download";
  return {blob: await response.blob(), filename};
}

export const api = {
  async restore(): Promise<T.AccountUser|null> { try { return await request<T.AccountUser>("/auth/me"); } catch (e) { if (e instanceof ApiError && e.status === 401) return null; throw e; } },
  async login(email: string, password: string) { const data=await request<T.AuthResponse>("/auth/login",{method:"POST",body:JSON.stringify({email,password})},false); await storeToken(data.token); return data.user; },
  async register(payload: {email:string;password:string;display_name:string;locale:string;currency:string}) { const data=await request<T.AuthResponse>("/auth/register",{method:"POST",body:JSON.stringify(payload)},false); await storeToken(data.token); return data.user; },
  async logout(){ try { await request<void>("/auth/logout",{method:"POST"}); } finally { await clearToken(); } },
  forgotPassword:(email:string)=>request<void>("/auth/forgot-password",{method:"POST",body:JSON.stringify({email})},false),
  resetPassword:(token:string,new_password:string)=>request<void>("/auth/reset-password",{method:"POST",body:JSON.stringify({token,new_password})},false),
  verifyEmail:(token:string)=>request<void>("/auth/verify-email",{method:"POST",body:JSON.stringify({token})},false),
  resendVerification:()=>request<void>("/auth/resend-verification",{method:"POST"}),
  sendContact:(payload:Record<string,string>)=>request<void>("/public/contact",{method:"POST",body:JSON.stringify(payload)},false),
  updateProfile:(payload:Record<string,string>)=>request<T.AccountUser>("/account/profile",{method:"PATCH",body:JSON.stringify(payload)}),
  changePassword:(current_password:string,new_password:string)=>request<void>("/account/change-password",{method:"POST",body:JSON.stringify({current_password,new_password})}),
  exportAccount:()=>download("/account/export"),
  deleteAccount:(password:string)=>request<void>("/account/delete",{method:"POST",body:JSON.stringify({password})}),
  lists:()=>request<T.ParticipantListSummary[]>("/participant-lists"),
  list:(id:string)=>request<T.ParticipantListDetail>(`/participant-lists/${id}`),
  createList:(name?:string)=>request<T.ParticipantListSummary>("/participant-lists",{method:"POST",body:JSON.stringify(name?.trim()?{name:name.trim()}:{})}),
  renameList:(id:string,name:string)=>request<T.ParticipantListSummary>(`/participant-lists/${id}`,{method:"PATCH",body:JSON.stringify({name})}),
  addParticipant:(listId:string,payload:Omit<T.Participant,"id"|"channels">)=>request<T.Participant>(`/participant-lists/${listId}/participants`,{method:"POST",body:JSON.stringify(payload)}),
  updateParticipant:(listId:string,id:string,payload:Omit<T.Participant,"id"|"channels">)=>request<T.Participant>(`/participant-lists/${listId}/participants/${id}`,{method:"PATCH",body:JSON.stringify(payload)}),
  updateParticipantChannel:(listId:string,id:string,channel:T.CommunicationChannel,payload:{enabled?:boolean;availability?:T.ChannelAvailability})=>request<T.Participant>(`/participant-lists/${listId}/participants/${id}/channels/${channel}`,{method:"PATCH",body:JSON.stringify(payload)}),
  deleteParticipant:(listId:string,id:string)=>request<void>(`/participant-lists/${listId}/participants/${id}`,{method:"DELETE"}),
  async previewImport(file:File){ const form=new FormData(); form.append("file",file); return request<T.ImportPreview>("/participant-lists/import-preview",{method:"POST",body:form}); },
  commitImport:(listId:string,participants:T.ImportDraft[])=>request<T.ImportResult>(`/participant-lists/${listId}/import`,{method:"POST",body:JSON.stringify({participants})}),
  collections:()=>request<T.CollectionSummary[]>("/collections"),
  openBalances:()=>request<T.ParticipantOpenBalance[]>("/collections/open-balances"),
  collection:(id:string)=>request<T.CollectionDetail>(`/collections/${id}`),
  createCollection:(payload:Record<string,unknown>)=>request<T.CollectionSummary>("/collections",{method:"POST",body:JSON.stringify(payload)}),
  updateCollection:(id:string,payload:Record<string,unknown>)=>request<T.CollectionSummary>(`/collections/${id}`,{method:"PATCH",body:JSON.stringify(payload)}),
  collectionMessageTranslations:(id:string)=>request<T.CollectionMessageTranslations>(`/collections/${id}/message-translations`),
  saveCollectionMessageTranslation:(id:string,language:string,body:string)=>request<T.CollectionMessageTranslations>(`/collections/${id}/message-translations`,{method:"PUT",body:JSON.stringify({language,body})}),
  translateCollectionMessageLanguages:(id:string,language:string,body:string)=>request<T.CollectionMessageTranslations>(`/collections/${id}/message-translations/translate-other-languages`,{method:"POST",body:JSON.stringify({language,body})}),
  setPaid:(cid:string,pid:string,paid:boolean)=>request<T.CollectionParticipant>(`/collections/${cid}/participants/${pid}/payment-status`,{method:"PUT",body:JSON.stringify({paid})}),
  dispatchCollection:(id:string,payload:{kind:"initial"|"reminder";external_channels:T.CommunicationChannel[];collection_participant_ids?:string[]})=>request<T.DispatchResult>(`/collections/${id}/dispatch`,{method:"POST",body:JSON.stringify(payload)}),
  sendCollection:(id:string)=>request<{queued:number}>(`/collections/${id}/send`,{method:"POST"}),
  remindCollection:(id:string)=>request<{queued:number}>(`/collections/${id}/remind`,{method:"POST"}),
  exportCollection:(id:string,format:string,detailed=false)=>download(`/collections/${id}/export?format=${encodeURIComponent(format)}&detailed=${detailed}`),
  templates:()=>request<T.MessageTemplate[]>("/message-templates"),
  templateTranslationStatus:()=>request<T.TemplateTranslationStatus>("/message-templates/translation-status"),
  createTemplate:(payload:{name:string;body?:string;source_language?:string;auto_translate?:boolean})=>request<T.MessageTemplate>("/message-templates",{method:"POST",body:JSON.stringify(payload)}),
  updateTemplate:(id:string,payload:Record<string,unknown>)=>request<T.MessageTemplate>(`/message-templates/${id}`,{method:"PUT",body:JSON.stringify(payload)}),
  translateMissingTemplate:(id:string,source_language:string)=>request<T.MessageTemplate>(`/message-templates/${id}/translate-missing`,{method:"POST",body:JSON.stringify({source_language})}),
  translateOtherTemplateLanguages:(id:string,source_language:string)=>request<T.MessageTemplate>(`/message-templates/${id}/translate-other-languages`,{method:"POST",body:JSON.stringify({source_language})}),
  deleteTemplate:(id:string)=>request<void>(`/message-templates/${id}`,{method:"DELETE"}),
  paymentSettings:()=>request<T.PaymentSettings>("/payment-settings"),
  savePaymentSettings:(payload:T.PaymentSettingsUpdate)=>request<T.PaymentSettings>("/payment-settings",{method:"PUT",body:JSON.stringify(payload)}),
  billingEntitlement:()=>request<T.BillingEntitlement>("/billing/entitlement"),
  billingProfile:()=>request<T.BillingProfile|null>("/billing/profile"),
  saveBillingProfile:(payload:T.BillingProfileWrite)=>request<T.BillingProfile>("/billing/profile",{method:"PUT",body:JSON.stringify(payload)}),
  billingInvoices:()=>request<T.BillingInvoice[]>("/billing/invoices"),
  mollieBillingConfig:()=>request<T.MollieBillingConfig>("/billing/mollie/config"),
  mollieBillingCheckout:()=>request<T.MollieBillingCheckout>("/billing/mollie/checkout",{method:"POST"}),
  mollieBillingSync:()=>request<T.BillingEntitlement>("/billing/mollie/sync",{method:"POST"}),
  mollieBillingCancel:()=>request<T.BillingEntitlement>("/billing/mollie/cancel",{method:"POST"}),
  publicPayment:(token:string)=>request<T.PublicPayment>(`/public/payments/${encodeURIComponent(token)}`,{},false),
  publicPaymentQr:(token:string)=>`${apiBase()}/public/payments/${encodeURIComponent(token)}/qr.png`,
  startOnlinePayment:(token:string)=>request<T.OnlineCheckout>(`/public/payments/${encodeURIComponent(token)}/online`,{method:"POST"},false),
  bankImports:()=>request<T.BankImportSummary[]>("/bank-imports"),
  bankImport:(id:string)=>request<T.BankImportSummary>(`/bank-imports/${id}`),
  async importBankStatement(file:File){ const form=new FormData(); form.append("file",file); return request<T.BankImportSummary>("/bank-imports",{method:"POST",body:form}); },
  confirmBankMatch:(iid:string,tid:string,collection_participant_id:string)=>request<T.BankImportSummary>(`/bank-imports/${iid}/transactions/${tid}/match`,{method:"POST",body:JSON.stringify({collection_participant_id})}),
  ignoreBankTransaction:(iid:string,tid:string)=>request<T.BankImportSummary>(`/bank-imports/${iid}/transactions/${tid}/ignore`,{method:"POST"}),
  bankSyncConnection:()=>request<T.BankSyncConnection|null>("/bank-sync/connection"),
  startPonto:()=>request<{authorization_url:string}>("/bank-sync/ponto/start",{method:"POST"}),
  testBankSync:()=>request<T.IntegrationTestResult>("/bank-sync/connection/test",{method:"POST"}),
  bankSyncAccounts:()=>request<T.BankSyncAccount[]>("/bank-sync/accounts"),
  setBankSyncAccount:(id:string,enabled:boolean)=>request<T.BankSyncAccount>(`/bank-sync/accounts/${id}`,{method:"PUT",body:JSON.stringify({enabled})}),
  syncBank:()=>request<T.BankSyncRunResult>("/bank-sync/sync",{method:"POST"}),
  disconnectBankSync:()=>request<void>("/bank-sync/connection",{method:"DELETE"}),
  onlinePaymentConnection:()=>request<T.OnlinePaymentConnection|null>("/online-payments/connection"),
  startMollie:()=>request<{authorization_url:string}>("/online-payments/mollie/oauth/start",{method:"POST"}),
  onlinePaymentProfiles:()=>request<T.OnlinePaymentProfile[]>("/online-payments/profiles"),
  selectOnlinePaymentProfile:(profile_id:string)=>request<T.OnlinePaymentConnection>("/online-payments/profile",{method:"PUT",body:JSON.stringify({profile_id})}),
  setOnlinePaymentsEnabled:(enabled:boolean)=>request<T.OnlinePaymentConnection>("/online-payments/enabled",{method:"PUT",body:JSON.stringify({enabled})}),
  testOnlinePayment:()=>request<T.IntegrationTestResult>("/online-payments/connection/test",{method:"POST"}),
  disconnectOnlinePayments:()=>request<void>("/online-payments/connection",{method:"DELETE"}),
  communicationConnections:()=>request<T.CommunicationConnection[]>("/communication-settings/connections"),
  communicationSettings:()=>request<T.ChannelSetting[]>("/communication-settings"),
  communicationPreferences:()=>request<T.CommunicationPreferences>("/communication-settings/preferences"),
  saveCommunicationPreferences:(channel_order:T.CommunicationChannel[])=>request<T.CommunicationPreferences>("/communication-settings/preferences",{method:"PUT",body:JSON.stringify({channel_order})}),
  connectInfobip:(payload:Record<string,unknown>)=>request<T.CommunicationConnection>("/communication-settings/infobip/api-key",{method:"POST",body:JSON.stringify(payload)}),
  startInfobip:()=>request<{authorization_url:string}>("/communication-settings/infobip/oauth/start"),
  startMicrosoft365:()=>request<{authorization_url:string}>("/communication-settings/microsoft365/oauth/start"),
  updateCommunicationConnection:(id:string,payload:Record<string,unknown>)=>request<T.CommunicationConnection>(`/communication-settings/connections/${id}`,{method:"PATCH",body:JSON.stringify(payload)}),
  disconnectCommunicationConnection:(id:string)=>request<void>(`/communication-settings/connections/${id}`,{method:"DELETE"}),
  testCommunicationConnection:(id:string)=>request<T.IntegrationTestResult>(`/communication-settings/connections/${id}/test`,{method:"POST"}),
  testCommunicationChannel:(channel:string)=>request<T.IntegrationTestResult>(`/communication-settings/${channel}/test`,{method:"POST"}),
  saveCommunicationSetting:(channel:string,payload:Record<string,unknown>)=>request<T.ChannelSetting>(`/communication-settings/${channel}`,{method:"PUT",body:JSON.stringify(payload)}),
  communications:(cid:string,pid:string)=>request<T.CommunicationItem[]>(`/collections/${cid}/participants/${pid}/communications`),
  createExternalDraft:(cid:string,pid:string,channel:T.CommunicationChannel,kind:"initial"|"reminder"|"manual")=>request<T.ExternalDraft>(`/collections/${cid}/participants/${pid}/communications/external-draft`,{method:"POST",body:JSON.stringify({channel,kind})}),
  markExternalOpened:(cid:string,pid:string,message_id:string)=>request<T.CommunicationItem>(`/collections/${cid}/participants/${pid}/communications/external-opened`,{method:"POST",body:JSON.stringify({message_id})}),
  confirmExternalResult:(cid:string,pid:string,message_id:string,result:"sent"|"unavailable"|"skipped")=>request<T.CommunicationItem>(`/collections/${cid}/participants/${pid}/communications/external-result`,{method:"POST",body:JSON.stringify({message_id,result})}),
  channelFeedback:(cid:string,pid:string,channel:T.CommunicationChannel,availability:T.ChannelAvailability)=>request<void>(`/collections/${cid}/participants/${pid}/channels/${channel}/feedback`,{method:"POST",body:JSON.stringify({availability})}),
  queueInternalCommunication:(cid:string,pid:string,channel:string,kind:"initial"|"reminder"|"manual")=>request<{message_id:string;status:string}>(`/collections/${cid}/participants/${pid}/communications/internal`,{method:"POST",body:JSON.stringify({channel,kind})}),
  apiSettings:()=>request<T.ApiSettings>("/account/api"),
  setApiEnabled:(enabled:boolean)=>request<T.ApiSettings>("/account/api/enabled",{method:"PUT",body:JSON.stringify({enabled})}),
  apiCredentials:()=>request<T.ApiCredential[]>("/account/api/credentials"),
  createApiCredential:(payload:{name:string;scopes:string[];expires_at?:string|null})=>request<T.ApiCredentialCreated>("/account/api/credentials",{method:"POST",body:JSON.stringify(payload)}),
  revokeApiCredential:(id:string)=>request<void>(`/account/api/credentials/${id}`,{method:"DELETE"}),
};

async function blobBase64(blob:Blob):Promise<string>{
  const buffer=new Uint8Array(await blob.arrayBuffer());
  let binary="";
  const chunk=0x8000;
  for(let offset=0;offset<buffer.length;offset+=chunk){
    binary+=String.fromCharCode(...buffer.subarray(offset,offset+chunk));
  }
  return btoa(binary);
}

export async function saveDownload(file: Promise<{blob:Blob;filename:string}>): Promise<void> {
  const {blob,filename}=await file;
  if(Capacitor.isNativePlatform()){
    const safeFilename=filename.replace(/[^A-Za-z0-9._-]/g,"_");
    await Filesystem.writeFile({path:safeFilename,data:await blobBase64(blob),directory:Directory.Cache});
    const stored=await Filesystem.getUri({path:safeFilename,directory:Directory.Cache});
    await Share.share({files:[stored.uri]});
    return;
  }
  const url=URL.createObjectURL(blob);
  const a=document.createElement("a");
  a.href=url;
  a.download=filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export async function savePublicFile(url:string,filename:string):Promise<void>{
  const response=await fetch(url);
  if(!response.ok)throw new ApiError("Request failed",response.status);
  await saveDownload(Promise.resolve({blob:await response.blob(),filename}));
}