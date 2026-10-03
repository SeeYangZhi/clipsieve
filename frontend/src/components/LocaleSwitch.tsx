"use client";

import { Button } from "@/components/ui/button";
import { type Locale, t, useLocale } from "@/lib/i18n";

export function LocaleSwitch() {
  const [locale, setLocale] = useLocale();
  const next: Locale = locale === "en" ? "zh" : "en";
  return (
    <Button
      aria-label={t(`locale.${next}`, locale)}
      onClick={() => setLocale(next)}
      size="sm"
      variant="ghost"
    >
      {t(`locale.${next}`, locale)}
    </Button>
  );
}
