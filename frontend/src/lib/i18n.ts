"use client";

import { useSyncExternalStore } from "react";
import { en } from "./i18n/en";
import { zh } from "./i18n/zh";

export type Locale = "en" | "zh";
export const STORAGE_KEY = "clipsieve.locale";

const dictionaries: Record<Locale, Record<string, string>> = { en, zh };

export function detectLocale(language: string | undefined): Locale {
  return language?.toLowerCase().startsWith("zh") ? "zh" : "en";
}

export function t(
  key: string,
  locale: Locale,
  vars?: Record<string, string | number>
): string {
  const template = dictionaries[locale][key] ?? dictionaries.en[key] ?? key;
  if (!vars) {
    return template;
  }
  return template.replace(/\{(\w+)\}/g, (match, name: string) =>
    name in vars ? String(vars[name]) : match
  );
}

export function tOr(key: string, fallback: string, locale: Locale): string {
  return dictionaries[locale][key] ?? dictionaries.en[key] ?? fallback;
}

let current: Locale | null = null;
const listeners = new Set<() => void>();

function readLocale(): Locale {
  if (current) {
    return current;
  }
  let stored: string | null = null;
  try {
    stored = window.localStorage.getItem(STORAGE_KEY);
  } catch {
    stored = null;
  }
  current =
    stored === "zh" || stored === "en"
      ? stored
      : detectLocale(navigator.language);
  return current;
}

export function setLocale(locale: Locale): void {
  current = locale;
  try {
    window.localStorage.setItem(STORAGE_KEY, locale);
  } catch {
    // storage unavailable; keep in memory
  }
  for (const fn of listeners) {
    fn();
  }
}

function subscribe(fn: () => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function useLocale(): [Locale, (l: Locale) => void] {
  const locale = useSyncExternalStore(
    subscribe,
    readLocale,
    () => "en" as Locale
  );
  return [locale, setLocale];
}
