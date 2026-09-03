/**
 * Modality 1 — inline A2UI.
 *
 * Each assistant turn gets its own surface, drawn directly under whatever the
 * agent said. That is the point of the inline modality: the interface is part of
 * the reply, in the place the reply appears, so choosing a flight is the same
 * gesture as answering a question.
 *
 * A turn's surface is addressed by id (`inline-3`), so an earlier card stays
 * live and interactive after the conversation has moved past it.
 */

import { useEffect, useRef, useState, type FormEvent } from 'react';
import { A2uiSurface } from '@travel-a2ui/renderer';

import type { Agent } from '../useAgent.js';
import { Disclosure, Empty, Spinner } from './bits.js';
import { PendingEdits } from './PendingEdits.js';

const OPENERS = [
  'Six days in Madrid in April, two of us, around $2,500 all in',
  'Find me a nonstop to Lisbon and somewhere to stay in Alfama',
  'Plan three days in Tokyo — first visit, we like walking',
  'What would a week in Mexico City cost in November?',
];

export function Chat({ agent }: { agent: Agent }) {
  const [draft, setDraft] = useState('');
  const feedRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);

  // Follow the stream, but stop following the moment the user scrolls up to
  // re-read something. Yanking someone back to the bottom mid-sentence is the
  // most annoying thing a chat UI can do.
  useEffect(() => {
    const feed = feedRef.current;
    if (!feed) return;
    const onScroll = () => {
      const distance = feed.scrollHeight - feed.scrollTop - feed.clientHeight;
      stickToBottom.current = distance < 120;
    };
    feed.addEventListener('scroll', onScroll, { passive: true });
    return () => feed.removeEventListener('scroll', onScroll);
  }, []);

  useEffect(() => {
    if (stickToBottom.current) bottomRef.current?.scrollIntoView({ block: 'end' });
  }, [agent.turns]);

  /**
   * The one surface still open to input: the newest one in the feed.
   *
   * Every earlier card answered a message the conversation has since moved
   * past. Leaving them clickable meant a tap could answer a question that was
   * settled three turns ago, against a data model describing a trip that no
   * longer exists. They stay on screen as the record of what was chosen; they
   * just stop being controls.
   */
  const liveSurfaceId = (() => {
    for (let index = agent.turns.length - 1; index >= 0; index--) {
      const parts = agent.turns[index]!.parts;
      for (let part = parts.length - 1; part >= 0; part--) {
        const entry = parts[part]!;
        if (entry.kind === 'surface') return entry.surfaceId;
      }
    }
    return null;
  })();

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const text = draft.trim();
    if (!text || agent.busy) return;
    setDraft('');
    void agent.send(text, { surface: 'inline' });
  };

  return (
    <section className="chat" aria-label="Conversation">
      <div className="chat__feed" ref={feedRef}>
        {agent.turns.length === 0 ? (
          <div className="chat__intro">
            <h2>Where are you going?</h2>
            <p>
              Ask for a trip and the agent answers with an interface — flights you can pick, dates
              you can set, an itinerary you can tap through. Everything on screen was generated for
              this conversation.
            </p>
            <ul className="chat__openers">
              {OPENERS.map((opener) => (
                <li key={opener}>
                  <button type="button" onClick={() => void agent.send(opener, { surface: 'inline' })}>
                    {opener}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {agent.turns.map((turn) =>
          turn.role === 'user' ? (
            <div key={turn.id} className={`bubble bubble--user${turn.fromSurface ? ' bubble--event' : ''}`}>
              {turn.fromSurface ? <span className="bubble__tag">from the interface</span> : null}
              <p>{turn.text}</p>
            </div>
          ) : (
            <div key={turn.id} className="turn">
              {turn.tools.length > 0 ? (
                <ul className="turn__tools">
                  {turn.tools.map((tool, index) => (
                    <li key={`${tool.name}-${index}`} className={tool.isError ? 'is-error' : undefined}>
                      <span className="turn__toolName">{tool.name.replace(/_/g, ' ')}</span>
                      {tool.result === undefined ? <Spinner /> : <span className="turn__tick">done</span>}
                    </li>
                  ))}
                </ul>
              ) : null}

              {turn.parts.map((part, index) =>
                part.kind === 'text' ? (
                  part.text.trim() ? (
                    <div key={index} className="bubble bubble--agent">
                      <p>{part.text.trim()}</p>
                    </div>
                  ) : null
                ) : (
                  <div
                    key={index}
                    className={`turn__surface${part.surfaceId === liveSurfaceId ? '' : ' turn__surface--spent'}`}
                  >
                    <A2uiSurface
                      store={agent.store}
                      surfaceId={part.surfaceId}
                      onEvent={agent.handleSurfaceEvent}
                      interactive={part.surfaceId === liveSurfaceId && !agent.busy}
                    />
                    {part.surfaceId === liveSurfaceId ? (
                      <PendingEdits
                        store={agent.store}
                        surfaceId={part.surfaceId}
                        busy={agent.busy}
                        onSubmit={agent.submitSurface}
                      />
                    ) : (
                      <p className="turn__spentNote">Answered · scroll down to continue</p>
                    )}
                  </div>
                ),
              )}

              {turn.streaming && turn.parts.length === 0 && turn.tools.length === 0 ? (
                <Spinner label="Thinking" />
              ) : null}

              {turn.error ? (
                <Disclosure tone="warn" summary={<span>Something went wrong on this turn</span>}>
                  <p>{turn.error}</p>
                </Disclosure>
              ) : null}
            </div>
          ),
        )}

        <div ref={bottomRef} />
      </div>

      <form className="composer" onSubmit={submit}>
        <textarea
          value={draft}
          rows={1}
          placeholder={agent.busy ? 'Working…' : 'Ask for a trip, or change one'}
          aria-label="Message"
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault();
              submit(event);
            }
          }}
        />
        {agent.busy ? (
          <button type="button" className="composer__stop" onClick={agent.stop}>
            Stop
          </button>
        ) : (
          <button type="submit" className="composer__send" disabled={!draft.trim()}>
            Send
          </button>
        )}
      </form>
    </section>
  );
}

export function ChatEmptyState() {
  return <Empty title="Nothing here yet">Send a message to start planning.</Empty>;
}
