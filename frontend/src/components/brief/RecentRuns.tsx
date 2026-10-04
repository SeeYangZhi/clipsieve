"use client";

import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { t, useLocale } from "@/lib/i18n";
import type { Run } from "@/lib/types";

function runHref(run: Run): string {
  const base = `/runs/${encodeURIComponent(run.id)}`;
  return run.stage === "planning" ? `${base}/plan` : base;
}

export function RecentRuns({ runs }: { runs: Run[] }) {
  const [locale] = useLocale();
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("brief.recent_runs", locale)}</CardTitle>
      </CardHeader>
      <CardContent>
        {runs.length === 0 ? (
          <p className="text-muted-foreground text-sm">
            {t("brief.no_runs", locale)}
          </p>
        ) : (
          <ul className="flex flex-col gap-2">
            {runs.map((r) => (
              <li
                className="flex items-center justify-between gap-3 text-sm"
                key={r.id}
              >
                <Link
                  className="min-w-0 truncate underline-offset-2 hover:underline"
                  href={runHref(r)}
                >
                  {r.brief.text}
                </Link>
                <Badge variant="outline">
                  {t(`run.stage.${r.stage}`, locale)}
                </Badge>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
