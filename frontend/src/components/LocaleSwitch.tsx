"use client";

import { useCallback } from "react";
import { Button } from "@/components/ui/button";
import { type Locale, t, useLocale } from "@/lib/i18n";

export function LocaleSwitch() {
  const [locale, setLocale] = useLocale();
  const next: Locale = locale === "en" ? "zh" : "en";
  const toggle = useCallback(() => setLocale(next), [setLocale, next]);
  return (
    <Button
      aria-label={t(`locale.${next}`, locale)}
      onClick={toggle}
      size="sm"
      variant="ghost"
    >
      {t(`locale.${next}`, locale)}
    </Button>
  );
}
