/**
 * The shell.
 *
 * Four views, one per modality, over one conversation and one surface store —
 * so switching tabs does not switch context.
 *
 * Three pickers used to sit in this header and none of them do now, for the
 * same reason each time: a control is only worth its space if the answer it
 * takes is the answer the app uses.
 *
 * - **Skill.** Three generated shapes were kept so they could be compared, they
 *   were compared (`tools/eval/skills.py`), and one won. A picker with one
 *   option asks a question with no answer.
 * - **Model** and **Effort.** These governed the reply and not the record: the
 *   panel was hardcoded to the small model with the picked one wired in as its
 *   *fallback*, so choosing the better model changed half the screen. Worse,
 *   the stored default meant a first visit ran the conversation on Flash Lite
 *   while `/api/meta` advertised Flash 3.8.
 *
 * One model now, chosen server-side and named in `/api/meta`. The runtime
 * picker stays, because Interactions and Live are genuinely different agents
 * and the difference is the point.
 *
 * The line under the header still says which skills are loaded.
 */

import { useEffect, useState } from 'react';

import { Catalog } from './components/Catalog.js';
import { Chat } from './components/Chat.js';
import { Home } from './components/Home.js';
import { KeyGate } from './components/KeyGate.js';
import { Protocol } from './components/Protocol.js';
import { RuntimePicker } from './components/RuntimePicker.js';
import { Sidebar } from './components/Sidebar.js';
import { useAgent, type Warmth } from './useAgent.js';

type View = 'chat' | 'home' | 'catalog' | 'protocol';

const VIEWS: Array<{ id: View; label: string; hint: string }> = [
  { id: 'chat', label: 'Chat', hint: 'Inline cards and the context sidebar' },
  { id: 'home', label: 'Home', hint: 'A dashboard generated for today' },
  { id: 'catalog', label: 'Catalog', hint: 'Everything the agent can draw' },
  { id: 'protocol', label: 'Wire', hint: 'What the agent actually emitted' },
];

/**
 * What each readiness state says, and what the hover explains.
 *
 * "Set up" rather than "Warm up" or "Connect": it is the word for the thing
 * that happens before you start, and it does not ask anybody to know that a
 * system instruction is uploaded once per conversation.
 */
const WARMTH: Record<Warmth, { label: string; hint: string }> = {
  cold: {
    label: 'Set up',
    hint: 'Open a conversation now so your first message is answered quickly. Typing without it works too — the first reply just takes longer.',
  },
  warming: { label: 'Getting ready…', hint: 'Opening a conversation with the agent.' },
  ready: { label: 'Ready', hint: 'A conversation is open. Your first message will be answered at full speed.' },
  failed: {
    label: 'Set up again',
    hint: 'Could not open a conversation. You can still type — the first reply will just be slower.',
  },
};

const THEME_KEY = 'travel-a2ui:theme';

function useTheme() {
  const [theme, setTheme] = useState<'system' | 'light' | 'dark'>(() => {
    try {
      const stored = localStorage.getItem(THEME_KEY);
      return stored === 'light' || stored === 'dark' ? stored : 'system';
    } catch {
      return 'system';
    }
  });

  useEffect(() => {
    const root = document.documentElement;
    if (theme === 'system') delete root.dataset.theme;
    else root.dataset.theme = theme;
    try {
      if (theme === 'system') localStorage.removeItem(THEME_KEY);
      else localStorage.setItem(THEME_KEY, theme);
    } catch {
      /* storage unavailable; the choice lasts this session */
    }
  }, [theme]);

  return { theme, setTheme };
}

export default function App() {
  const agent = useAgent();
  const { theme, setTheme } = useTheme();
  const [view, setView] = useState<View>('chat');
  const [showGate, setShowGate] = useState(false);

  const needsKey = !agent.apiKey && agent.meta !== null && !agent.meta.keyProvided;

  const activeSkill = agent.meta?.skills.find((skill) => skill.variant === agent.prefs.skill);

  return (
    <div className="app">
      <header className="topbar">
        <div className="topbar__brand">
          <span className="topbar__mark" aria-hidden>
            🧭
          </span>
          <div>
            <strong>{agent.meta?.name ?? 'Travel A2UI'}</strong>
            <span>an agent that answers in interfaces</span>
          </div>
        </div>

        <nav className="topbar__views" aria-label="Views">
          {VIEWS.map((entry) => (
            <button
              key={entry.id}
              type="button"
              title={entry.hint}
              aria-current={view === entry.id}
              className={view === entry.id ? 'is-active' : undefined}
              onClick={() => setView(entry.id)}
            >
              {entry.label}
            </button>
          ))}
        </nav>

        <div className="topbar__controls">
          {agent.meta?.backends ? (
            <RuntimePicker
              backends={agent.meta.backends}
              current={agent.backend}
              error={agent.backendError}
              onChange={agent.setBackend}
            />
          ) : null}

          {/*
            Whether the agent has a conversation open, and a way to open one.

            A first message costs about eight times as long to draw as every one
            after it, because the whole prompt goes up once when a conversation
            starts. The app opens one as soon as it has a key, so by the time
            anybody types the expensive part is paid — this is that, said out
            loud, because a page that is quietly doing something on your behalf
            should say so.

            It is a **status with a retry**, not a gate. Nothing below is
            disabled while it is cold, and a message sent before it finishes
            works exactly as it always did, just slower. The version of this
            that blocked the control until you had pressed something else is the
            one that made the microphone unusable, and it is not being rebuilt
            here.
          */}
          {agent.warmth === 'ready' || agent.warmth === 'warming' ? (
            <span className={`warmth warmth--${agent.warmth}`} title={WARMTH[agent.warmth].hint}>
              <span className="warmth__dot" aria-hidden />
              {WARMTH[agent.warmth].label}
            </span>
          ) : null}

          {/*
            No model picker, and no effort picker.

            It was here to make "switch models mid-trip and watch the same
            components come back" a thing anyone could try, which is a good
            demo. What it actually offered was a choice the app did not keep:
            the answer used what you picked, and the panel beside it was
            hardcoded to the small model — with your choice wired in as the
            *fallback*, so it was consulted only when the small one was busy.
            Pick the better model and the record beside your conversation was
            still drawn by the other one.

            A control that governs some of the screen and not the rest is worse
            than no control, because the part it misses is the part you are
            looking at when you judge it. One model, chosen server-side, named
            in `/api/meta` for anyone who wants to know which.
          */}
          <button
            type="button"
            className="iconButton"
            title={`Theme: ${theme}`}
            aria-label="Change theme"
            onClick={() => setTheme(theme === 'system' ? 'light' : theme === 'light' ? 'dark' : 'system')}
          >
            {theme === 'dark' ? '◑' : theme === 'light' ? '◐' : '◒'}
          </button>

          <button type="button" className="iconButton" title="API key" onClick={() => setShowGate(true)}>
            {agent.apiKey ? '🔑' : '🔓'}
          </button>

          <button
            type="button"
            className="iconButton"
            title="Start over"
            onClick={() => void agent.reset()}
          >
            ⟲
          </button>
        </div>
      </header>

      {agent.metaError ? (
        <div className="banner banner--error">
          Could not reach the backend: {agent.metaError}
        </div>
      ) : null}

      {/*
        Setup, when it has not happened.

        Same place and same shape as the key warning, because it is the same
        kind of thing: something worth doing before you start, said once, with
        the button that does it. It appears only when there *is* a key to warm
        with and the warming has not happened — on load it is already gone by
        the time most people look, because the app does it unasked.

        Still not a gate. The composer below works cold; this is the difference
        between a first reply in three seconds and one in twenty.
      */}
      {(agent.apiKey || agent.meta?.keyProvided) &&
      (agent.warmth === 'cold' || agent.warmth === 'failed') ? (
        <div className={`banner banner--${agent.warmth === 'failed' ? 'error' : 'warn'}`}>
          <span>
            {agent.warmth === 'failed'
              ? 'Could not open a conversation with the agent.'
              : 'The agent has no conversation open yet.'}{' '}
            Your first message will take about twenty seconds instead of three — setting
            up now does that waiting for you. You can also just start typing.
          </span>{' '}
          <button type="button" className="banner__action" onClick={() => void agent.warm()}>
            {WARMTH[agent.warmth].label}
          </button>
        </div>
      ) : null}

      {agent.keyWasExposed ? (
        <div className="banner banner--warn">
          That key arrived in the query string, so the server saw it and it is probably in a log.
          It has been removed from the address bar and saved here — but treat it as compromised and
          rotate it. Next time use <code>#key=…</code>, which never leaves the browser.
        </div>
      ) : null}

      <main className={`main main--${view}`}>
        {view === 'chat' ? (
          <>
            <Chat agent={agent} />
            <Sidebar agent={agent} />
          </>
        ) : null}
        {view === 'home' ? <Home agent={agent} /> : null}
        {view === 'catalog' ? <Catalog /> : null}
        {view === 'protocol' ? <Protocol agent={agent} /> : null}
      </main>

      <footer className="statusbar">
        <span>
          {activeSkill
            ? `${activeSkill.skills.join(' + ')} · ${activeSkill.inferenceFormat} · A2UI ${activeSkill.protocolVersion}`
            : 'loading…'}
        </span>
        <span>
          {agent.usage.turns > 0
            ? `${agent.usage.turns} turn${agent.usage.turns > 1 ? 's' : ''} · ` +
              `${agent.usage.inputTokens.toLocaleString()} in / ${agent.usage.outputTokens.toLocaleString()} out` +
              (agent.usage.cacheReadTokens > 0
                ? ` · ${agent.usage.cacheReadTokens.toLocaleString()} cached`
                : '')
            : 'no turns yet'}
        </span>
      </footer>

      {needsKey || showGate ? (
        <KeyGate
          existing={agent.apiKey}
          onSave={(key) => {
            agent.setApiKey(key);
            setShowGate(false);
          }}
          {...(needsKey && !showGate ? {} : { onDismiss: () => setShowGate(false) })}
        />
      ) : null}
    </div>
  );
}
