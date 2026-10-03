"use client";

import { Pause, Play } from "lucide-react";
import { useCallback } from "react";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { t, useLocale } from "@/lib/i18n";

export const SPEEDS = [1, 4, 16] as const;

interface Props {
  done: number;
  onSpeed: (s: number) => void;
  onToggle: () => void;
  playing: boolean;
  progress: number;
  speed: number;
  total: number;
}

interface SpeedButtonProps {
  active: boolean;
  onSpeed: (s: number) => void;
  speed: number;
}

function SpeedButton({ speed, active, onSpeed }: SpeedButtonProps) {
  const onClick = useCallback(() => onSpeed(speed), [onSpeed, speed]);
  return (
    <Button
      aria-pressed={active}
      onClick={onClick}
      size="sm"
      variant={active ? "default" : "outline"}
    >
      {speed}x
    </Button>
  );
}

export function ReplayControls({
  playing,
  speed,
  progress,
  done,
  total,
  onToggle,
  onSpeed,
}: Props) {
  const [locale] = useLocale();
  const pct = Math.round(progress * 100);
  return (
    <div className="flex flex-wrap items-center gap-3">
      <Button
        aria-label={t(playing ? "replay.pause" : "replay.play", locale)}
        onClick={onToggle}
        size="sm"
      >
        {playing ? (
          <Pause aria-hidden="true" className="size-4" />
        ) : (
          <Play aria-hidden="true" className="size-4" />
        )}
      </Button>
      <span className="text-muted-foreground text-xs">
        {t("replay.speed", locale)}
      </span>
      {SPEEDS.map((s) => (
        <SpeedButton active={s === speed} key={s} onSpeed={onSpeed} speed={s} />
      ))}
      <div className="flex min-w-48 flex-1 items-center gap-2">
        <Progress
          aria-valuemax={100}
          aria-valuemin={0}
          aria-valuenow={pct}
          value={pct}
        />
        <span className="whitespace-nowrap font-mono text-xs">
          {t("replay.progress", locale, { done, total })}
        </span>
      </div>
    </div>
  );
}
