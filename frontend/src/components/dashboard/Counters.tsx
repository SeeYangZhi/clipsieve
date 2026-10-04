"use client";

import { Card, CardContent } from "@/components/ui/card";
import { type Locale, t, useLocale } from "@/lib/i18n";
import type { Counters as CountersT } from "@/lib/types";

export function formatCost(usd: number): string {
  return `$${usd.toFixed(4)}`;
}

/** 12.2s under a minute, then 4m 05s, then 1h 02m (localised units). */
export function formatElapsed(seconds: number, locale: Locale): string {
  if (seconds < 60) {
    return t("duration.seconds", locale, { s: seconds.toFixed(1) });
  }
  const whole = Math.floor(seconds);
  const pad = (n: number) => String(n).padStart(2, "0");
  if (whole < 3600) {
    return t("duration.minutes", locale, {
      m: Math.floor(whole / 60),
      s: pad(whole % 60),
    });
  }
  return t("duration.hours", locale, {
    h: Math.floor(whole / 3600),
    m: pad(Math.floor((whole % 3600) / 60)),
  });
}

export function Counters({
  counters,
  rate,
}: {
  counters: CountersT;
  rate: number;
}) {
  const [locale] = useLocale();
  const tiles: [string, string][] = [
    ["counters.collected", String(counters.collected)],
    ["counters.pass_one_kept", String(counters.pass_one_kept)],
    ["counters.judged", String(counters.judged)],
    ["counters.answers_per_sec", rate.toFixed(1)],
    ["counters.elapsed", formatElapsed(counters.elapsed_s, locale)],
    ["counters.cost", formatCost(counters.jev_cost_usd)],
  ];
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
      {tiles.map(([key, value]) => (
        <Card key={key} size="sm">
          <CardContent className="flex flex-col gap-1">
            <span className="text-muted-foreground text-xs uppercase tracking-wide">
              {t(key, locale)}
            </span>
            <span className="font-mono text-2xl tabular-nums">{value}</span>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
