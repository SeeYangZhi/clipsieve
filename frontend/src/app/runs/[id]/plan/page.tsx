"use client";

import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { PlanEditor } from "@/components/plan/PlanEditor";
import { Button } from "@/components/ui/button";
import { ApiError, api } from "@/lib/api";
import { readyPlan } from "@/lib/events";
import { t, useLocale } from "@/lib/i18n";
import type { Plan } from "@/lib/types";
import { useRunEvents } from "@/lib/useRunEvents";

/** What GET /runs/{id} said, tagged with the id it was for. */
type Loaded =
  | { id: string; plan: Plan | null; status: "ok" }
  | { detail: string | null; id: string; status: "failed" };

export default function PlanPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [locale] = useLocale();
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [busy, setBusy] = useState(false);
  const { events } = useRunEvents(id, { mode: "live" });
  const mounted = useRef<boolean>(false);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  // biome-ignore lint/correctness/useExhaustiveDependencies: `attempt` is the Retry trigger
  useEffect(() => {
    let active = true;
    api
      .getRun(id)
      .then(({ plan: storedPlan }) => {
        if (active) {
          setLoaded({ id, plan: storedPlan, status: "ok" });
        }
      })
      .catch((e: unknown) => {
        if (active) {
          const detail = e instanceof ApiError ? e.detail : null;
          setLoaded({ detail, id, status: "failed" });
        }
      });
    return () => {
      active = false;
    };
  }, [id, attempt]);

  const showError = (e: unknown) => {
    toast.error(e instanceof ApiError ? e.detail : t("common.error", locale));
  };

  const onSave = async (p: Plan) => {
    try {
      const saved = await api.savePlan(id, p);
      if (mounted.current) {
        setLoaded({ id, plan: saved, status: "ok" });
      }
      toast.success(t("plan.saved", locale));
    } catch (e) {
      showError(e);
    }
  };

  const onApprove = async (p: Plan) => {
    setBusy(true);
    try {
      await api.savePlan(id, p);
      await api.approveRun(id);
      router.push(`/runs/${encodeURIComponent(id)}`);
    } catch (e) {
      showError(e);
      if (mounted.current) {
        setBusy(false);
      }
    }
  };

  const retry = useCallback(() => {
    setLoaded(null);
    setAttempt((a) => a + 1);
  }, []);

  // Ignore a response for a previous id until this id's load lands.
  const current = loaded?.id === id ? loaded : null;
  if (current === null) {
    return (
      <p className="text-muted-foreground text-sm">
        {t("common.loading", locale)}
      </p>
    );
  }
  if (current.status === "failed") {
    return (
      <div className="flex flex-col items-start gap-3">
        <p className="text-destructive text-sm" role="alert">
          {current.detail ?? t("common.error", locale)}
        </p>
        <Button onClick={retry} variant="outline">
          {t("common.retry", locale)}
        </Button>
      </div>
    );
  }
  // The stored plan wins: it carries the user's saved edits and approval.
  // While planning it is null, and the live log's plan_ready supplies it.
  const plan = current.plan ?? readyPlan(events);
  if (plan === null) {
    return (
      <p className="text-muted-foreground text-sm">
        {t("plan.pending", locale)}
      </p>
    );
  }
  return (
    <PlanEditor
      busy={busy}
      key={id}
      onApprove={onApprove}
      onSave={onSave}
      plan={plan}
    />
  );
}
