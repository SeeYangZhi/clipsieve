"use client";

import Link from "next/link";
import { LocaleSwitch } from "@/components/LocaleSwitch";
import { t, useLocale } from "@/lib/i18n";

export function AppHeader() {
  const [locale] = useLocale();
  return (
    <header className="flex items-center justify-between border-b px-6 py-3">
      <Link className="font-semibold tracking-tight" href="/">
        {t("app.title", locale)}
      </Link>
      <LocaleSwitch />
    </header>
  );
}
