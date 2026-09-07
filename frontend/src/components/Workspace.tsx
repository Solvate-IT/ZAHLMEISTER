"use client";

import {useEffect, useState} from "react";
import {useRouter, useSearchParams} from "next/navigation";
import {api} from "@/lib/api";
import type {AccountUser} from "@/lib/types";
import {useI18n} from "@/lib/i18n";
import {Brand} from "./Brand";
import {LocaleSelect} from "./LocaleSelect";
import {Loading} from "./State";
import {OverviewPage} from "./workspace/OverviewPage";
import {ListsPage} from "./workspace/ListsPage";
import {CollectionsPage} from "./workspace/CollectionsPage";
import {SettingsPage} from "./workspace/SettingsPage";

type View="overview"|"lists"|"collections"|"settings";

export function Workspace(){const router=useRouter();const params=useSearchParams();const {t,setLocale}=useI18n();const [user,setUser]=useState<AccountUser|null>(null);const [loading,setLoading]=useState(true);const raw=params.get("view");const view:View=raw==="lists"||raw==="collections"||raw==="settings"?raw:"overview";
  useEffect(()=>{api.restore().then(u=>{if(!u){router.replace("/?auth=login");return}setUser(u);if(u.locale)setLocale(u.locale)}).catch(()=>router.replace("/?auth=login")).finally(()=>setLoading(false))},[router,setLocale]);
  function navigate(next:View){const url=new URL(window.location.href);url.searchParams.set("view",next);url.searchParams.delete("id");router.push(`${url.pathname}?${url.searchParams}`)}
  async function logout(){await api.logout();router.replace("/")}
  if(loading||!user)return <div className="auth-wrap"><Loading/></div>;
  const nav=[{id:"overview" as View,label:t("overview")},{id:"lists" as View,label:t("participantLists")},{id:"collections" as View,label:t("collections")},{id:"settings" as View,label:t("configuration")}];
  return <div className="workspace"><aside className="sidebar"><Brand compact/><nav className="nav">{nav.map(n=><button key={n.id} className={view===n.id?"active":""} onClick={()=>navigate(n.id)}>{n.label}</button>)}</nav><div className="sidebar-bottom"><div className="card"><strong>{user.display_name}</strong><div className="muted">{user.organization_name}</div></div><button className="button ghost" onClick={logout}>{t("logout")}</button></div></aside><main className="workspace-main"><header className="workspace-header"><div><strong>{nav.find(n=>n.id===view)?.label}</strong></div><div className="top-actions"><LocaleSelect/><span className="hide-mobile muted">{user.email}</span><button className="button secondary small" onClick={logout}>{t("logout")}</button></div></header><div className="workspace-body">{view==="overview"&&<OverviewPage onNavigate={navigate}/>} {view==="lists"&&<ListsPage/>}{view==="collections"&&<CollectionsPage/>}{view==="settings"&&<SettingsPage user={user} onUser={setUser} onDeleted={()=>router.replace("/")}/>}</div></main><nav className="mobile-nav">{nav.map(n=><button key={n.id} className={view===n.id?"active":""} onClick={()=>navigate(n.id)}>{n.label}</button>)}</nav></div>}
