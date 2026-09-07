"use client";

import {useEffect} from "react";
import {useRouter} from "next/navigation";
import {Capacitor} from "@capacitor/core";
import {App} from "@capacitor/app";

function routeForUrl(raw: string): string | null {
  try {
    const url = new URL(raw);
    const paymentToken = url.searchParams.get("pay") ?? (url.hostname === "payment" || url.pathname.replace(/\/$/, "") === "/payment" ? url.searchParams.get("token") : null);
    if (paymentToken) return `/payment/?token=${encodeURIComponent(paymentToken)}`;
    const action = url.searchParams.get("action") ?? (url.hostname === "action" ? url.searchParams.get("type") : null);
    const token = url.searchParams.get("token");
    if (action && token) return `/action/?action=${encodeURIComponent(action)}&token=${encodeURIComponent(token)}`;
  } catch {}
  return null;
}

export function NativeBridge() {
  const router = useRouter();
  useEffect(() => {
    if (!Capacitor.isNativePlatform()) return;
    let active = true;
    let remove: (() => Promise<void>) | null = null;
    App.addListener("appUrlOpen", event => {
      if (!active) return;
      const route = routeForUrl(event.url);
      if (route) router.replace(route);
    }).then(handle => { remove = () => handle.remove(); }).catch(() => {});
    App.getLaunchUrl().then(result => {
      if (!active || !result?.url) return;
      const route = routeForUrl(result.url);
      if (route) router.replace(route);
    }).catch(() => {});
    return () => { active = false; if (remove) void remove(); };
  }, [router]);
  return null;
}
