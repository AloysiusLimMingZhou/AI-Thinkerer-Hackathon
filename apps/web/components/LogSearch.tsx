"use client";

import { useEffect, useState } from "react";
import { Icon } from "./Icon";
import styles from "./LogSearch.module.css";

/**
 * Filters the server-rendered meeting log in place. Rows carry a lowercase
 * `data-search` haystack; day groups hide when all their rows do.
 */
export function LogSearch({ targetId }: { targetId: string }) {
  const [query, setQuery] = useState("");

  useEffect(() => {
    const root = document.getElementById(targetId);
    if (!root) return;
    const needle = query.trim().toLowerCase();
    let shown = 0;
    root.querySelectorAll<HTMLElement>("[data-day]").forEach((group) => {
      let inGroup = 0;
      group.querySelectorAll<HTMLElement>("[data-search]").forEach((row) => {
        const match = !needle || (row.dataset.search ?? "").includes(needle);
        row.hidden = !match;
        if (match) inGroup += 1;
      });
      group.hidden = inGroup === 0;
      shown += inGroup;
    });
    const empty = root.querySelector<HTMLElement>("[data-empty]");
    if (empty) {
      empty.hidden = shown > 0;
      const echo = empty.querySelector("[data-query]");
      if (echo) echo.textContent = query.trim();
    }
  }, [query, targetId]);

  return (
    <label className={styles.search}>
      <Icon name="search" size={17} />
      <span className="sr-only">Search meetings</span>
      <input
        type="search"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Search by meeting, person or topic"
        aria-controls={targetId}
      />
    </label>
  );
}
