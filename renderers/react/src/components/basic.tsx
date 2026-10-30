/**
 * The A2UI basic catalog, rendered.
 *
 * Every component here reads its props through `resolve*`, because any of them
 * may be a data binding rather than a literal, and writes user input back to
 * the bound pointer rather than to local state. That is the whole contract: the
 * data model is the state, and the next agent turn reads the same thing the
 * user just changed.
 */

import { createElement, useId, useState, type ReactNode } from 'react';
import type { Json } from '@travel-a2ui/express';

import { ariaOf } from '../accessibility.js';
import {
  bindingPointer,
  resolve,
  resolveBoolean,
  resolveNumber,
  resolveText,
} from '../binding.js';
import { evaluateChecks } from '../checks.js';
import { isSafeUrl } from '../functions.js';
import { runAction, type ComponentProps } from '../context.js';
import { Icon } from './icons.js';

const cx = (...parts: Array<string | false | undefined>) => parts.filter(Boolean).join(' ');

const HEADING_TAGS: Record<string, string> = { h1: 'h1', h2: 'h2', h3: 'h3', h4: 'h4', h5: 'h5' };

/** Renders a field's error text once the user has had a chance to fill it in. */
function FieldErrors({ node, scope, ctx, pointer }: ComponentProps & { pointer?: string }) {
  const result = evaluateChecks(node['checks'], scope);
  if (result.ok) return null;
  if (pointer && !ctx.isTouched(pointer)) return null;
  return (
    <p className="a2-field__error" role="alert">
      {result.errors[0]}
    </p>
  );
}

export function Text({ node, scope }: ComponentProps) {
  const variant = typeof node['variant'] === 'string' ? node['variant'] : 'body';
  const content = resolveText(node['text'], scope);
  // Headings render as real heading elements so the surface has a document
  // outline a screen reader can navigate, not just larger text.
  const tag = HEADING_TAGS[variant] ?? 'p';
  return createElement(
    tag,
    // No fallback role: a heading is already one, and a paragraph the agent
    // named reads as its own text. What a `Text` wants from this block is
    // usually `live` — a price that re-reckons — or `hidden`.
    { ...ariaOf(node, scope), className: `a2-text a2-text--${variant}` },
    content,
  );
}

export function ImageComponent({ node, scope }: ComponentProps) {
  const url = resolveText(node['url'], scope);
  const description = resolveText(node['description'], scope);
  const fit = typeof node['fit'] === 'string' ? node['fit'] : 'cover';
  const variant = typeof node['variant'] === 'string' ? node['variant'] : 'mediumFeature';
  if (!isSafeUrl(url)) return null;
  // `alt` first, then the block: an `accessibility.label` is the more specific
  // of the two and should win, which spreading after `alt` arranges.
  return (
    <img
      className={cx('a2-image', `a2-image--${variant}`)}
      style={{ objectFit: fit as never }}
      src={url}
      alt={description}
      loading="lazy"
      {...ariaOf(node, scope)}
    />
  );
}

export function IconComponent({ node, scope }: ComponentProps) {
  // An icon is decoration until somebody names it, and then it is an image.
  const aria = ariaOf(node, scope, 'img');
  return (
    <Icon
      name={resolveText(node['name'], scope)}
      className="a2-icon"
      {...aria}
      // `Icon` sets `aria-hidden` itself, which is right for the glyphs inside
      // a card and wrong for the one component that *is* a glyph: a named icon
      // would have carried a label and a role into a subtree screen readers
      // skip, announcing it to nobody. So the name clears it, an explicit
      // `hidden` still wins, and an unnamed icon keeps the default.
      aria-hidden={aria['aria-hidden'] ?? (aria.role ? undefined : true)}
    />
  );
}

export function VideoComponent({ node, scope }: ComponentProps) {
  const url = resolveText(node['url'], scope);
  if (!isSafeUrl(url)) return null;
  return <video className="a2-video" src={url} controls preload="metadata" {...ariaOf(node, scope)} />;
}

export function AudioComponent({ node, scope }: ComponentProps) {
  const url = resolveText(node['url'], scope);
  if (!isSafeUrl(url)) return null;
  return <audio className="a2-audio" src={url} controls preload="metadata" {...ariaOf(node, scope)} />;
}

function flexStyle(node: ComponentProps['node']) {
  const justifyMap: Record<string, string> = {
    start: 'flex-start',
    center: 'center',
    end: 'flex-end',
    spaceBetween: 'space-between',
    spaceAround: 'space-around',
    spaceEvenly: 'space-evenly',
    stretch: 'stretch',
  };
  const alignMap: Record<string, string> = {
    start: 'flex-start',
    center: 'center',
    end: 'flex-end',
    stretch: 'stretch',
  };
  const justify = typeof node['justify'] === 'string' ? justifyMap[node['justify']] : undefined;
  const align = typeof node['align'] === 'string' ? alignMap[node['align']] : undefined;
  return { justifyContent: justify, alignItems: align };
}

export function Column({ node, scope, ctx }: ComponentProps) {
  return (
    <div className="a2-column" style={flexStyle(node)} {...ariaOf(node, scope, 'group')}>
      {ctx.renderChildren(node['children'], scope)}
    </div>
  );
}

export function Row({ node, scope, ctx }: ComponentProps) {
  return (
    <div className="a2-row" style={flexStyle(node)} {...ariaOf(node, scope, 'group')}>
      {ctx.renderChildren(node['children'], scope)}
    </div>
  );
}

export function List({ node, scope, ctx }: ComponentProps) {
  const direction = node['direction'] === 'horizontal' ? 'horizontal' : 'vertical';
  // `group` rather than `list`: a real list role obliges every child to be a
  // `listitem`, and the children here are whatever the agent put in it.
  return (
    <div
      className={`a2-list a2-list--${direction}`}
      style={flexStyle(node)}
      {...ariaOf(node, scope, 'group')}
    >
      {ctx.renderChildren(node['children'], scope)}
    </div>
  );
}

export function Card({ node, scope, ctx }: ComponentProps) {
  return (
    <div className="a2-card" {...ariaOf(node, scope, 'group')}>
      {ctx.renderChild(node['child'], scope)}
    </div>
  );
}

export function Divider({ node, scope }: ComponentProps) {
  const axis = node['axis'] === 'vertical' ? 'vertical' : 'horizontal';
  return <hr className={`a2-divider a2-divider--${axis}`} {...ariaOf(node, scope)} />;
}

export function Tabs({ node, scope, ctx }: ComponentProps) {
  const tabs = Array.isArray(node['tabs']) ? node['tabs'] : [];
  const [active, setActive] = useState(0);
  if (tabs.length === 0) return null;
  const current = tabs[Math.min(active, tabs.length - 1)] as Record<string, Json> | undefined;
  return (
    <div className="a2-tabs" {...ariaOf(node, scope, 'group')}>
      <div className="a2-tabs__strip" role="tablist">
        {tabs.map((tab, index) => (
          <button
            key={index}
            type="button"
            role="tab"
            aria-selected={index === active}
            className={cx('a2-tabs__tab', index === active && 'is-active')}
            onClick={() => setActive(index)}
          >
            {resolveText((tab as Record<string, Json>)['title'], scope)}
          </button>
        ))}
      </div>
      <div className="a2-tabs__panel" role="tabpanel">
        {current ? ctx.renderChild(current['child'], scope) : null}
      </div>
    </div>
  );
}

export function Modal({ node, scope, ctx }: ComponentProps) {
  const [open, setOpen] = useState(false);
  return (
    <div className="a2-modal" {...ariaOf(node, scope, 'group')}>
      <div className="a2-modal__trigger" onClick={() => setOpen(true)}>
        {ctx.renderChild(node['trigger'], scope)}
      </div>
      {open ? (
        <div className="a2-modal__scrim" role="dialog" aria-modal onClick={() => setOpen(false)}>
          <div className="a2-modal__panel" onClick={(event) => event.stopPropagation()}>
            <button
              type="button"
              className="a2-modal__close"
              aria-label="Close"
              onClick={() => setOpen(false)}
            >
              <Icon name="close" />
            </button>
            {ctx.renderChild(node['content'], scope)}
          </div>
        </div>
      ) : null}
    </div>
  );
}

export function Button({ node, scope, ctx }: ComponentProps) {
  const variant = typeof node['variant'] === 'string' ? node['variant'] : 'default';
  const action = node['action'];
  const label = ctx.renderChild(node['child'], scope);
  return (
    <button
      type="button"
      className={cx('a2-button', `a2-button--${variant}`)}
      // `node` so the event can name what was pressed. A2UI's action envelope
      // carries a sourceComponentId, and the agent uses it to tell two buttons
      // on one surface apart.
      onClick={() => runAction(action, scope, ctx, node)}
      {...ariaOf(node, scope)}
    >
      {label}
    </button>
  );
}

export function TextField(props: ComponentProps) {
  const { node, scope, ctx } = props;
  const id = useId();
  const pointer = bindingPointer(node['value'], scope);
  const value = resolveText(node['value'], scope);
  const variant = typeof node['variant'] === 'string' ? node['variant'] : 'shortText';
  const invalid = pointer
    ? ctx.isTouched(pointer) && !evaluateChecks(node['checks'], scope).ok
    : false;

  const shared = {
    id,
    className: cx('a2-input', invalid && 'is-invalid'),
    value,
    onBlur: () => pointer && ctx.touch(pointer),
    onChange: (event: { target: { value: string } }) =>
      pointer && ctx.setValue(pointer, event.target.value),
    'aria-invalid': invalid || undefined,
    // On the field rather than the wrapper: a name belongs on the thing that
    // takes the input. No fallback role — this already is a textbox.
    ...ariaOf(node, scope),
  };

  return (
    <div className="a2-field">
      <label className="a2-field__label" htmlFor={id}>
        {resolveText(node['label'], scope)}
      </label>
      {variant === 'longText' ? (
        <textarea {...shared} rows={4} />
      ) : (
        <input
          {...shared}
          type={variant === 'obscured' ? 'password' : variant === 'number' ? 'number' : 'text'}
        />
      )}
      <FieldErrors {...props} pointer={pointer} />
    </div>
  );
}

export function CheckBox(props: ComponentProps) {
  const { node, scope, ctx } = props;
  const id = useId();
  const pointer = bindingPointer(node['value'], scope);
  const checked = resolveBoolean(node['value'], scope);
  return (
    <div className="a2-check">
      <input
        id={id}
        type="checkbox"
        className="a2-check__box"
        checked={checked}
        onChange={(event) => {
          if (!pointer) return;
          ctx.touch(pointer);
          ctx.setValue(pointer, event.target.checked);
        }}
        {...ariaOf(node, scope)}
      />
      <label className="a2-check__label" htmlFor={id}>
        {resolveText(node['label'], scope)}
      </label>
    </div>
  );
}

export function ChoicePicker(props: ComponentProps) {
  const { node, scope, ctx } = props;
  const pointer = bindingPointer(node['value'], scope);
  const multiple = node['variant'] === 'multipleSelection';
  const raw = resolve(node['value'], scope);
  const selected = new Set(
    Array.isArray(raw) ? raw.map(String) : raw === undefined || raw === null ? [] : [String(raw)],
  );
  const options = (Array.isArray(node['options']) ? node['options'] : []) as Array<
    Record<string, Json>
  >;

  const toggle = (value: string) => {
    if (!pointer) return;
    ctx.touch(pointer);
    if (!multiple) {
      ctx.setValue(pointer, value);
      return;
    }
    const next = new Set(selected);
    if (next.has(value)) next.delete(value);
    else next.add(value);
    ctx.setValue(pointer, [...next]);
  };

  return (
    <div className="a2-field">
      {node['label'] ? (
        <span className="a2-field__label">{resolveText(node['label'], scope)}</span>
      ) : null}
      <div
        className="a2-choices"
        role={multiple ? 'group' : 'radiogroup'}
        {...ariaOf(node, scope)}
      >
        {options.map((option, index) => {
          const value = String(option['value'] ?? index);
          const isSelected = selected.has(value);
          return (
            <button
              key={value}
              type="button"
              role={multiple ? 'checkbox' : 'radio'}
              aria-checked={isSelected}
              className={cx('a2-chip', isSelected && 'is-selected')}
              onClick={() => toggle(value)}
            >
              {resolveText(option['label'], scope) || value}
            </button>
          );
        })}
      </div>
      <FieldErrors {...props} pointer={pointer} />
    </div>
  );
}

export function Slider(props: ComponentProps) {
  const { node, scope, ctx } = props;
  const id = useId();
  const pointer = bindingPointer(node['value'], scope);
  const min = resolveNumber(node['min'], scope) ?? 0;
  const max = resolveNumber(node['max'], scope) ?? 100;
  const value = resolveNumber(node['value'], scope) ?? min;
  return (
    <div className="a2-field">
      <div className="a2-field__row">
        <label className="a2-field__label" htmlFor={id}>
          {resolveText(node['label'], scope)}
        </label>
        <span className="a2-field__value">{value}</span>
      </div>
      <input
        id={id}
        type="range"
        className="a2-slider"
        min={min}
        max={max}
        value={value}
        onChange={(event) => pointer && ctx.setValue(pointer, Number(event.target.value))}
        {...ariaOf(node, scope)}
      />
    </div>
  );
}

export function DateTimeInput(props: ComponentProps) {
  const { node, scope, ctx } = props;
  const id = useId();
  const pointer = bindingPointer(node['value'], scope);
  const value = resolveText(node['value'], scope);
  const withDate = node['enableDate'] !== false;
  const withTime = node['enableTime'] === true;
  const type = withDate && withTime ? 'datetime-local' : withTime ? 'time' : 'date';

  // The wire format is RFC 3339; the input wants a truncated local form. Slice
  // rather than round-trip through Date, which would shift the value by the
  // viewer's offset and quietly change the trip's dates.
  const display = type === 'date' ? value.slice(0, 10) : type === 'time' ? value.slice(11, 16) : value.slice(0, 16);

  return (
    <div className="a2-field">
      <label className="a2-field__label" htmlFor={id}>
        {resolveText(node['label'], scope)}
      </label>
      <input
        id={id}
        type={type}
        className="a2-input"
        value={display}
        onBlur={() => pointer && ctx.touch(pointer)}
        onChange={(event) => {
          if (!pointer) return;
          const next = event.target.value;
          ctx.setValue(pointer, type === 'date' && next ? `${next}T00:00:00Z` : next);
        }}
        {...ariaOf(node, scope)}
      />
      <FieldErrors {...props} pointer={pointer} />
    </div>
  );
}

export function Unknown({ node }: ComponentProps): ReactNode {
  return (
    <div className="a2-unknown" role="note">
      <strong>{String(node['component'])}</strong> is not in this host's catalog.
    </div>
  );
}
