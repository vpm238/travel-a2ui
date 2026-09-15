/**
 * The microphone and the speaker, and nothing else.
 *
 * Everything that makes this a *travel* agent — the catalog, the compiler, the
 * tools, the trip — is on the other end of the socket. This file knows how to
 * turn a microphone into 16 kHz PCM, how to play 24 kHz PCM back without gaps,
 * and how to forward JSON. The Flutter client needs exactly these
 * three things and nothing more, which is the test this design is trying to
 * pass.
 *
 * Two pieces of audio plumbing are worth explaining, because both are the sort
 * of thing that produces confident nonsense rather than an error.
 *
 * **Resampling is done by hand.** `AudioContext` will happily run at 48 kHz and
 * the Live API only accepts 16 kHz in, so the capture path takes every third
 * sample rather than trusting a rate that is not guaranteed. Getting this wrong
 * does not throw: the model simply hears a chipmunk.
 *
 * **Playback is scheduled, not fired.** Audio arrives in chunks faster than it
 * plays, so each one is queued at the end of the last rather than started on
 * arrival. Calling `start()` on arrival overlaps them into noise.
 */

import { clientHints } from './api.js';

/** What the relay sends down. Mirrors `ServerMessage` in the Worker. */
export type VoiceEvent =
  | { type: 'ready'; model: string; contract: string }
  | { type: 'audio'; data: string }
  | { type: 'transcript'; text: string; who: 'you' | 'agent' }
  | { type: 'ui'; surfaceId: string; messages: unknown[]; done: boolean }
  | { type: 'tool'; name: string; input: unknown }
  | { type: 'trip'; trip: Record<string, unknown> }
  | { type: 'turn_end' }
  /** The traveller spoke over the answer; whatever is queued should not play. */
  | { type: 'interrupted' }
  | { type: 'error'; message: string };

const INPUT_RATE = 16_000;
const OUTPUT_RATE = 24_000;

const toBase64 = (bytes: Uint8Array): string => {
  let binary = '';
  for (let i = 0; i < bytes.length; i += 1) binary += String.fromCharCode(bytes[i]!);
  return btoa(binary);
};

const fromBase64 = (value: string): Uint8Array => {
  const binary = atob(value);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return bytes;
};

/** Float samples at `from` Hz → signed 16-bit little-endian at `INPUT_RATE`. */
export function toPcm16(samples: Float32Array, from: number): Uint8Array {
  const ratio = from / INPUT_RATE;
  const length = Math.floor(samples.length / ratio);
  const out = new DataView(new ArrayBuffer(length * 2));

  for (let i = 0; i < length; i += 1) {
    const sample = samples[Math.floor(i * ratio)] ?? 0;
    const clamped = Math.max(-1, Math.min(1, sample));
    out.setInt16(i * 2, clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff, true);
  }
  return new Uint8Array(out.buffer);
}

/**
 * Signed 16-bit little-endian → float samples an AudioBuffer can hold.
 *
 * The length is in *samples*, and getting that wrong is quiet rather than
 * loud. `new Float32Array(new ArrayBuffer(bytes.byteLength))` looks right and
 * allocates a float per *byte pair of bytes* — four bytes each — so it holds
 * half the samples the chunk contains, and the second half of every chunk was
 * dropped on the floor. Nothing throws; the agent just sounds clipped and
 * hurried, in a way that is easy to blame on the model.
 */
export function fromPcm16(bytes: Uint8Array): Float32Array<ArrayBuffer> {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  // Four bytes per float, one float per *sample* — and a sample is two bytes.
  // Allocated through an ArrayBuffer rather than from a length so the type is
  // the one `copyToChannel` accepts.
  const samples = Math.floor(bytes.byteLength / 2);
  const out = new Float32Array(new ArrayBuffer(samples * 4));
  for (let i = 0; i < out.length; i += 1) out[i] = view.getInt16(i * 2, true) / 0x8000;
  return out;
}

/**
 * Both audio contexts, actually running.
 *
 * This is the bug that made speaking do nothing at all, and it is invisible in
 * the code that causes it. `startVoice` awaits `getUserMedia` before it
 * constructs either context — so by the time they are constructed the user
 * gesture that opened the microphone has been spent, and Chrome's autoplay
 * policy starts both of them **suspended**.
 *
 * A suspended capture context never runs its ScriptProcessor, so `audioprocess`
 * never fires and not one audio frame is ever sent: the traveller speaks, stops,
 * and the model is still waiting for a first byte. A suspended playback context
 * would swallow the answer even if one arrived. Neither throws, neither logs,
 * and the relay is in perfect health the whole time — which is exactly why this
 * survived a round of fixes to the server.
 *
 * `resume()` rejects if the context is already closed, which is a race with
 * hanging up rather than a failure worth surfacing.
 */
export async function wake(...contexts: AudioContext[]): Promise<void> {
  await Promise.all(
    contexts.map(async (context) => {
      if (context.state === 'suspended') {
        try {
          await context.resume();
        } catch {
          /* closed while we were waking it */
        }
      }
    }),
  );
}

/**
 * Talking to the app, the way you talk to the assistant on a phone.
 *
 * This was modelled as a *call* — `startCall`, `hangUp`, a button that said
 * "End the call" — and the model was the bug. Nobody dials an assistant. You
 * tap the microphone, say a thing, and it answers; the screen never goes away
 * and there is nothing to hang up. Built as a call, the microphone toggle was
 * wired to the hang-up, so speaking and then stopping tore the session down
 * before the answer could arrive.
 *
 * `listen` and `stopListening` open and close the microphone. Everything else —
 * the socket, the surfaces, the transcript — outlives both of them, and `close`
 * exists for leaving the page, not for ending a sentence.
 */
export interface VoiceSession {
  /** Releases the microphone and drops the socket. For leaving, not for stopping. */
  close(): void;
  /** Opens the microphone. Audio streams until `stopListening`. */
  listen(): void;
  /** Closes the microphone and lets the model take its turn. */
  stopListening(): void;
  /** Whether the microphone is open right now. */
  listening(): boolean;
  /**
   * Whether the socket behind it is still there.
   *
   * A session can die without anybody pressing anything: the relay ends when
   * *either* side does, so an upstream session that reaches its own limit
   * closes the browser's socket too. Everything above then still holds a
   * `VoiceSession` object whose methods all succeed and do nothing — `listen`
   * sets a flag, the microphone lights up, and `audioprocess` drops every
   * sample on the floor because the socket is not open. A live-looking
   * microphone that transmits nothing is the worst of the three states.
   */
  alive(): boolean;
  /** Types instead of speaking — useful when saying an airport code out loud fails. */
  say(text: string): void;
  /** True while the agent is speaking. */
  speaking(): boolean;
}

export interface VoiceOptions {
  origin: string;
  sessionId: string;
  apiKey: string;
  onEvent: (event: VoiceEvent) => void;
  onSpeakingChange?: (speaking: boolean) => void;
  /** The socket went away. Whoever holds this session should stop holding it. */
  onClosed?: () => void;
}

/**
 * What instantiating the Live agent returns.
 *
 * `contract` is the fingerprint of what the session was actually bound to —
 * catalog, skill, tools, model — echoed back by the server rather than read
 * from `/api/meta` a moment earlier, so a deploy landing mid-handshake cannot
 * leave a client believing it bound to something it did not.
 */
export interface LiveInstantiation {
  model: string;
  contract: string;
}

/**
 * Instantiates the Live agent, without touching the microphone.
 *
 * The Live API keeps no agent object: a session is whatever its opening `setup`
 * frame says it is — a model, a system instruction built from the catalog's
 * skill, and the tool declarations. So this opens a session, lets the server
 * send that frame, waits for the API to accept it, and hangs up. Real work: it
 * proves the key is good and reports the contract that was accepted, which is
 * what the app then remembers.
 *
 * Deliberately no `getUserMedia`. Asking for a microphone in order to check a
 * key is a permission prompt at the wrong moment, and a traveller who only ever
 * types should never see one.
 */
export async function instantiateLive(options: {
  origin: string;
  sessionId: string;
  apiKey: string;
  /** Milliseconds before giving up. The upstream handshake is normally fast. */
  timeoutMs?: number;
}): Promise<LiveInstantiation> {
  const base = options.origin || window.location.origin;
  const url = new URL('/api/voice', base);
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  url.searchParams.set('sessionId', options.sessionId);

  const socket = new WebSocket(url.toString());

  try {
    return await new Promise<LiveInstantiation>((resolve, reject) => {
      const timer = setTimeout(
        () => reject(new Error('The voice service did not answer in time.')),
        options.timeoutMs ?? 20000,
      );
      const finish = (error: Error | null, value?: LiveInstantiation) => {
        clearTimeout(timer);
        if (error) reject(error);
        else resolve(value!);
      };

      socket.addEventListener('open', () => {
        // The same hints a typed turn sends. A call had none of them, so it asked
  // people to say an airport code out loud — the exact question a
  // suggestion exists to avoid.
  socket.send(JSON.stringify({ type: 'start', apiKey: options.apiKey, client: clientHints() }));
      });
      socket.addEventListener('message', (event) => {
        let message: VoiceEvent;
        try {
          message = JSON.parse(String(event.data)) as VoiceEvent;
        } catch {
          return;
        }
        // `error` carries what the upstream said — a rejected key reads as a
        // rejected key rather than as "the socket closed".
        if (message.type === 'error') finish(new Error(message.message));
        if (message.type === 'ready') {
          finish(null, { model: message.model, contract: message.contract });
        }
      });
      socket.addEventListener('error', () =>
        finish(new Error('Could not reach the voice service.')),
      );
      socket.addEventListener('close', () =>
        finish(new Error('The voice service closed the connection.')),
      );
    });
  } finally {
    try {
      socket.close();
    } catch {
      /* already closing */
    }
  }
}

/**
 * Opens the microphone and the relay behind it. Resolves once connected,
 * rejects if the microphone is refused or the socket never opens.
 */
export async function startVoice(options: VoiceOptions): Promise<VoiceSession> {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
  });

  const base = options.origin || window.location.origin;
  const url = new URL('/api/voice', base);
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  url.searchParams.set('sessionId', options.sessionId);

  const socket = new WebSocket(url.toString());
  const capture = new AudioContext();
  const playback = new AudioContext({ sampleRate: OUTPUT_RATE });

  let playHead = 0;
  let speaking = false;
  const setSpeaking = (next: boolean) => {
    if (next === speaking) return;
    speaking = next;
    options.onSpeakingChange?.(next);
  };

  // Everything scheduled and not yet finished, so an interruption can stop it.
  // Chunks arrive faster than they play, so at the moment the traveller speaks
  // over the model there can be several seconds already queued — and a queue
  // that plays out after "stop" is a model that does not appear to have.
  const queued = new Set<AudioBufferSourceNode>();
  const hush = () => {
    for (const source of queued) {
      try {
        source.stop();
      } catch {
        /* never started, or already ended */
      }
    }
    queued.clear();
    playHead = 0;
    setSpeaking(false);
  };

  const stop = () => {
    for (const track of stream.getTracks()) track.stop();
    void capture.close().catch(() => {});
    void playback.close().catch(() => {});
    try {
      socket.close();
    } catch {
      /* already closing */
    }
  };

  // Before anything is sent or played. See `wake`: both of these were
  // constructed after an `await`, so they are born suspended and a suspended
  // capture context never delivers a single sample.
  await wake(capture, playback);

  await new Promise<void>((resolve, reject) => {
    socket.addEventListener('open', () => resolve(), { once: true });
    socket.addEventListener(
      'error',
      () => reject(new Error('Could not reach the voice service.')),
      { once: true },
    );
  });

  // The same hints a typed turn sends. A call had none of them, so it asked
  // people to say an airport code out loud — the exact question a
  // suggestion exists to avoid.
  socket.send(JSON.stringify({ type: 'start', apiKey: options.apiKey, client: clientHints() }));

  socket.addEventListener('message', (event) => {
    const message = JSON.parse(String(event.data)) as VoiceEvent;

    if (message.type === 'audio') {
      const samples = fromPcm16(fromBase64(message.data));
      const buffer = playback.createBuffer(1, samples.length, OUTPUT_RATE);
      buffer.copyToChannel(samples, 0);

      const source = playback.createBufferSource();
      source.buffer = buffer;
      source.connect(playback.destination);

      // Queue behind whatever is already playing. `playHead` running behind
      // `currentTime` means the queue drained, so the next chunk starts now.
      playHead = Math.max(playHead, playback.currentTime);
      source.start(playHead);
      playHead += buffer.duration;
      queued.add(source);
      setSpeaking(true);
      source.addEventListener('ended', () => {
        queued.delete(source);
        if (playHead <= playback.currentTime + 0.05) setSpeaking(false);
      });
      return;
    }

    if (message.type === 'interrupted') hush();
    if (message.type === 'turn_end') setSpeaking(false);
    options.onEvent(message);
  });

  socket.addEventListener('close', () => {
    setSpeaking(false);
    // The microphone cannot stay open over a socket that is gone. Leaving
    // `open` true is what made the next tap *close* a dead microphone instead
    // of opening a live one, so the button needed two presses to do nothing.
    open = false;
    options.onEvent({ type: 'turn_end' });
    options.onClosed?.();
  });

  // `createScriptProcessor` is deprecated in favour of an AudioWorklet, which
  // needs a separate module file the bundler has to emit. For a demo that reads
  // 4096 samples at a time this is the smaller moving part; the worklet is the
  // upgrade when it stops being.
  const source = capture.createMediaStreamSource(stream);
  const processor = capture.createScriptProcessor(4096, 1, 1);
  let open = false;
  processor.addEventListener('audioprocess', (event) => {
    if (!open || socket.readyState !== WebSocket.OPEN) return;
    const pcm = toPcm16(event.inputBuffer.getChannelData(0), capture.sampleRate);
    socket.send(JSON.stringify({ type: 'audio', data: toBase64(pcm) }));
  });
  source.connect(processor);
  // Through a silent gain node: a ScriptProcessor only runs while connected to
  // a destination, and connecting it directly would play the microphone back
  // into the room.
  const mute = capture.createGain();
  mute.gain.value = 0;
  processor.connect(mute);
  mute.connect(capture.destination);

  return {
    close: () => {
      try {
        socket.send(JSON.stringify({ type: 'end' }));
      } catch {
        /* already closed */
      }
      stop();
    },
    listen: () => {
      // Again on every tap, not only at setup. A context is suspended again
      // whenever the browser feels like it — a backgrounded tab is the common
      // one — and it comes back as a microphone that is on and silent.
      void wake(capture, playback);
      open = true;
    },
    stopListening: () => {
      if (!open) return;
      open = false;
      // The model answers on voice activity detection, and VAD notices somebody
      // has stopped talking by hearing the silence after them. Cutting the
      // stream dead sends no silence, so it waits for audio that is not coming.
      // This says it instead, and the session stays open.
      try {
        socket.send(JSON.stringify({ type: 'audio_end' }));
      } catch {
        /* already closed */
      }
    },
    listening: () => open,
    alive: () => socket.readyState === WebSocket.OPEN,
    say: (text: string) => {
      if (socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: 'text', text }));
      }
    },
    speaking: () => speaking,
  };
}
