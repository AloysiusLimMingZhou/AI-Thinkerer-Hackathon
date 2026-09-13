"use client";

import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { Icon } from "./Icon";
import styles from "./DownloadMenu.module.css";

export interface DownloadOption {
  label: string;
  hint: string;
  href: string;
  filename: string;
}

/** "Download transcript" with a format menu. Each option is a plain download link. */
export function DownloadMenu({ options, extra, variant = "primary" }: { options: DownloadOption[]; extra?: DownloadOption; variant?: "primary" | "quiet" }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const rootRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const itemRefs = useRef<(HTMLAnchorElement | null)[]>([]);

  useEffect(() => {
    if (!open) return;
    itemRefs.current[0]?.focus();
    const onDown = (e: PointerEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", onDown);
    return () => document.removeEventListener("pointerdown", onDown);
  }, [open]);

  const close = (refocus = true) => {
    setOpen(false);
    if (refocus) buttonRef.current?.focus();
  };

  const onMenuKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const items = itemRefs.current.filter(Boolean) as HTMLAnchorElement[];
    const i = items.indexOf(document.activeElement as HTMLAnchorElement);
    if (e.key === "Escape") {
      e.preventDefault();
      close();
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      items[(i + 1) % items.length]?.focus();
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      items[(i - 1 + items.length) % items.length]?.focus();
    } else if (e.key === "Tab") {
      close(false);
    }
  };

  const item = (o: DownloadOption, index: number) => (
    <a
      key={o.href}
      ref={(el) => {
        itemRefs.current[index] = el;
      }}
      role="menuitem"
      href={o.href}
      download={o.filename}
      className={styles.item}
      onClick={() => close(false)}
    >
      <span className={styles.itemLabel}>{o.label}</span>
      <span className={styles.itemHint}>{o.hint}</span>
    </a>
  );

  return (
    <div className={styles.root} ref={rootRef}>
      <button
        ref={buttonRef}
        type="button"
        className={`btn ${variant === "primary" ? "btn-primary" : "btn-quiet"}`}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((o) => !o)}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") {
            e.preventDefault();
            setOpen(true);
          }
        }}
      >
        <Icon name="download" size={17} />
        Download transcript
        <Icon name="chevronDown" size={15} className={open ? styles.flip : undefined} />
      </button>
      {open && (
        <div id={id} role="menu" aria-label="Transcript formats" className={styles.menu} onKeyDown={onMenuKey}>
          {options.map((o, i) => item(o, i))}
          {extra && (
            <>
              <div className={styles.sep} role="separator" />
              {item(extra, options.length)}
            </>
          )}
        </div>
      )}
    </div>
  );
}
