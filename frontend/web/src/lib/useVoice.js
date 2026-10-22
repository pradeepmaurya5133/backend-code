import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Browser speech recognition and synthesis via the Web Speech API.
 *
 * This is why voice works with no API keys and no audio upload: the browser
 * does recognition locally, the server only ever sees text, and the reply is
 * spoken by speechSynthesis. Support is uneven (Chrome and Edge are reliable,
 * Firefox has no recognition), so `supported` is reported rather than assumed.
 */
export function useVoice({ onTranscript } = {}) {
  const [listening, setListening] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [interim, setInterim] = useState("");
  const [error, setError] = useState(null);

  const recognitionRef = useRef(null);
  const callbackRef = useRef(onTranscript);
  callbackRef.current = onTranscript;

  const SpeechRecognition =
    typeof window !== "undefined" &&
    (window.SpeechRecognition || window.webkitSpeechRecognition);
  const synthesis = typeof window !== "undefined" ? window.speechSynthesis : null;

  const recognitionSupported = Boolean(SpeechRecognition);
  const synthesisSupported = Boolean(synthesis);

  useEffect(() => {
    if (!recognitionSupported) return undefined;

    const recognition = new SpeechRecognition();
    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.lang = "en-US";

    recognition.onresult = (event) => {
      let finalText = "";
      let partial = "";
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const result = event.results[i];
        if (result.isFinal) finalText += result[0].transcript;
        else partial += result[0].transcript;
      }
      setInterim(partial);
      if (finalText.trim()) {
        setInterim("");
        callbackRef.current?.(finalText.trim());
      }
    };

    recognition.onerror = (event) => {
      // "aborted" is what a deliberate stop() looks like; not worth surfacing.
      if (event.error !== "aborted") {
        setError(
          event.error === "not-allowed"
            ? "Microphone access was blocked. Allow it in your browser settings."
            : `Speech recognition error: ${event.error}`
        );
      }
      setListening(false);
    };

    recognition.onend = () => {
      setListening(false);
      setInterim("");
    };

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
  }, [recognitionSupported, SpeechRecognition]);

  const startListening = useCallback(() => {
    setError(null);
    const recognition = recognitionRef.current;
    if (!recognition) {
      setError("This browser has no speech recognition. Chrome or Edge work; typing always works.");
      return;
    }
    // Never record while speaking - the mic would transcribe our own voice.
    synthesis?.cancel();
    setSpeaking(false);
    try {
      recognition.start();
      setListening(true);
    } catch {
      // start() throws if already running; treat that as already listening.
      setListening(true);
    }
  }, [synthesis]);

  const stopListening = useCallback(() => {
    try {
      recognitionRef.current?.stop();
    } catch {
      /* not running */
    }
    setListening(false);
  }, []);

  const speak = useCallback(
    (text) => {
      if (!synthesis || !text) return;
      synthesis.cancel();
      const utterance = new SpeechSynthesisUtterance(text);
      utterance.rate = 1.03;
      utterance.pitch = 1;
      utterance.onstart = () => setSpeaking(true);
      utterance.onend = () => setSpeaking(false);
      utterance.onerror = () => setSpeaking(false);
      synthesis.speak(utterance);
    },
    [synthesis]
  );

  const stopSpeaking = useCallback(() => {
    synthesis?.cancel();
    setSpeaking(false);
  }, [synthesis]);

  useEffect(() => () => synthesis?.cancel(), [synthesis]);

  return {
    listening,
    speaking,
    interim,
    error,
    recognitionSupported,
    synthesisSupported,
    startListening,
    stopListening,
    speak,
    stopSpeaking,
  };
}
