import React from "react";

// Minimal stroke icon set, 24x24, currentColor. No emoji anywhere in the
// product surface; these inherit text color so both themes just work.

function I({ children, size = 15, label }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round"
      strokeLinejoin="round" aria-hidden={label ? undefined : true}
      role={label ? "img" : undefined} aria-label={label}
      style={{ flexShrink: 0, verticalAlign: "-2px" }}>
      {children}
    </svg>
  );
}

export const CalendarIcon = (p) => (
  <I {...p}><rect x="3" y="4" width="18" height="17" rx="2" />
    <path d="M3 9h18M8 2v4M16 2v4" /></I>
);
export const WeatherIcon = (p) => (
  <I {...p}><path d="M17 16a4 4 0 100-8 5.5 5.5 0 00-10.4 1.2A3.5 3.5 0 007 16z" />
    <path d="M8 20h.01M12 20h.01M16 20h.01" /></I>
);
export const DataIcon = (p) => (
  <I {...p}><ellipse cx="12" cy="5.5" rx="8" ry="2.8" />
    <path d="M4 5.5v6c0 1.6 3.6 2.8 8 2.8s8-1.2 8-2.8v-6" />
    <path d="M4 11.5v6c0 1.6 3.6 2.8 8 2.8s8-1.2 8-2.8v-6" /></I>
);
export const AgentIcon = (p) => (
  <I {...p}><rect x="5" y="7" width="14" height="12" rx="3" />
    <path d="M12 7V3M8 12h.01M16 12h.01M9 16h6" /></I>
);
export const ShieldIcon = (p) => (
  <I {...p}><path d="M12 3l7 3v6c0 4.4-3 7.6-7 9-4-1.4-7-4.6-7-9V6z" />
    <path d="M9 12l2 2 4-4" /></I>
);
export const FlagIcon = (p) => (
  <I {...p}><path d="M5 21V4" /><path d="M5 4h11l-2 3.5L16 11H5" /></I>
);
export const LayersIcon = (p) => (
  <I {...p}><path d="M12 3l9 5-9 5-9-5z" /><path d="M3 13l9 5 9-5" /></I>
);
export const BranchIcon = (p) => (
  <I {...p}><circle cx="6" cy="5" r="2.2" /><circle cx="6" cy="19" r="2.2" />
    <circle cx="18" cy="12" r="2.2" />
    <path d="M6 7.2v9.6M8 6.2l7.8 4.6M8 17.8l7.8-4.6" /></I>
);
export const TrophyIcon = (p) => (
  <I {...p}><path d="M8 4h8v5a4 4 0 01-8 0z" />
    <path d="M8 5H4.5A3.5 3.5 0 008 12M16 5h3.5A3.5 3.5 0 0116 12" />
    <path d="M12 13v4M8 21h8M10 17h4v4h-4z" /></I>
);
export const AlertIcon = (p) => (
  <I {...p}><path d="M12 3l10 17H2z" /><path d="M12 10v4M12 17.5h.01" /></I>
);
export const BirdIcon = (p) => (
  <I {...p}><path d="M3.5 18H11a8 8 0 008-8V7a4 4 0 00-7.3-2.3L2.5 19.5" />
    <path d="M16 7h.01" />
    <path d="M19 6.7l2.5.8-2.5 1" />
    <path d="M9.5 18v3M13.5 17.6V21" /></I>
);
export const HikeIcon = (p) => (
  <I {...p}><path d="M3 20l6-9 4 5 3-4 5 8z" /><circle cx="17" cy="5" r="2" /></I>
);
export const PaddleIcon = (p) => (
  <I {...p}><path d="M4 20L18 6" /><path d="M18 6c1.5-1.5 3-1.5 3-1.5S21 6 19.5 7.5 16.5 9 16.5 9 16.5 7.5 18 6z" />
    <path d="M4 20c-1.5 1.5-1.5 3-1.5 3s1.5 0 3-1.5" /></I>
);
export const MuseumIcon = (p) => (
  <I {...p}><path d="M3 9l9-5 9 5" /><path d="M4 9h16v2H4z" />
    <path d="M6 11v7M10 11v7M14 11v7M18 11v7M3 20h18" /></I>
);
export const PinIcon = (p) => (
  <I {...p}><path d="M12 21s-7-6.2-7-11a7 7 0 0114 0c0 4.8-7 11-7 11z" />
    <circle cx="12" cy="10" r="2.5" /></I>
);
export const TrainIcon = (p) => (
  <I {...p}><rect x="5" y="3" width="14" height="14" rx="3" />
    <path d="M5 11h14M9 21l1.5-4M15 21L13.5 17M9 14h.01M15 14h.01" /></I>
);
export const WalkIcon = (p) => (
  <I {...p}><circle cx="13" cy="4.5" r="2" />
    <path d="M10 21l2.5-6L10 12l1-5 4 2 3 1M10 12l-3 2 1 7M15 21l-1.5-5" /></I>
);
export const StarIcon = (p) => (
  <I {...p}><path d="M12 3l2.7 5.6 6.3.8-4.6 4.3 1.2 6.1L12 16.9 6.4 19.8l1.2-6.1L3 9.4l6.3-.8z" /></I>
);
export const SunIcon = (p) => (
  <I {...p}><circle cx="12" cy="12" r="4" />
    <path d="M12 2v2.5M12 19.5V22M2 12h2.5M19.5 12H22M4.6 4.6l1.8 1.8M17.6 17.6l1.8 1.8M19.4 4.6l-1.8 1.8M6.4 17.6l-1.8 1.8" /></I>
);
export const MoonIcon = (p) => (
  <I {...p}><path d="M20 14.5A8.5 8.5 0 019.5 4 8.5 8.5 0 1020 14.5z" /></I>
);
export const MapIcon = (p) => (
  <I {...p}><path d="M9 4L3 6v14l6-2 6 2 6-2V4l-6 2z" /><path d="M9 4v14M15 6v14" /></I>
);
export const DocIcon = (p) => (
  <I {...p}><path d="M6 2h9l4 4v16H6z" /><path d="M15 2v4h4M9 12h7M9 16h7" /></I>
);
export const GridIcon = (p) => (
  <I {...p}><rect x="3" y="3" width="18" height="18" rx="2" />
    <path d="M3 9h18M9 3v18M15 3v18" /></I>
);
export const CheckIcon = (p) => (
  <I {...p}><path d="M4 12.5l5 5L20 6.5" /></I>
);
export const PruneIcon = (p) => (
  <I {...p}><circle cx="6" cy="6" r="2.5" /><circle cx="6" cy="18" r="2.5" />
    <path d="M8 7.5L20 19M8 16.5L20 5" /></I>
);
export const ScaleIcon = (p) => (
  <I {...p}><path d="M12 3v18M4 7h16M8 21h8" />
    <path d="M6 7l-2.8 6a3 3 0 005.6 0zM18 7l-2.8 6a3 3 0 005.6 0z" /></I>
);
export const SigmaIcon = (p) => (
  <I {...p}><path d="M18 5H6l6 7-6 7h12" /></I>
);
export const StampIcon = (p) => (
  <I {...p}><path d="M12 13a3.5 3.5 0 10-3.5-3.5" />
    <path d="M7 13h10l1 4H6zM5 21h14" /></I>
);
export const DotIcon = (p) => (
  <I {...p}><circle cx="12" cy="12" r="2" fill="currentColor" stroke="none" /></I>
);

// Category icon for a scored candidate (or a weekly pick, which carries
// `category` instead of `domain`). Birding gets the bird; events, markets
// and other mapped locations get the place pin; venues get the museum.
const CATEGORY = {
  birding: BirdIcon,
  nature: BirdIcon,
  hike: HikeIcon,
  kayaking: PaddleIcon,
  outdoor_event: PinIcon,
  indoor: MuseumIcon,
  museum: MuseumIcon,
};

export function CategoryIcon({ candidate, size = 15 }) {
  const id = candidate?.base?.candidate_id || candidate?.candidate_id || "";
  const key = candidate?.domain || candidate?.category || "";
  let Cmp = CATEGORY[key] || PinIcon;
  if (id.startsWith("venue@")) Cmp = MuseumIcon;
  else if (id.startsWith("event@")) Cmp = PinIcon;
  return <Cmp size={size} />;
}
