/**
 * The arithmetic under `TripCalendar`.
 *
 * A calendar is the one component where the bugs are all silent and all at the
 * edges: a departure drawn a day early because a `Date` was built from a
 * string, a February that gets a 30th, a range across New Year that stops in
 * December. None of those throw. So the grid is tested on civil dates, in
 * whatever timezone the test happens to run in — and one case sets an offset
 * far enough west that the old parsing would have moved every date.
 */

import { afterEach, describe, expect, it } from 'vitest';

import {
  daysInMonth,
  monthsFor,
  parseCivil,
  toIso,
  weekStartFor,
  weekdayLetters,
  weekdayOf,
} from '../src/calendar.js';

const originalTz = process.env['TZ'];
afterEach(() => {
  if (originalTz === undefined) delete process.env['TZ'];
  else process.env['TZ'] = originalTz;
});

describe('parsing a day', () => {
  it('reads yyyy-MM-dd', () => {
    expect(parseCivil('2027-04-12')).toEqual({ year: 2027, month: 4, day: 12 });
  });

  it('reads the day out of an RFC 3339 instant and ignores the rest', () => {
    // What DateRangePicker binds. The offset is a fact about the browser that
    // set it, not about the trip, and applying it is how a departure moves a
    // day.
    expect(parseCivil('2027-04-12T00:00:00Z')).toEqual({ year: 2027, month: 4, day: 12 });
    expect(parseCivil('2027-04-12T23:30:00-08:00')).toEqual({ year: 2027, month: 4, day: 12 });
  });

  it('is not moved by the timezone the code runs in', () => {
    process.env['TZ'] = 'Pacific/Honolulu';
    expect(toIso(parseCivil('2027-04-12')!)).toBe('2027-04-12');
    const [april] = monthsFor(parseCivil('2027-04-12')!, null, 1);
    const start = april!.weeks.flat().find((cell) => cell?.isStart);
    expect(start?.iso).toBe('2027-04-12');
  });

  it('refuses what is not a day', () => {
    expect(parseCivil('')).toBeNull();
    expect(parseCivil(undefined)).toBeNull();
    expect(parseCivil('April 12')).toBeNull();
    expect(parseCivil('2027-13-01')).toBeNull();
    expect(parseCivil('2027-02-30')).toBeNull();
  });
});

describe('the month', () => {
  it('knows February', () => {
    expect(daysInMonth(2027, 2)).toBe(28);
    expect(daysInMonth(2028, 2)).toBe(29);
    expect(daysInMonth(2100, 2)).toBe(28);
  });

  it('knows the weekday', () => {
    // 12 April 2027 is a Monday.
    expect(weekdayOf({ year: 2027, month: 4, day: 12 })).toBe(1);
  });
});

describe('the grid', () => {
  const start = parseCivil('2027-04-12')!;
  const end = parseCivil('2027-04-18')!;

  it('pads the first week to the day the week starts on', () => {
    // April 2027 starts on a Thursday.
    const [mondayFirst] = monthsFor(start, end, 1);
    expect(mondayFirst!.weeks[0]!.slice(0, 3)).toEqual([null, null, null]);
    expect(mondayFirst!.weeks[0]![3]!.iso).toBe('2027-04-01');

    const [sundayFirst] = monthsFor(start, end, 0);
    expect(sundayFirst!.weeks[0]!.slice(0, 4)).toEqual([null, null, null, null]);
    expect(sundayFirst!.weeks[0]![4]!.iso).toBe('2027-04-01');
  });

  it('is whole weeks, every month', () => {
    for (const month of monthsFor(start, parseCivil('2027-06-03')!, 1)) {
      for (const week of month.weeks) expect(week).toHaveLength(7);
    }
  });

  it('bands the range with both ends inside it', () => {
    const [april] = monthsFor(start, end, 1);
    const banded = april!.weeks.flat().filter((cell) => cell?.inRange).map((cell) => cell!.iso);
    expect(banded).toEqual([
      '2027-04-12',
      '2027-04-13',
      '2027-04-14',
      '2027-04-15',
      '2027-04-16',
      '2027-04-17',
      '2027-04-18',
    ]);
    expect(april!.weeks.flat().find((cell) => cell?.isStart)?.iso).toBe('2027-04-12');
    expect(april!.weeks.flat().find((cell) => cell?.isEnd)?.iso).toBe('2027-04-18');
  });

  it('spans months, and years', () => {
    const months = monthsFor(parseCivil('2027-12-28')!, parseCivil('2028-01-03')!, 1);
    expect(months.map((m) => [m.year, m.month])).toEqual([
      [2027, 12],
      [2028, 1],
    ]);
    const banded = months.flatMap((m) => m.weeks.flat()).filter((cell) => cell?.inRange);
    expect(banded).toHaveLength(7);
    expect(banded[0]!.isStart).toBe(true);
    expect(banded[6]!.isEnd).toBe(true);
  });

  it('draws one day when there is no end, or the end is before the start', () => {
    // A range being edited passes through inverted. Vanishing at that moment
    // is worse than showing the one day that is certainly true.
    for (const finish of [null, parseCivil('2027-04-01')]) {
      const [april] = monthsFor(start, finish, 1);
      const banded = april!.weeks.flat().filter((cell) => cell?.inRange);
      expect(banded).toHaveLength(1);
      expect(banded[0]!.isStart && banded[0]!.isEnd).toBe(true);
    }
  });

  it('stops at the cap rather than drawing a typo', () => {
    expect(monthsFor(start, parseCivil('2072-04-18')!, 1)).toHaveLength(4);
  });
});

describe('the week', () => {
  it('starts on Sunday for the regions that count that way, Monday elsewhere', () => {
    expect(weekStartFor('en-US')).toBe(0);
    expect(weekStartFor('en-GB')).toBe(1);
    expect(weekStartFor('de-DE')).toBe(1);
    expect(weekStartFor(undefined)).toBe(1);
  });

  it('labels the columns in week order', () => {
    expect(weekdayLetters(1, 'en')).toEqual(['M', 'T', 'W', 'T', 'F', 'S', 'S']);
    expect(weekdayLetters(0, 'en')).toEqual(['S', 'M', 'T', 'W', 'T', 'F', 'S']);
  });
});
