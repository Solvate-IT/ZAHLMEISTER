"use client";

import { AppLauncher } from "@capacitor/app-launcher";
import { Capacitor } from "@capacitor/core";

export async function openExternalUri(url: string): Promise<boolean> {
  if (Capacitor.isNativePlatform()) {
    await AppLauncher.openUrl({ url });
    return true;
  }

  const opened = window.open(url, "_blank", "noopener,noreferrer");
  if (opened) return true;

  // Browsers can block a new window for non-HTTP schemes. Falling back to
  // same-window navigation still hands mailto:/sms:/whatsapp: URLs to the OS.
  window.location.href = url;
  return true;
}
