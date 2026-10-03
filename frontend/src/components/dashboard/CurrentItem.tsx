"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import type { DashboardState } from "@/lib/events";
import { type Locale, t, tOr, useLocale } from "@/lib/i18n";
import type { JudgeAnswer } from "@/lib/types";

export function answerLabel(a: JudgeAnswer, locale: Locale): string {
  if (a.type === "choice") {
    return tOr(`label.${String(a.value)}`, String(a.value), locale);
  }
  if (a.type === "score") {
    const levels = a.legend ? Object.keys(a.legend).length : 5;
    return t("current.score", locale, {
      levels,
      value: Number(a.value).toFixed(1),
    });
  }
  return `${Math.round(Number(a.value) * 100)}%`;
}

/** Noul answers show their probability; choice and score their confidence. */
export function answerMetric(a: JudgeAnswer): {
  kind: "confidence" | "probability";
  value: number;
} {
  if (a.type === "noul") {
    return { kind: "probability", value: Number(a.value) };
  }
  return { kind: "confidence", value: a.confidence ?? 0 };
}

function AnswerRow({
  qid,
  answer,
  locale,
}: {
  answer: JudgeAnswer;
  locale: Locale;
  qid: string;
}) {
  const question = tOr(`question.${qid}`, qid, locale);
  const m = answerMetric(answer);
  const pct = Math.round(m.value * 100);
  return (
    <div className="contents">
      <dt className="text-muted-foreground text-xs uppercase tracking-wide">
        {question}
      </dt>
      <dd>{answerLabel(answer, locale)}</dd>
      <dd>
        <Progress
          aria-label={`${question}: ${t(`current.${m.kind}`, locale)}`}
          value={m.value * 100}
        />
      </dd>
      <dd className="text-right font-mono text-xs tabular-nums">{pct}%</dd>
    </div>
  );
}

export function CurrentItem({ latest }: { latest: DashboardState["latest"] }) {
  const [locale] = useLocale();
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("current.title", locale)}</CardTitle>
      </CardHeader>
      <CardContent>
        {latest ? (
          <div className="flex flex-col gap-3">
            <div>
              <p className="font-medium">
                {latest.post.text.title ??
                  latest.post.text.caption ??
                  latest.post.id}
              </p>
              <p className="text-muted-foreground text-xs">
                {latest.post.platform} ·{" "}
                {t(`post.kind.${latest.post.kind}`, locale)} ·{" "}
                {t("current.tokens", locale, {
                  ms: latest.judge.latency_ms,
                  tokens: latest.judge.input_tokens,
                })}
              </p>
            </div>
            <dl className="grid grid-cols-[minmax(7rem,auto)_minmax(6rem,auto)_1fr_3rem] items-center gap-x-3 gap-y-2 text-sm">
              {Object.entries(latest.judge.answers).map(([qid, a]) => (
                <AnswerRow answer={a} key={qid} locale={locale} qid={qid} />
              ))}
            </dl>
            <p className="text-sm">
              <span className="text-muted-foreground">
                {t("current.composite", locale)}:{" "}
              </span>
              <span className="font-mono">{latest.composite.toFixed(2)}</span>
            </p>
          </div>
        ) : (
          <p className="text-muted-foreground text-sm">
            {t("current.empty", locale)}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
