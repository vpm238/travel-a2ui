/**
 * The travel components, drawn for the A2UI SDK.
 *
 * Each is a React view handed to `@a2ui/react`'s `createComponentImplementation`,
 * so it receives props the SDK's generic binder has already resolved: bound
 * values are values, `action` is a function to call, a bound field has a setter
 * beside it (`setValue`, `setStart`), and `checks` arrive as `isValid` and
 * `validationErrors`. Nothing here reads a data model, follows a pointer or
 * evaluates a function — that is `@a2ui/web_core`'s job, and this package does
 * not do it a second time.
 *
 * What is left is the part only a travel app can do: decide what a fare, a stay
 * and a day look like.
 */

import {
  useContext,
  useEffect,
  useId,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type ReactNode,
} from 'react';

import { monthLabel, monthsFor, parseCivil, toIso, weekStartFor, weekdayLetters } from '../calendar.js';
import { Icon, hasIcon } from './icons.js';
import { ariaFrom } from '../accessibility.js';
import { MapsKeyContext } from '../maps.js';

// The binder's prop types are inferred from schemas loaded at runtime, so they
// are `any` by construction. Reading them through these helpers keeps the
// coercion in one place.
type Props = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
type BuildChild = (id: string, basePath?: string) => ReactNode;
export interface ViewProps {
  props: Props;
  buildChild: BuildChild;
}

const cx = (...parts: Array<string | false | null | undefined>) => parts.filter(Boolean).join(' ');
const text = (value: unknown): string => (value === null || value === undefined ? '' : String(value));
const rows = (value: unknown): Props[] =>
  Array.isArray(value)
    ? value.filter((item): item is Props => Boolean(item) && typeof item === 'object')
    : [];

/** A field that has not arrived: the binder resolves an unfilled binding to `undefined`. */
const isPending = (value: unknown) => value === undefined;
const isAction = (value: unknown): value is () => unknown => typeof value === 'function';

/**
 * Bound text, or a shimmer of roughly its size while its row is on its way.
 *
 * Only while the *row* is on its way. A row that has arrived without a field —
 * a panel fare has no duration — shows nothing there; a shimmer would say
 * "loading" about something that is never coming.
 */
function Field({ value, width, waiting }: { value: unknown; width?: number; waiting: boolean }) {
  if (isPending(value)) return waiting ? <span className="tv-pending" style={{ width }} aria-hidden /> : null;
  return <>{text(value)}</>;
}

/** What assistive technology is told: the standard `accessibility` block (`ariaFrom`). */
function aria(props: Props, role?: string) {
  return { ...(role ? { role } : {}), ...ariaFrom(props['accessibility']) };
}

/**
 * The root of a view: what assistive technology is told, and the `weight` a
 * Row or Column gives it.
 *
 * The SDK hosts each view in an element with `display: contents`, so the
 * view's own root is the flex item, and `weight` is its `flex-grow`, as the
 * SDK's basic components apply it.
 */
function frame(props: Props, role?: string, style?: CSSProperties) {
  const weight = typeof props['weight'] === 'number' ? props['weight'] : undefined;
  const merged = weight === undefined ? style : { ...style, flexGrow: weight, minWidth: 0 };
  return { ...aria(props, role), ...(merged ? { style: merged } : {}) };
}

/** Whether a chosen card says so: `aria-pressed` on one that is a control, else `aria-current`. */
function chosen(selected: boolean, pressed: boolean) {
  if (!selected) return pressed ? { 'aria-pressed': false } : {};
  return pressed ? { 'aria-pressed': true } : { 'aria-current': true as const };
}

/** Click and Enter/Space for a card that is itself the control. */
function pressable(action: unknown, enabled = true) {
  const run = typeof action === 'function' && enabled ? (action as () => unknown) : null;
  if (!run) return {};
  return {
    role: 'button',
    tabIndex: 0,
    onClick: () => void run(),
    onKeyDown: (event: KeyboardEvent) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        void run();
      }
    },
  };
}

/** `IB426` → `IB`: what a boarding pass leads with. Nothing for anything else. */
function carrierCode(flightNumber: string): string {
  const match = /^([A-Z0-9]{2})\s?\d/.exec(flightNumber.trim().toUpperCase());
  return match ? match[1]! : '';
}

/**
 * Carrier-mark hues, chosen rather than hashed: a raw hash lands on olive and
 * mustard as often as on anything a livery would use. Eight that read as a
 * brand in both themes, picked stably per carrier.
 */
const MARK_HUES = [222, 352, 199, 262, 14, 168, 236, 330];

/** A stable number from a string, for artwork and colours that never shuffle. */
function seedOf(value: string): number {
  let hash = 0x811c9dc5;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193);
  }
  return Math.abs(hash);
}

/**
 * "01:00 +1" → ["01:00", "+1"]. The day offset is the detail people miss on a
 * departures board, so it is drawn as its own mark rather than run into the time.
 */
function splitDayOffset(value: string): [string, string] {
  const match = /^(.*?)\s*([+-]\d)$/.exec(value.trim());
  return match ? [match[1]!, match[2]!] : [value, ''];
}

/** "$352 each · $704 for 2" → the number they pay, and what it is made of. */
function splitPrice(value: string): [string, string] {
  const at = value.indexOf(' · ');
  return at === -1 ? [value, ''] : [value.slice(0, at), value.slice(at + 3)];
}

// ---------------------------------------------------------------- fares

export function FlightOption({ props }: ViewProps) {
  const pending = isPending(props['flightNumber']) && isPending(props['price']);
  const selected = props['selected'] === true;
  const flightNumber = text(props['flightNumber']);
  const code = carrierCode(flightNumber);
  const hue = MARK_HUES[seedOf(code || text(props['airline'])) % MARK_HUES.length];
  const [fare, inline] = splitPrice(text(props['price']));
  const party = text(props['total']) || inline;
  const [arrive, offset] = splitDayOffset(text(props['arriveTime']));
  const stops = text(props['stops']);
  const nonstop = /^non-?stop$/i.test(stops.trim());
  const badge = text(props['badge']);

  return (
    <article
      className={cx('tv-fare', selected && 'is-selected', pending && 'is-awaiting')}
      aria-busy={pending || undefined}
      {...frame(props, 'group')}
      {...pressable(props['action'], !pending)}
      {...chosen(selected, isAction(props['action']) && !pending)}
    >
      <div className="tv-fare__carrier">
        <span className="tv-fare__mark" style={{ ['--mark-hue' as string]: String(hue) }} aria-hidden>
          {code || <Icon name="plane" />}
        </span>
        <span className="tv-fare__airline">
          <strong>
            <Field value={props['airline']} width={96} waiting={pending} />
          </strong>
          <span>{flightNumber}</span>
        </span>
      </div>

      <div className="tv-fare__route">
        <div className="tv-fare__end">
          <strong className="tv-time">
            <Field value={props['departTime']} width={52} waiting={pending} />
          </strong>
          <span className="tv-code">
            <Field value={props['origin']} width={32} waiting={pending} />
          </span>
        </div>
        <div className="tv-fare__leg" aria-hidden>
          <span className="tv-fare__duration">
            <Field value={props['duration']} width={48} waiting={pending} />
          </span>
          <span className="tv-fare__line">
            <i />
            {!nonstop && stops ? <b /> : null}
            <i />
          </span>
          <span className={cx('tv-fare__stops', nonstop && 'is-nonstop')}>
            <Field value={props['stops']} width={56} waiting={pending} />
          </span>
        </div>
        <div className="tv-fare__end">
          <strong className="tv-time">
            {isPending(props['arriveTime']) ? (
              <Field value={undefined} width={52} waiting={pending} />
            ) : (
              arrive
            )}
            {offset ? <sup>{offset}</sup> : null}
          </strong>
          <span className="tv-code">
            <Field value={props['destination']} width={32} waiting={pending} />
          </span>
        </div>
      </div>

      <div className="tv-fare__price">
        {badge ? <span className="tv-badge">{badge}</span> : null}
        <strong className="tv-money">
          {isPending(props['price']) ? <Field value={undefined} width={64} waiting={pending} /> : fare}
        </strong>
        <span className="tv-fare__party">{party || text(props['cabin']) || 'economy'}</span>
      </div>

      {selected ? (
        <span className="tv-chosen" aria-label="Chosen">
          <Icon name="check" />
        </span>
      ) : null}
    </article>
  );
}

// ---------------------------------------------------------------- stays

/**
 * The picture on a stay with no photograph: a skyline drawn from its name.
 *
 * The stays are invented, and a stock photo of a hotel that does not exist
 * would be the one dishonest pixel in the app. A drawing cannot be mistaken
 * for a photograph, and every property keeps its own.
 */
function Skyline({ name }: { name: string }) {
  const seed = seedOf(name || 'stay');
  const hue = seed % 360;
  const towers = Array.from({ length: 9 }, (_, index) => {
    const local = seedOf(`${name}:${index}`);
    return { x: index * 16, width: 11 + (local % 5), height: 16 + (local % 38), lit: local % 3 };
  });
  return (
    <div className="tv-art" style={{ ['--art-hue' as string]: String(hue) }} aria-hidden>
      <svg viewBox="0 0 144 62" preserveAspectRatio="xMidYMax slice">
        <circle cx={118 - (seed % 80)} cy="15" r="7" className="tv-art__sun" />
        {towers.map((tower) => (
          <g key={tower.x}>
            <rect
              x={tower.x}
              y={62 - tower.height}
              width={tower.width}
              height={tower.height}
              className="tv-art__tower"
            />
            {Array.from({ length: Math.floor(tower.height / 10) }, (_, row) => (
              <rect
                key={row}
                x={tower.x + 3}
                y={62 - tower.height + 6 + row * 9}
                width={tower.width - 6}
                height="3"
                rx="1"
                className="tv-art__window"
                opacity={(row + tower.lit) % 3 === 0 ? 0.95 : 0.35}
              />
            ))}
          </g>
        ))}
      </svg>
    </div>
  );
}

const SAFE_IMAGE = /^https:\/\/[^\s"'<>]+$/i;

export function HotelCard({ props }: ViewProps) {
  const pending = isPending(props['name']) && isPending(props['price']);
  const selected = props['selected'] === true;
  const name = text(props['name']);
  const image = text(props['imageUrl']);
  const [nightly, stay] = splitPrice(text(props['price']));
  const amenities = (Array.isArray(props['amenities']) ? props['amenities'] : []).slice(0, 4);
  const badge = text(props['badge']);
  const rating = text(props['rating']);

  return (
    <article
      className={cx('tv-stay', selected && 'is-selected', pending && 'is-awaiting')}
      aria-busy={pending || undefined}
      {...frame(props, 'group')}
      {...pressable(props['action'], !pending)}
      {...chosen(selected, isAction(props['action']) && !pending)}
    >
      <div className="tv-stay__media">
        {SAFE_IMAGE.test(image) ? <img src={image} alt="" loading="lazy" /> : <Skyline name={name} />}
        {badge ? <span className="tv-badge tv-badge--float">{badge}</span> : null}
        {selected ? (
          <span className="tv-chosen tv-chosen--float" aria-label="Chosen">
            <Icon name="check" />
          </span>
        ) : null}
      </div>
      <div className="tv-stay__body">
        <div className="tv-stay__head">
          <h4>
            <Field value={props['name']} width={140} waiting={pending} />
          </h4>
          {rating ? <span className="tv-score">{rating}</span> : null}
        </div>
        {props['neighborhood'] ? (
          <p className="tv-stay__where">
            <Icon name="pin" />
            {text(props['neighborhood'])}
          </p>
        ) : null}
        {amenities.length ? (
          <ul className="tv-chips">
            {amenities.map((amenity: unknown, index: number) => (
              <li key={index}>{text(amenity)}</li>
            ))}
          </ul>
        ) : null}
        <div className="tv-stay__price">
          <strong className="tv-money">
            {isPending(props['price']) ? <Field value={undefined} width={72} waiting={pending} /> : nightly}
          </strong>
          {stay ? <span>{stay}</span> : null}
        </div>
      </div>
    </article>
  );
}

// ---------------------------------------------------------------- plans

export function ItineraryDay({ props, buildChild }: ViewProps) {
  const children = Array.isArray(props['children']) ? props['children'] : [];
  const add = isAction(props['onAdd']) ? props['onAdd'] : null;
  const open = isAction(props['action']) ? props['action'] : null;
  const title = text(props['title']);
  return (
    <section className="tv-day" {...frame(props, 'group')}>
      <header className="tv-day__head">
        <div>
          <h3>{title}</h3>
          {props['summary'] ? <p>{text(props['summary'])}</p> : null}
        </div>
        {props['date'] ? <span className="tv-day__date">{text(props['date'])}</span> : null}
        {/* The whole day's own control: a heading cannot sit inside a button. */}
        {open ? (
          <button
            type="button"
            className="tv-ghost tv-day__edit"
            aria-label={`Edit ${title || 'this day'}`}
            onClick={() => void open()}
          >
            Edit day
          </button>
        ) : null}
      </header>
      <div className="tv-day__timeline">
        {children.map((child: string | { id: string; basePath?: string }) =>
          typeof child === 'string' ? (
            <div key={child}>{buildChild(child)}</div>
          ) : (
            <div key={`${child.id}@${child.basePath ?? ''}`}>{buildChild(child.id, child.basePath)}</div>
          ),
        )}
      </div>
      {add ? (
        <button type="button" className="tv-ghost" onClick={() => void add()}>
          <Icon name="plus" /> Add something
        </button>
      ) : null}
    </section>
  );
}

export function ActivityItem({ props }: ViewProps) {
  const category = text(props['category']) || 'sight';
  const done = props['done'] === true;
  const meta = [text(props['location']), text(props['duration'])].filter(Boolean).join(' · ');
  const remove = isAction(props['onRemove']) ? props['onRemove'] : null;
  const open = isAction(props['action']) ? props['action'] : null;
  const title = text(props['title']);
  const content = (
    <>
      <span className="tv-activity__time">{text(props['time'])}</span>
      <span className={`tv-activity__dot tv-cat--${category}`} aria-hidden>
        <Icon name={hasIcon(category) ? category : 'pin'} />
      </span>
      <span className="tv-activity__body">
        <strong>{title}</strong>
        {meta ? <span className="tv-activity__meta">{meta}</span> : null}
        {props['note'] ? <em className="tv-activity__note">{text(props['note'])}</em> : null}
      </span>
    </>
  );
  return (
    <div className={cx('tv-activity', done && 'is-done')} {...frame(props, 'group')}>
      {/* Two sibling controls, never one inside the other: "tell me more" and
          "get rid of it" sharing one gesture is how a plan loses a museum
          nobody meant to lose. */}
      {open ? (
        <button type="button" className="tv-activity__main" onClick={() => void open()}>
          {content}
        </button>
      ) : (
        <div className="tv-activity__main">{content}</div>
      )}
      {remove ? (
        <button
          type="button"
          className="tv-activity__remove"
          aria-label={`Remove ${title}`}
          onClick={() => void remove()}
        >
          <Icon name="close" />
        </button>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------- money

export function PriceSummary({ props }: ViewProps) {
  const lines = rows(props['lines']);
  const act = typeof props['action'] === 'function' ? (props['action'] as () => unknown) : null;
  return (
    <div className="tv-receipt" {...frame(props, 'group')}>
      <ul className="tv-receipt__lines">
        {lines.map((line, index) => (
          <li key={index}>
            <span className="tv-receipt__label">
              {text(line['label'])}
              {line['note'] ? <em>{text(line['note'])}</em> : null}
            </span>
            <span className="tv-receipt__leader" aria-hidden />
            <span className="tv-money">{text(line['amount'])}</span>
          </li>
        ))}
      </ul>
      <div className="tv-receipt__total">
        <span>{text(props['totalLabel']) || 'Total'}</span>
        <strong className="tv-money">{text(props['total'])}</strong>
      </div>
      {props['caption'] ? <p className="tv-caption">{text(props['caption'])}</p> : null}
      {act ? (
        <button type="button" className="tv-primary" onClick={() => void act()}>
          {text(props['actionLabel']) || 'Continue'}
        </button>
      ) : null}
    </div>
  );
}

export function ExpenseSplit({ props }: ViewProps) {
  const people = rows(props['participants']);
  const act = typeof props['action'] === 'function' ? (props['action'] as () => unknown) : null;
  return (
    <div className="tv-split" {...frame(props, 'group')}>
      <div className="tv-split__head">
        <strong>{text(props['title'])}</strong>
        <span className="tv-money">{text(props['total'])}</span>
      </div>
      <ul className="tv-split__people">
        {people.map((person, index) => {
          const status = text(person['status']) || 'owes';
          const name = text(person['name']);
          return (
            <li key={index}>
              <span
                className="tv-avatar"
                style={{ ['--mark-hue' as string]: String(MARK_HUES[seedOf(name) % MARK_HUES.length]) }}
                aria-hidden
              >
                {name.slice(0, 1).toUpperCase()}
              </span>
              <span className="tv-split__name">{name}</span>
              <span className="tv-money">{text(person['share'])}</span>
              <span className={`tv-pill tv-pill--${status}`}>{status}</span>
            </li>
          );
        })}
      </ul>
      {act ? (
        <button type="button" className="tv-secondary" onClick={() => void act()}>
          {text(props['actionLabel']) || 'Settle up'}
        </button>
      ) : null}
    </div>
  );
}

export function StatTile({ props }: ViewProps) {
  const tone = text(props['tone']) || 'neutral';
  return (
    <div
      className={cx('tv-stat', `tv-tone--${tone}`)}
      {...frame(props, 'group')}
      {...pressable(props['action'])}
    >
      <span className="tv-stat__label">{text(props['label'])}</span>
      <strong className="tv-stat__value">
        <Field value={props['value']} width={56} waiting />
      </strong>
      {props['caption'] ? <span className="tv-stat__caption">{text(props['caption'])}</span> : null}
    </div>
  );
}

export function ProgressMeter({ props }: ViewProps) {
  const value = Number(props['value'] ?? 0) || 0;
  const max = Number(props['max'] ?? 100) || 0;
  const tone = text(props['tone']) || (max > 0 && value > max ? 'critical' : 'accent');
  const pct = max > 0 ? Math.min(100, Math.max(0, (value / max) * 100)) : 0;
  return (
    <div className={cx('tv-meter', `tv-tone--${tone}`)} {...frame(props, 'group')}>
      <div className="tv-meter__head">
        <span>{text(props['label'])}</span>
        {props['caption'] ? <em>{text(props['caption'])}</em> : null}
      </div>
      <div
        className="tv-meter__track"
        role="progressbar"
        aria-label={text(props['label']) || 'Progress'}
        aria-valuetext={text(props['caption']) || undefined}
        aria-valuenow={value}
        aria-valuemin={0}
        aria-valuemax={max}
      >
        <span className="tv-meter__fill" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- inputs

/** The validation errors a field shows, linked to its inputs by id. */
function useErrors(props: Props) {
  const id = useId();
  const errors: string[] = Array.isArray(props['validationErrors'])
    ? props['validationErrors'].map(text)
    : [];
  const invalid = errors.length > 0;
  return {
    invalid,
    describe: invalid ? { 'aria-invalid': true as const, 'aria-describedby': id } : {},
    list: invalid ? (
      <span id={id} className="tv-field__errors">
        {errors.map((error, index) => (
          <span key={index} className="tv-field__error">
            {error}
          </span>
        ))}
      </span>
    ) : null,
  };
}

export function DateRangePicker({ props }: ViewProps) {
  const start = text(props['start']).slice(0, 10);
  const end = text(props['end']).slice(0, 10);
  const setStart = typeof props['setStart'] === 'function' ? props['setStart'] : null;
  const setEnd = typeof props['setEnd'] === 'function' ? props['setEnd'] : null;
  const errors = useErrors(props);
  const commit = isAction(props['action']) ? props['action'] : null;

  // `action` is "fired when the traveler commits a new range": once an edit
  // has landed in the data model and both ends are set, so whatever the event
  // carries reads the range the traveller now sees.
  const edited = useRef(false);
  useEffect(() => {
    if (!edited.current || !commit || !start || !end || end < start) return;
    edited.current = false;
    void commit();
  }, [start, end, commit]);
  const edit = (set: ((value: string) => void) | null, value: string) => {
    edited.current = true;
    set?.(value);
  };

  return (
    <div className={cx('tv-field', errors.invalid && 'is-invalid')} {...frame(props, 'group')}>
      <span className="tv-field__label">{text(props['label'])}</span>
      <div className="tv-dates">
        {/* Calendar dates, as the catalog says: a trip day is a day. */}
        <label className="tv-dates__half">
          <span>Depart</span>
          <input
            type="date"
            value={start}
            {...errors.describe}
            onChange={(event) => edit(setStart, event.target.value)}
          />
        </label>
        <span className="tv-dates__arrow" aria-hidden>
          <Icon name="arrow" />
        </span>
        <label className="tv-dates__half">
          <span>Return</span>
          <input
            type="date"
            value={end}
            min={start || undefined}
            {...errors.describe}
            onChange={(event) => edit(setEnd, event.target.value)}
          />
        </label>
      </div>
      {props['nightsLabel'] ? (
        <span className="tv-pill tv-pill--accent">{text(props['nightsLabel'])}</span>
      ) : null}
      {errors.list}
    </div>
  );
}

interface Place {
  value: string;
  label: string;
  code: string;
  detail: string;
}

/** Best first: a code typed exactly, then names that start with what was typed. */
function placesMatching(places: Place[], query: string): Place[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return places;
  const score = (place: Place) => {
    const code = place.code.toLowerCase();
    const label = place.label.toLowerCase();
    if (code === needle) return 0;
    if (label.startsWith(needle)) return 1;
    if (code.startsWith(needle)) return 2;
    if (label.split(/[\s·,-]+/).some((word) => word.startsWith(needle))) return 3;
    if (`${label} ${code} ${place.detail} ${place.value}`.toLowerCase().includes(needle)) return 4;
    return -1;
  };
  return places
    .map((place, index) => ({ place, index, rank: score(place) }))
    .filter((entry) => entry.rank >= 0)
    .sort((a, b) => a.rank - b.rank || a.index - b.index)
    .map((entry) => entry.place);
}

/**
 * Where from, where to: a search field with a type-ahead list, the way a
 * flight search asks it. An ARIA combobox — type to narrow, arrows to move,
 * Enter to choose, Escape to close — that writes the chosen place's `value`
 * through the SDK's binding and sends nothing, like every other editor.
 */
export function AirportPicker({ props }: ViewProps) {
  const places: Place[] = rows(props['options']).map((option) => ({
    value: text(option['value']),
    label: text(option['label']) || text(option['value']),
    code: text(option['code']),
    detail: text(option['detail']),
  }));
  const value = text(props['value']);
  const set = typeof props['setValue'] === 'function' ? props['setValue'] : null;
  const picked = places.find((place) => place.value === value);
  const errors = useErrors(props);
  const destination = props['kind'] === 'destination';

  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [active, setActive] = useState(0);
  const listId = useId();
  const list = useRef<HTMLUListElement>(null);
  const matches = placesMatching(places, query).slice(0, 50);

  useEffect(() => {
    list.current?.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: 'nearest' });
  }, [active, open]);

  const choose = (place: Place) => {
    set?.(place.value);
    setQuery('');
    setOpen(false);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      if (!open) setOpen(true);
      const step = event.key === 'ArrowDown' ? 1 : -1;
      setActive((index) => (matches.length ? (index + step + matches.length) % matches.length : 0));
    } else if (event.key === 'Enter' && open && matches[active]) {
      event.preventDefault();
      choose(matches[active]);
    } else if (event.key === 'Escape') {
      setOpen(false);
      setQuery('');
    }
  };

  const shown = open ? query : picked ? picked.label : value;

  return (
    <div className={cx('tv-field', 'tv-place', errors.invalid && 'is-invalid')} {...frame(props, 'group')}>
      <span className="tv-field__label">{text(props['label'])}</span>
      <div className={cx('tv-place__box', open && 'is-open')}>
        {/* Material Icons, the font the SDK's own basic Icon draws with. */}
        <span className="tv-place__icon material-icons" aria-hidden>
          {destination ? 'flight_land' : 'flight_takeoff'}
        </span>
        <input
          role="combobox"
          aria-expanded={open}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-label={text(props['label'])}
          {...errors.describe}
          aria-activedescendant={open && matches[active] ? `${listId}-${active}` : undefined}
          placeholder={text(props['placeholder']) || 'City or airport'}
          value={shown}
          disabled={!set}
          onFocus={() => {
            setOpen(true);
            setActive(
              Math.max(
                0,
                matches.findIndex((place) => place.value === value),
              ),
            );
          }}
          onBlur={() => {
            setOpen(false);
            setQuery('');
          }}
          onChange={(event) => {
            setQuery(event.target.value);
            setActive(0);
            setOpen(true);
          }}
          onKeyDown={onKeyDown}
        />
        {picked?.code && !open ? <span className="tv-place__code">{picked.code}</span> : null}
      </div>
      {open ? (
        <ul className="tv-place__list" id={listId} role="listbox" ref={list}>
          {matches.length === 0 ? (
            <li className="tv-place__none" role="presentation">
              Nowhere called “{query.trim()}” here
            </li>
          ) : (
            matches.map((place, index) => (
              <li
                key={place.value}
                id={`${listId}-${index}`}
                role="option"
                aria-selected={index === active}
                className={cx('tv-place__option', place.value === value && 'is-chosen')}
                // Before the input's blur, which would close the list first.
                onMouseDown={(event) => {
                  event.preventDefault();
                  choose(place);
                }}
                onMouseEnter={() => setActive(index)}
              >
                <span className="tv-place__pin" aria-hidden>
                  <Icon name="pin" />
                </span>
                <span className="tv-place__name">
                  <strong>{place.label}</strong>
                  {place.detail ? <span>{place.detail}</span> : null}
                </span>
                {place.code ? <span className="tv-place__code">{place.code}</span> : null}
              </li>
            ))
          )}
        </ul>
      ) : null}
      {errors.list}
    </div>
  );
}

export function TravelerCounter({ props }: ViewProps) {
  const value = Number(props['value'] ?? 0) || 0;
  const min = typeof props['min'] === 'number' ? props['min'] : 0;
  const max = typeof props['max'] === 'number' ? props['max'] : 9;
  const set = typeof props['setValue'] === 'function' ? props['setValue'] : null;
  const step = (delta: number) => set?.(Math.min(max, Math.max(min, value + delta)));
  const label = text(props['label']) || 'Travellers';
  return (
    <div className="tv-counter" {...frame(props, 'group')}>
      <div className="tv-counter__labels">
        <span className="tv-field__label">{text(props['label'])}</span>
        {props['caption'] ? <span className="tv-caption">{text(props['caption'])}</span> : null}
      </div>
      <div className="tv-stepper">
        <button
          type="button"
          onClick={() => step(-1)}
          disabled={!set || value <= min}
          aria-label={`One fewer: ${label}`}
        >
          <Icon name="minus" />
        </button>
        <output aria-live="polite" aria-label={`${label}: ${value}`}>
          {value}
        </output>
        <button
          type="button"
          onClick={() => step(1)}
          disabled={!set || value >= max}
          aria-label={`One more: ${label}`}
        >
          <Icon name="plus" />
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- places and time

export function WeatherStrip({ props }: ViewProps) {
  const days = rows(props['days']).slice(0, 7);
  return (
    <div className="tv-weather" {...frame(props, 'group')}>
      {props['place'] ? <span className="tv-eyebrow">{text(props['place'])}</span> : null}
      <ul className="tv-weather__days">
        {days.map((day, index) => {
          const condition = text(day['condition']) || 'sun';
          return (
            <li key={index}>
              <span className="tv-weather__day">{text(day['day'])}</span>
              <Icon
                name={hasIcon(condition) ? condition : 'sun'}
                className={`tv-weather__icon is-${condition}`}
              />
              <span className="tv-weather__temps">
                {/* Display strings, degree sign included, as the catalog says. */}
                <strong>{text(day['high'])}</strong>
                <span>{text(day['low'])}</span>
              </span>
            </li>
          );
        })}
      </ul>
      {props['caption'] ? <p className="tv-caption">{text(props['caption'])}</p> : null}
    </div>
  );
}

function Glyph({ name, className }: { name: string; className?: string }) {
  if (hasIcon(name)) return <Icon name={name} className={className} />;
  return (
    <span className={className} aria-hidden>
      {name}
    </span>
  );
}

export function TripCalendar({ props }: ViewProps) {
  const start = parseCivil(text(props['start']));
  const end = parseCivil(text(props['end']));
  const locale = typeof navigator === 'undefined' ? undefined : navigator.language;
  const weekStart = weekStartFor(locale);
  const marks = new Map<string, { icon: string; label: string }>();
  for (const mark of rows(props['marks'])) {
    const day = parseCivil(text(mark['date']));
    if (day) marks.set(toIso(day), { icon: text(mark['icon']), label: text(mark['label']) });
  }
  const legend = [
    ...new Map(
      [...marks.values()]
        .filter((mark) => mark.icon && mark.label)
        .map((mark) => [`${mark.icon} ${mark.label}`, mark]),
    ).values(),
  ];
  return (
    <div className="tv-cal" {...frame(props, 'group')} {...pressable(props['action'])}>
      {props['title'] ? <span className="tv-eyebrow">{text(props['title'])}</span> : null}
      {start ? (
        <div className="tv-cal__months">
          {monthsFor(start, end, weekStart).map((month) => (
            <table className="tv-cal__month" key={`${month.year}-${month.month}`}>
              <caption>{monthLabel(month.year, month.month, locale)}</caption>
              <thead>
                <tr>
                  {weekdayLetters(weekStart, locale).map((letter, index) => (
                    <th key={index} scope="col">
                      {letter}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {month.weeks.map((week, row) => (
                  <tr key={row}>
                    {week.map((cell, column) => {
                      if (!cell) return <td key={column} className="is-pad" />;
                      const mark = marks.get(cell.iso);
                      return (
                        <td
                          key={column}
                          className={cx(
                            cell.inRange && 'in-range',
                            cell.isStart && 'is-start',
                            cell.isEnd && 'is-end',
                          )}
                          title={mark?.label || undefined}
                        >
                          <span className="tv-cal__day">{cell.date.day}</span>
                          {mark?.icon ? <Glyph name={mark.icon} className="tv-cal__glyph" /> : null}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          ))}
        </div>
      ) : (
        <span className="tv-caption">Dates to come</span>
      )}
      {legend.length ? (
        <ul className="tv-cal__legend">
          {legend.map((mark, index) => (
            <li key={index}>
              <Glyph name={mark.icon} />
              <span>{mark.label}</span>
            </li>
          ))}
        </ul>
      ) : null}
      {props['caption'] ? <p className="tv-caption">{text(props['caption'])}</p> : null}
    </div>
  );
}

export function MapPreview({ props }: ViewProps) {
  const markers = rows(props['markers']).slice(0, 8);
  const columns = markers.length <= 2 ? markers.length || 1 : markers.length <= 6 ? 3 : 4;
  const lines = Math.max(1, Math.ceil(markers.length / columns));
  const placed = markers.map((marker, index) => {
    const label = text(marker['label']);
    const hash = seedOf(label);
    const column = index % columns;
    const row = Math.floor(index / columns);
    return {
      label,
      kind: text(marker['kind']) || 'pin',
      left: Math.min(88, Math.max(12, (100 / columns) * (column + 0.5) + ((hash % 9) - 4))),
      top: Math.min(84, Math.max(20, (100 / (lines + 1)) * (row + 1) + (((hash >> 8) % 11) - 5))),
    };
  });
  return (
    <figure className="tv-mapsketch" {...frame(props, 'group')} {...pressable(props['action'])}>
      <div className="tv-mapsketch__canvas" aria-hidden>
        <svg className="tv-mapsketch__route" viewBox="0 0 100 100" preserveAspectRatio="none">
          <polyline points={placed.map((p) => `${p.left},${p.top}`).join(' ')} />
        </svg>
        {placed.map((marker, index) => (
          <span
            key={index}
            className="tv-mapsketch__pin"
            style={{ left: `${marker.left}%`, top: `${marker.top}%` }}
          >
            <Icon name={hasIcon(marker.kind) ? marker.kind : 'pin'} />
            <em>{marker.label}</em>
          </span>
        ))}
      </div>
      {props['caption'] ? <figcaption className="tv-caption">{text(props['caption'])}</figcaption> : null}
    </figure>
  );
}

// ---------------------------------------------------------------- the real map

interface Pin {
  lat: number;
  lng: number;
  label: string;
  placeId: string;
}

function point(value: unknown): { lat: number; lng: number } | null {
  if (!value || typeof value !== 'object') return null;
  const lat = Number((value as Props)['lat']);
  const lng = Number((value as Props)['lng']);
  return Number.isFinite(lat) && Number.isFinite(lng) ? { lat, lng } : null;
}

function pin(value: unknown): Pin | null {
  const at = point(value);
  return at
    ? { ...at, label: text((value as Props)['label']), placeId: text((value as Props)['placeId']) }
    : null;
}

/** The catalog's `travelMode`, as the Maps Directions API spells it. */
const TRAVEL_MODES: Record<string, string> = {
  driving: 'DRIVING',
  walking: 'WALKING',
  bicycling: 'BICYCLING',
  transit: 'TRANSIT',
};

/** Where a place opens in Google Maps: its place id when there is one. */
function placeUrl(place: Pin): string {
  const query = encodeURIComponent(place.label || `${place.lat},${place.lng}`);
  const id = place.placeId ? `&query_place_id=${encodeURIComponent(place.placeId)}` : '';
  return `https://www.google.com/maps/search/?api=1&query=${query}${id}`;
}

/**
 * The Maps JavaScript API, loaded once per key.
 *
 * Only a load that succeeded, or is under way, is kept: a key that had not
 * arrived yet, or a script that failed, is tried again on the next map rather
 * than leaving every map on the page unavailable.
 */
const mapsLoads = new Map<string, Promise<boolean>>();

function loadMaps(apiKey: string): Promise<boolean> {
  if (typeof document === 'undefined' || !apiKey) return Promise.resolve(false);
  if (typeof window.google?.maps?.importLibrary === 'function') return Promise.resolve(true);
  const known = mapsLoads.get(apiKey);
  if (known) return known;
  const loading = new Promise<boolean>((resolve) => {
    const script = document.createElement('script');
    script.async = true;
    script.dataset['a2uiMaps'] = 'yes';
    script.src = `https://maps.googleapis.com/maps/api/js?loading=async&libraries=maps,marker&key=${encodeURIComponent(apiKey)}`;
    const fail = () => {
      script.remove();
      mapsLoads.delete(apiKey);
      resolve(false);
    };
    script.onload = () => {
      const started = Date.now();
      const settle = () => {
        if (typeof window.google?.maps?.importLibrary === 'function') return resolve(true);
        if (Date.now() - started > 15_000) return fail();
        setTimeout(settle, 50);
      };
      settle();
    };
    script.onerror = fail;
    document.head.appendChild(script);
  });
  mapsLoads.set(apiKey, loading);
  return loading;
}

/**
 * Google's demo map id: advanced markers, heading and tilt need a map id, and
 * this one carries Google's default style. A deployment with its own styled
 * map would pass that instead.
 */
const MAP_ID = 'DEMO_MAP_ID';

export function GoogleMap({ props }: ViewProps) {
  const host = useRef<HTMLDivElement | null>(null);
  const [ready, setReady] = useState<'loading' | 'ready' | 'unavailable'>('loading');
  const key = useContext(MapsKeyContext);
  const centre = point(props['center']);
  const zoom = Math.min(16, Number(props['zoom'] ?? 11) || 11);
  const mode = text(props['mode']) || 'roadmap';
  const tilt = Number(props['tilt']);
  const heading = Number(props['heading']);
  const travelMode = TRAVEL_MODES[text(props['travelMode']).toLowerCase()] ?? '';
  const anchor = pin(props['anchorMarker']);
  const markers = rows(props['markers'])
    .map(pin)
    .filter((item): item is Pin => item !== null);
  const legs = rows(props['routes'])
    .map((row) => ({ from: pin(row['origin']), to: pin(row['destination']) }))
    .filter((leg): leg is { from: Pin; to: Pin } => leg.from !== null && leg.to !== null);
  const from = pin(props['origin']);
  const to = pin(props['destination']);
  const single = from && to ? { from, to } : null;

  useEffect(() => {
    let live = true;
    setReady('loading');
    void loadMaps(key).then((ok) => live && setReady(ok ? 'ready' : 'unavailable'));
    return () => {
      live = false;
    };
  }, [key]);

  const signature = JSON.stringify({
    centre,
    zoom,
    mode,
    tilt,
    heading,
    travelMode,
    anchor,
    markers,
    legs,
    single,
  });
  useEffect(() => {
    if (ready !== 'ready' || !host.current || !centre) return;
    const element = host.current;
    let cancelled = false;
    void (async () => {
      const maps = window.google?.maps;
      if (!maps?.importLibrary) return;
      const [{ Map, Polyline }, { LatLngBounds }, { AdvancedMarkerElement, Marker }] = await Promise.all([
        maps.importLibrary('maps'),
        maps.importLibrary('core'),
        maps.importLibrary('marker'),
      ]);
      if (cancelled) return;
      element.replaceChildren();
      const canvas = document.createElement('div');
      canvas.style.cssText = 'width:100%;height:100%';
      element.appendChild(canvas);
      const map = new Map(canvas, {
        center: centre,
        zoom,
        mapId: MAP_ID,
        mapTypeId: mode === 'satellite' ? 'satellite' : 'roadmap',
        ...(Number.isFinite(tilt) ? { tilt } : {}),
        ...(Number.isFinite(heading) ? { heading } : {}),
        disableDefaultUI: true,
        zoomControl: true,
      });
      const bounds = new LatLngBounds();
      let points = 0;
      const drop = (place: Pin) => {
        const position = { lat: place.lat, lng: place.lng };
        // `AdvancedMarkerElement` where the API has it; the classic `Marker`
        // (deprecated) only where it does not.
        const marker = AdvancedMarkerElement
          ? new AdvancedMarkerElement({
              map,
              position,
              title: place.label,
              gmpClickable: Boolean(place.placeId),
            })
          : new Marker({ map, position, title: place.label });
        if (place.placeId) {
          marker.addListener(AdvancedMarkerElement ? 'gmp-click' : 'click', () =>
            window.open(placeUrl(place), '_blank', 'noopener'),
          );
        }
        bounds.extend(position);
        points += 1;
      };
      for (const place of anchor ? [anchor, ...markers] : markers) drop(place);
      const line = (leg: { from: Pin; to: Pin }) => {
        const ends = [leg.from, leg.to].map((end) => ({ lat: end.lat, lng: end.lng }));
        new Polyline({ map, path: ends, geodesic: true, strokeOpacity: 0.9, strokeWeight: 3 });
        for (const end of ends) bounds.extend(end);
        points += 2;
      };
      for (const leg of legs) line(leg);
      if (single) {
        // A route travelled a named way is drawn along the way it is
        // travelled; without a mode, or if directions are unavailable for this
        // key, as the straight line between its ends.
        let routed = false;
        if (travelMode) {
          try {
            const { DirectionsService, DirectionsRenderer } = await maps.importLibrary('routes');
            const result = await new DirectionsService().route({
              origin: { lat: single.from.lat, lng: single.from.lng },
              destination: { lat: single.to.lat, lng: single.to.lng },
              travelMode,
            });
            if (cancelled) return;
            new DirectionsRenderer({
              map,
              directions: result,
              suppressMarkers: false,
              preserveViewport: false,
            });
            routed = true;
          } catch {
            routed = false;
          }
        }
        if (!routed) line(single);
      }
      if (points > 1) map.fitBounds(bounds, 48);
    })().catch(() => !cancelled && setReady('unavailable'));
    return () => {
      cancelled = true;
      element.replaceChildren();
    };
  }, [ready, signature]); // eslint-disable-line react-hooks/exhaustive-deps

  const how = text(props['travelMode']);
  const caption = [
    ...[anchor?.label, ...markers.map((m) => m.label)].filter(Boolean).slice(0, 4),
    ...(single && how ? [`${how} · ${single.from.label || 'start'} → ${single.to.label || 'end'}`] : []),
  ].join(' · ');
  if (!centre) {
    return (
      <div className="tv-map tv-map--empty" role="note" {...frame(props)}>
        No map for this one — there are no coordinates for it.
      </div>
    );
  }
  return (
    <figure className="tv-map" {...frame(props, 'group')}>
      <div className="tv-map__canvas" ref={host} aria-label={caption || 'Map'}>
        {ready !== 'ready' ? (
          <p className="tv-map__fallback">
            {ready === 'loading'
              ? 'Loading the map…'
              : `The map could not load${key ? '' : ' — no Google Maps key is configured'}.`}
          </p>
        ) : null}
      </div>
      {caption ? <figcaption className="tv-caption">{caption}</figcaption> : null}
    </figure>
  );
}

/** Every travel component, by the name the catalog gives it. */
export const TRAVEL_VIEWS: Record<string, (view: ViewProps) => ReactNode> = {
  ActivityItem,
  AirportPicker,
  DateRangePicker,
  ExpenseSplit,
  FlightOption,
  GoogleMap,
  HotelCard,
  ItineraryDay,
  MapPreview,
  PriceSummary,
  ProgressMeter,
  StatTile,
  TravelerCounter,
  TripCalendar,
  WeatherStrip,
};
