"use client";

import Link from "next/link";
import {useEffect, useState} from "react";

type ToastDetail = {message: string; kind?: "error" | "success"; action?: {label: string; href: string}};
const eventName = "zahlmeister:toast";

export function showToast(detail: ToastDetail) {
  window.dispatchEvent(new CustomEvent<ToastDetail>(eventName, {detail}));
}

export function ToastHost() {
  const [toast, setToast] = useState<(ToastDetail & {id: number}) | null>(null);
  useEffect(() => {
    const onToast = (event: Event) => setToast({...((event as CustomEvent<ToastDetail>).detail), id: Date.now()});
    window.addEventListener(eventName, onToast);
    return () => window.removeEventListener(eventName, onToast);
  }, []);
  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(null), toast.action ? 8000 : 2000);
    return () => window.clearTimeout(timer);
  }, [toast]);
  if (!toast) return null;
  return <div className={`toast app-toast ${toast.kind === "error" ? "error" : ""}`} role={toast.kind === "error" ? "alert" : "status"}>
    <span>{toast.message}</span>{toast.action && <Link href={toast.action.href} onClick={() => setToast(null)}>{toast.action.label} →</Link>}
  </div>;
}
