"""
voice_pipeline.py
Handles audio capture + offline speech-to-text (SpeechRecognition + PyAudio,
using the Google Web Speech API's offline-capable pocketsphinx backend is NOT
required here - we use the default recognizer with a local mic stream) and
offline text-to-speech (pyttsx3).

NOTE: SpeechRecognition's `recognize_google` requires internet. For a fully
offline pipeline, install `vosk` and swap in recognize_vosk, or use
`recognizer.recognize_sphinx` (requires pocketsphinx). This scaffold uses
whichever recognizer function you configure below - see RECOGNIZE_FN.
"""

import logging
import threading

import pyttsx3
import speech_recognition as sr

logger = logging.getLogger("assistant")

# Swap this to "sphinx" for fully offline recognition if pocketsphinx is installed.
RECOGNIZER_BACKEND = "google"  # "google" | "sphinx"


class VoicePipeline:
    # Class-level (shared across every VoicePipeline instance and thread) -
    # pyttsx3's Windows SAPI5 backend is not safe to run from two threads at
    # once, even with separate engine instances. Observed 2026-08-20: the
    # voice loop's background thread was still mid-speak() when the Pause
    # button fired a second speak() call on its own thread; the second
    # engine.runAndWait() crashed with "RuntimeError: run loop already
    # started" and the Pause announcement was silently lost. This lock
    # forces every speak() call in the whole app to run one at a time -
    # a second caller just waits its turn instead of colliding.
    _speak_lock = threading.Lock()

    def __init__(self):
        self.recognizer = sr.Recognizer()
        self.microphone = sr.Microphone()

        # Calibrate for ambient noise once at startup
        with self.microphone as source:
            logger.info("Calibrating microphone for ambient noise...")
            self.recognizer.adjust_for_ambient_noise(source, duration=1)

    def listen(self, timeout: float = 5.0, phrase_time_limit: float = 8.0) -> str:
        """
        Blocks until a phrase is captured (or timeout), returns transcribed text.
        Raises sr.WaitTimeoutError / sr.UnknownValueError / sr.RequestError on failure -
        callers should catch these and handle gracefully (e.g. re-prompt user).
        """
        with self.microphone as source:
            logger.info("Listening...")
            audio = self.recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_time_limit)

        logger.info("Transcribing...")
        if RECOGNIZER_BACKEND == "sphinx":
            text = self.recognizer.recognize_sphinx(audio)
        else:
            text = self.recognizer.recognize_google(audio)

        logger.info("Transcribed text: %s", text)
        return text

    def speak(self, text: str):
        """
        Synthesize and play spoken confirmation.
        Re-initializes the TTS engine on every call - pyttsx3's SAPI5 backend
        on Windows unreliably stops producing audio after the first
        runAndWait() if the engine instance is reused across multiple calls.
        Serialized via _speak_lock so concurrent callers (voice loop thread
        vs. Pause/Resume button thread) queue instead of crashing each other.
        """
        with self._speak_lock:
            logger.info("Speaking: %s", text)
            engine = pyttsx3.init()
            engine.setProperty("rate", 175)
            engine.say(text)
            engine.runAndWait()
            engine.stop()


if __name__ == "__main__":
    # Quick manual test: python voice_pipeline.py
    logging.basicConfig(level=logging.INFO)
    pipeline = VoicePipeline()
    pipeline.speak("Voice pipeline ready. Say something.")
    try:
        heard = pipeline.listen()
        print("You said:", heard)
        pipeline.speak(f"You said: {heard}")
    except Exception as e:
        print("Error:", e)