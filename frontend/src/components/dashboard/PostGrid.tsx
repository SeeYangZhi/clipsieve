"use client";

import {
  CircleQuestionMark,
  Film,
  Images,
  type LucideIcon,
  Star,
  TriangleAlert,
} from "lucide-react";
import { memo, useCallback, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { mediaUrl } from "@/lib/api";
import type { PostTile, PostTileState } from "@/lib/events";
import { t, useLocale } from "@/lib/i18n";

/** Tiles rendered at most; the progress label still counts every post. */
export const MAX_TILES = 2000;

/** One look per state, so a state reads without hovering (and without colour alone, see STATE_ICON). */
export const TILE_STATE_CLASS: Record<PostTileState, string> = {
  collected: "opacity-80",
  dropped_pass_one: "opacity-25 grayscale",
  judge_failed: "opacity-60 ring-2 ring-destructive",
  judged: "opacity-100",
  review: "opacity-100 outline-2 outline-rose-500 outline-dashed",
  shortlisted: "opacity-100 ring-2 ring-amber-500",
};

const STATE_ICON: Partial<Record<PostTileState, LucideIcon>> = {
  judge_failed: TriangleAlert,
  review: CircleQuestionMark,
  shortlisted: Star,
};

const STATE_ICON_CLASS: Partial<Record<PostTileState, string>> = {
  judge_failed: "text-destructive",
  review: "text-rose-500",
  shortlisted: "fill-amber-500 text-amber-500",
};

function TileView({ runId, tile }: { runId: string; tile: PostTile }) {
  const [locale] = useLocale();
  // The state the thumbnail failed in: a later state (e.g. after evidence
  // extraction) tries the thumbnail once more.
  const [failedIn, setFailedIn] = useState<PostTileState | null>(null);
  const onError = useCallback(() => setFailedIn(tile.state), [tile.state]);
  const broken = failedIn === tile.state;
  const title = tile.post.text.title || tile.post.text.caption || tile.post.id;
  const KindIcon = tile.post.kind === "video" ? Film : Images;
  const StateIcon = STATE_ICON[tile.state];
  return (
    <li
      aria-label={`${title} (${t(`grid.state.${tile.state}`, locale)})`}
      className={`relative aspect-square overflow-hidden rounded bg-muted ${TILE_STATE_CLASS[tile.state]}`}
      data-state={tile.state}
      data-testid={`tile-${tile.post.id}`}
      title={title}
    >
      {broken ? (
        <KindIcon
          aria-hidden="true"
          className="absolute inset-0 m-auto size-5 text-muted-foreground"
        />
      ) : (
        // biome-ignore lint/performance/noImgElement lint/a11y/noNoninteractiveElementInteractions: thumbnails come from the local API, not an optimizable remote; onError is a resource load event, not a user interaction
        <img
          alt=""
          className="size-full object-cover"
          decoding="async"
          height={44}
          loading="lazy"
          onError={onError}
          src={mediaUrl(runId, tile.post.id, "thumb.jpg")}
          width={44}
        />
      )}
      {StateIcon ? (
        <StateIcon
          aria-hidden="true"
          className={`absolute top-0.5 right-0.5 size-3 drop-shadow ${STATE_ICON_CLASS[tile.state] ?? ""}`}
        />
      ) : null}
    </li>
  );
}

// The reducer keeps untouched tiles by reference, so only changed tiles re-render.
const Tile = memo(TileView);

export function PostGrid({
  runId,
  posts,
  total,
}: {
  runId: string;
  posts: Record<string, PostTile>;
  total: number;
}) {
  const [locale] = useLocale();
  const all = Object.values(posts);
  const tiles = all.slice(0, MAX_TILES);
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle>{t("grid.title", locale)}</CardTitle>
        <span className="font-mono text-muted-foreground text-xs">
          {t("grid.progress", locale, { done: all.length, total })}
        </span>
      </CardHeader>
      <CardContent>
        <ul className="grid grid-cols-[repeat(auto-fill,minmax(44px,1fr))] gap-1">
          {tiles.map((tile) => (
            <Tile key={tile.post.id} runId={runId} tile={tile} />
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
