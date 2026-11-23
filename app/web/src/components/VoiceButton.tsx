import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { Loader2, Mic, Square } from "lucide-react";
import { useEffect, useRef, useState } from "react";

// Voice input: record a question, transcribe it on the platform (local Whisper service,
// /speech/transcribe), put the text in the question box. Nothing is sent to the assistant
// until the person reads it and presses Enter.
type State = "idle" | "recording" | "transcribing";
const MAX_SECONDS = 60;

export default function VoiceButton({ onText, disabled }: { onText: (text: string) => void; disabled: boolean }) {
  const reduce = useReducedMotion();
  const [state, setState] = useState<State>("idle");
  const [error, setError] = useState<string>();
  const [seconds, setSeconds] = useState(0);
  const [levels, setLevels] = useState<number[]>([0.2, 0.2, 0.2, 0.2, 0.2]);
  const recorder = useRef<MediaRecorder>();
  const chunks = useRef<Blob[]>([]);
  const cancelled = useRef(false);
  const cleanup = useRef<() => void>();

  const supported = typeof window !== "undefined" && Boolean(navigator.mediaDevices?.getUserMedia) && typeof MediaRecorder !== "undefined";

  useEffect(() => () => cleanup.current?.(), []);

  useEffect(() => {
    if (state !== "recording") return undefined;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        cancelled.current = true;
        recorder.current?.stop();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [state]);

  async function start() {
    setError(undefined);
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
    } catch {
      setError("Microphone access was refused. Allow it for this site in the browser settings.");
      return;
    }
    const type = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg"].find((t) => MediaRecorder.isTypeSupported(t));
    const rec = new MediaRecorder(stream, type ? { mimeType: type } : undefined);
    chunks.current = [];
    cancelled.current = false;
    rec.ondataavailable = (e) => e.data.size && chunks.current.push(e.data);

    // Level meter: five bars that follow the voice.
    const context = new AudioContext();
    const analyser = context.createAnalyser();
    analyser.fftSize = 64;
    context.createMediaStreamSource(stream).connect(analyser);
    const data = new Uint8Array(analyser.frequencyBinCount);
    let frame = 0;
    const tick = () => {
      analyser.getByteFrequencyData(data);
      const bands = [2, 4, 6, 9, 13].map((i) => Math.min(1, Math.max(0.15, data[i] / 200)));
      setLevels(bands);
      frame = requestAnimationFrame(tick);
    };
    if (!reduce) frame = requestAnimationFrame(tick);
    const started = Date.now();
    const timer = setInterval(() => {
      const s = (Date.now() - started) / 1000;
      setSeconds(s);
      if (s >= MAX_SECONDS) rec.stop();
    }, 200);

    cleanup.current = () => {
      cancelAnimationFrame(frame);
      clearInterval(timer);
      stream.getTracks().forEach((t) => t.stop());
      context.close().catch(() => {});
    };

    rec.onstop = async () => {
      cleanup.current?.();
      cleanup.current = undefined;
      setSeconds(0);
      if (cancelled.current || !chunks.current.length) {
        setState("idle");
        return;
      }
      setState("transcribing");
      try {
        const blob = new Blob(chunks.current, { type: rec.mimeType || "audio/webm" });
        const response = await fetch("/speech/transcribe", { method: "POST", headers: { "Content-Type": blob.type }, body: blob });
        if (!response.ok) throw new Error(response.status >= 500 ? "unavailable" : `HTTP ${response.status}`);
        const { text } = (await response.json()) as { text: string };
        if (text.trim()) onText(text.trim());
        else setError("No speech was recognised. Try again, a little closer to the microphone.");
      } catch (e) {
        setError(
          String(e).includes("unavailable")
            ? "Voice input is not available right now (the speech service is starting or stopped)."
            : "The recording could not be transcribed.",
        );
      } finally {
        setState("idle");
      }
    };
    recorder.current = rec;
    rec.start(250);
    setState("recording");
  }

  if (!supported) return null;

  return (
    <div className="relative flex items-center">
      <AnimatePresence>
        {state === "recording" && (
          <motion.div
            initial={{ opacity: 0, x: 8 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: 8 }}
            className="mr-2 flex items-center gap-2 rounded-input bg-bad/10 px-2.5 py-1.5 text-xs text-bad-ink"
            aria-live="polite"
          >
            <span className="blink h-2 w-2 rounded-full bg-bad" aria-hidden="true" />
            <span className="flex h-4 items-end gap-[3px]" aria-hidden="true">
              {levels.map((l, i) => (
                <motion.span key={i} className="w-[3px] rounded-full bg-bad" animate={{ height: `${Math.round(l * 16)}px` }} transition={{ duration: 0.08 }} />
              ))}
            </span>
            <span className="num">0:{String(Math.floor(seconds)).padStart(2, "0")}</span>
            <span className="hidden sm:inline">· Esc to cancel</span>
          </motion.div>
        )}
      </AnimatePresence>
      <button
        type="button"
        onClick={() => (state === "recording" ? recorder.current?.stop() : start())}
        disabled={disabled || state === "transcribing"}
        aria-pressed={state === "recording"}
        aria-label={state === "recording" ? "Stop and transcribe" : state === "transcribing" ? "Transcribing" : "Ask by voice"}
        title={state === "recording" ? "Stop and transcribe" : "Ask by voice (transcribed on this platform)"}
        className={`grid h-9 w-9 shrink-0 place-items-center rounded-input transition-colors duration-150 ${
          state === "recording" ? "bg-bad text-white" : "text-ink-2 hover:bg-tint hover:text-ink"
        }`}
      >
        {state === "recording" ? (
          <Square size={14} fill="currentColor" aria-hidden="true" />
        ) : state === "transcribing" ? (
          <Loader2 size={17} className="animate-spin" aria-hidden="true" />
        ) : (
          <Mic size={18} aria-hidden="true" />
        )}
      </button>
      {error && (
        <div role="alert" className="absolute bottom-full right-0 mb-2 w-72 rounded-input border border-line bg-surface p-3 text-xs text-ink-2 shadow-raised">
          {error}
          <button className="ml-1 font-medium text-primary-strong hover:underline" onClick={() => setError(undefined)}>
            Dismiss
          </button>
        </div>
      )}
    </div>
  );
}
