import type { SVGProps } from "react";

/** A small hand-drawn icon set. 20px grid, 1.6 stroke, currentColor. */
const paths = {
  chevronLeft: <path d="M12.5 4.5 7 10l5.5 5.5" />,
  chevronRight: <path d="M7.5 4.5 13 10l-5.5 5.5" />,
  chevronDown: <path d="M4.5 7.5 10 13l5.5-5.5" />,
  download: (
    <>
      <path d="M10 3v9.5" />
      <path d="m6 8.8 4 3.9 4-3.9" />
      <path d="M3.5 13.5v2.2c0 .5.4.8.8.8h11.4c.4 0 .8-.3.8-.8v-2.2" />
    </>
  ),
  search: (
    <>
      <circle cx="8.8" cy="8.8" r="5.3" />
      <path d="m12.7 12.7 3.8 3.8" />
    </>
  ),
  hash: (
    <>
      <path d="M8 3.5 6.5 16.5M13.5 3.5 12 16.5M4 7.5h12.5M3.5 12.5H16" />
    </>
  ),
  doc: (
    <>
      <path d="M5 2.8h6.5l3.5 3.5v10.1c0 .4-.4.8-.8.8H5c-.4 0-.8-.4-.8-.8V3.6c0-.4.4-.8.8-.8Z" />
      <path d="M11.3 2.9v3.6h3.6M7 10.5h6M7 13.5h4" />
    </>
  ),
  calendar: (
    <>
      <rect x="3.2" y="4.3" width="13.6" height="12.4" rx="1.4" />
      <path d="M3.2 8.3h13.6M7 2.8v3M13 2.8v3" />
    </>
  ),
  chat: <path d="M4.2 4h11.6c.6 0 1 .4 1 1v7.6c0 .6-.4 1-1 1H9.4L6 16.4v-2.8H4.2c-.6 0-1-.4-1-1V5c0-.6.4-1 1-1Z" />,
  flag: (
    <>
      <path d="M5 17V3.5" />
      <path d="M5 4h9.2l-2 3.3 2 3.3H5" />
    </>
  ),
  check: <path d="m4.5 10.5 3.6 3.5 7.4-8" />,
  copy: (
    <>
      <rect x="7" y="7" width="9.5" height="9.5" rx="1.3" />
      <path d="M13 7V4.8c0-.7-.6-1.3-1.3-1.3H4.8c-.7 0-1.3.6-1.3 1.3v6.9c0 .7.6 1.3 1.3 1.3H7" />
    </>
  ),
  ring: <circle cx="10" cy="10" r="4.6" />,
  door: (
    <>
      <path d="M5 17V3.6c0-.4.3-.6.6-.6h8.8c.3 0 .6.2.6.6V17" />
      <path d="M3 17h14M11.5 10.2v.6" />
    </>
  ),
  x: <path d="m5.5 5.5 9 9m0-9-9 9" />,
} as const;

export type IconName = keyof typeof paths;

export function Icon({ name, size = 18, ...rest }: { name: IconName; size?: number } & SVGProps<SVGSVGElement>) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...rest}
    >
      {paths[name]}
    </svg>
  );
}

export function SourceIcon({ kind, size = 16 }: { kind: "slack" | "drive" | "calendar"; size?: number }) {
  const name: IconName = kind === "slack" ? "hash" : kind === "drive" ? "doc" : "calendar";
  return <Icon name={name} size={size} />;
}
