/**
 * The shell.
 *
 * Four views, one per modality, over one conversation and one surface store —
 * so switching tabs does not switch context. The controls in the header
 * (model, skill variant, effort) are deliberately in the product rather than in
 * a config file: comparing the monolithic and modular skills on the same trip,
 * mid-conversation, is the fastest way to find out whether the split costs you
 * anything.
 */

import { useEffect, useState } from 'react';

import { Catalog } from './components/Catalog.js';
import { Chat } from './components/Chat.js';
import { Home } from './components/Home.js';
import { KeyGate } from './components/KeyGate.js';
import { McpConsole } from './components/McpConsole.js';
import { Protocol } from './components/Protocol.js';
import { RuntimePicker } from './components/RuntimePicker.js';
import { Sidebar } from './components/Sidebar.js';
import { Select } from './components/bits.js';
import { useAgent } from './useAgent.js';

type View = 'chat' | 'home' | 'mcp' | 'catalog' | 'protocol';

const VIEWS: Array<{ id: View; label: string; hint: string }> = [
  { id: 'chat', label: 'Chat', hint: 'Inline cards and the context sidebar' },
  { id: 'home', label: 'Home', hint: 'A dashboard generated for today' },
  { id: 'mcp', label: 'MCP', hint: 'Tools that return interfaces' },
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

  const skillOptions =
    agent.meta?.skills.map((skill) => ({
      value: skill.variant,
      label:
        skill.variant === 'express-monolithic'
          ? 'Express · one skill'
          : skill.variant === 'express-modular'
            ? 'Express · core + catalog'
            : 'JSON · one skill',
    })) ?? [];

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

          {agent.meta ? (
            <>
              <Select
                label="Model"
                value={agent.prefs.model}
                options={agent.meta.models.map((model) => ({ value: model.id, label: model.label }))}
                onChange={(model) => agent.setPrefs({ model })}
              />
              <Select
                label="Skill"
                value={agent.prefs.skill}
                options={skillOptions}
                onChange={(skill) => agent.setPrefs({ skill })}
              />
              <Select
                label="Effort"
                value={agent.prefs.effort}
                options={[
                  { value: 'low', label: 'Low' },
                  { value: 'medium', label: 'Medium' },
                  { value: 'high', label: 'High' },
                ]}
                onChange={(effort) => agent.setPrefs({ effort })}
              />
            </>
          ) : null}

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
        {view === 'mcp' ? <McpConsole agent={agent} /> : null}
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
