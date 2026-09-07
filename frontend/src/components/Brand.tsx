"use client";
import Image from "next/image";
import {useI18n} from "@/lib/i18n";
export function Brand({compact=false}:{compact?:boolean}){const {t}=useI18n();return <div className="brand"><Image src="/brand/logo.svg" alt="" width={compact?32:44} height={compact?32:44} priority/><strong>{t("appName")}</strong></div>}
