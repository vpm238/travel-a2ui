/**
 * The two audio bugs that made speaking into the app do nothing.
 *
 * Neither of them threw, neither of them logged, and the relay behind them was
 * in perfect health the whole time — a real Live session, driven over the real
 * socket, answered speech with speech and drew a flight picker. That is what
 * makes them worth a test file: everything reported "working" except the thing
 * the traveller was doing.
 */

import { afterEach, describe, expect, it, vi } from 'vitest';

import { fromPcm16, toPcm16, wake } from '../src/voice.js';

/** Signed 16-bit little-endian, the format both ends of the relay speak. */
function pcm16(...samples: number[]): Uint8Array {
  const view = new DataView(new ArrayBuffer(samples.length * 2));
  samples.forEach((sample, index) => view.setInt16(index * 2, sample, true));
  return new Uint8Array(view.buffer);
}

describe('playing back what the agent said', () => {
  it('keeps every sample in the chunk', () => {
    // The bug: the Float32Array was allocated from the *byte* length, which is
    // four bytes per float and therefore half as many samples as the chunk
    // holds. Half of every chunk was silently discarded.
    const chunk = pcm16(1, 2, 3, 4, 5, 6, 7, 8);
    expect(chunk.byteLength).toBe(16);
    expect(fromPcm16(chunk)).toHaveLength(8);
  });

  it('is the same length the relay sent', () => {
    // A real frame: 1,920 bytes is the 960-sample chunk the server forwards.
    const frame = pcm16(...Array.from({ length: 960 }, (_, i) => i - 480));
    expect(fromPcm16(frame)).toHaveLength(960);
  });

  it('reads the samples in order rather than the first half twice', () => {
    const heard = fromPcm16(pcm16(0, 0x4000, -0x4000, 0x7fff));
    expect(heard[0]).toBeCloseTo(0, 5);
    expect(heard[1]).toBeCloseTo(0.5, 5);
    expect(heard[2]).toBeCloseTo(-0.5, 5);
    expect(heard[3]).toBeCloseTo(1, 3);
  });

  it('survives a chunk with an odd trailing byte', () => {
    // Never send one, but a truncated frame should clip rather than allocate a
    // fractional sample and produce a NaN that plays as a click.
    expect(() => fromPcm16(new Uint8Array([1, 2, 3]))).not.toThrow();
    expect(fromPcm16(new Uint8Array([1, 2, 3]))).toHaveLength(1);
  });
});

describe('what the microphone sends up', () => {
  it('resamples 48 kHz down to the 16 kHz the Live API accepts', () => {
    // Three samples in, one out. Getting this wrong does not throw — the model
    // just hears a chipmunk and answers something nobody said.
    const captured = new Float32Array(48_000).fill(0.5);
    expect(toPcm16(captured, 48_000)).toHaveLength(16_000 * 2);
  });

  it('passes 16 kHz through unchanged', () => {
    expect(toPcm16(new Float32Array(16_000), 16_000)).toHaveLength(16_000 * 2);
  });

  it('round-trips a sample through both directions', () => {
    const heard = fromPcm16(toPcm16(Float32Array.from([0.5, -0.5]), 16_000));
    expect(heard).toHaveLength(2);
    expect(heard[0]).toBeCloseTo(0.5, 3);
    expect(heard[1]).toBeCloseTo(-0.5, 3);
  });

  it('clamps rather than wrapping a sample past full scale', () => {
    // Without the clamp, 1.2 wraps to a large negative int16 — a loud click
    // that reads as a broken microphone.
    const heard = fromPcm16(toPcm16(Float32Array.from([1.2, -1.2]), 16_000));
    expect(heard[0]!).toBeGreaterThan(0.9);
    expect(heard[1]!).toBeLessThan(-0.9);
  });
});

describe('waking the audio contexts', () => {
  /** Just enough of an AudioContext to record whether it was resumed. */
  function fake(state: AudioContextState, onResume?: () => void) {
    const context = {
      state,
      resumed: 0,
      async resume() {
        context.resumed += 1;
        onResume?.();
        context.state = 'running' as AudioContextState;
      },
    };
    return context;
  }

  const as = (context: unknown) => context as AudioContext;

  it('resumes a context the browser started suspended', async () => {
    // The whole bug: `startVoice` awaits `getUserMedia` before constructing
    // either context, so the user gesture is spent and Chrome starts both of
    // them suspended. A suspended capture context never fires `audioprocess`,
    // so not one audio frame is ever sent and speaking does nothing at all.
    const capture = fake('suspended');
    const playback = fake('suspended');

    await wake(as(capture), as(playback));

    expect(capture.resumed).toBe(1);
    expect(playback.resumed).toBe(1);
    expect(capture.state).toBe('running');
  });

  it('leaves a running context alone', async () => {
    const running = fake('running');
    await wake(as(running));
    expect(running.resumed).toBe(0);
  });

  it('does not reject when the context was closed mid-wake', async () => {
    // Racing a hang-up. `resume()` rejects on a closed context, and that is
    // not a failure worth taking the session down for.
    const closing = fake('suspended', () => {
      throw new Error('Cannot resume a closed AudioContext');
    });
    await expect(wake(as(closing))).resolves.toBeUndefined();
  });

  it('wakes every context even when an earlier one fails', async () => {
    const broken = fake('suspended', () => {
      throw new Error('closed');
    });
    const good = fake('suspended');
    await wake(as(broken), as(good));
    expect(good.state).toBe('running');
  });
});

describe('a session whose socket has gone', () => {
  /**
   * The microphone that looked live and transmitted nothing.
   *
   * The relay ends when *either* side does, so an upstream Live session that
   * reaches its own limit closes the browser's socket with it — without anybody
   * pressing anything. Everything above still held a `VoiceSession` whose
   * methods all succeeded: `listen()` set a flag, the button lit up, and
   * `audioprocess` dropped every sample because the socket was not open.
   *
   * Three states, and this was the worst of them: not "off", not "on", but "on
   * and deaf". The button appeared to work and the model never answered.
   */
  const sockets: FakeSocket[] = [];

  class FakeSocket {
    static readonly OPEN = 1;
    static readonly CLOSED = 3;
    readyState = FakeSocket.OPEN;
    sent: string[] = [];
    private readonly listeners: Record<string, ((event: unknown) => void)[]> = {};

    constructor() {
      sockets.push(this);
    }

    addEventListener(type: string, handler: (event: unknown) => void) {
      (this.listeners[type] ??= []).push(handler);
      // `startVoice` awaits `getUserMedia` and `wake` before it listens for
      // `open`, so a fake that fires once, early, is never heard — the real
      // socket is still connecting at that point. Replay it instead.
      if (type === 'open' && this.readyState === FakeSocket.OPEN) {
        queueMicrotask(() => handler({}));
      }
    }

    send(data: string) {
      this.sent.push(data);
    }

    close() {
      this.readyState = FakeSocket.CLOSED;
      this.fire('close', {});
    }

    fire(type: string, event: unknown) {
      for (const handler of this.listeners[type] ?? []) handler(event);
    }
  }

  /** The `audioprocess` handlers the session registered, so a test can fire one. */
  const mics: ((event: unknown) => void)[] = [];
  /** `ended` handlers on scheduled playback, so a test can finish a chunk. */
  const played: ((event: unknown) => void)[] = [];

  /** Every AudioContext the session made: capture first, playback second. */
  const contexts: { currentTime: number }[] = [];

  function fakeAudioContext() {
    const node = () => ({ connect: () => {} });
    return class {
      constructor() {
        contexts.push(this as unknown as { currentTime: number });
      }
      state = 'running';
      sampleRate = 16000;
      currentTime = 0;
      destination = {};
      resume = async () => {};
      close = async () => {};
      createMediaStreamSource = () => node();
      createScriptProcessor = () => ({
        ...node(),
        addEventListener: (type: string, handler: (event: unknown) => void) => {
          if (type === 'audioprocess') mics.push(handler);
        },
      });
      createGain = () => ({ ...node(), gain: { value: 1 } });
      createBuffer = () => ({ copyToChannel: () => {}, duration: 0.5 });
      createBufferSource = () => ({
        ...node(),
        start: () => {},
        stop: () => {},
        addEventListener: (type: string, handler: (event: unknown) => void) => {
          if (type === 'ended') played.push(handler);
        },
      });
    };
  }

  /** One frame of microphone input, as the ScriptProcessor delivers it. */
  const frame = () => ({
    inputBuffer: { getChannelData: () => new Float32Array(4096).fill(0.25) },
  });

  /** Makes the session believe the agent is speaking, by sending it audio. */
  function agentSpeaks(socket: FakeSocket) {
    // `toBase64` is private to the module, so the frame is encoded here. Any
    // decodable chunk will do: what matters is that the session schedules it
    // and therefore believes it is speaking.
    const data = Buffer.from(pcm16(1, 2, 3, 4)).toString('base64');
    socket.fire('message', { data: JSON.stringify({ type: 'audio', data }) });
  }

  /** How many audio frames the session has forwarded upstream. */
  const uploaded = (socket: FakeSocket) =>
    socket.sent.filter((line) => JSON.parse(line).type === 'audio').length;

  async function open(onClosed?: () => void) {
    sockets.length = 0;
    mics.length = 0;
    played.length = 0;
    contexts.length = 0;
    // `navigator` is getter-only on the global in Node, so it cannot simply be
    // assigned. `stubGlobal` defines over it and `unstubAllGlobals` puts it back.
    vi.stubGlobal('WebSocket', FakeSocket);
    vi.stubGlobal('AudioContext', fakeAudioContext());
    vi.stubGlobal('navigator', {
      mediaDevices: { getUserMedia: async () => ({ getTracks: () => [] }) },
    });
    vi.stubGlobal('window', { location: { origin: 'http://localhost' } });
    const { startVoice } = await import('../src/voice.js');
    return startVoice({
      origin: 'http://localhost',
      sessionId: 's1',
      apiKey: 'k',
      onEvent: () => {},
      ...(onClosed ? { onClosed } : {}),
    });
  }

  afterEach(() => vi.unstubAllGlobals());

  it('forwards the microphone while nobody is speaking', async () => {
    const session = await open();
    const socket = sockets[sockets.length - 1]!;
    session.listen();

    mics[0]!(frame());
    expect(uploaded(socket)).toBe(1);
  });

  it('does not forward the microphone while the agent is speaking', async () => {
    // The self-repeat, in one assertion.
    //
    // The microphone is a toggle, so it stays open for the whole call. With
    // nothing gating it, the agent's own answer went back up the socket, the
    // API's voice activity detection read it as the traveller talking, and the
    // model was handed its own last sentence as the newest thing the user
    // said. It answered itself — usually by repeating itself — and the
    // interruption that came with it chopped each attempt off mid-word.
    const session = await open();
    const socket = sockets[sockets.length - 1]!;
    session.listen();
    agentSpeaks(socket);
    expect(session.speaking()).toBe(true);

    const before = uploaded(socket);
    mics[0]!(frame());
    mics[0]!(frame());
    expect(uploaded(socket)).toBe(before);
  });

  it('opens the microphone again on its own once the audio has played out', async () => {
    // The gate is the playback clock, not the `speaking` flag, and this is
    // why: `speaking` is cleared by events — an `ended` callback, a `turn_end`
    // from the relay, a socket close — and a gate waiting on an event that
    // never arrives is a microphone dead for the rest of the call. That would
    // be a worse bug than the self-repeat it was put there to stop.
    //
    // So no event is sent here at all. Only time passes.
    const session = await open();
    const socket = sockets[sockets.length - 1]!;
    const playback = contexts[1]!;
    session.listen();
    agentSpeaks(socket);

    const before = uploaded(socket);
    mics[0]!(frame());
    expect(uploaded(socket)).toBe(before);

    // Still inside the tail: the output device has its own latency and the
    // speaker keeps moving after the last sample, and just after an answer is
    // when the model is listening hardest.
    playback.currentTime = 0.5;
    mics[0]!(frame());
    expect(uploaded(socket)).toBe(before);

    playback.currentTime = 0.9;
    mics[0]!(frame());
    expect(uploaded(socket)).toBe(before + 1);
  });

  it('lets the traveller cut the agent off and be heard at once', async () => {
    // Barge-in, which the gate above would otherwise have taken away: talking
    // over the agent cannot work when the microphone is not being forwarded.
    // So it becomes a tap, which is deterministic — where a loudness threshold
    // between "a speaker" and "a person" is a guess that differs per room, and
    // guessing it wrong restores the loop.
    const session = await open();
    const socket = sockets[sockets.length - 1]!;
    session.listen();
    agentSpeaks(socket);
    expect(session.speaking()).toBe(true);

    session.interrupt();
    expect(session.speaking()).toBe(false);
    expect(session.listening()).toBe(true);

    const before = uploaded(socket);
    mics[0]!(frame());
    expect(uploaded(socket)).toBe(before + 1);
  });

  it('reports itself dead once the socket closes', async () => {
    const session = await open();
    expect(session.alive()).toBe(true);

    sockets[sockets.length - 1]!.close();
    expect(session.alive()).toBe(false);
  });

  it('does not keep claiming the microphone is open', async () => {
    const session = await open();
    session.listen();
    expect(session.listening()).toBe(true);

    // Nobody pressed anything. The upstream session ended.
    sockets[sockets.length - 1]!.close();

    // The thing that made the button need two presses to do nothing: `open`
    // stayed true, so the next tap read as "stop" on a microphone that was
    // already deaf.
    expect(session.listening()).toBe(false);
  });

  it('tells its owner to let go', async () => {
    let told = false;
    await open(() => {
      told = true;
    });

    sockets[sockets.length - 1]!.close();
    expect(told).toBe(true);
  });
});
