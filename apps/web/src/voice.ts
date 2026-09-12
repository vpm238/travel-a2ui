/**
 * The microphone and the speaker, and nothing else.
 *
 * Everything that makes this a *travel* agent — the catalog, the compiler, the
 * tools, the trip — is on the other end of the socket. This file knows how to
 * turn a microphone into 16 kHz PCM, how to play 24 kHz PCM back without gaps,
 * and how to forward JSON. A Swift or Kotlin client would need exactly these
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
function toPcm16(samples: Float32Array, from: number): Uint8Array {
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

/** Signed 16-bit little-endian → float samples an AudioBuffer can hold. */
function fromPcm16(bytes: Uint8Array): Float32Array<ArrayBuffer> {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const out = new Float32Array(new ArrayBuffer(bytes.byteLength));
  for (let i = 0; i < out.length; i += 1) out[i] = view.getInt16(i * 2, true) / 0x8000;
  return out;
}

export interface VoiceCall {
  /** Ends the call and releases the microphone. */
  hangUp(): void;
  /** Types into a voice call — useful when saying an airport code out loud fails. */
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
 * Opens a call. Resolves once the relay is connected, rejects if the
 * microphone is refused or the socket never opens.
 */
export async function startCall(options: VoiceOptions): Promise<VoiceCall> {
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
      setSpeaking(true);
      source.addEventListener('ended', () => {
        if (playHead <= playback.currentTime + 0.05) setSpeaking(false);
      });
      return;
    }

    if (message.type === 'turn_end') setSpeaking(false);
    options.onEvent(message);
  });

  socket.addEventListener('close', () => {
    setSpeaking(false);
    options.onEvent({ type: 'turn_end' });
  });

  // `createScriptProcessor` is deprecated in favour of an AudioWorklet, which
  // needs a separate module file the bundler has to emit. For a demo that reads
  // 4096 samples at a time this is the smaller moving part; the worklet is the
  // upgrade when it stops being.
  const source = capture.createMediaStreamSource(stream);
  const processor = capture.createScriptProcessor(4096, 1, 1);
  processor.addEventListener('audioprocess', (event) => {
    if (socket.readyState !== WebSocket.OPEN) return;
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
    hangUp: () => {
      try {
        socket.send(JSON.stringify({ type: 'end' }));
      } catch {
        /* already closed */
      }
      stop();
    },
    say: (text: string) => {
      if (socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: 'text', text }));
      }
    },
    speaking: () => speaking,
  };
}
