/**
 * Browser-mode voice, matching the backend's VOICE_MODE=browser default: the
 * browser does recognition and synthesis, the server only runs the turn. No
 * provider keys, and audio never leaves the machine.
 */

import { useCallback, useEffect, useRef, useState } from "react";

const Recognition =
  typeof window !== "undefined" &&
  (window.SpeechRecognition || window.webkitSpeechRecognition);

export function useVoice({ onTranscript }) {
  const [listening, setListening] = useState(false);
  const [error, setError] = useState(null);
  const recognitionRef = useRef(null);
  const callbackRef = useRef(onTranscript);
  callbackRef.current = onTranscript;

  const supported = Boolean(Recognition);

  useEffect(() => {
    if (!supported) return undefined;

    const recognition = new Recognition();
    recognition.lang = "en-US";
    recognition.continuous = false;
    recognition.interimResults = false;

    recognition.onresult = (event) => {
      const transcript = event.results?.[0]?.[0]?.transcript?.trim();
      if (transcript) callbackRef.current?.(transcript);
    };
    recognition.onerror = (event) => {
      setError(
        event.error === "not-allowed"
          ? "Microphone access was denied."
          : `Speech recognition failed (${event.error}).`
      );
      setListening(false);
    };
    recognition.onend = () => setListening(false);

    recognitionRef.current = recognition;
    return () => {
      recognition.onresult = null;
      recognition.onerror = null;
      recognition.onend = null;
      try {
        recognition.abort();
      } catch {
        /* already stopped */
      }
    };
  }, [supported]);

  const start = useCallback(() => {
    if (!recognitionRef.current || listening) return;
    setError(null);
    try {
      recognitionRef.current.start();
      setListening(true);
    } catch {
      // start() throws if a previous session has not fully ended yet.
      setListening(false);
    }
  }, [listening]);

  const stop = useCallback(() => {
    try {
      recognitionRef.current?.stop();
    } catch {
      /* nothing in flight */
    }
    setListening(false);
  }, []);

  return { supported, listening, error, start, stop, toggle: listening ? stop : start };
}

export function speak(text) {
  if (!text || typeof window === "undefined" || !window.speechSynthesis) return;
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.rate = 1.02;
  window.speechSynthesis.speak(utterance);
}

export function cancelSpeech() {
  window.speechSynthesis?.cancel();
}
