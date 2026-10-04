"use client";

import { useRouter } from "next/navigation";
import { useEffect, useEffectEvent, useState } from "react";
import { toast } from "sonner";
import { BriefForm } from "@/components/brief/BriefForm";
import { RecentRuns } from "@/components/brief/RecentRuns";
import {
  type AdapterStatus,
  ApiError,
  api,
  type CreateRunBody,
  type RubricPackSummary,
} from "@/lib/api";
import { t, useLocale } from "@/lib/i18n";
import type { Run } from "@/lib/types";

export default function HomePage() {
  const router = useRouter();
  const [locale] = useLocale();
  const [adapters, setAdapters] = useState<AdapterStatus[]>([]);
  const [rubrics, setRubrics] = useState<RubricPackSummary[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [busy, setBusy] = useState(false);

  const showError = (e: unknown) => {
    toast.error(e instanceof ApiError ? e.detail : t("common.error", locale));
  };
  // Reads the current locale without making the load effect depend on it.
  const onLoadError = useEffectEvent(showError);

  useEffect(() => {
    let active = true;
    Promise.all([api.listAdapters(), api.listRubrics(), api.listRuns()])
      .then(([a, r, rs]) => {
        if (!active) {
          return;
        }
        setAdapters(a);
        setRubrics(r);
        setRuns(rs);
      })
      .catch((e: unknown) => {
        if (active) {
          onLoadError(e);
        }
      });
    return () => {
      active = false;
    };
  }, []);

  const onSubmit = async (body: CreateRunBody) => {
    setBusy(true);
    try {
      const run = await api.createRun(body);
      router.push(`/runs/${encodeURIComponent(run.id)}/plan`);
    } catch (e) {
      showError(e);
      setBusy(false);
    }
  };

  return (
    <div className="grid gap-6 lg:grid-cols-[2fr_1fr]">
      <BriefForm
        adapters={adapters}
        busy={busy}
        onSubmit={onSubmit}
        rubrics={rubrics}
      />
      <RecentRuns runs={runs} />
    </div>
  );
}
