"use client";

import { useParams } from "next/navigation";
import { useCallback, useState } from "react";
import { Dashboard } from "@/components/dashboard/Dashboard";
import { ReplayControls } from "@/components/dashboard/ReplayControls";
import { useRunEvents } from "@/lib/useRunEvents";

export default function ReplayPage() {
  const { id } = useParams<{ id: string }>();
  const [playing, setPlaying] = useState(true);
  const [speed, setSpeed] = useState(4);
  const { state, events, connected, progress } = useRunEvents(id, {
    mode: "replay",
    playing,
    speed,
  });
  const total = progress > 0 ? Math.round(events.length / progress) : 0;
  const onToggle = useCallback(() => setPlaying((p) => !p), []);

  return (
    <Dashboard
      connected={connected}
      controls={
        <ReplayControls
          done={events.length}
          onSpeed={setSpeed}
          onToggle={onToggle}
          playing={playing}
          progress={progress}
          speed={speed}
          total={total}
        />
      }
      events={events}
      mode="replay"
      runId={id}
      state={state}
      total={Math.max(
        state.counters.collected,
        Object.keys(state.posts).length
      )}
    />
  );
}
