"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

/**
 * Polls the backend's local state while a bot is on its way or in the call, by
 * re-rendering the server components (the handoff says to poll, not to call Recall).
 * Pauses while the tab is hidden.
 */
export function LiveRefresh({ every = 3000 }: { every?: number }) {
  const router = useRouter();
  useEffect(() => {
    let timer: ReturnType<typeof setInterval> | undefined;
    const start = () => {
      if (!timer) timer = setInterval(() => router.refresh(), every);
    };
    const stop = () => {
      clearInterval(timer);
      timer = undefined;
    };
    const onVisibility = () => (document.hidden ? stop() : (router.refresh(), start()));
    if (!document.hidden) start();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      stop();
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [router, every]);
  return null;
}
