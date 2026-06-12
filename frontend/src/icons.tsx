import type { SVGProps } from "react";

const I = (p: SVGProps<SVGSVGElement>) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.6}
       strokeLinecap="round" strokeLinejoin="round" {...p} />
);

type P = SVGProps<SVGSVGElement>;

export const Icon = {
  map: (p: P) => <I {...p}><polygon points="1 6 8 3 16 6 23 3 23 18 16 21 8 18 1 21"/><line x1="8" y1="3" x2="8" y2="18"/><line x1="16" y1="6" x2="16" y2="21"/></I>,
  trace: (p: P) => <I {...p}><circle cx="5" cy="6" r="2.2"/><circle cx="19" cy="6" r="2.2"/><circle cx="12" cy="18" r="2.2"/><path d="M7 6h10M6 8l5 8M18 8l-5 8"/></I>,
  tables: (p: P) => <I {...p}><rect x="3" y="4" width="18" height="16" rx="2"/><line x1="3" y1="10" x2="21" y2="10"/><line x1="9" y1="10" x2="9" y2="20"/></I>,
  chat: (p: P) => <I {...p}><path d="M21 11.5a8.4 8.4 0 0 1-12 7.6L3 21l1.9-5.6A8.4 8.4 0 1 1 21 11.5z"/></I>,
  settings: (p: P) => <I {...p}><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1"/></I>,
  search: (p: P) => <I {...p}><circle cx="11" cy="11" r="7"/><line x1="21" y1="21" x2="16.5" y2="16.5"/></I>,
  refresh: (p: P) => <I {...p}><path d="M21 12a9 9 0 1 1-2.6-6.4M21 3v4h-4"/></I>,
  sun: (p: P) => <I {...p}><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.4 1.4M17.6 17.6L19 19M5 19l1.4-1.4M17.6 6.4L19 5"/></I>,
  moon: (p: P) => <I {...p}><path d="M21 12.8A8.5 8.5 0 1 1 11.2 3a6.6 6.6 0 0 0 9.8 9.8z"/></I>,
  plus: (p: P) => <I {...p}><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></I>,
  minus: (p: P) => <I {...p}><line x1="5" y1="12" x2="19" y2="12"/></I>,
  fit: (p: P) => <I {...p}><path d="M4 9V5a1 1 0 0 1 1-1h4M20 9V5a1 1 0 0 0-1-1h-4M4 15v4a1 1 0 0 0 1 1h4M20 15v4a1 1 0 0 1-1 1h-4"/></I>,
  upload: (p: P) => <I {...p}><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M12 3v13M7 8l5-5 5 5"/></I>,
  zip: (p: P) => <I {...p}><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/><path d="M10 6h2M10 9h2M10 12h2"/></I>,
  spark: (p: P) => <I {...p}><path d="M12 3l1.8 5.6L19.5 10.4 13.8 12.2 12 18l-1.8-5.8L4.5 10.4l5.7-1.8z" fill="currentColor" stroke="none"/></I>,
  check: (p: P) => <I {...p}><polyline points="20 6 9 17 4 12"/></I>,
  arrow: (p: P) => <I {...p}><line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/></I>,
  link: (p: P) => <I {...p}><path d="M10 13a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1 1"/><path d="M14 11a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1-1"/></I>,
  file: (p: P) => <I {...p}><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/></I>,
  db: (p: P) => <I {...p}><ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v6c0 1.7 3.6 3 8 3s8-1.3 8-3V5M4 11v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"/></I>,
  send: (p: P) => <I {...p}><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></I>,
  clock: (p: P) => <I {...p}><circle cx="12" cy="12" r="9"/><polyline points="12 7 12 12 15 14"/></I>,
  diff: (p: P) => <I {...p}><circle cx="6.5" cy="6.5" r="2.5"/><circle cx="17.5" cy="17.5" r="2.5"/><path d="M6.5 9.5V13a3.5 3.5 0 0 0 3.5 3.5h3M17.5 14.5V11a3.5 3.5 0 0 0-3.5-3.5h-3"/></I>,
  cloud: (p: P) => <I {...p}><path d="M17.5 19a4.5 4.5 0 0 0 .5-8.97A6 6 0 0 0 6.34 9.2 4 4 0 0 0 7 17h10.5z"/></I>,
  bolt: (p: P) => <I {...p}><polygon points="13 2 4 14 11 14 10 22 19 9 12 9 13 2"/></I>,
  x: (p: P) => <I {...p}><line x1="6" y1="6" x2="18" y2="18"/><line x1="18" y1="6" x2="6" y2="18"/></I>,
};

export function Logo() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" width={18} height={18}>
      <circle cx="6" cy="6" r="2.4" /><circle cx="6" cy="18" r="2.4" /><circle cx="18" cy="12" r="2.4" />
      <path d="M8 7l8 4M8 17l8-4" />
    </svg>
  );
}

export function Spinner(p: { size?: number }) {
  const s = p.size ?? 38;
  return (
    <span className="spin" style={{ width: s, height: s }}>
      <svg viewBox="0 0 38 38" style={{ width: s, height: s }}>
        <circle cx="19" cy="19" r="15.5" />
      </svg>
    </span>
  );
}
