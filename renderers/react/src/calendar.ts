/**
 * The arithmetic behind `TripCalendar`, kept away from the DOM so it can be
 * tested on a list of strings.
 *
 * Everything here works on civil dates — `2027-04-12` as a year, a month and a
 * day — and never on instants. A trip's dates are days, not moments: the
 * traveller leaves on the 12th whichever timezone the browser is in, and a
 * `Date` built from `"2027-04-12"` is midnight UTC, which is the 11th in
 * California. Every calendar that has ever shown a departure one day early got
 * there by that route, so the parsing below reads the digits and stops.
 */

/** A civil date, with no timezone to be wrong about. */
export interface CivilDate {
  year: number;
  /** 1–12. */
  month: number;
  /** 1–31. */
  day: number;
}

/** One cell of a month grid. `null` pads the first and last week. */
export interface CalendarCell {
  date: CivilDate;
  iso: string;
  /** Inside the highlighted travel band, ends inclusive. */
  inRange: boolean;
  isStart: boolean;
  isEnd: boolean;
}

export interface CalendarMonth {
  year: number;
  month: number;
  /** Weeks of seven, padded with `null` outside the month. */
  weeks: Array<Array<CalendarCell | null>>;
}

const ISO_DATE = /^(\d{4})-(\d{2})-(\d{2})/;

/**
 * Reads a civil date out of the front of a string.
 *
 * Accepts `yyyy-MM-dd` and anything that starts with one — an RFC 3339 instant
 * from `DateRangePicker`, say — because the first ten characters are the day
 * and the rest is a timezone this component must not apply. Anything else is
 * `null`, and the caller draws nothing rather than guessing.
 */
export function parseCivil(value: string | undefined | null): CivilDate | null {
  if (!value) return null;
  const match = ISO_DATE.exec(value.trim());
  if (!match) return null;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  if (month < 1 || month > 12 || day < 1 || day > daysInMonth(year, month)) return null;
  return { year, month, day };
}

export function toIso(date: CivilDate): string {
  const mm = String(date.month).padStart(2, '0');
  const dd = String(date.day).padStart(2, '0');
  return `${date.year}-${mm}-${dd}`;
}

/** Comparable integer: later dates are larger. */
const ordinal = (date: CivilDate): number => date.year * 10_000 + date.month * 100 + date.day;

export function daysInMonth(year: number, month: number): number {
  // Day zero of the next month is the last day of this one; `Date.UTC` does
  // the leap-year arithmetic and is not affected by the browser's zone.
  return new Date(Date.UTC(year, month, 0)).getUTCDate();
}

/** 0 = Sunday … 6 = Saturday, as `Date` counts them. */
export function weekdayOf(date: CivilDate): number {
  return new Date(Date.UTC(date.year, date.month - 1, date.day)).getUTCDay();
}

/**
 * Which day the week starts on, from the locale.
 *
 * `Intl.Locale#getWeekInfo` knows, where it exists; elsewhere the answer that is
 * right for the most people is Monday everywhere except the handful of regions
 * that count from Sunday. A prop for this would be one more argument the model
 * has to be taught for a fact the browser already has.
 */
export function weekStartFor(locale: string | undefined): 0 | 1 {
  // No locale is not "English": a bare `en` maximises to `en-US` and answers
  // Sunday for everybody the browser did not identify.
  if (!locale) return 1;
  try {
    const info = (new Intl.Locale(locale) as unknown as {
      getWeekInfo?: () => { firstDay: number };
      weekInfo?: { firstDay: number };
    });
    const firstDay = info.getWeekInfo?.().firstDay ?? info.weekInfo?.firstDay;
    if (firstDay === 7) return 0;
    if (firstDay === 1) return 1;
  } catch {
    /* an unknown locale tag; fall through to the region rule */
  }
  const region = /-([A-Z]{2})\b/.exec(locale || '')?.[1];
  return region && SUNDAY_FIRST.has(region) ? 0 : 1;
}

const SUNDAY_FIRST = new Set(['US', 'CA', 'JP', 'IL', 'BR', 'MX', 'PH', 'ZA', 'IN', 'KR', 'TW', 'HK', 'AU']);

/**
 * Every month the range touches, as padded week grids.
 *
 * With no `end`, or an `end` before `start`, the band is the single day: a
 * calendar that draws nothing when handed an inverted range is a calendar that
 * disappears the moment somebody edits the first date, and a one-day band is
 * both true and recoverable. Capped at `maxMonths` so a typo in a year does not
 * render three hundred grids.
 */
export function monthsFor(
  start: CivilDate,
  end: CivilDate | null,
  weekStart: 0 | 1,
  maxMonths = 4,
): CalendarMonth[] {
  const last = end && ordinal(end) >= ordinal(start) ? end : start;
  const startKey = ordinal(start);
  const endKey = ordinal(last);

  const months: CalendarMonth[] = [];
  let year = start.year;
  let month = start.month;
  while (months.length < maxMonths) {
    months.push(monthGrid(year, month, startKey, endKey, weekStart));
    if (year === last.year && month === last.month) break;
    month += 1;
    if (month > 12) {
      month = 1;
      year += 1;
    }
  }
  return months;
}

function monthGrid(
  year: number,
  month: number,
  startKey: number,
  endKey: number,
  weekStart: 0 | 1,
): CalendarMonth {
  const total = daysInMonth(year, month);
  const cells: Array<CalendarCell | null> = [];

  // Pad up to the first day, counting from the week's first column.
  const leading = (weekdayOf({ year, month, day: 1 }) - weekStart + 7) % 7;
  for (let i = 0; i < leading; i += 1) cells.push(null);

  for (let day = 1; day <= total; day += 1) {
    const date = { year, month, day };
    const key = ordinal(date);
    cells.push({
      date,
      iso: toIso(date),
      inRange: key >= startKey && key <= endKey,
      isStart: key === startKey,
      isEnd: key === endKey,
    });
  }
  while (cells.length % 7 !== 0) cells.push(null);

  const weeks: Array<Array<CalendarCell | null>> = [];
  for (let i = 0; i < cells.length; i += 7) weeks.push(cells.slice(i, i + 7));
  return { year, month, weeks };
}

/** Column headings in week order, e.g. `['M','T','W','T','F','S','S']`. */
export function weekdayLetters(weekStart: 0 | 1, locale?: string): string[] {
  const letters: string[] = [];
  for (let i = 0; i < 7; i += 1) {
    const weekday = (weekStart + i) % 7;
    // The 4th of January 1970 was a Sunday; the offset lands on each weekday in
    // turn, and the formatter names it in the reader's language.
    const sample = new Date(Date.UTC(1970, 0, 4 + weekday));
    const name = new Intl.DateTimeFormat(locale, { weekday: 'narrow', timeZone: 'UTC' }).format(sample);
    letters.push(name);
  }
  return letters;
}

/** "April 2027", in the reader's language. */
export function monthLabel(year: number, month: number, locale?: string): string {
  const sample = new Date(Date.UTC(year, month - 1, 1));
  return new Intl.DateTimeFormat(locale, { month: 'long', year: 'numeric', timeZone: 'UTC' }).format(sample);
}
