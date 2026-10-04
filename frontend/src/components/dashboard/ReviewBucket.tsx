"use client";

import { type MouseEvent, useCallback, useState } from "react";
import { PostDialog } from "@/components/report/PostDialog";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { type PostTile, tileView } from "@/lib/events";
import { t, useLocale } from "@/lib/i18n";

export function ReviewBucket({
  review,
  posts,
}: {
  review: string[];
  posts: Record<string, PostTile>;
}) {
  const [locale] = useLocale();
  const [selected, setSelected] = useState<string | null>(null);
  const selectedTile = selected === null ? undefined : posts[selected];
  const pick = useCallback((e: MouseEvent<HTMLButtonElement>) => {
    setSelected(e.currentTarget.dataset.id ?? null);
  }, []);
  const onDialogOpenChange = useCallback((open: boolean) => {
    if (!open) {
      setSelected(null);
    }
  }, []);
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("review.title", locale)}</CardTitle>
      </CardHeader>
      <CardContent className="flex items-center justify-between gap-3">
        <div>
          <p className="font-mono text-2xl text-rose-500">
            {t("review.count", locale, { count: review.length })}
          </p>
          <p className="text-muted-foreground text-xs">
            {t("review.help", locale)}
          </p>
        </div>
        <Dialog>
          <DialogTrigger asChild>
            <Button disabled={review.length === 0} size="sm" variant="outline">
              {t("review.open", locale)}
            </Button>
          </DialogTrigger>
          {/* The generated close button has an untranslated label; ours is below. */}
          <DialogContent showCloseButton={false}>
            <DialogHeader>
              <DialogTitle>{t("review.title", locale)}</DialogTitle>
              <DialogDescription>{t("review.help", locale)}</DialogDescription>
            </DialogHeader>
            {review.length === 0 ? (
              <p className="text-muted-foreground text-sm">
                {t("review.empty", locale)}
              </p>
            ) : (
              <ul className="flex flex-col gap-2 text-sm">
                {review.map((id) => (
                  <li key={id}>
                    <button
                      className="text-left underline-offset-2 hover:underline"
                      data-id={id}
                      onClick={pick}
                      type="button"
                    >
                      {posts[id]?.post.text.title ||
                        posts[id]?.post.text.caption ||
                        id}
                    </button>
                  </li>
                ))}
              </ul>
            )}
            <DialogFooter>
              <DialogClose asChild>
                <Button variant="outline">{t("common.close", locale)}</Button>
              </DialogClose>
            </DialogFooter>
          </DialogContent>
        </Dialog>
        <PostDialog
          onOpenChange={onDialogOpenChange}
          open={selected !== null}
          view={selectedTile ? tileView(selectedTile) : null}
        />
      </CardContent>
    </Card>
  );
}
