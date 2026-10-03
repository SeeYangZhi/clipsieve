"use client";

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
import type { PostView } from "@/lib/api";
import { t, tOr, useLocale } from "@/lib/i18n";

/** One cited post: its caption and the latest pass's Jev answers. */
export function PostDialog({
  view,
  open,
  onOpenChange,
}: {
  onOpenChange: (open: boolean) => void;
  open: boolean;
  view: PostView | null;
}) {
  const [locale] = useLocale();
  const judge = view?.judge.pass_two ?? view?.judge.pass_one;
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
            <DialogTitle>{view.post.text.title || view.post.id}</DialogTitle>
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
