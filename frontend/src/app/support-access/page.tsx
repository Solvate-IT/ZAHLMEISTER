"use client";

import {useEffect,useState} from "react";
import {useRouter} from "next/navigation";
import {startSupportSession} from "@/lib/session";
import {useI18n} from "@/lib/i18n";

export default function SupportAccessPage(){
  const router=useRouter();
  const {t}=useI18n();
  const [failed,setFailed]=useState(false);

  useEffect(()=>{
    try{
      const fragment=new URLSearchParams(window.location.hash.replace(/^#/,""));
      const accessToken=fragment.get("access_token")||"";
      const expiresAt=fragment.get("expires_at")||"";
      const userId=fragment.get("user_id")||"";
      const userName=fragment.get("user_name")||"";
      const userEmail=fragment.get("user_email")||"";
      const organizationId=fragment.get("organization_id")||"";
      const organizationName=fragment.get("organization_name")||"";
      window.history.replaceState(null,"","/support-access");
      if(!accessToken||!expiresAt||!userId||!organizationId)throw new Error("invalid support handoff");
      startSupportSession(accessToken,{
        user_id:userId,
        user_name:userName,
        user_email:userEmail,
        organization_id:organizationId,
        organization_name:organizationName,
        expires_at:expiresAt,
        read_only:true,
      });
      router.replace("/app");
    }catch{
      setFailed(true);
    }
  },[router]);

  return <div className="auth-wrap"><div className="auth-card"><p>{t(failed?"supportSessionOpenError":"supportOpening")}</p></div></div>;
}
