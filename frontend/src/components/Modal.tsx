"use client";
import {useEffect,type CSSProperties} from "react";
import {useI18n} from "@/lib/i18n";

export function Modal({title,onClose,children,wide=false,large=false,resizable=false}:{title:string;onClose:()=>void;children:React.ReactNode;wide?:boolean;large?:boolean;resizable?:boolean}){
  const {t}=useI18n();
  useEffect(()=>{const h=(e:KeyboardEvent)=>{if(e.key==="Escape")onClose()};window.addEventListener("keydown",h);return()=>window.removeEventListener("keydown",h)},[onClose]);
  const style:CSSProperties={};
  if(large)style.width="min(1080px, calc(100vw - 36px))";
  if(resizable){style.resize="both";style.overflow="hidden";style.minWidth="min(680px, calc(100vw - 36px))";style.minHeight="min(620px, calc(100vh - 36px))";style.maxWidth="calc(100vw - 36px)";style.maxHeight="calc(100vh - 36px)"}
  return <div className="modal-backdrop" role="presentation" onMouseDown={e=>{if(e.currentTarget===e.target)onClose()}}><section className={`modal ${wide?"wide":""}`} style={style} role="dialog" aria-modal="true" aria-label={title}><header><h2>{title}</h2><button className="icon-button" onClick={onClose} aria-label={t("closeDialog")}>×</button></header><div className="modal-body" style={{flex:1,minHeight:0}}>{children}</div></section></div>
}
