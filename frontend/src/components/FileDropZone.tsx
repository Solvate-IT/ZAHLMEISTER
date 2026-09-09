"use client";

import {useRef,useState} from "react";
import styles from "./FileDropZone.module.css";

type CaptureMode="user"|"environment";

export function FileDropZone({accept,disabled=false,file,label,hint,selectLabel,dropLabel,capture,onFile}:{accept:string;disabled?:boolean;file?:File|null;label?:string;hint:string;selectLabel:string;dropLabel:string;capture?:CaptureMode;onFile:(file:File)=>void}){
  const inputRef=useRef<HTMLInputElement|null>(null);
  const [dragging,setDragging]=useState(false);

  function choose(){if(!disabled)inputRef.current?.click()}
  function picked(next:File|undefined){if(next&&!disabled)onFile(next)}

  return <div className="field">
    {label&&<label>{label}</label>}
    <div
      className={`${styles.zone}${dragging?` ${styles.dragging}`:""}${disabled?` ${styles.disabled}`:""}`}
      role="button"
      tabIndex={disabled?-1:0}
      aria-disabled={disabled}
      onClick={choose}
      onKeyDown={event=>{if(event.key==="Enter"||event.key===" "){event.preventDefault();choose()}}}
      onDragEnter={event=>{event.preventDefault();if(!disabled)setDragging(true)}}
      onDragOver={event=>{event.preventDefault();if(!disabled){event.dataTransfer.dropEffect="copy";setDragging(true)}}}
      onDragLeave={event=>{event.preventDefault();setDragging(false)}}
      onDrop={event=>{event.preventDefault();setDragging(false);picked(event.dataTransfer.files?.[0])}}
    >
      <input ref={inputRef} className="hidden" type="file" accept={accept} capture={capture} disabled={disabled} onClick={event=>event.stopPropagation()} onChange={event=>{picked(event.target.files?.[0]);event.currentTarget.value=""}}/>
      <strong>{file?.name??dropLabel}</strong>
      <span className="muted">{file?selectLabel:hint}</span>
    </div>
  </div>
}
