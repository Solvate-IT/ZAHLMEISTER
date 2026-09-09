"use client";

import { Capacitor } from "@capacitor/core";
import { Contacts } from "@capacitor/contacts";

export interface DeviceContact {
  id: string;
  name: string;
  email: string | null;
  phone: string | null;
}

export interface DeviceContactSelection {
  contacts: DeviceContact[];
  requiresSelection: boolean;
  available: boolean;
}

type ContactNavigator = Navigator & {
  contacts?: {
    select: (
      fields: string[],
      options: { multiple: boolean },
    ) => Promise<Array<{ name?: string[]; email?: string[]; tel?: string[] }>>;
  };
};

function clean(value: string | undefined | null): string | null {
  const result = value?.trim();
  return result ? result : null;
}

export function deviceContactsAvailable(): boolean {
  if (typeof navigator === "undefined") return false;
  if (Capacitor.isNativePlatform()) return true;
  return Boolean((navigator as ContactNavigator).contacts?.select);
}

export async function selectDeviceContacts(): Promise<DeviceContactSelection> {
  if (Capacitor.isNativePlatform()) {
    const contact = await Contacts.pickContact();
    const name = clean(contact.displayName) ?? clean(contact.name?.formatted);
    if (!name) return { contacts: [], requiresSelection: true, available: true };
    return {
      contacts: [{
        id: contact.id ?? `native-${name}`,
        name,
        email: clean(contact.emails?.find((field) => field.pref)?.value) ?? clean(contact.emails?.[0]?.value),
        phone: clean(contact.phoneNumbers?.find((field) => field.pref)?.value) ?? clean(contact.phoneNumbers?.[0]?.value),
      }],
      requiresSelection: true,
      available: true,
    };
  }

  const nav = navigator as ContactNavigator;
  if (!nav.contacts) return { contacts: [], requiresSelection: false, available: false };
  const rows = await nav.contacts.select(["name", "email", "tel"], { multiple: true });
  const contacts = rows
    .map((row, index): DeviceContact | null => {
      const name = clean(row.name?.[0]);
      if (!name) return null;
      return {
        id: `web-${index}-${name}`,
        name,
        email: clean(row.email?.[0]),
        phone: clean(row.tel?.[0]),
      };
    })
    .filter((contact): contact is DeviceContact => contact !== null);
  return { contacts, requiresSelection: false, available: true };
}
