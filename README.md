# AI-Powered Home Virtual Assistant

Comprehensive technical documentation for the AI-Powered Home Virtual Assistant prototype. This project is an offline, privacy-first smart home hub prototype that captures voice commands locally, parses natural-language intent with a locally hosted LLM (Ollama + Qwen), updates a simulated smart-home GUI, and provides spoken confirmations — with no cloud dependency.

Built as a Prelim Mini-Project for **BSCS 3112 (9420-AY126) Artificial Intelligence**.

Team:
- De Dios, Louise Jeanne T.
- Mangubat, Angel Julliane I.

--

**Contents**
- Overview
- Features
- Architecture & data flow
- Project layout
- Requirements
- Installation & configuration
- Usage
- Module reference
- Development notes
- Troubleshooting
- Contributing & license

## Overview

This prototype demonstrates an end-to-end offline voice-controlled smart home assistant. It combines local speech-to-text (STT), a locally hosted LLM for intent parsing, a simple state machine driving a GUI simulator, and local text-to-speech (TTS) feedback. The focus is on privacy, reproducibility, and a clear separation between sensing, reasoning, and actuation.

## Features

- Offline-first voice interaction (no cloud services required).
- Intent parsing via Ollama-hosted Qwen model (model pulled locally).
- Structured JSON actions emitted by the LLM for deterministic handling.
- GUI simulator that visualizes device state changes in real time.
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
- Integration: [src/main.py](src/main.py) — bootstraps components and runs the application event loop.

## Project layout

Repository structure (top-level):

```text
AI-Powered-Home-Virtual-Assistant/
├─ README.md
├─ requirements.txt
├─ logs/
│  └─ assistant_execution.log
└─ src/
  ├─ main.py
  ├─ voice_pipeline.py
  ├─ ai_engine.py
  └─ home_simulator.py
```

Mapping of files:

- [README.md](README.md) — Project documentation and usage notes.
- [requirements.txt](requirements.txt) — Python dependencies.
- [logs/assistant_execution.log](logs/assistant_execution.log) — Runtime log (gitignored).
- [src/main.py](src/main.py) — Application entry point and orchestration.
- [src/voice_pipeline.py](src/voice_pipeline.py) — STT/TTS helpers and audio I/O.
- [src/ai_engine.py](src/ai_engine.py) — LLM communication and intent → JSON conversion.
- [src/home_simulator.py](src/home_simulator.py) — State machine and GUI implementation.

## Requirements

- Python 3.10 or newer
- Ollama installed and running locally (see https://ollama.com/download)
- A locally pulled model (example: `qwen2.5:1.5b`) available to Ollama
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

2. Install and run Ollama locally, then pull the recommended model:

```bash
# Install Ollama (see https://ollama.com/download)
ollama pull qwen2.5:1.5b
```

3. Optional: If `pyaudio` fails to install on Windows, use `pipwin`:

```bash
pip install pipwin
pipwin install pyaudio
```

4. Configuration (environment variables)

The code expects to contact a local Ollama instance. You can configure the host and model used by exporting or setting environment variables before launching the app. Example (bash):

```bash
export OLLAMA_HOST=http://127.0.0.1:11434
export OLLAMA_MODEL=qwen2.5:1.5b
# Windows PowerShell
$env:OLLAMA_HOST = 'http://127.0.0.1:11434'
$env:OLLAMA_MODEL = 'qwen2.5:1.5b'
```

If you don't set these, the app will attempt sensible defaults; check [src/ai_engine.py](src/ai_engine.py) for exact resolution logic.

## Usage

Start the application:

```bash
python src/main.py
```

Speak a command when prompted. Example utterances:

- "Hey Sophia, set the living room thermostat to 22 degrees." 
- "Turn off the kitchen lights." 
- "Lock the front door." 

Expected runtime behavior:

1. STT prints the transcribed text to console.
2. `src/ai_engine.py` sends the text to Ollama and parses the response into a JSON action.
3. `src/home_simulator.py` applies the action to the simulated device state and updates the GUI.
4. TTS provides a spoken confirmation.

## JSON action schema (examples)

The LLM should return a compact, deterministic JSON structure describing the desired action. Example shapes:

Single-device action:

```json
{
  "action": "set_thermostat",
  "target": "living_room",
  "value": 22,
  "units": "celsius",
  "confidence": 0.97
}
```

Multi-action batch (optional):

```json
[
  {"action":"turn_off","target":"kitchen_lights"},
  {"action":"lock","target":"front_door"}
]
```

Standardizing responses reduces downstream parsing complexity — see [src/ai_engine.py](src/ai_engine.py) for the normalization rules currently implemented.

## Module reference

- `src/voice_pipeline.py` — Contains functions for:
  - Capturing microphone audio and producing transcriptions (STT).
  - Playing TTS audio for confirmations.
  - Utility wrappers around the selected STT/TTS libraries.

- `src/ai_engine.py` — Responsible for:
  - Sending text prompts to the local Ollama API.
  - Applying prompt templates that instruct the LLM to produce structured JSON output.
  - Validating and normalizing model responses into the canonical action schema.

- `src/home_simulator.py` — Implements:
  - A minimal state model for devices (lights, thermostat, locks, etc.).
  - A `tkinter`-based GUI visualizing device states in real time.
  - APIs for applying JSON actions to the simulator.

- `src/main.py` — Bootstraps the system and wires the components together. It handles the event loop that receives transcriptions, forwards them to the `ai_engine`, and dispatches actions to the simulator and TTS.

## Development notes

- Logging: runtime events are appended to `logs/assistant_execution.log` when enabled.
- Tests: There are no unit tests included by default. For development, consider adding small unit tests around the JSON normalization in `src/ai_engine.py`.
- Extensibility: Add new device types by extending the simulator's state machine and updating the normalization layer that maps LLM intents to actions.

## Troubleshooting

- No audio input / STT fails:
  - Verify microphone permissions and availability.
  - On Windows, ensure the correct audio device is selected.

- Ollama connection errors:
  - Confirm Ollama is running locally and the model is pulled.
  - Check `OLLAMA_HOST` and `OLLAMA_MODEL` environment variables.

- Poor or inconsistent JSON from the LLM:
  - Improve the prompt template in [src/ai_engine.py](src/ai_engine.py) to be more prescriptive (use examples and explicit JSON-only instructions).

## Contributing

If you'd like to contribute:

1. Fork the repository and create a branch for your change.
2. Keep edits focused and small; update or add unit tests where applicable.
3. Open a pull request describing the change and rationale.

## License & Academic Use

This repository is an academic prototype for student work; it is not intended for commercial use. Use it as a learning artifact and adapt the code with attribution if reusing substantial parts.

---

If you'd like, I can also:
- Add a quick-start script that automates environment setup and model pull.
- Create a small JSON schema file and a validation function for actions in [src/ai_engine.py](src/ai_engine.py).
- Add example utterances and a short demo script that runs a series of commands against the simulator.

Tell me which of the above you'd like next.
