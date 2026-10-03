"use client";

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
import type { PostTile } from "@/lib/events";
import { t, useLocale } from "@/lib/i18n";

export function ReviewBucket({
  review,
  posts,
}: {
  review: string[];
  posts: Record<string, PostTile>;
}) {
  const [locale] = useLocale();
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
                    {posts[id]?.post.text.title ??
                      posts[id]?.post.text.caption ??
                      id}
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
      </CardContent>
    </Card>
  );
}
