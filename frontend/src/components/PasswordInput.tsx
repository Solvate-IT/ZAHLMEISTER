"use client";

import {useState} from "react";
import type {InputHTMLAttributes} from "react";
import {useI18n} from "@/lib/i18n";
import styles from "./PasswordInput.module.css";

type PasswordInputProps = Omit<InputHTMLAttributes<HTMLInputElement>, "type">;

export function PasswordInput({className,...props}:PasswordInputProps){
  const {t}=useI18n();
  const [visible,setVisible]=useState(false);
  const label=visible?t("hidePassword"):t("showPassword");

  return <div className={styles.wrapper}>
    <input {...props} className={`${className??"input"} ${styles.input}`} type={visible?"text":"password"}/>
    <button
      className={styles.toggle}
      type="button"
      aria-label={label}
      aria-pressed={visible}
      title={label}
      onClick={()=>setVisible(value=>!value)}
    >
      {visible?
        <svg className={styles.icon} viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M3 3l18 18"/><path d="M10.6 10.6a2 2 0 002.8 2.8"/><path d="M9.9 4.2A10.8 10.8 0 0112 4c5 0 8.7 4.3 9.6 5.5a.8.8 0 010 1c-.5.7-1.9 2.4-4 3.7"/><path d="M6.2 6.2C4.3 7.4 3 9 2.4 9.5a.8.8 0 000 1C3.3 11.7 7 16 12 16c1 0 1.9-.2 2.8-.5"/></svg>
        :<svg className={styles.icon} viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M2.4 9.5C3.3 8.3 7 4 12 4s8.7 4.3 9.6 5.5a.8.8 0 010 1C20.7 11.7 17 16 12 16s-8.7-4.3-9.6-5.5a.8.8 0 010-1z"/><circle cx="12" cy="10" r="2.5"/></svg>}
    </button>
  </div>;
}
