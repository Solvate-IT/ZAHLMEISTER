"use client";

import {Capacitor} from "@capacitor/core";
import {Preferences} from "@capacitor/preferences";

const TOKEN_KEY = "zahlmeister_auth_token";

export async function readToken(): Promise<string | null> {
  if (Capacitor.isNativePlatform()) {
    return (await Preferences.get({key: TOKEN_KEY})).value;
  }
  return typeof window === "undefined" ? null : window.localStorage.getItem(TOKEN_KEY);
}

export async function storeToken(token: string): Promise<void> {
  if (Capacitor.isNativePlatform()) {
    await Preferences.set({key: TOKEN_KEY, value: token});
  } else if (typeof window !== "undefined") {
    window.localStorage.setItem(TOKEN_KEY, token);
  }
}

export async function clearToken(): Promise<void> {
  if (Capacitor.isNativePlatform()) {
    await Preferences.remove({key: TOKEN_KEY});
  } else if (typeof window !== "undefined") {
    window.localStorage.removeItem(TOKEN_KEY);
  }
}
