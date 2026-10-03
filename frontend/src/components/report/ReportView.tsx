"use client";

import { type ReactNode, useCallback, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { PostView } from "@/lib/api";
import { type Locale, t, useLocale } from "@/lib/i18n";
import type { Report } from "@/lib/types";
import { PostDialog } from "./PostDialog";

/** The run's post for a cited id; own keys only, so "constructor" is not a post. */
function lookup(
  posts: Record<string, PostView>,
  id: string
): PostView | undefined {
  return Object.hasOwn(posts, id) ? posts[id] : undefined;
}

function Section({
  title,
  empty,
  locale,
  children,
}: {
  children: ReactNode;
  empty: boolean;
  locale: Locale;
  title: string;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-5">
        {empty ? (
          <p className="text-muted-foreground text-sm">
            {t("report.section_empty", locale)}
          </p>
        ) : (
          children
        )}
      </CardContent>
    </Card>
  );
}

function Citation({
  id,
  known,
  locale,
  onOpen,
}: {
  id: string;
  known: boolean;
  locale: Locale;
  onOpen: (id: string) => void;
}) {
  const open = useCallback(() => onOpen(id), [id, onOpen]);
  // A post the run did not return cannot open; the title says why. The stock
  // `disabled:pointer-events-none` would swallow the hover, so the tooltip
  // never showed; a disabled button still fires no click.
  return (
    <Button
      className={
        known
          ? "font-mono"
          : "font-mono disabled:pointer-events-auto disabled:cursor-not-allowed"
      }
      disabled={!known}
      onClick={open}
      size="xs"
      title={known ? undefined : t("report.unknown_post", locale)}
      variant="outline"
    >
      {id}
    </Button>
  );
}

function Cites({
  ids,
  posts,
  locale,
  onOpen,
}: {
  ids: string[];
  locale: Locale;
  onOpen: (id: string) => void;
  posts: Record<string, PostView>;
}) {
  if (ids.length === 0) {
    return null;
  }
  return (
    <div className="flex flex-wrap items-center gap-1 text-xs">
      <span className="text-muted-foreground">
        {t("report.cited", locale)}:
      </span>
      {[...new Set(ids)].map((id) => (
        <Citation
          id={id}
          key={id}
          known={lookup(posts, id) !== undefined}
          locale={locale}
          onOpen={onOpen}
        />
      ))}
    </div>
  );
}

function Labelled({ label, children }: { children: ReactNode; label: string }) {
  return (
    <p>
      <span className="text-muted-foreground">{label}: </span>
      {children}
    </p>
  );
}

export function ReportView({
  report,
  posts,
}: {
  posts: Record<string, PostView>;
  report: Report;
}) {
  const [locale] = useLocale();
  // The id outlives `open` so the dialog keeps its content while it animates shut.
  const [openId, setOpenId] = useState<string | null>(null);
  const [open, setOpen] = useState(false);

  const onOpen = useCallback((id: string) => {
    setOpenId(id);
    setOpen(true);
  }, []);

  const cites = (ids: string[]) => (
    <Cites ids={ids} locale={locale} onOpen={onOpen} posts={posts} />
  );

  return (
    <div className="flex flex-col gap-6">
      <h1 className="font-semibold text-lg">{t("report.title", locale)}</h1>

      <Section
        empty={report.patterns.length === 0}
        locale={locale}
        title={t("report.patterns", locale)}
      >
        {report.patterns.map((p) => (
          <article className="flex flex-col gap-1 text-sm" key={p.title}>
            <h3 className="font-medium">{p.title}</h3>
            <Labelled label={t("report.observation", locale)}>
              {p.observation}
            </Labelled>
            <Labelled label={t("report.hypothesis", locale)}>
              {p.hypothesis}
            </Labelled>
            {cites(p.post_ids)}
          </article>
        ))}
      </Section>

      <Section
        empty={report.clips.length === 0}
        locale={locale}
        title={t("report.clips", locale)}
      >
        {report.clips.map((c) => {
          const text = lookup(posts, c.post_id)?.post.text;
          return (
            <article className="flex flex-col gap-1 text-sm" key={c.post_id}>
              <h3 className="font-medium">
                {text?.title || text?.caption || c.post_id}
              </h3>
              <Labelled label={t("report.hook_quote", locale)}>
                <q>{c.hook_quote}</q>
              </Labelled>
              <Labelled label={t("report.why_it_works", locale)}>
                {c.why_it_works}
              </Labelled>
              <Labelled label={t("report.weaknesses", locale)}>
                {c.weaknesses}
              </Labelled>
              {cites([c.post_id])}
            </article>
          );
        })}
      </Section>

      <Section
        empty={report.gaps.length === 0}
        locale={locale}
        title={t("report.gaps", locale)}
      >
        {report.gaps.map((g) => (
          <article className="flex flex-col gap-1 text-sm" key={g.title}>
            <h3 className="font-medium">{g.title}</h3>
            <p>{g.rationale}</p>
            {cites(g.post_ids)}
          </article>
        ))}
      </Section>

      <Section
        empty={report.concepts.length === 0}
        locale={locale}
        title={t("report.concepts", locale)}
      >
        {report.concepts.map((c) => (
          <article className="flex flex-col gap-2 text-sm" key={c.hook}>
            <dl className="grid gap-x-3 gap-y-1 sm:grid-cols-[6rem_1fr]">
              <dt className="text-muted-foreground">
                {t("report.concept.hook", locale)}
              </dt>
              <dd className="font-medium">{c.hook}</dd>
              <dt className="text-muted-foreground">
                {t("report.concept.structure", locale)}
              </dt>
              <dd>{c.structure}</dd>
              <dt className="text-muted-foreground">
                {t("report.concept.visual", locale)}
              </dt>
              <dd>{c.visual}</dd>
              <dt className="text-muted-foreground">
                {t("report.concept.proof", locale)}
              </dt>
              <dd>{c.proof}</dd>
              <dt className="text-muted-foreground">
                {t("report.concept.cta", locale)}
              </dt>
              <dd>{c.cta}</dd>
            </dl>
            {cites(c.inspired_by_post_ids)}
          </article>
        ))}
      </Section>

      {report.caveats.length > 0 ? (
        <Section
          empty={false}
          locale={locale}
          title={t("report.caveats", locale)}
        >
          <ul className="list-disc pl-5 text-sm">
            {report.caveats.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
        </Section>
      ) : null}

      <PostDialog
        onOpenChange={setOpen}
        open={open}
        view={openId === null ? null : (lookup(posts, openId) ?? null)}
      />
    </div>
  );
}
