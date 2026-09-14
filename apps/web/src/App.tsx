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
import { useAgent } from './useAgent.js';

type View = 'chat' | 'home' | 'catalog' | 'protocol';

const VIEWS: Array<{ id: View; label: string; hint: string }> = [
  { id: 'chat', label: 'Chat', hint: 'Inline cards and the context sidebar' },
  { id: 'home', label: 'Home', hint: 'A dashboard generated for today' },
  { id: 'catalog', label: 'Catalog', hint: 'Everything the agent can draw' },
  { id: 'protocol', label: 'Wire', hint: 'What the agent actually emitted' },
];

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
