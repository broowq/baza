"use client";

import { useEffect, useRef, useState } from "react";
import { Mic, MicOff } from "lucide-react";
import { toast } from "sonner";

/**
 * Voice-to-text button using the Web Speech API (SpeechRecognition).
 *
 * Browser support: Chrome / Edge / Safari (iOS 14.5+). Firefox does NOT ship
 * webkitSpeechRecognition — we hide the button entirely on unsupported
 * browsers rather than show a useless mic icon.
 *
 * Behaviour:
 *  - First click → starts continuous recognition in ru-RU; existing textarea
 *    value is kept and new transcribed text is appended (so users can mix
 *    typing + dictation).
 *  - Second click → stops; final transcript is committed.
 *  - Interim results stream into the textarea live so users see progress
 *    instead of staring at a blinking cursor.
 *  - On permission denial, network error, or no-speech we surface a toast
 *    rather than silently doing nothing.
 *
 * The component is intentionally headless — it owns no text state. Parent
 * passes `value` + `onChange` (same shape as a controlled <textarea>) so the
 * existing form state stays the single source of truth.
 */

// Minimal Web Speech API shape — `lib.dom.d.ts` doesn't include it on older
// TS versions, and we only touch a small subset.
interface SpeechRecognitionEventLike {
  resultIndex: number;
  results: ArrayLike<{
    isFinal: boolean;
    0: { transcript: string };
  }>;
}
interface SpeechRecognitionLike {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  start: () => void;
  stop: () => void;
  abort: () => void;
  onresult: ((e: SpeechRecognitionEventLike) => void) | null;
  onerror: ((e: { error: string }) => void) | null;
  onend: (() => void) | null;
}
type SpeechRecognitionCtor = new () => SpeechRecognitionLike;

function getSpeechRecognitionCtor(): SpeechRecognitionCtor | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as {
    SpeechRecognition?: SpeechRecognitionCtor;
    webkitSpeechRecognition?: SpeechRecognitionCtor;
  };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export function VoiceInput({
  value,
  onChange,
  className = "",
}: {
  value: string;
  onChange: (next: string) => void;
  className?: string;
}) {
  const [supported, setSupported] = useState(false);
  const [listening, setListening] = useState(false);
  const recRef = useRef<SpeechRecognitionLike | null>(null);
  // Snapshot of `value` at the moment recognition started — we append the
  // transcript onto this base so finalised speech doesn't keep clobbering
  // earlier text the user typed mid-session.
  const baseRef = useRef("");

  useEffect(() => {
    setSupported(getSpeechRecognitionCtor() !== null);
    return () => {
      // Stop recognition when the component unmounts (modal close etc.) so we
      // don't leak the mic permission or fire onresult into a dead handler.
      try {
        recRef.current?.abort();
      } catch {
        /* ignore */
      }
    };
  }, []);

  if (!supported) return null;

  const start = () => {
    const Ctor = getSpeechRecognitionCtor();
    if (!Ctor) return;
    const rec = new Ctor();
    rec.lang = "ru-RU";
    rec.continuous = true;
    rec.interimResults = true;

    baseRef.current = value;

    rec.onresult = (event) => {
      // Re-concatenate every result on each event — that way correction
      // mid-utterance (Chrome occasionally rewrites earlier interim results)
      // updates the textarea instead of duplicating phrases.
      let final = "";
      let interim = "";
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const r = event.results[i];
        const t = r[0].transcript;
        if (r.isFinal) final += t;
        else interim += t;
      }
      const combined = (baseRef.current + " " + final + interim).replace(
        /\s+/g,
        " ",
      ).trimStart();
      onChange(combined);
      if (final) {
        // Move base forward so subsequent results don't re-stack the same
        // finalised text on top of itself.
        baseRef.current = (baseRef.current + " " + final).replace(/\s+/g, " ").trimStart();
      }
    };

    rec.onerror = (e) => {
      const err = e.error;
      if (err === "not-allowed" || err === "service-not-allowed") {
        toast.error("Доступ к микрофону запрещён. Разрешите его в настройках браузера.");
      } else if (err === "no-speech") {
        toast.message("Не услышал голос. Попробуй ещё раз ближе к микрофону.");
      } else if (err === "audio-capture") {
        toast.error("Микрофон не найден.");
      } else if (err !== "aborted") {
        toast.error(`Ошибка распознавания: ${err}`);
      }
      setListening(false);
    };

    rec.onend = () => {
      setListening(false);
      recRef.current = null;
    };

    try {
      rec.start();
      recRef.current = rec;
      setListening(true);
    } catch {
      // .start() throws InvalidStateError if called twice — flip back so the
      // button isn't stuck in "listening".
      setListening(false);
    }
  };

  const stop = () => {
    try {
      recRef.current?.stop();
    } catch {
      /* ignore */
    }
  };

  const toggle = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (listening) stop();
    else start();
  };

  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={listening ? "Остановить запись" : "Записать голосом"}
      title={listening ? "Остановить запись" : "Записать голосом"}
      className={
        "inline-flex h-9 w-9 items-center justify-center rounded-full border transition-all " +
        (listening
          ? "border-[var(--rose)]/50 bg-[var(--rose)]/10 text-[var(--rose)] animate-pulse"
          : "border-[var(--line-2)] bg-white/[0.04] text-white/72 hover:bg-white/[0.08] hover:text-white") +
        " " +
        className
      }
    >
      {listening ? <MicOff className="h-4 w-4" /> : <Mic className="h-4 w-4" />}
    </button>
  );
}
