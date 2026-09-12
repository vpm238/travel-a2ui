/**
 * Modality 1 — inline A2UI.
 *
 * Each assistant turn gets its own surface, drawn directly under whatever the
 * agent said. That is the point of the inline modality: the interface is part of
 * the reply, in the place the reply appears, so choosing a flight is the same
 * gesture as answering a question.
 *
 * A turn's surface is addressed by id (`inline-3`), one per turn, so the
 * transcript is a list of things that were asked rather than one card being
 * rewritten. Once the turn that drew it ends, a card is greyed and made inert:
 * it is a record of what was answered, not a control that still works.
 */

import { useEffect, useRef, useState, type FormEvent } from 'react';
import { A2uiSurface } from '@travel-a2ui/renderer';

import type { Agent } from '../useAgent.js';
import { Disclosure, Empty, Spinner } from './bits.js';

/**
 * What a running tool is called, where the traveler can see it.
 *
 * A tool name is an internal identifier and reads like one. `save_trip` was
 * appearing under nearly every reply as "save trip", which is not a thing
 * anyone asked for and not a thing they can act on — it is the agent writing
 * down what was just decided. Being asked "what is save trip?" is the whole
 * argument: a progress line that prompts a question has spent the traveler's
 * attention and given nothing back.
 *
 * So the ones that mean waiting say what is being waited for, and the ones that
 * are bookkeeping say nothing at all.
 */
const TOOL_LABELS: Record<string, string> = {
  search_flights: 'Finding flights',
  search_hotels: 'Finding places to stay',
  get_destination: 'Reading up on the place',
  get_weather: 'Checking the weather',
  estimate_cost: 'Working out the cost',
};

/**
 * Tools with nothing to report.
 *
 * These are state, not work: recording a decision, letting one go, reading back
 * what is already on screen. They finish instantly and change nothing the
 * traveler cannot already see in the panel, so a chip for them is noise that
 * looks like activity.
 */
const SILENT_TOOLS = new Set(['save_trip', 'release_decision', 'get_trip']);

/** The one-line version: how long until there was an interface to look at. */
function formatTiming(ms: Record<string, number>): string {
  const say = (value: number) =>
    value < 1000 ? `${Math.round(value)} ms` : `${(value / 1000).toFixed(1)} s`;
  const surface = ms.firstSurface;
  const done = ms.done;
  if (surface === undefined) {
    return done === undefined ? 'Timing' : `No surface · ${say(done)} in total`;
  }
  return `Interface in ${say(surface)}${done === undefined ? '' : ` · ${say(done)} in total`}`;
}

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
    if (!text) return;
    // Typing during a call goes *into* the call rather than starting a second
    // conversation beside it — the Live session already holds the thread.
    if (agent.voice.listening) {
      setDraft('');
      agent.voice.say(text);
      return;
    }
    if (agent.busy) return;
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
              {(() => {
                // A failed bookkeeping call is still worth showing: it is the
                // one case where "recorded what you chose" did not happen, and
                // the traveler is about to be asked something they answered.
                const shown = turn.tools.filter(
                  (tool) => tool.isError || !SILENT_TOOLS.has(tool.name),
                );
                if (shown.length === 0) return null;
                return (
                  <ul className="turn__tools">
                    {shown.map((tool, index) => (
                      <li
                        key={`${tool.name}-${index}`}
                        className={tool.isError ? 'is-error' : undefined}
                      >
                        <span className="turn__toolName">
                          {TOOL_LABELS[tool.name] ?? tool.name.replace(/_/g, ' ')}
                        </span>
                        {tool.result === undefined ? (
                          <Spinner />
                        ) : (
                          <span className="turn__tick">done</span>
                        )}
                      </li>
                    ))}
                  </ul>
                );
              })()}

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
                    {part.surfaceId === liveSurfaceId ? null : (
                      <p className="turn__spentNote">Answered · scroll down to continue</p>
                    )}
                  </div>
                ),
              )}

              {turn.retrying ? (
                <p className="turn__retry">
                  <Spinner /> That layout did not compile — rewriting it.
                </p>
              ) : null}

              {turn.streaming && turn.parts.length === 0 && turn.tools.length === 0 ? (
                <Spinner label="Thinking" />
              ) : null}

              {turn.error ? (
                <Disclosure tone="warn" summary={<span>Something went wrong on this turn</span>}>
                  <p>{turn.error}</p>
                </Disclosure>
              ) : null}

              {/*
                Where the turn's time went.

                Folded away, because it is not what the traveler came for — but
                present, because "the interface takes too long to appear" was
                not a claim anyone could check before this. `firstSurface` is
                the number that decides how the app feels: until then the reply
                is a blank space.
              */}
              {turn.timing ? (
                <Disclosure summary={<span>{formatTiming(turn.timing)}</span>}>
                  <ul className="turn__timing">
                    {Object.entries(turn.timing).map(([name, ms]) => (
                      <li key={name}>
                        <span>{name.startsWith('tool:') ? name.slice(5) : name}</span>
                        <span>{ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(1)} s`}</span>
                      </li>
                    ))}
                  </ul>
                </Disclosure>
              ) : null}
            </div>
          ),
        )}

        <div ref={bottomRef} />
      </div>

      {agent.voice.error ? <p className="composer__voiceError">{agent.voice.error}</p> : null}

      {/*
        Instantiating the Live agent, said out loud.

        The Live API keeps no agent object, so the app holds the receipt for one
        — which contract it bound to, and when. This is where that shows: while
        the handshake runs, when it fails, and when the deployment has moved on
        from what was instantiated. It is only ever on screen for the framework
        that has an agent to instantiate.
      */}
      {agent.canSpeak && agent.live.status !== 'ready' ? (
        <p className={`composer__live is-${agent.live.status}`}>
          {agent.live.status === 'instantiating' ? (
            <>
              <span className="composer__liveDot" aria-hidden />
              Instantiating the Gemini Live agent — binding the catalog, the skill and the tools…
            </>
          ) : agent.live.status === 'stale' ? (
            <>
              This deployment&rsquo;s catalog has changed since you instantiated. Initialise again
              with your key to pick it up.{' '}
              <button type="button" onClick={() => void agent.live.instantiate()}>
                Re-initialise
              </button>
            </>
          ) : agent.live.status === 'failed' ? (
            <>
              Could not instantiate: {agent.live.error}{' '}
              <button type="button" onClick={() => void agent.live.instantiate()}>
                Try again
              </button>
            </>
          ) : (
            <>Add your Gemini key to instantiate the Live agent.</>
          )}
        </p>
      ) : null}

      <form className="composer" onSubmit={submit}>
        {/*
          The microphone belongs to the framework that has one.

          It used to sit here unconditionally, and pressing it quietly opened a
          second runtime on a different API with its own conversation history —
          which made two agent frameworks look like one app with a feature. The
          traveller picks the framework in the header now, and Live is the one
          that listens. Typing still works in both.
        */}
        {agent.canSpeak ? (
          <button
            type="button"
            className={`composer__call${agent.voice.listening ? ' is-live' : ''}${
              agent.voice.speaking ? ' is-speaking' : ''
            }`}
            onClick={() => void agent.voice.start()}
            aria-pressed={agent.voice.listening}
            disabled={agent.live.status !== 'ready'}
            title={
              agent.live.status !== 'ready'
                ? 'Instantiate the Live agent first'
                : agent.voice.listening
                  ? 'End the call'
                  : 'Talk to it'
            }
          >
            <span aria-hidden>{agent.voice.listening ? '■' : '🎙'}</span>
            <span className="visually-hidden">
              {agent.voice.listening ? 'End the call' : 'Start a voice call'}
            </span>
          </button>
        ) : null}
        <textarea
          value={draft}
          rows={1}
          placeholder={
            agent.voice.listening
              ? agent.voice.speaking
                ? 'Speaking…'
                : 'Listening — or type'
              : agent.busy
                ? 'Working…'
                : agent.canSpeak
                  ? 'Say it, or type it'
                  : 'Ask for a trip, or change one'
          }
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
