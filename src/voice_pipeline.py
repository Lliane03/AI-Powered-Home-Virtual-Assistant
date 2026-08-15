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

import pyttsx3
import speech_recognition as sr

logger = logging.getLogger("assistant")

# Swap this to "sphinx" for fully offline recognition if pocketsphinx is installed.
RECOGNIZER_BACKEND = "google"  # "google" | "sphinx"


class VoicePipeline:
    def __init__(self):
        self.recognizer = sr.Recognizer()
        self.microphone = sr.Microphone()
        self.tts_engine = pyttsx3.init()
        self.tts_engine.setProperty("rate", 175)

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
        """Synthesize and play spoken confirmation."""
        logger.info("Speaking: %s", text)
        self.tts_engine.say(text)
        self.tts_engine.runAndWait()


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