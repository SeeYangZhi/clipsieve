"use client";

import { type ChangeEvent, useCallback, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import type {
  AdapterStatus,
  CreateRunBody,
  RubricPackSummary,
} from "@/lib/api";
import { t, useLocale } from "@/lib/i18n";

export const DEFAULT_QUANTITY = 500;
export const MAX_QUANTITY = 5000;

// The quantity field holds raw text so it can be cleared while typing; parse at submit.
function parseQuantity(raw: string | undefined): number {
  const n = Number.parseInt(raw ?? "", 10);
  return Number.isInteger(n) && n >= 1
    ? Math.min(n, MAX_QUANTITY)
    : DEFAULT_QUANTITY;
}

interface PlatformRowProps {
  adapter: AdapterStatus;
  checked: boolean;
  onCheckedChange: (platform: string, checked: boolean) => void;
  onQuantityChange: (platform: string, value: string) => void;
  quantity: string;
}

function PlatformRow({
  adapter,
  checked,
  onCheckedChange,
  onQuantityChange,
  quantity,
}: PlatformRowProps) {
  const [locale] = useLocale();
  const { healthy, message, platform } = adapter;
  const id = `platform-${platform}`;
  const toggle = useCallback(
    (value: boolean | "indeterminate") =>
      onCheckedChange(platform, value === true),
    [onCheckedChange, platform]
  );
  const changeQuantity = useCallback(
    (e: ChangeEvent<HTMLInputElement>) =>
      onQuantityChange(platform, e.target.value),
    [onQuantityChange, platform]
  );
  return (
    <div className="flex flex-wrap items-center gap-3">
      <Checkbox
        aria-label={platform}
        checked={checked}
        disabled={!healthy}
        id={id}
        onCheckedChange={toggle}
      />
      <label className="min-w-28 text-sm" htmlFor={id}>
        {platform}
      </label>
      <Badge variant={healthy ? "secondary" : "destructive"}>
        {t(
          healthy ? "brief.adapter.healthy" : "brief.adapter.unhealthy",
          locale
        )}
      </Badge>
      {healthy ? null : (
        <span className="text-muted-foreground text-xs">{message}</span>
      )}
      {checked ? (
        <Input
          aria-label={`${t("brief.quantity", locale)}: ${platform}`}
          className="w-28"
          max={MAX_QUANTITY}
          min={1}
          onChange={changeQuantity}
          type="number"
          value={quantity}
        />
      ) : null}
    </div>
  );
}

interface Props {
  adapters: AdapterStatus[];
  busy: boolean;
  onSubmit: (body: CreateRunBody) => void;
  rubrics: RubricPackSummary[];
}

export function BriefForm({ adapters, rubrics, onSubmit, busy }: Props) {
  const [locale] = useLocale();
  const [brief, setBrief] = useState("");
  const [ticked, setTicked] = useState<Record<string, boolean>>({});
  const [quantities, setQuantities] = useState<Record<string, string>>({});
  const [rubricChoice, setRubricChoice] = useState("");
  const [languageHint, setLanguageHint] = useState("");
  const [errorKey, setErrorKey] = useState<string | null>(null);

  // Rubrics load after mount; fall back to the first one until the user picks.
  const rubric = rubrics.some((r) => r.name === rubricChoice)
    ? rubricChoice
    : (rubrics[0]?.name ?? "");

  const onBriefChange = useCallback(
    (e: ChangeEvent<HTMLTextAreaElement>) => setBrief(e.target.value),
    []
  );
  const onTickedChange = useCallback(
    (platform: string, value: boolean) =>
      setTicked((s) => ({ ...s, [platform]: value })),
    []
  );
  const onQuantityChange = useCallback(
    (platform: string, value: string) =>
      setQuantities((q) => ({ ...q, [platform]: value })),
    []
  );
  const onRubricChange = useCallback(
    (e: ChangeEvent<HTMLSelectElement>) => setRubricChoice(e.target.value),
    []
  );
  const onLanguageHintChange = useCallback(
    (e: ChangeEvent<HTMLInputElement>) => setLanguageHint(e.target.value),
    []
  );

  const submit = useCallback(() => {
    const platforms = adapters
      .filter((a) => a.healthy && ticked[a.platform])
      .map((a) => a.platform);
    if (!brief.trim()) {
      setErrorKey("brief.validation.text");
      return;
    }
    if (platforms.length === 0) {
      setErrorKey("brief.validation.platforms");
      return;
    }
    setErrorKey(null);
    onSubmit({
      brief: brief.trim(),
      language_hint: languageHint.trim() || undefined,
      platforms,
      quantities: Object.fromEntries(
        platforms.map((p) => [p, parseQuantity(quantities[p])])
      ),
      rubric_pack: rubric,
    });
  }, [adapters, brief, languageHint, onSubmit, quantities, rubric, ticked]);

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("brief.title", locale)}</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-6">
        <div className="flex flex-col gap-2">
          <label className="font-medium text-sm" htmlFor="brief-text">
            {t("brief.text.label", locale)}
          </label>
          <Textarea
            id="brief-text"
            onChange={onBriefChange}
            placeholder={t("brief.text.placeholder", locale)}
            rows={4}
            value={brief}
          />
        </div>

        <fieldset className="flex flex-col gap-3">
          <legend className="font-medium text-sm">
            {t("brief.platforms", locale)}
          </legend>
          {adapters.map((a) => (
            <PlatformRow
              adapter={a}
              checked={a.healthy && Boolean(ticked[a.platform])}
              key={a.platform}
              onCheckedChange={onTickedChange}
              onQuantityChange={onQuantityChange}
              quantity={quantities[a.platform] ?? String(DEFAULT_QUANTITY)}
            />
          ))}
        </fieldset>

        <div className="grid gap-4 sm:grid-cols-2">
          <div className="flex flex-col gap-2">
            <label className="font-medium text-sm" htmlFor="rubric">
              {t("brief.rubric", locale)}
            </label>
            {/* Native select: the shadcn Select portals, which jsdom cannot drive. */}
            <select
              className="h-8 rounded-lg border bg-background px-2.5 text-sm"
              id="rubric"
              onChange={onRubricChange}
              value={rubric}
            >
              {rubrics.map((r) => (
                <option key={r.name} value={r.name}>
                  {r.name}
                </option>
              ))}
            </select>
          </div>
          <div className="flex flex-col gap-2">
            <label className="font-medium text-sm" htmlFor="language-hint">
              {t("brief.language_hint", locale)}
            </label>
            <Input
              id="language-hint"
              onChange={onLanguageHintChange}
              placeholder={t("brief.language_hint.placeholder", locale)}
              value={languageHint}
            />
          </div>
        </div>

        {errorKey ? (
          <p className="text-destructive text-sm" role="alert">
            {t(errorKey, locale)}
          </p>
        ) : null}
        <Button disabled={busy} onClick={submit}>
          {busy ? t("brief.submitting", locale) : t("brief.submit", locale)}
        </Button>
      </CardContent>
    </Card>
  );
}
