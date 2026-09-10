"use client";

import {useState} from "react";
import {useRouter} from "next/navigation";
import {clearSupportSession,getSupportSessionInfo} from "@/lib/session";
import {endSupportSessionRemote} from "@/lib/support";
import {useI18n} from "@/lib/i18n";

export function SupportSessionBanner(){
  const router=useRouter();
  const {t,locale}=useI18n();
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const info=getSupportSessionInfo();
  if(!info)return null;

  async function endSupport(){
    setBusy(true);setError("");
    try{
      await endSupportSessionRemote();
      clearSupportSession();
      router.replace("/admin");
      router.refresh();
    }catch{
      setError(t("supportEndError"));
    }finally{
      setBusy(false);
    }
  }

  const expiry=new Date(info.expires_at).toLocaleTimeString(locale,{hour:"2-digit",minute:"2-digit"});
  return <div className="support-session-banner" role="status">
    <div><strong>{t("supportReadOnly")}</strong><span>{t("supportViewingAs",{name:info.user_name||info.user_email,organization:info.organization_name})}</span><span className="muted">{t("supportExpiresAt",{time:expiry})}</span>{error&&<span className="danger-text">{error}</span>}</div>
    <button type="button" className="button secondary small" disabled={busy} onClick={()=>void endSupport()}>{t("supportReturnAdmin")}</button>
  </div>;
}
