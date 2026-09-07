"use client";
import {useI18n} from "@/lib/i18n";
export function Loading(){const {t}=useI18n();return <div className="state"><div className="spinner"/><span>{t("loading")}</span></div>}
export function ErrorState({onRetry}:{onRetry?:()=>void}){const {t}=useI18n();return <div className="state"><strong>{t("loadError")}</strong>{onRetry&&<button className="button secondary" onClick={onRetry}>{t("retry")}</button>}</div>}
export function Empty({text}:{text?:string}){const {t}=useI18n();return <div className="empty">{text??t("noData")}</div>}
