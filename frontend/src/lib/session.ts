"use client";

import {Capacitor} from "@capacitor/core";
import {Preferences} from "@capacitor/preferences";

const TOKEN_KEY = "zahlmeister_auth_token";
const SUPPORT_TOKEN_KEY = "zahlmeister_support_token";
const SUPPORT_INFO_KEY = "zahlmeister_support_info";

export interface SupportSessionInfo {
  user_id: string;
  user_name: string;
  user_email: string;
  organization_id: string;
  organization_name: string;
  expires_at: string;
  read_only: true;
}

function supportToken(): string | null {
  if (Capacitor.isNativePlatform() || typeof window === "undefined") return null;
  return window.sessionStorage.getItem(SUPPORT_TOKEN_KEY);
}

export function isSupportSession(): boolean {
  return Boolean(supportToken());
}

export function getSupportSessionInfo(): SupportSessionInfo | null {
  if (Capacitor.isNativePlatform() || typeof window === "undefined") return null;
  const raw = window.sessionStorage.getItem(SUPPORT_INFO_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as SupportSessionInfo;
  } catch {
    return null;
  }
}

export function startSupportSession(
  accessToken: string,
  info: SupportSessionInfo,
): void {
  if (Capacitor.isNativePlatform() || typeof window === "undefined") return;
  window.sessionStorage.setItem(SUPPORT_TOKEN_KEY, accessToken);
  window.sessionStorage.setItem(SUPPORT_INFO_KEY, JSON.stringify(info));
}

export function clearSupportSession(): void {
  if (Capacitor.isNativePlatform() || typeof window === "undefined") return;
  window.sessionStorage.removeItem(SUPPORT_TOKEN_KEY);
  window.sessionStorage.removeItem(SUPPORT_INFO_KEY);
}

export async function readToken(): Promise<string | null> {
  if (Capacitor.isNativePlatform()) {
    return (await Preferences.get({key: TOKEN_KEY})).value;
  }
  if (typeof window === "undefined") return null;
  return supportToken() ?? window.localStorage.getItem(TOKEN_KEY);
}

export async function storeToken(token: string): Promise<void> {
  if (Capacitor.isNativePlatform()) {
    await Preferences.set({key: TOKEN_KEY, value: token});
  } else if (typeof window !== "undefined") {
    if (isSupportSession()) window.sessionStorage.setItem(SUPPORT_TOKEN_KEY, token);
    else window.localStorage.setItem(TOKEN_KEY, token);
  }
}

export async function clearToken(): Promise<void> {
  if (Capacitor.isNativePlatform()) {
    await Preferences.remove({key: TOKEN_KEY});
  } else if (typeof window !== "undefined") {
    if (isSupportSession()) clearSupportSession();
    else window.localStorage.removeItem(TOKEN_KEY);
  }
}
