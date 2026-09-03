/**
 * Inline SVG icons.
 *
 * Inline rather than an icon font or a package: the whole renderer has to work
 * inside a Cloudflare-hosted bundle with no network fetches beyond the API, and
 * an icon that fails to load turns a travel card into a mystery. These are all
 * on a 24px grid with `currentColor` strokes, so they inherit text colour and
 * work in both themes without a second definition.
 */

import type { ReactElement, SVGProps } from 'react';

export type IconName =
  | 'plane'
  | 'bed'
  | 'food'
  | 'sight'
  | 'transit'
  | 'outdoors'
  | 'shopping'
  | 'event'
  | 'free'
  | 'stay'
  | 'sun'
  | 'cloud'
  | 'rain'
  | 'storm'
  | 'snow'
  | 'fog'
  | 'pin'
  | 'check'
  | 'close'
  | 'chevron'
  | 'wallet'
  | 'calendar'
  | 'sparkle'
  | 'users';

const paths: Record<string, ReactElement> = {
  plane: <path d="M2.5 14.2 21.3 4.6a1 1 0 0 1 1.3 1.4l-4.4 7.6 1.6 6.6-2 .9-3.4-5.6-4.5 2.4-.3 3.3-1.7.8-1.2-4-3.6-2 .8-1.7 3.3-.3Z" />,
  bed: (
    <>
      <path d="M3 18v-9" />
      <path d="M3 13h18v5" />
      <path d="M21 18v-4" />
      <path d="M7 13v-2a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2" />
    </>
  ),
  food: (
    <>
      <path d="M6 3v8a2 2 0 0 0 4 0V3" />
      <path d="M8 11v10" />
      <path d="M17 3c-1.5 1.5-2 3.5-2 6s.5 3 2 3v9" />
    </>
  ),
  sight: (
    <>
      <path d="M4 20V9l8-5 8 5v11" />
      <path d="M9 20v-6h6v6" />
    </>
  ),
  transit: (
    <>
      <rect x="5" y="4" width="14" height="12" rx="2" />
      <path d="M5 11h14" />
      <path d="M8 20l-1.5 2M16 20l1.5 2" />
      <circle cx="8.5" cy="14" r=".6" />
      <circle cx="15.5" cy="14" r=".6" />
    </>
  ),
  outdoors: (
    <>
      <path d="M12 3 4 19h16L12 3Z" />
      <path d="M12 12 8 19h8l-4-7Z" />
    </>
  ),
  shopping: (
    <>
      <path d="M5 8h14l-1 12H6L5 8Z" />
      <path d="M9 8V6a3 3 0 0 1 6 0v2" />
    </>
  ),
  event: (
    <>
      <rect x="4" y="5" width="16" height="16" rx="2" />
      <path d="M4 10h16M9 3v4M15 3v4" />
    </>
  ),
  free: <circle cx="12" cy="12" r="7" />,
  sun: (
    <>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.5 1.5M17.5 17.5 19 19M19 5l-1.5 1.5M6.5 17.5 5 19" />
    </>
  ),
  cloud: <path d="M7 18a4 4 0 0 1 .6-8 5.5 5.5 0 0 1 10.6 1.6A3.4 3.4 0 0 1 17.5 18H7Z" />,
  rain: (
    <>
      <path d="M7 15a4 4 0 0 1 .6-8 5.5 5.5 0 0 1 10.6 1.6A3.4 3.4 0 0 1 17.5 15H7Z" />
      <path d="M9 18l-1 3M13 18l-1 3M17 18l-1 3" />
    </>
  ),
  storm: (
    <>
      <path d="M7 14a4 4 0 0 1 .6-8 5.5 5.5 0 0 1 10.6 1.6A3.4 3.4 0 0 1 17.5 14H7Z" />
      <path d="M13 16l-3 4h3l-1 3" />
    </>
  ),
  snow: (
    <>
      <path d="M7 14a4 4 0 0 1 .6-8 5.5 5.5 0 0 1 10.6 1.6A3.4 3.4 0 0 1 17.5 14H7Z" />
      <path d="M9 18v.01M13 19v.01M17 18v.01M11 21v.01M15 21v.01" />
    </>
  ),
  fog: (
    <>
      <path d="M7 12a4 4 0 0 1 .6-8 5.5 5.5 0 0 1 10.6 1.6A3.4 3.4 0 0 1 17.5 12H7Z" />
      <path d="M5 16h14M7 20h12" />
    </>
  ),
  pin: (
    <>
      <path d="M12 21s7-5.5 7-11a7 7 0 1 0-14 0c0 5.5 7 11 7 11Z" />
      <circle cx="12" cy="10" r="2.5" />
    </>
  ),
  check: <path d="m4 12 5 5L20 6" />,
  close: <path d="M6 6l12 12M18 6 6 18" />,
  chevron: <path d="m9 6 6 6-6 6" />,
  wallet: (
    <>
      <rect x="3" y="6" width="18" height="13" rx="2" />
      <path d="M3 10h18" />
      <circle cx="17" cy="14" r="1" />
    </>
  ),
  calendar: (
    <>
      <rect x="4" y="5" width="16" height="16" rx="2" />
      <path d="M4 10h16M9 3v4M15 3v4" />
    </>
  ),
  sparkle: <path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3Z" />,
  users: (
    <>
      <circle cx="9" cy="9" r="3" />
      <path d="M3 20a6 6 0 0 1 12 0" />
      <path d="M16 7a3 3 0 0 1 0 6M17 20a6 6 0 0 0-2-4.5" />
    </>
  ),
};

const ALIASES: Record<string, IconName> = {
  stay: 'bed',
  hotel: 'bed',
  restaurant: 'food',
  museum: 'sight',
  flight: 'plane',
  clear: 'sun',
  sunny: 'sun',
  cloudy: 'cloud',
  showers: 'rain',
  thunderstorm: 'storm',
  location: 'pin',
  map: 'pin',
  money: 'wallet',
  date: 'calendar',
};

export interface IconProps extends SVGProps<SVGSVGElement> {
  name: string;
}

export function Icon({ name, ...rest }: IconProps) {
  const key = ALIASES[name?.toLowerCase?.() ?? ''] ?? name;
  const glyph = paths[key] ?? paths['sparkle']!;
  return (
    <svg
      viewBox="0 0 24 24"
      width="1em"
      height="1em"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
      focusable="false"
      {...rest}
    >
      {glyph}
    </svg>
  );
}
