"use client";
import {useEffect} from "react";
import {useI18n} from "@/lib/i18n";

export function Modal({title,onClose,children,wide=false,large=false,resizable=false}:{title:string;onClose:()=>void;children:React.ReactNode;wide?:boolean;large?:boolean;resizable?:boolean}){
  const {t}=useI18n();
  useEffect(()=>{const h=(e:KeyboardEvent)=>{if(e.key==="Escape")onClose()};window.addEventListener("keydown",h);return()=>window.removeEventListener("keydown",h)},[onClose]);
  const classes=["modal",wide?"wide":"",large?"large":"",resizable?"resizable":""].filter(Boolean).join(" ");
  return <div className="modal-backdrop" role="presentation" onMouseDown={e=>{if(e.currentTarget===e.target)onClose()}}><section className={classes} role="dialog" aria-modal="true" aria-label={title}><header><h2>{title}</h2><button className="icon-button" onClick={onClose} aria-label={t("closeDialog")}>×</button></header><div className="modal-body">{children}</div></section></div>
}
