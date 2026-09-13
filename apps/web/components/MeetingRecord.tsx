"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState, type KeyboardEvent, type MouseEvent, type ReactNode } from "react";
import { isView, VIEWS, type View } from "@/lib/views";
import styles from "./MeetingRecord.module.css";

type GoTo = (view: View, targetId?: string) => void;
const NavContext = createContext<GoTo>(() => {});

/** Jump to a tab, and optionally to an element in it (a transcript line, a turn). */
export function useGoTo(): GoTo {
  return useContext(NavContext);
}

function reducedMotion(): boolean {
  return typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function reveal(id: string) {
  const el = document.getElementById(id);
  if (!el) return;
  el.scrollIntoView({ block: "center", behavior: reducedMotion() ? "auto" : "smooth" });
  el.classList.remove("flash");
  // Restart the animation on repeat visits to the same element.
  void el.offsetWidth;
  el.classList.add("flash");
  el.addEventListener("animationend", () => el.classList.remove("flash"), { once: true });
}

interface Props {
  initialView: View;
  labels: Record<View, { label: string; count?: number }>;
  score: ReactNode;
  panels: Record<View, ReactNode>;
}

/**
 * The meeting record: score, tabs and panels. Owns which tab is open and handles
 * deep links. Any `<a data-view="transcript" href="?view=transcript#u12">` inside it
 * switches tab and scrolls to the target instead of navigating, and still works without JS.
 */
export function MeetingRecord({ initialView, labels, score, panels }: Props) {
  const [view, setView] = useState<View>(initialView);
  const [target, setTarget] = useState<{ id: string; nonce: number } | null>(null);
  const tabRefs = useRef<Record<View, HTMLButtonElement | null>>({ summary: null, said: null, transcript: null });

  const goTo = useCallback<GoTo>((next, targetId) => {
    setView(next);
    if (targetId) setTarget({ id: targetId, nonce: Date.now() });
    const url = new URL(window.location.href);
    url.searchParams.set("view", next);
    url.hash = targetId ?? "";
    window.history.replaceState(window.history.state, "", url);
  }, []);

  // Scroll once the target's panel is visible.
  useEffect(() => {
    if (!target) return;
    const frame = requestAnimationFrame(() => reveal(target.id));
    return () => cancelAnimationFrame(frame);
  }, [target]);

  // Honour a hash on first load, e.g. /meetings/x?view=said#turn-t-budget
  useEffect(() => {
    const id = decodeURIComponent(window.location.hash.slice(1));
    if (id) setTarget({ id, nonce: Date.now() });
  }, []);

  const onClick = (e: MouseEvent<HTMLDivElement>) => {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    const a = (e.target as HTMLElement).closest<HTMLAnchorElement>("a[data-view]");
    if (!a || !isView(a.dataset.view)) return;
    e.preventDefault();
    goTo(a.dataset.view, a.hash ? decodeURIComponent(a.hash.slice(1)) : undefined);
  };

  const onTabKey = (e: KeyboardEvent<HTMLButtonElement>) => {
    const i = VIEWS.indexOf(view);
    const next =
      e.key === "ArrowRight" ? VIEWS[(i + 1) % VIEWS.length] : e.key === "ArrowLeft" ? VIEWS[(i + VIEWS.length - 1) % VIEWS.length] : e.key === "Home" ? VIEWS[0] : e.key === "End" ? VIEWS[VIEWS.length - 1] : null;
    if (!next) return;
    e.preventDefault();
    goTo(next);
    tabRefs.current[next]?.focus();
  };

  return (
    <NavContext.Provider value={goTo}>
      <div onClick={onClick}>
        {score}
        <div className={styles.tabs} role="tablist" aria-label="Meeting record">
          {VIEWS.map((v) => (
            <button
              key={v}
              ref={(el) => {
                tabRefs.current[v] = el;
              }}
              id={`tab-${v}`}
              role="tab"
              type="button"
              aria-selected={view === v}
              aria-controls={`panel-${v}`}
              tabIndex={view === v ? 0 : -1}
              className={styles.tab}
              onClick={() => goTo(v)}
              onKeyDown={onTabKey}
            >
              {labels[v].label}
              {labels[v].count !== undefined && <span className={styles.count}>{labels[v].count}</span>}
            </button>
          ))}
        </div>
        {VIEWS.map((v) => (
          <section key={v} id={`panel-${v}`} role="tabpanel" aria-labelledby={`tab-${v}`} hidden={view !== v} className={styles.panel}>
            {panels[v]}
          </section>
        ))}
      </div>
    </NavContext.Provider>
  );
}
