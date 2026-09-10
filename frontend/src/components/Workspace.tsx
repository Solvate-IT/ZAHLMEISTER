"use client";

import {useEffect, useState} from "react";
import {useRouter, useSearchParams} from "next/navigation";
import {api} from "@/lib/api";
import {clearSupportSession,isSupportSession} from "@/lib/session";
import {endSupportSessionRemote} from "@/lib/support";
import type {AccountUser} from "@/lib/types";
import {useI18n} from "@/lib/i18n";
import {Brand} from "./Brand";
import {LocaleSelect} from "./LocaleSelect";
import {Loading} from "./State";
import {SupportSessionBanner} from "./SupportSessionBanner";
import {OverviewPage} from "./workspace/OverviewPage";
import {ListsPage} from "./workspace/ListsPage";
import {CollectionsPage} from "./workspace/CollectionsPage";
import {SettingsPage} from "./workspace/SettingsPage";

type View="overview"|"lists"|"collections"|"settings";
type CreateAction="list"|"collection";

export function Workspace(){const router=useRouter();const params=useSearchParams();const {t,setLocale}=useI18n();const [user,setUser]=useState<AccountUser|null>(null);const [loading,setLoading]=useState(true);const raw=params.get("view");const view:View=raw==="lists"||raw==="collections"||raw==="settings"||raw==="billing"?(raw==="billing"?"settings":raw):"overview";const create=params.get("create");const billingRequested=raw==="billing"||params.has("billing");const pontoRequested=params.has("ponto");
  useEffect(()=>{const support=isSupportSession();api.restore().then(u=>{if(!u){router.replace(support?"/admin":"/?auth=login");return}setUser(u);if(u.locale)setLocale(u.locale)}).catch(()=>router.replace(support?"/admin":"/?auth=login")).finally(()=>setLoading(false))},[router,setLocale]);
  function navigate(next:View,createAction?:CreateAction){const url=new URL(window.location.href);url.searchParams.set("view",next);url.searchParams.delete("id");url.searchParams.delete("billing");url.searchParams.delete("ponto");if(createAction)url.searchParams.set("create",createAction);else url.searchParams.delete("create");router.push(`${url.pathname}?${url.searchParams}`)}
  function consumeCreate(){const url=new URL(window.location.href);url.searchParams.delete("create");router.replace(`${url.pathname}?${url.searchParams}`)}
  async function logout(){if(isSupportSession()){try{await endSupportSessionRemote()}finally{clearSupportSession();router.replace("/admin")}return}await api.logout();router.replace("/")}
  if(loading||!user)return <div className="auth-wrap"><Loading/></div>;
  const support=isSupportSession();
  const primaryNav=[{id:"overview" as View,label:t("overview")},{id:"lists" as View,label:t("participantLists")},{id:"collections" as View,label:t("collections")}];
  const settingsNav={id:"settings" as View,label:t("configuration")};
  const allNav=[...primaryNav,settingsNav];
  return <div className="workspace"><aside className="sidebar"><Brand compact/><nav className="nav">{primaryNav.map(n=><button key={n.id} className={view===n.id?"active":""} onClick={()=>navigate(n.id)}>{n.label}</button>)}{user.is_platform_admin&&<button onClick={()=>router.push("/admin")}>{t("platformAdmin")}</button>}</nav><div className="sidebar-bottom"><nav className="nav sidebar-settings"><button className={view==="settings"?"active":""} onClick={()=>navigate("settings")}>{settingsNav.label}</button></nav><button className="button ghost" onClick={logout}>{support?t("supportReturnAdmin"):t("logout")}</button></div></aside><main className="workspace-main"><header className="workspace-header"><div><strong>{allNav.find(n=>n.id===view)?.label}</strong></div><div className="top-actions"><LocaleSelect/>{user.is_platform_admin&&<button className="button secondary small" onClick={()=>router.push("/admin")}>{t("platformAdmin")}</button>}<span className="hide-mobile workspace-user-name">{user.display_name}</span><button className="button secondary small" onClick={logout}>{support?t("supportReturnAdmin"):t("logout")}</button></div></header><div className="workspace-body">{support&&<SupportSessionBanner/>}{view==="overview"&&<OverviewPage onNavigate={navigate}/>} {view==="lists"&&<ListsPage autoCreate={create==="list"} onCreateConsumed={consumeCreate}/>} {view==="collections"&&<CollectionsPage autoCreate={create==="collection"} onCreateConsumed={consumeCreate}/>} {view==="settings"&&<SettingsPage user={user} onUser={setUser} onDeleted={()=>router.replace("/")} initialSection={billingRequested?"billing":pontoRequested?"bankSync":undefined}/>}</div></main><nav className="mobile-nav">{allNav.map(n=><button key={n.id} className={view===n.id?"active":""} onClick={()=>navigate(n.id)}>{n.label}</button>)}</nav></div>}
