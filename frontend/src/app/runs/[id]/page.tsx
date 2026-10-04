"use client";

import { Pause, Play } from "lucide-react";
import { useParams } from "next/navigation";
import {
  useCallback,
  useEffect,
  useEffectEvent,
  useRef,
  useState,
} from "react";
import { toast } from "sonner";
import { Dashboard } from "@/components/dashboard/Dashboard";
import { Button } from "@/components/ui/button";
import { ApiError, api } from "@/lib/api";
import { t, useLocale } from "@/lib/i18n";
import { pollUntil } from "@/lib/poll";
import type { Plan, Run } from "@/lib/types";
import { useRunEvents } from "@/lib/useRunEvents";

/** After a pause/resume is accepted, GET /runs/{id} this often, for this long. */
const PAUSE_POLL_MS = 500;
const PAUSE_POLL_MAX_MS = 10_000;

/** GET /runs/{id}, tagged with the id it was for. */
interface Loaded {
  id: string;
  plan: Plan | null;
  run: Run;
}

function sum(quantities: Record<string, number> | undefined): number {
  return Object.values(quantities ?? {}).reduce((a, b) => a + b, 0);
}

export default function RunPage() {
  const { id } = useParams<{ id: string }>();
  const [locale] = useLocale();
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [busy, setBusy] = useState(false);
  const { state, events, connected } = useRunEvents(id, { mode: "live" });
  const mounted = useRef<boolean>(false);
  /** The pause/resume re-poll in flight; a new toggle cancels the previous one. */
  const settle = useRef<{ cancelled: boolean }>({ cancelled: false });

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const showError = useCallback(
    (e: unknown) => {
      toast.error(e instanceof ApiError ? e.detail : t("common.error", locale));
    },
    [locale]
  );
  // Reads the current locale without making the load effect depend on it.
  const onLoadError = useEffectEvent(showError);

  useEffect(() => {
    let active = true;
    api
      .getRun(id)
      .then(({ plan: storedPlan, run: storedRun }) => {
        if (active) {
          setLoaded({ id, plan: storedPlan, run: storedRun });
        }
      })
      .catch((e: unknown) => {
        if (active) {
          onLoadError(e);
        }
      });
    return () => {
      active = false;
    };
  }, [id]);

  // Ignore a response for a previous id.
  const current = loaded?.id === id ? loaded : null;
  const run = current?.run ?? null;
  // The stored plan carries the user's edited quantities; the run has the brief's.
  const planned = sum(current?.plan?.quantities ?? run?.quantities);
  const total = Math.max(planned, state.counters.collected);

  const setRun = useCallback((runId: string, next: Run) => {
    if (mounted.current) {
      setLoaded((l) => (l?.id === runId ? { ...l, run: next } : l));
    }
  }, []);

  const toggle = useCallback(async () => {
    if (run === null) {
      return;
    }
    const want = !run.paused;
    settle.current.cancelled = true;
    const poll = { cancelled: false };
    settle.current = poll;
    setBusy(true);
    try {
      // The API answers before the pipeline reaches its pause point (a pause
      // returns `paused: false`; a resume while busy still `paused: true`), so
      // a 2xx is the intent accepted: show it, then re-poll until the server
      // agrees, falling back to whatever it last said.
      const accepted = want ? await api.pauseRun(id) : await api.resumeRun(id);
      setRun(id, { ...accepted, paused: want });
      if (mounted.current) {
        setBusy(false);
      }
      const settled = await pollUntil(
        async () => (await api.getRun(id)).run,
        (r) => r.paused === want,
        { cancel: poll, intervalMs: PAUSE_POLL_MS, maxMs: PAUSE_POLL_MAX_MS }
      );
      if (settled !== null && !poll.cancelled) {
        setRun(id, settled);
      }
    } catch (e) {
      showError(e);
    } finally {
      if (mounted.current) {
        setBusy(false);
      }
    }
  }, [id, run, setRun, showError]);

  const controls =
    run && !state.done ? (
      <Button disabled={busy} onClick={toggle} size="sm" variant="outline">
        {run.paused ? (
          <Play aria-hidden="true" data-icon="inline-start" />
        ) : (
          <Pause aria-hidden="true" data-icon="inline-start" />
        )}
        {t(run.paused ? "run.resume" : "run.pause", locale)}
      </Button>
    ) : null;

  return (
    <Dashboard
      connected={connected}
      controls={controls}
      error={run?.error}
      events={events}
      mode="live"
      runId={id}
      state={state}
      total={total}
    />
  );
}
