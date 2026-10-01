"use client";

import {useEffect, useRef} from "react";
import {useI18n} from "@/lib/i18n";
import styles from "./UserMenu.module.css";

export function UserMenu({name, onLists, onSettings, onLogout}: {
  name: string;
  onLists: () => void;
  onSettings: () => void;
  onLogout?: () => void;
}) {
  const {t} = useI18n();
  const details = useRef<HTMLDetailsElement>(null);
  const trigger = useRef<HTMLElement>(null);
  const openedByHover = useRef(false);

  useEffect(() => {
    function closeOutside(event: PointerEvent | FocusEvent) {
      if (event.target instanceof Node && !details.current?.contains(event.target)) {
        details.current?.removeAttribute("open");
      }
    }
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape" && details.current?.open) {
        details.current.open = false;
        trigger.current?.focus();
      }
    }
    document.addEventListener("pointerdown", closeOutside);
    document.addEventListener("focusin", closeOutside);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOutside);
      document.removeEventListener("focusin", closeOutside);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, []);

  function select(action: () => void) {
    details.current?.removeAttribute("open");
    action();
  }

  return <details ref={details} className={styles.menu}
    onPointerEnter={event => {
      if (event.pointerType === "mouse" && !event.currentTarget.open) {
        openedByHover.current = true;
        event.currentTarget.open = true;
      }
    }}
    onPointerLeave={event => {
      if (event.pointerType === "mouse" && !event.currentTarget.contains(document.activeElement)) {
        event.currentTarget.open = false;
      }
    }}>
    <summary ref={trigger} className={styles.trigger} onClick={event => {
      // The first mouse click must not undo opening on pointer entry.
      if (event.detail > 0 && openedByHover.current && details.current?.open) {
        event.preventDefault();
      }
      openedByHover.current = false;
    }}>
      <span>{name}</span><svg viewBox="0 0 16 16" aria-hidden="true"><path d="m4 6 4 4 4-4"/></svg>
    </summary>
    <div className={styles.options}>
      <button className={styles.mobileOnly} type="button" onClick={() => select(onLists)}>{t("participantLists")}</button>
      <button type="button" onClick={() => select(onSettings)}>{t("settings")}</button>
      {onLogout && <button type="button" onClick={() => select(onLogout)}>{t("logout")}</button>}
    </div>
  </details>;
}
