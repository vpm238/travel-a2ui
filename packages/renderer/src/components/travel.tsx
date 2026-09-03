/**
 * The travel catalog, rendered.
 *
 * These are why the catalog exists. A flight option assembled out of Row and
 * Text is a paragraph with a border; a `FlightOption` is a row the host knows
 * how to lay out, align across siblings, and mark as selected. The model gets
 * to say *what* it is showing instead of *how* to draw it, which is both fewer
 * tokens and a better result.
 */

import type { Json } from '@travel-a2ui/express';

import { resolveBoolean, resolveNumber, resolveText } from '../binding.js';
import { runAction, type ComponentProps } from '../context.js';
import { isSafeUrl } from '../functions.js';
import { Icon } from './icons.js';

const cx = (...parts: Array<string | false | undefined>) => parts.filter(Boolean).join(' ');

type Row = Record<string, Json>;

const rowsOf = (value: Json | undefined): Row[] =>
  Array.isArray(value) ? (value.filter((item) => item && typeof item === 'object') as Row[]) : [];

const str = (value: Json | undefined): string =>
  value === null || value === undefined ? '' : String(value);

export function FlightOption({ node, scope, ctx }: ComponentProps) {
  const selected = resolveBoolean(node['selected'], scope);
  const badge = resolveText(node['badge'], scope);
  const interactive = Boolean(node['action']);

  return (
    <div
      className={cx('tv-flight', selected && 'is-selected', interactive && 'is-interactive')}
      role={interactive ? 'button' : undefined}
      tabIndex={interactive ? 0 : undefined}
      onClick={() => runAction(node['action'], scope, ctx, node)}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          runAction(node['action'], scope, ctx, node);
        }
      }}
    >
      <div className="tv-flight__carrier">
        <span className="tv-flight__mark" aria-hidden>
          <Icon name="plane" />
        </span>
        <span className="tv-flight__airline">{resolveText(node['airline'], scope)}</span>
        <span className="tv-flight__number">{resolveText(node['flightNumber'], scope)}</span>
      </div>

      <div className="tv-flight__times">
        <div className="tv-flight__endpoint">
          <strong>{resolveText(node['departTime'], scope)}</strong>
          <span>{resolveText(node['origin'], scope)}</span>
        </div>
        <div className="tv-flight__leg" aria-hidden>
          <span className="tv-flight__duration">{resolveText(node['duration'], scope)}</span>
          <span className="tv-flight__line" />
          <span className="tv-flight__stops">{resolveText(node['stops'], scope)}</span>
        </div>
        <div className="tv-flight__endpoint">
          <strong>{resolveText(node['arriveTime'], scope)}</strong>
          <span>{resolveText(node['destination'], scope)}</span>
        </div>
      </div>

      <div className="tv-flight__price">
        {badge ? <span className="tv-badge">{badge}</span> : null}
        <strong>{resolveText(node['price'], scope)}</strong>
        <span className="tv-flight__cabin">{str(node['cabin']) || 'economy'}</span>
      </div>

      {selected ? (
        <span className="tv-flight__tick" aria-label="Selected">
          <Icon name="check" />
        </span>
      ) : null}
    </div>
  );
}

export function HotelCard({ node, scope, ctx }: ComponentProps) {
  const image = resolveText(node['imageUrl'], scope);
  const amenities = (Array.isArray(node['amenities']) ? node['amenities'] : []).slice(0, 5);
  const selected = resolveBoolean(node['selected'], scope);
  const badge = resolveText(node['badge'], scope);
  const name = resolveText(node['name'], scope);

  return (
    <div
      className={cx('tv-hotel', selected && 'is-selected')}
      role="button"
      tabIndex={0}
      onClick={() => runAction(node['action'], scope, ctx, node)}
      onKeyDown={(event) => {
        if (event.key === 'Enter') runAction(node['action'], scope, ctx, node);
      }}
    >
      <div className="tv-hotel__media" data-seed={name.length % 6}>
        {isSafeUrl(image) ? <img src={image} alt="" loading="lazy" /> : <Icon name="bed" />}
        {badge ? <span className="tv-badge tv-badge--onMedia">{badge}</span> : null}
      </div>
      <div className="tv-hotel__body">
        <div className="tv-hotel__head">
          <h4>{name}</h4>
          <span className="tv-hotel__price">{resolveText(node['price'], scope)}</span>
        </div>
        <p className="tv-hotel__meta">
          {[resolveText(node['neighborhood'], scope), resolveText(node['rating'], scope)]
            .filter(Boolean)
            .join(' · ')}
        </p>
        {amenities.length > 0 ? (
          <ul className="tv-hotel__amenities">
            {amenities.map((amenity, index) => (
              <li key={index}>{str(amenity)}</li>
            ))}
          </ul>
        ) : null}
      </div>
    </div>
  );
}

export function ItineraryDay({ node, scope, ctx }: ComponentProps) {
  return (
    <section className="tv-day">
      <header className="tv-day__head">
        <div>
          <h3>{resolveText(node['title'], scope)}</h3>
          {node['summary'] ? <p>{resolveText(node['summary'], scope)}</p> : null}
        </div>
        {node['date'] ? <span className="tv-day__date">{resolveText(node['date'], scope)}</span> : null}
      </header>
      <div className="tv-day__body">{ctx.renderChildren(node['children'], scope)}</div>
    </section>
  );
}

export function ActivityItem({ node, scope, ctx }: ComponentProps) {
  const category = str(node['category']) || 'sight';
  const done = resolveBoolean(node['done'], scope);
  const interactive = Boolean(node['action']);
  const meta = [resolveText(node['location'], scope), resolveText(node['duration'], scope)]
    .filter(Boolean)
    .join(' · ');

  return (
    <div
      className={cx('tv-activity', done && 'is-done', interactive && 'is-interactive')}
      onClick={() => runAction(node['action'], scope, ctx, node)}
    >
      <span className="tv-activity__time">{resolveText(node['time'], scope)}</span>
      <span className={`tv-activity__icon tv-activity__icon--${category}`} aria-hidden>
        <Icon name={category} />
      </span>
      <div className="tv-activity__body">
        <strong>{resolveText(node['title'], scope)}</strong>
        {meta ? <span className="tv-activity__meta">{meta}</span> : null}
        {node['note'] ? <em className="tv-activity__note">{resolveText(node['note'], scope)}</em> : null}
      </div>
    </div>
  );
}

export function MapPreview({ node, scope, ctx }: ComponentProps) {
  const markers = rowsOf(node['markers']).slice(0, 8);

  // Pins are laid out on a grid with a small per-label jitter, rather than at
  // hashed coordinates. Pure hashing looks organic until two pins land on top
  // of each other and one of them silently disappears — on a map with four
  // places that is not a rare case, it is most of them. The grid guarantees
  // separation; the jitter keeps it from looking like a spreadsheet. Both are
  // deterministic, so a surface re-rendering on every streamed token does not
  // shuffle its own map.
  const columns = markers.length <= 2 ? markers.length || 1 : markers.length <= 6 ? 3 : 4;
  const rows = Math.max(1, Math.ceil(markers.length / columns));

  const placed = markers.map((marker, index) => {
    const label = str(marker['label']);
    let hash = 0;
    for (let i = 0; i < label.length; i++) hash = (hash * 31 + label.charCodeAt(i)) >>> 0;

    const column = index % columns;
    const row = Math.floor(index / columns);
    const cellWidth = 100 / columns;
    const cellHeight = 100 / (rows + 1);

    return {
      label,
      kind: str(marker['kind']) || 'sight',
      day: str(marker['day']),
      left: Math.min(88, Math.max(12, cellWidth * (column + 0.5) + ((hash % 9) - 4))),
      top: Math.min(86, Math.max(22, cellHeight * (row + 1) + (((hash >> 8) % 11) - 5))),
    };
  });

  return (
    <div className="tv-map" onClick={() => runAction(node['action'], scope, ctx, node)}>
      <div className="tv-map__canvas" aria-hidden>
        {placed.map((marker, index) => (
          <span
            key={index}
            className={`tv-map__pin tv-map__pin--${marker.kind}`}
            style={{ left: `${marker.left}%`, top: `${marker.top}%` }}
          >
            <Icon name={marker.kind} />
            <em>{marker.label}</em>
          </span>
        ))}
      </div>
      {node['caption'] ? <p className="tv-map__caption">{resolveText(node['caption'], scope)}</p> : null}
    </div>
  );
}

export function PriceSummary({ node, scope, ctx }: ComponentProps) {
  const lines = rowsOf(node['lines']);
  const actionLabel = resolveText(node['actionLabel'], scope);

  return (
    <div className="tv-price">
      <ul className="tv-price__lines">
        {lines.map((line, index) => (
          <li key={index}>
            <span className="tv-price__label">
              {str(line['label'])}
              {line['note'] ? <em>{str(line['note'])}</em> : null}
            </span>
            <span className="tv-price__amount">{str(line['amount'])}</span>
          </li>
        ))}
      </ul>
      <div className="tv-price__total">
        <span>{resolveText(node['totalLabel'], scope) || 'Total'}</span>
        <strong>{resolveText(node['total'], scope)}</strong>
      </div>
      {node['caption'] ? <p className="tv-price__caption">{resolveText(node['caption'], scope)}</p> : null}
      {node['action'] ? (
        <button
          type="button"
          className="a2-button a2-button--primary tv-price__cta"
          onClick={() => runAction(node['action'], scope, ctx, node)}
        >
          {actionLabel || 'Continue'}
        </button>
      ) : null}
    </div>
  );
}

export function DateRangePicker({ node, scope, ctx }: ComponentProps) {
  const startPointer = pointerOf(node['start'], scope);
  const endPointer = pointerOf(node['end'], scope);
  const start = resolveText(node['start'], scope).slice(0, 10);
  const end = resolveText(node['end'], scope).slice(0, 10);

  /**
   * Writes the date and stops there.
   *
   * This used to run the component's action on every change, which meant typing
   * a date sent a turn — and then a *second* turn when you filled in the other
   * one, each arriving with half an answer. An editor edits; sending is a
   * separate, deliberate act, the same way Slider and TravelerCounter already
   * behaved. The host commits the surface when the traveler says so.
   */
  const commit = (pointer: string | undefined, value: string) => {
    if (!pointer) return;
    ctx.setValue(pointer, value ? `${value}T00:00:00Z` : '');
  };

  return (
    <div className="tv-dates">
      <span className="a2-field__label">{resolveText(node['label'], scope)}</span>
      <div className="tv-dates__row">
        <input
          type="date"
          className="a2-input"
          value={start}
          aria-label="Start date"
          onChange={(event) => commit(startPointer, event.target.value)}
        />
        <span className="tv-dates__arrow" aria-hidden>
          <Icon name="chevron" />
        </span>
        <input
          type="date"
          className="a2-input"
          value={end}
          aria-label="End date"
          min={start || undefined}
          onChange={(event) => commit(endPointer, event.target.value)}
        />
      </div>
      {node['nightsLabel'] ? (
        <span className="tv-dates__nights">{resolveText(node['nightsLabel'], scope)}</span>
      ) : null}
    </div>
  );
}

export function TravelerCounter({ node, scope, ctx }: ComponentProps) {
  const pointer = pointerOf(node['value'], scope);
  const value = resolveNumber(node['value'], scope) ?? 0;
  const min = typeof node['min'] === 'number' ? node['min'] : 0;
  const max = typeof node['max'] === 'number' ? node['max'] : 9;

  const step = (delta: number) => {
    if (!pointer) return;
    ctx.setValue(pointer, Math.min(max, Math.max(min, value + delta)));
  };

  return (
    <div className="tv-counter">
      <div className="tv-counter__labels">
        <span className="a2-field__label">{resolveText(node['label'], scope)}</span>
        {node['caption'] ? <span className="tv-counter__caption">{resolveText(node['caption'], scope)}</span> : null}
      </div>
      <div className="tv-counter__controls">
        <button type="button" onClick={() => step(-1)} disabled={value <= min} aria-label="One fewer">
          −
        </button>
        <output>{value}</output>
        <button type="button" onClick={() => step(1)} disabled={value >= max} aria-label="One more">
          +
        </button>
      </div>
    </div>
  );
}

export function StatTile({ node, scope, ctx }: ComponentProps) {
  const tone = str(node['tone']) || 'neutral';
  const interactive = Boolean(node['action']);
  return (
    <div
      className={cx('tv-stat', `tv-stat--${tone}`, interactive && 'is-interactive')}
      role={interactive ? 'button' : undefined}
      tabIndex={interactive ? 0 : undefined}
      onClick={() => runAction(node['action'], scope, ctx, node)}
    >
      <span className="tv-stat__label">{resolveText(node['label'], scope)}</span>
      <strong className="tv-stat__value">{resolveText(node['value'], scope)}</strong>
      {node['caption'] ? <span className="tv-stat__caption">{resolveText(node['caption'], scope)}</span> : null}
    </div>
  );
}

export function ProgressMeter({ node, scope }: ComponentProps) {
  const value = resolveNumber(node['value'], scope) ?? 0;
  const max = resolveNumber(node['max'], scope) ?? 100;
  const tone = str(node['tone']) || 'accent';
  const pct = max > 0 ? Math.min(100, Math.max(0, (value / max) * 100)) : 0;
  return (
    <div className={`tv-meter tv-meter--${tone}`}>
      <div className="tv-meter__head">
        <span>{resolveText(node['label'], scope)}</span>
        {node['caption'] ? <em>{resolveText(node['caption'], scope)}</em> : null}
      </div>
      <div
        className="tv-meter__track"
        role="progressbar"
        aria-valuenow={value}
        aria-valuemin={0}
        aria-valuemax={max}
      >
        <span className="tv-meter__fill" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

export function WeatherStrip({ node, scope }: ComponentProps) {
  const days = rowsOf(node['days']).slice(0, 7);
  return (
    <div className="tv-weather">
      {node['place'] ? <span className="tv-weather__place">{resolveText(node['place'], scope)}</span> : null}
      <ul className="tv-weather__days">
        {days.map((day, index) => (
          <li key={index}>
            <span className="tv-weather__day">{str(day['day'])}</span>
            <Icon name={str(day['condition']) || 'sun'} className="tv-weather__icon" />
            <span className="tv-weather__high">{str(day['high'])}</span>
            <span className="tv-weather__low">{str(day['low'])}</span>
          </li>
        ))}
      </ul>
      {node['caption'] ? <p className="tv-weather__caption">{resolveText(node['caption'], scope)}</p> : null}
    </div>
  );
}

export function ExpenseSplit({ node, scope, ctx }: ComponentProps) {
  const participants = rowsOf(node['participants']);
  return (
    <div className="tv-split">
      <div className="tv-split__head">
        <strong>{resolveText(node['title'], scope)}</strong>
        <span>{resolveText(node['total'], scope)}</span>
      </div>
      <ul className="tv-split__people">
        {participants.map((person, index) => {
          const status = str(person['status']) || 'owes';
          return (
            <li key={index} className={`is-${status}`}>
              <span className="tv-split__name">{str(person['name'])}</span>
              <span className="tv-split__share">{str(person['share'])}</span>
              <span className="tv-split__status">{status}</span>
            </li>
          );
        })}
      </ul>
      {node['action'] ? (
        <button
          type="button"
          className="a2-button a2-button--default"
          onClick={() => runAction(node['action'], scope, ctx, node)}
        >
          {resolveText(node['actionLabel'], scope) || 'Settle up'}
        </button>
      ) : null}
    </div>
  );
}

/** Local helper: these components bind several values, not just one. */
function pointerOf(value: Json | undefined, scope: { itemPointer: string }): string | undefined {
  if (!value || typeof value !== 'object' || Array.isArray(value) || !('path' in value)) {
    return undefined;
  }
  const path = String((value as { path: string }).path);
  if (path.startsWith('/')) return path;
  return scope.itemPointer ? `${scope.itemPointer}/${path}` : `/${path}`;
}
