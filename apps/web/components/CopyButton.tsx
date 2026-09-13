"use client";

import { useEffect, useState } from "react";
import { Icon } from "./Icon";

/** Copies `text` to the clipboard; the label confirms for two seconds. */
export function CopyButton({ text, label, done }: { text: string; label: string; done: string }) {
  const [copied, setCopied] = useState(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!copied && !failed) return;
    const t = setTimeout(() => {
      setCopied(false);
      setFailed(false);
    }, 2200);
    return () => clearTimeout(t);
  }, [copied, failed]);

  return (
    <button
      type="button"
      className="btn btn-quiet"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setCopied(true);
        } catch {
          setFailed(true);
        }
      }}
    >
      <Icon name={copied ? "check" : "copy"} size={17} />
      <span aria-live="polite">{copied ? done : failed ? "Couldn’t copy. Use Download instead" : label}</span>
    </button>
  );
}
