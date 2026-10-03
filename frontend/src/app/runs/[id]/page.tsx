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
import type { Plan, Run } from "@/lib/types";
import { useRunEvents } from "@/lib/useRunEvents";

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

  const toggle = useCallback(async () => {
    if (run === null) {
      return;
    }
    setBusy(true);
    try {
      const next = run.paused
        ? await api.resumeRun(id)
        : await api.pauseRun(id);
      if (mounted.current) {
        setLoaded((l) => (l?.id === id ? { ...l, run: next } : l));
      }
    } catch (e) {
      showError(e);
    } finally {
      if (mounted.current) {
        setBusy(false);
      }
    }
  }, [id, run, showError]);

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
      events={events}
      runId={id}
      state={state}
      total={total}
    />
  );
}
