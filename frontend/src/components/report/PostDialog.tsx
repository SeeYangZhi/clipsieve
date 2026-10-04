"use client";

import { useCallback, useState } from "react";
import { answerLabel } from "@/components/dashboard/CurrentItem";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { mediaUrl, type PostView } from "@/lib/api";
import { t, tOr, useLocale } from "@/lib/i18n";

/** One cited post: its caption and the latest pass's Jev answers. */
export function PostDialog({
  view,
  open,
  onOpenChange,
  runId,
}: {
  onOpenChange: (open: boolean) => void;
  open: boolean;
  /** When given, the downloaded media under `GET /runs/{id}/media/...` is shown. */
  runId?: string;
  view: PostView | null;
}) {
  const [locale] = useLocale();
  const judge = view?.judge.pass_two ?? view?.judge.pass_one;
  // The post whose local media failed to load (only kept posts have media on disk).
  const [brokenFor, setBrokenFor] = useState<string | null>(null);
  const mediaBroken = brokenFor === view?.post.id;
  const markBroken = useCallback(
    () => setBrokenFor(view?.post.id ?? null),
    [view]
  );
  return (
    // Without a post there is nothing to title, so the dialog stays shut.
    <Dialog onOpenChange={onOpenChange} open={open && view !== null}>
      {view ? (
        // The generated close button has an untranslated label; ours is in the footer.
        <DialogContent
          className="max-h-[80vh] overflow-y-auto sm:max-w-lg"
          showCloseButton={false}
        >
          <DialogHeader>
            <DialogTitle>
              {view.post.text.title || view.post.text.caption || view.post.id}
            </DialogTitle>
            <DialogDescription>
              {view.post.id} · {t(`post.kind.${view.post.kind}`, locale)}
            </DialogDescription>
          </DialogHeader>
          {view.post.text.caption ? (
            <section className="flex flex-col gap-1">
              <h3 className="text-muted-foreground text-xs uppercase tracking-wide">
                {t("report.post.caption", locale)}
              </h3>
              <p>{view.post.text.caption}</p>
            </section>
          ) : null}
          {runId && !mediaBroken ? (
            <LocalMedia onError={markBroken} runId={runId} view={view} />
          ) : null}
          {view.post.url ? (
            <a
              className="text-sm underline underline-offset-2"
              href={view.post.url}
              rel="noreferrer"
              target="_blank"
            >
              {t("post.open_original", locale)}
            </a>
          ) : null}
          {judge ? (
            <section className="flex flex-col gap-1">
              <h3 className="text-muted-foreground text-xs uppercase tracking-wide">
                {t("report.post.answers", locale)}
              </h3>
              <dl className="grid grid-cols-[1fr_auto] gap-x-3 gap-y-1">
                {Object.entries(judge.answers).map(([qid, a]) => (
                  <div className="contents" key={qid}>
                    <dt className="text-muted-foreground">
                      {tOr(`question.${qid}`, qid, locale)}
                    </dt>
                    <dd className="text-right">{answerLabel(a, locale)}</dd>
                  </div>
                ))}
              </dl>
            </section>
          ) : null}
          <DialogFooter>
            <DialogClose asChild>
              <Button variant="outline">{t("common.close", locale)}</Button>
            </DialogClose>
          </DialogFooter>
        </DialogContent>
      ) : null}
    </Dialog>
  );
}

/** The media the Runner downloaded for a kept post; the caller hides it when the file is missing. */
function LocalMedia({
  runId,
  view,
  onError,
}: {
  onError: () => void;
  runId: string;
  view: PostView;
}) {
  if (view.post.kind === "video") {
    return (
      // biome-ignore lint/a11y/useMediaCaption: the transcript is in the evidence, not a caption track
      <video
        className="max-h-72 w-full rounded bg-black"
        controls
        onError={onError}
        preload="metadata"
        src={mediaUrl(runId, view.post.id, "video.mp4")}
      />
    );
  }
  return (
    // biome-ignore lint/performance/noImgElement lint/a11y/noNoninteractiveElementInteractions: local API image; onError only hides a missing file
    <img
      alt=""
      className="max-h-72 w-full rounded object-contain"
      height={288}
      onError={onError}
      src={mediaUrl(runId, view.post.id, "img_00.jpg")}
      width={512}
    />
  );
}
