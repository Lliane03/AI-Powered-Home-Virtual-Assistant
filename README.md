# AI-Powered Home Virtual Assistant

Comprehensive technical documentation for the AI-Powered Home Virtual Assistant prototype. This project is an offline, privacy-first smart home hub prototype that captures voice commands locally, parses natural-language intent with a locally hosted LLM (Ollama + Qwen), updates a simulated smart-home GUI, and provides spoken confirmations — with no cloud dependency.

Built as a Prelim Mini-Project for **BSCS 3112 (9420-AY126) Artificial Intelligence**.

Team:
- De Dios, Louise Jeanne T.
- Mangubat, Angel Julliane I.

---

**Contents**
- Overview
- Features
- Architecture & data flow
- Project layout
- Requirements
- Installation & configuration
- Usage
- JSON action schema
- Module reference
- Development notes
- Troubleshooting
- License & Academic Use

## Overview

This prototype demonstrates an end-to-end offline voice-controlled smart home assistant. It combines local speech-to-text (STT), a locally hosted LLM for intent parsing, a simple state machine driving a GUI simulator, and local text-to-speech (TTS) feedback. The focus is on privacy, reproducibility, and a clear separation between sensing, reasoning, and actuation.

## Features

- Offline-first voice interaction (STT/TTS run locally; intent parsing runs against a locally hosted LLM).
- Intent parsing via Ollama-hosted Qwen model (`qwen2.5:1.5b`, pulled locally).
- Structured JSON actions emitted by the LLM and validated with `pydantic` for deterministic handling.
- Canvas-drawn GUI dashboard (bulb, lock, thermostat dial, TV icons) that visualizes device state changes in real time.
- Pause/Resume Listening control and a live "listening" status indicator.
- Recent-commands history panel showing the last few heard commands and their responses.
- TTS confirmation for user feedback.

## Architecture & data flow

High-level flow:

```
Mic Input → STT (voice_pipeline.py) → Text
Text → LLM via Ollama (ai_engine.py) → Structured JSON Action
Structured JSON Action → State Machine + GUI (home_simulator.py) → Visual Update
Structured JSON Action → TTS (voice_pipeline.py) → Spoken Confirmation
```

Important responsibilities by layer:
- Perception: [src/voice_pipeline.py](src/voice_pipeline.py) — captures microphone input, performs STT, and plays TTS.
- Reasoning: [src/ai_engine.py](src/ai_engine.py) — forwards transcribed text to the local LLM and maps responses to a predictable JSON action schema.
- Actuation & UI: [src/home_simulator.py](src/home_simulator.py) — maintains the simulated device state and renders the GUI.
- Integration: [src/main.py](src/main.py) — bootstraps components, runs the application event loop, and wires the Pause/Resume control to the voice loop.

## Project layout

Repository structure (top-level):

```text
AI-Powered-Home-Virtual-Assistant/
├─ README.md
├─ requirements.txt
├─ .gitignore
├─ logs/
│  └─ assistant_execution.log      (generated at runtime, gitignored)
└─ src/
   ├─ main.py
   ├─ voice_pipeline.py
   ├─ ai_engine.py
   └─ home_simulator.py
```

Mapping of files:

- [README.md](README.md) — Project documentation and usage notes.
- [requirements.txt](requirements.txt) — Python dependencies.
- `logs/assistant_execution.log` — Runtime log, auto-created by `main.py` on first run (gitignored — will not appear until you run the app locally).
- [src/main.py](src/main.py) — Application entry point and orchestration.
- [src/voice_pipeline.py](src/voice_pipeline.py) — STT/TTS helpers and audio I/O.
- [src/ai_engine.py](src/ai_engine.py) — LLM communication and intent → JSON conversion.
- [src/home_simulator.py](src/home_simulator.py) — State machine and GUI implementation.

## Requirements

- Python 3.10 or newer (tested on 3.12; PyAudio may lack prebuilt wheels on very new Python versions — see Troubleshooting)
- Ollama installed and running locally (see https://ollama.com/download)
- The `qwen2.5:1.5b` model pulled locally via Ollama
- Microphone access and audio playback (PyAudio or equivalent)
- `tkinter` for the GUI (bundled on most platforms)

Suggested development environment:

- Create and use a virtual environment (venv or similar).

## Installation & configuration

1. Clone the repository and create a virtual environment:

```bash
git clone <repo-url>
cd AI-Powered-Home-Virtual-Assistant
python -m venv venv
# Windows
venv\Scripts\activate
# macOS / Linux
source venv/bin/activate
pip install -r requirements.txt
```

2. Install and run Ollama locally, then pull the model this project uses:

```bash
# Install Ollama (see https://ollama.com/download)
ollama pull qwen2.5:1.5b
```

3. Optional: If `pyaudio` fails to install on Windows, first try:

```bash
pip install pipwin
pipwin install pyaudio
```

If `pipwin` itself fails (common on very new Python versions), install the Microsoft C++ Build Tools ("Desktop development with C++" workload) from https://visualstudio.microsoft.com/visual-cpp-build-tools/ and re-run `pip install pyaudio`, or use an older Python version (3.11/3.12) for the virtual environment instead.

4. Model configuration

The Ollama model name is currently set directly in code (`MODEL_NAME = "qwen2.5:1.5b"` in [src/ai_engine.py](src/ai_engine.py)) and the app connects to Ollama's default local endpoint. There are no environment variables to set — as long as Ollama is running locally with the model pulled, the app will connect automatically.

## Usage

Start the application:

```bash
python src/main.py
```

Speak a command when prompted. Example utterances:

- "Set the living room thermostat to 22 degrees and turn off the kitchen lights."
- "It's getting dark in here and I'm freezing."
- "Turn on the TV and kitchen lights."
- "Lock the front door."

Expected runtime behavior:

1. STT prints the transcribed text to console.
2. `src/ai_engine.py` sends the text to Ollama and parses the response into a validated JSON action list.
3. `src/home_simulator.py` applies the actions to the simulated device state and updates the GUI (icons, thermostat dial, history panel).
4. TTS speaks a confirmation aloud.

Use the **Pause Listening** button on the dashboard to stop the microphone without closing the app; click **Resume Listening** to continue.

## JSON action schema

The LLM is prompted to return a JSON object matching this exact shape, validated with `pydantic` in [src/ai_engine.py](src/ai_engine.py):

```python
class DeviceAction(BaseModel):
    action: Literal["turn_on", "turn_off", "set_temperature",
                     "increase_temp", "decrease_temp", "lock", "unlock"]
    target: Literal["living_room_light", "kitchen_light", "bedroom_light",
                     "thermostat", "front_door_lock", "tv"]
    value: Optional[float] = None  # used by set_temperature / increase_temp / decrease_temp

class AssistantResponse(BaseModel):
    actions: List[DeviceAction]
    response_text: str  # spoken back via TTS
```

Example — command: *"turn on the tv and kitchen lights"*:

```json
{
  "actions": [
    {"action": "turn_on", "target": "tv", "value": null},
    {"action": "turn_on", "target": "kitchen_light", "value": null}
  ],
  "response_text": "The TV and kitchen lights have been turned on."
}
```

Responses that don't match this schema are rejected by `pydantic` validation and logged as parse errors rather than silently applied.

## Module reference

- `src/voice_pipeline.py` — Contains:
  - Microphone calibration and audio capture.
  - Speech-to-text via `SpeechRecognition` (Google Web Speech API by default — requires internet; can be swapped to an offline backend such as `pocketsphinx`).
  - Text-to-speech via `pyttsx3`, re-initializing the engine on every call for reliability on Windows.

- `src/ai_engine.py` — Responsible for:
  - Sending transcribed text to the local Ollama API with a system prompt instructing JSON-only output.
  - Stripping stray formatting (e.g. code fences) from the model's response.
  - Validating and normalizing model responses into the `AssistantResponse` schema above.

- `src/home_simulator.py` — Implements:
  - A minimal state model for devices (lights, thermostat, lock, TV).
  - A `tkinter`-based GUI with Canvas-drawn device icons, a thermostat dial, a listening indicator, a Pause/Resume control, and a command history panel.
  - APIs for applying validated `DeviceAction` objects to the simulator's state.

- `src/main.py` — Bootstraps the system: creates the GUI on the main thread, runs the voice loop on a background thread, and coordinates state via a `threading.Event` for pause/resume.

## Development notes

- Logging: runtime events (transcriptions, parsed JSON, state changes, latency) are always written to `logs/assistant_execution.log` on every run, and also printed to the console.
- Tests: There are no automated unit tests included. For development, consider adding small unit tests around the JSON validation in `src/ai_engine.py`.
- Extensibility: Add new device types by extending the `Literal` target list and `DEFAULT_STATE` in `src/ai_engine.py` / `src/home_simulator.py`, and adding a matching icon-drawing method.

## Troubleshooting

- No audio input / STT fails:
  - Verify microphone permissions and availability for your OS.
  - On Windows, ensure the correct audio input device is selected as default.

- `PyAudio` fails to build during `pip install`:
  - This usually means no prebuilt wheel exists for your Python version. Try `pipwin install pyaudio`, or use a Python 3.11/3.12 virtual environment instead of a very new release, or install the Microsoft C++ Build Tools so pip can compile it locally.

- TTS only speaks once, then goes silent on later commands:
  - Known `pyttsx3`/Windows SAPI5 issue. `voice_pipeline.py` works around this by creating a fresh TTS engine instance on every `speak()` call.

- Ollama connection errors:
  - Confirm the Ollama app/daemon is running and `ollama pull qwen2.5:1.5b` has completed.
  - Test directly with `ollama run qwen2.5:1.5b` in a terminal.

- Poor or inconsistent JSON from the LLM (e.g. mismatched action/target pairs):
  - Improve the prompt template in [src/ai_engine.py](src/ai_engine.py) to be more prescriptive, or add stricter `pydantic` validation rejecting nonsensical action/target combinations.

## License & Academic Use

This repository is an academic prototype for student work; it is not intended for commercial use. Use it as a learning artifact and adapt the code with attribution if reusing substantial parts.