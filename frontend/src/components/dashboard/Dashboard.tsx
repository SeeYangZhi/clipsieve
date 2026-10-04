"use client";

import { CircleAlert } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  answersPerSecond,
  type DashboardState,
  failureMessage,
} from "@/lib/events";
import { t, useLocale } from "@/lib/i18n";
import type { RunEvent } from "@/lib/types";
import { Aggregates } from "./Aggregates";
import { Counters } from "./Counters";
import { CurrentItem } from "./CurrentItem";
import { PostGrid } from "./PostGrid";
import { ReviewBucket } from "./ReviewBucket";

export type DashboardMode = "live" | "replay";

interface Props {
  connected: boolean;
  /** Extra header actions, e.g. the live page's pause/resume. */
  controls?: ReactNode;
  /** The stored run's `error`; shown when the log carries no failure message. */
  error?: string | null;
  events: RunEvent[];
  /** Live shows the connection badge and a Replay link; replay shows a Back-to-run link. */
  mode: DashboardMode;
  runId: string;
  state: DashboardState;
  /** Posts expected (the plan's quantities); defaults to the collected count. */
  total?: number;
}

export function Dashboard({
  runId,
  state,
  events,
  connected,
  mode,
  total,
  controls,
  error,
}: Props) {
  const [locale] = useLocale();
  const base = `/runs/${encodeURIComponent(runId)}`;
  const failed = state.stage === "failed";
  const failure = failed ? (failureMessage(state.errors) ?? error) : null;
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <h1 className="font-semibold text-lg">{t("run.title", locale)}</h1>
          <Badge>{t(`run.stage.${state.stage}`, locale)}</Badge>
          {/* A finished run's stream is closed on purpose, and a replay plays a
              log it already holds: neither is reconnecting. */}
          {state.done || mode === "replay" ? null : (
            <Badge variant={connected ? "secondary" : "destructive"}>
              {t(connected ? "run.connected" : "run.disconnected", locale)}
            </Badge>
          )}
        </div>
        <div className="flex items-center gap-2">
          {controls}
          {/* `done` is also true for a failed run, which has no report. */}
          {state.stage === "done" ? (
            <Button asChild size="sm">
              <Link href={`${base}/report`}>
                {t("run.view_report", locale)}
              </Link>
            </Button>
          ) : null}
          <Button asChild size="sm" variant="outline">
            {mode === "replay" ? (
              <Link href={base}>{t("run.back_to_run", locale)}</Link>
            ) : (
              <Link href={`${base}/replay`}>
                {t("run.view_replay", locale)}
              </Link>
            )}
          </Button>
        </div>
      </div>
      {failed ? (
        <Alert variant="destructive">
          <CircleAlert aria-hidden="true" />
          <AlertTitle>{t("run.failed", locale)}</AlertTitle>
          {failure ? <AlertDescription>{failure}</AlertDescription> : null}
        </Alert>
      ) : null}
      <Counters counters={state.counters} rate={answersPerSecond(events)} />
      <div className="grid gap-4 lg:grid-cols-[3fr_2fr]">
        <PostGrid
          posts={state.posts}
          runId={runId}
          total={total ?? state.counters.collected}
        />
        <div className="flex flex-col gap-4">
          <CurrentItem latest={state.latest} />
          <Aggregates aggregates={state.aggregates} />
          <ReviewBucket posts={state.posts} review={state.review} />
        </div>
      </div>
    </div>
  );
}
