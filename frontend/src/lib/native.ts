"use client";

import { AppLauncher } from "@capacitor/app-launcher";
import { Capacitor } from "@capacitor/core";
import type {CommunicationChannel} from "@/lib/types";

export function isNativeApp(): boolean {
  return typeof window !== "undefined" && Capacitor.isNativePlatform();
}

export function externalChannelCapabilities(): CommunicationChannel[] {
  if (typeof window === "undefined") return ["email","whatsapp","telegram"];
  const mobileBrowser = /Android|iPhone|iPad|iPod/i.test(navigator.userAgent);
  const result: CommunicationChannel[] = ["email","whatsapp","telegram"];
  if (Capacitor.isNativePlatform() || mobileBrowser) result.push("sms");
  return result;
}

export async function openExternalUri(url: string): Promise<boolean> {
  if (Capacitor.isNativePlatform()) {
    await AppLauncher.openUrl({ url });
    return true;
  }

  const opened = window.open(url, "_blank", "noopener,noreferrer");
  if (opened) return true;

  // Browsers can block a new window for non-HTTP schemes. Falling back to
  // same-window navigation still hands mailto:/sms: URLs to the OS.
  window.location.href = url;
  return true;
}
