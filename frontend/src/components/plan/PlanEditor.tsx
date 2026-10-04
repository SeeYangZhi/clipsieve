"use client";

import { Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { type ChangeEvent, useCallback, useId, useState } from "react";
import { MAX_QUANTITY } from "@/components/brief/BriefForm";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { t, useLocale } from "@/lib/i18n";
import type { Plan, Query } from "@/lib/types";

/** The backend schema requires exactly five persona fit levels. */
const PERSONA_LEVELS = [0, 1, 2, 3, 4] as const;

/** A query row with a stable client-only id, so edits never remount a row. */
interface QueryDraft extends Query {
  id: number;
}

interface Draft {
  criteria: string[];
  nextId: number;
  /** Raw input text, so a field can be cleared while typing; parsed at submit. */
  quantities: Record<string, string>;
  queries: QueryDraft[];
}

function toDraft(plan: Plan): Draft {
  return {
    criteria: PERSONA_LEVELS.map((i) => plan.persona_fit_criteria[i] ?? ""),
    nextId: plan.queries.length,
    quantities: Object.fromEntries(
      Object.entries(plan.quantities).map(([p, n]) => [p, String(n)])
    ),
    queries: plan.queries.map((q, id) => ({ ...q, id })),
  };
}

/** 1..MAX_QUANTITY; blank or invalid keeps the planned number. */
function parseQuantity(raw: string | undefined, planned: number): number {
  const n = Number.parseInt(raw ?? "", 10);
  return Number.isInteger(n) && n >= 1 ? Math.min(n, MAX_QUANTITY) : planned;
}

/** The plan as the backend takes it: Query fields only, five levels. */
function toPlan(plan: Plan, draft: Draft): Plan {
  return {
    ...plan,
    persona_fit_criteria: draft.criteria.map((c) => c.trim()),
    quantities: Object.fromEntries(
      Object.entries(plan.quantities).map(([p, n]) => [
        p,
        parseQuantity(draft.quantities[p], n),
      ])
    ),
    queries: draft.queries.map(({ lang, platform, query }) => ({
      lang: lang.trim(),
      platform,
      query: query.trim(),
    })),
  };
}

/** Saving keeps a work-in-progress draft; approving starts a search, so it needs text. */
function approvalErrorKey(plan: Plan): string | null {
  if (plan.queries.length === 0) {
    return "plan.validation.queries";
  }
  if (plan.queries.some((q) => !q.query)) {
    return "plan.validation.query_text";
  }
  if (plan.persona_fit_criteria.some((c) => !c)) {
    return "plan.validation.criteria";
  }
  return null;
}

interface QueryRowProps {
  disabled: boolean;
  index: number;
  onChange: (id: number, patch: Partial<Query>) => void;
  onRemove: (id: number) => void;
  platforms: string[];
  row: QueryDraft;
}

function QueryRow({
  disabled,
  index,
  onChange,
  onRemove,
  platforms,
  row,
}: QueryRowProps) {
  const [locale] = useLocale();
  const { id } = row;
  const n = index + 1;
  // Keep a platform the plan names even if the run did not tick it.
  const options = platforms.includes(row.platform)
    ? platforms
    : [...platforms, row.platform];
  const changePlatform = useCallback(
    (e: ChangeEvent<HTMLSelectElement>) =>
      onChange(id, { platform: e.target.value }),
    [id, onChange]
  );
  const changeQuery = useCallback(
    (e: ChangeEvent<HTMLInputElement>) =>
      onChange(id, { query: e.target.value }),
    [id, onChange]
  );
  const changeLang = useCallback(
    (e: ChangeEvent<HTMLInputElement>) =>
      onChange(id, { lang: e.target.value }),
    [id, onChange]
  );
  const remove = useCallback(() => onRemove(id), [id, onRemove]);
  return (
    <TableRow>
      <TableCell>
        {/* Native select, like BriefForm: the shadcn Select portals, which jsdom cannot drive. */}
        <select
          aria-label={`${t("plan.query.platform", locale)} ${n}`}
          className="h-8 w-36 rounded-lg border bg-background px-2.5 text-sm disabled:opacity-50"
          disabled={disabled}
          onChange={changePlatform}
          value={row.platform}
        >
          {options.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
      </TableCell>
      <TableCell className="min-w-64">
        <Input
          aria-label={`${t("plan.query.text", locale)} ${n}`}
          disabled={disabled}
          onChange={changeQuery}
          value={row.query}
        />
      </TableCell>
      <TableCell>
        <Input
          aria-label={`${t("plan.query.lang", locale)} ${n}`}
          className="w-20"
          disabled={disabled}
          onChange={changeLang}
          value={row.lang}
        />
      </TableCell>
      <TableCell>
        <Button
          aria-label={t("plan.query.remove", locale)}
          disabled={disabled}
          onClick={remove}
          size="icon-sm"
          variant="ghost"
        >
          <Trash2 />
        </Button>
      </TableCell>
    </TableRow>
  );
}

interface QuantityFieldProps {
  disabled: boolean;
  onChange: (platform: string, value: string) => void;
  platform: string;
  value: string;
}

function QuantityField({
  disabled,
  onChange,
  platform,
  value,
}: QuantityFieldProps) {
  const id = useId();
  const change = useCallback(
    (e: ChangeEvent<HTMLInputElement>) => onChange(platform, e.target.value),
    [onChange, platform]
  );
  return (
    <div className="flex items-center gap-2">
      <label className="text-sm" htmlFor={id}>
        {platform}
      </label>
      <Input
        className="w-28"
        disabled={disabled}
        id={id}
        max={MAX_QUANTITY}
        min={1}
        onChange={change}
        type="number"
        value={value}
      />
    </div>
  );
}

interface CriterionFieldProps {
  disabled: boolean;
  level: number;
  onChange: (level: number, value: string) => void;
  value: string;
}

function CriterionField({
  disabled,
  level,
  onChange,
  value,
}: CriterionFieldProps) {
  const [locale] = useLocale();
  const n = level + 1;
  const change = useCallback(
    (e: ChangeEvent<HTMLInputElement>) => onChange(level, e.target.value),
    [level, onChange]
  );
  return (
    <div className="flex items-center gap-3">
      <span aria-hidden="true" className="w-6 text-muted-foreground text-sm">
        {n}
      </span>
      <Input
        aria-label={t("plan.persona_criteria.level", locale, { n })}
        disabled={disabled}
        onChange={change}
        value={value}
      />
    </div>
  );
}

interface Props {
  busy: boolean;
  onApprove: (plan: Plan) => void;
  onSave: (plan: Plan) => void;
  plan: Plan;
}

/**
 * Edits a copy of `plan`; the prop seeds the draft once (remount with a new
 * `key` to reseed). An approved plan is read-only.
 */
export function PlanEditor({ plan, onSave, onApprove, busy }: Props) {
  const [locale] = useLocale();
  const [draft, setDraft] = useState(() => toDraft(plan));
  const [errorKey, setErrorKey] = useState<string | null>(null);
  const locked = Boolean(plan.approved_at);
  const disabled = busy || locked;
  const platforms = Object.keys(plan.quantities);

  const changeQuery = useCallback(
    (id: number, patch: Partial<Query>) =>
      setDraft((d) => ({
        ...d,
        queries: d.queries.map((q) => (q.id === id ? { ...q, ...patch } : q)),
      })),
    []
  );
  const removeQuery = useCallback(
    (id: number) =>
      setDraft((d) => ({
        ...d,
        queries: d.queries.filter((q) => q.id !== id),
      })),
    []
  );
  const addQuery = useCallback(
    () =>
      setDraft((d) => ({
        ...d,
        nextId: d.nextId + 1,
        queries: [
          ...d.queries,
          {
            id: d.nextId,
            lang: "en",
            platform: Object.keys(d.quantities)[0] ?? "local",
            query: "",
          },
        ],
      })),
    []
  );
  const changeQuantity = useCallback(
    (platform: string, value: string) =>
      setDraft((d) => ({
        ...d,
        quantities: { ...d.quantities, [platform]: value },
      })),
    []
  );
  const changeCriterion = useCallback(
    (level: number, value: string) =>
      setDraft((d) => ({
        ...d,
        criteria: d.criteria.map((c, i) => (i === level ? value : c)),
      })),
    []
  );

  const save = useCallback(() => {
    setErrorKey(null);
    onSave(toPlan(plan, draft));
  }, [draft, onSave, plan]);
  const approve = useCallback(() => {
    const next = toPlan(plan, draft);
    const key = approvalErrorKey(next);
    setErrorKey(key);
    if (key === null) {
      onApprove(next);
    }
  }, [draft, onApprove, plan]);

  return (
    <div className="flex flex-col gap-6">
      {locked ? (
        <div
          className="flex flex-wrap items-center justify-between gap-3 rounded-lg border px-4 py-3 text-sm"
          role="status"
        >
          <span>{t("plan.approved", locale)}</span>
          <Button asChild size="sm" variant="outline">
            <Link href={`/runs/${encodeURIComponent(plan.run_id)}`}>
              {t("plan.open_run", locale)}
            </Link>
          </Button>
        </div>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle>{t("plan.title", locale)}</CardTitle>
        </CardHeader>
        <CardContent>
          <dl className="grid gap-2 text-sm sm:grid-cols-3">
            <div>
              <dt className="text-muted-foreground">
                {t("plan.topic", locale)}
              </dt>
              <dd>{plan.brief.topic}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">
                {t("plan.audience", locale)}
              </dt>
              <dd>{plan.brief.audience}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">
                {t("plan.persona", locale)}
              </dt>
              <dd>{plan.brief.persona}</dd>
            </div>
          </dl>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("plan.queries", locale)}</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("plan.query.platform", locale)}</TableHead>
                <TableHead>{t("plan.query.text", locale)}</TableHead>
                <TableHead>{t("plan.query.lang", locale)}</TableHead>
                <TableHead>
                  <span className="sr-only">
                    {t("plan.query.remove", locale)}
                  </span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {draft.queries.map((q, i) => (
                <QueryRow
                  disabled={disabled}
                  index={i}
                  key={q.id}
                  onChange={changeQuery}
                  onRemove={removeQuery}
                  platforms={platforms}
                  row={q}
                />
              ))}
            </TableBody>
          </Table>
          <Button
            className="self-start"
            disabled={disabled}
            onClick={addQuery}
            size="sm"
            variant="outline"
          >
            <Plus data-icon="inline-start" />
            {t("plan.query.add", locale)}
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("plan.quantities", locale)}</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-4">
          {platforms.map((p) => (
            <QuantityField
              disabled={disabled}
              key={p}
              onChange={changeQuantity}
              platform={p}
              value={draft.quantities[p] ?? ""}
            />
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("plan.persona_criteria", locale)}</CardTitle>
          <p className="text-muted-foreground text-sm">
            {t("plan.persona_criteria.help", locale)}
          </p>
        </CardHeader>
        <CardContent className="flex flex-col gap-2">
          {PERSONA_LEVELS.map((level) => (
            <CriterionField
              disabled={disabled}
              key={level}
              level={level}
              onChange={changeCriterion}
              value={draft.criteria[level]}
            />
          ))}
        </CardContent>
      </Card>

      <div className="flex flex-col gap-3">
        {errorKey ? (
          <p className="text-destructive text-sm" role="alert">
            {t(errorKey, locale)}
          </p>
        ) : null}
        <div className="flex gap-3">
          <Button disabled={disabled} onClick={save} variant="outline">
            {t("plan.save", locale)}
          </Button>
          <Button disabled={disabled} onClick={approve}>
            {busy ? t("plan.approving", locale) : t("plan.approve", locale)}
          </Button>
        </div>
      </div>
    </div>
  );
}
