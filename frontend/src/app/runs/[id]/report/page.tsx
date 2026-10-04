"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { ReportView } from "@/components/report/ReportView";
import { Button } from "@/components/ui/button";
import { ApiError, api, type PostView } from "@/lib/api";
import { t, useLocale } from "@/lib/i18n";
import type { Report } from "@/lib/types";

/** Posts per request while indexing the run's posts for citations. */
const PAGE_SIZE = 500;

/** What the report load ended in, tagged with the id it was for. */
type Loaded =
  | {
      id: string;
      posts: Record<string, PostView>;
      report: Report;
      status: "ready";
    }
  | { id: string; status: "not_ready" }
  | { detail: string | null; id: string; status: "failed" };

/** Every post of the run, page by page; stops early once `active()` is false. */
async function allPosts(
  id: string,
  active: () => boolean
): Promise<PostView[]> {
  const all: PostView[] = [];
  for (;;) {
    // Each page's offset depends on the previous page, so they cannot overlap.
    // biome-ignore lint/performance/noAwaitInLoops: sequential paging
    const page = await api.getPosts(id, all.length, PAGE_SIZE);
    all.push(...page.items);
    if (!active() || page.items.length === 0 || all.length >= page.total) {
      return all;
    }
  }
}

/** The report and an index of the run's posts; a 404 means not written yet. */
async function load(id: string, active: () => boolean): Promise<Loaded> {
  try {
    const report = await api.getReport(id);
    const posts = await allPosts(id, active);
    return {
      id,
      posts: Object.fromEntries(posts.map((v) => [v.post.id, v])),
      report,
      status: "ready",
    };
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) {
      return { id, status: "not_ready" };
    }
    const detail = e instanceof ApiError ? e.detail : null;
    return { detail, id, status: "failed" };
  }
}

export default function ReportPage() {
  const { id } = useParams<{ id: string }>();
  const [locale] = useLocale();
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [attempt, setAttempt] = useState(0);

  // biome-ignore lint/correctness/useExhaustiveDependencies: `attempt` is the Retry trigger
  useEffect(() => {
    let active = true;
    load(id, () => active).then((result) => {
      if (active) {
        setLoaded(result);
      }
    });
    return () => {
      active = false;
    };
  }, [id, attempt]);

  const retry = useCallback(() => {
    setLoaded(null);
    setAttempt((a) => a + 1);
  }, []);

  const back = (
    <Button asChild className="self-start" size="sm" variant="outline">
      <Link href={`/runs/${encodeURIComponent(id)}`}>
        <ArrowLeft aria-hidden="true" data-icon="inline-start" />
        {t("report.back_to_run", locale)}
      </Link>
    </Button>
  );

  // Ignore a response for a previous id until this id's load lands.
  const current = loaded?.id === id ? loaded : null;
  if (current === null) {
    return (
      <p className="text-muted-foreground text-sm">
        {t("report.loading", locale)}
      </p>
    );
  }
  if (current.status === "not_ready") {
    return (
      <div className="flex flex-col items-start gap-3">
        <p className="text-muted-foreground text-sm">
          {t("report.not_ready", locale)}
        </p>
        {back}
      </div>
    );
  }
  if (current.status === "failed") {
    return (
      <div className="flex flex-col items-start gap-3">
        <p className="text-destructive text-sm" role="alert">
          {current.detail ?? t("common.error", locale)}
        </p>
        <div className="flex gap-2">
          <Button onClick={retry} size="sm" variant="outline">
            {t("common.retry", locale)}
          </Button>
          {back}
        </div>
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-4">
      {back}
      <ReportView posts={current.posts} report={current.report} runId={id} />
    </div>
  );
}
