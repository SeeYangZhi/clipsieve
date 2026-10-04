"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { type Locale, t, tOr, useLocale } from "@/lib/i18n";

/** Addendum D.5: the category picture is hook type, format and persona fit. */
const SHOWN = ["hook_type", "format", "persona_fit"] as const;
type Shown = (typeof SHOWN)[number];

function bucketLabel(qid: Shown, label: string, locale: Locale): string {
  // persona_fit is counted by rounded level, not by a choice label.
  return qid === "persona_fit"
    ? t("plan.persona_criteria.level", locale, { n: label })
    : tOr(`label.${label}`, label, locale);
}

function Distribution({
  qid,
  row,
  locale,
}: {
  locale: Locale;
  qid: Shown;
  row: Record<string, number>;
}) {
  const total = Object.values(row).reduce((a, b) => a + b, 0) || 1;
  const entries = Object.entries(row).sort((a, b) => b[1] - a[1]);
  return (
    <div className="flex flex-col gap-2">
      <h3 className="text-muted-foreground text-xs uppercase tracking-wide">
        {t(`aggregates.${qid}`, locale)}
      </h3>
      {entries.map(([label, n]) => {
        const name = bucketLabel(qid, label, locale);
        const pct = Math.round((n / total) * 100);
        return (
          <div className="flex flex-col gap-1 text-sm" key={label}>
            <div className="flex justify-between gap-2">
              <span>{name}</span>
              <span className="font-mono text-xs tabular-nums">{pct}%</span>
            </div>
            <Progress aria-label={name} value={(n / total) * 100} />
          </div>
        );
      })}
    </div>
  );
}

export function Aggregates({
  aggregates,
}: {
  aggregates: Record<string, Record<string, number>>;
}) {
  const [locale] = useLocale();
  const empty = SHOWN.every((q) => !aggregates[q]);
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("aggregates.title", locale)}</CardTitle>
      </CardHeader>
      <CardContent>
        {empty ? (
          <p className="text-muted-foreground text-sm">
            {t("aggregates.empty", locale)}
          </p>
        ) : (
          <div className="grid gap-6 sm:grid-cols-3">
            {SHOWN.map((qid) => (
              <Distribution
                key={qid}
                locale={locale}
                qid={qid}
                row={aggregates[qid] ?? {}}
              />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
