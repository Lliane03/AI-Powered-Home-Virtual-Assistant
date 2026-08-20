# AI-Powered Home Virtual Assistant

A comprehensive technical documentation for the AI-Powered Home Virtual Assistant prototype. This project is an offline, privacy-first smart home hub prototype that captures voice commands locally, parses natural-language intent with a locally hosted LLM (Ollama + Qwen), updates a simulated smart-home GUI, and provides spoken confirmations — with no cloud dependency for the reasoning step.

Built as a Prelim Mini-Project for **BSCS 3112 (9420-AY126) Artificial Intelligence**.

**Repository:** https://github.com/Lliane03/AI-Powered-Home-Virtual-Assistant

Team:
- De Dios, Louise Jeanne T.
- Mangubat, Angel Julliane I.

---

**Contents**
- Overview
- Features
- System architecture & data flow
- Project layout
- Requirements
- Installation & configuration
- Usage
- JSON action schema
- Module reference
- Resource monitoring
- GUI design — "Home OS" HUD theme
- Troubleshooting
- License & Academic Use

## Overview

This prototype demonstrates an end-to-end offline voice-controlled smart home assistant. A person speaks a command; the system transcribes it locally, sends the text to a **locally hosted LLM (Qwen 2.5 1.5B, via Ollama)** for intent parsing, converts the model's response into a validated structured action, applies that action to a simulated smart-home state machine, updates a live GUI dashboard, and speaks a confirmation back. The focus is on privacy, reproducibility, and a clear separation between sensing, reasoning, and actuation.

The project satisfies four required modules:

| # | Module | File | Responsibility |
|---|--------|------|-----------------|
| 1 | Speech-to-Text | `src/voice_pipeline.py` | Capture mic audio, transcribe to text |
| 2 | AI Intent Extraction | `src/ai_engine.py` | Turn text into a structured JSON action via Qwen |
| 3 | GUI Simulation | `src/home_simulator.py` | Hold device state, render the dashboard |
| 4 | Text-to-Speech | `src/voice_pipeline.py` | Speak a natural-language confirmation |

`src/main.py` is the integration layer that wires all four together and keeps the GUI responsive while the voice loop runs on a background thread.

## Features

- Offline-first voice interaction (STT/TTS run locally; intent parsing runs against a locally hosted LLM).
- Intent parsing via Ollama-hosted Qwen model (`qwen2.5:1.5b`, pulled locally).
- Structured JSON actions emitted by the LLM and validated with `pydantic` for deterministic handling.
- Canvas-drawn GUI dashboard (bulb, lock, thermostat dial, TV icons) that visualizes device state changes in real time.
- Pause/Resume Listening control and a live "listening" status indicator.
- Recent-commands history panel showing the last few heard commands and their responses.
- TTS confirmation for user feedback.

## System architecture & data flow

High-level flow:

```
Mic Input → STT (voice_pipeline.py) → Text
Text → LLM via Ollama (ai_engine.py) → Structured JSON Action
Structured JSON Action → State Machine + GUI (home_simulator.py) → Visual Update
Structured JSON Action → TTS (voice_pipeline.py) → Spoken Confirmation
```

In more detail:

```
                    ┌─────────────────────────┐
                    │        Microphone       │
                    └────────────┬────────────┘
                                 │ raw audio
                                 ▼
                 ┌───────────────────────────────┐
                 │   voice_pipeline.py — STT     │
                 │   (SpeechRecognition/Google)  │
                 └───────────────┬───────────────┘
                                 │ transcribed text
                                 ▼
                 ┌───────────────────────────────┐
                 │ ai_engine.py — Intent Engine  │
                 │   Ollama + Qwen2.5:1.5b       │
                 │ → validated DeviceAction JSON │
                 └───────────────┬───────────────┘
                                 │ AssistantResponse
                                 ▼
                 ┌─────────────────────────────────┐
                 │ home_simulator.py — State + GUI │
                 │  applies actions, redraws HUD   │
                 └───────────────┬─────────────────┘
                                 │ response_text
                                 ▼
                 ┌──────────────────────────────────┐
                 │   voice_pipeline.py — TTS        │
                 │   (pyttsx3, fresh engine/call)   │
                 └──────────────────────────────────┘
```

`main.py` runs the Tkinter GUI on the main thread and the listen → parse → apply → speak loop on a daemon background thread, using `root.after(...)` to push every GUI mutation back onto the main thread (Tkinter is not thread-safe). A `threading.Event` links the dashboard's Pause/Resume button to the voice loop so the microphone can be paused without closing the app.

Important responsibilities by layer:
- **Perception:** [src/voice_pipeline.py](src/voice_pipeline.py) — captures microphone input, performs STT, and plays TTS.
- **Reasoning:** [src/ai_engine.py](src/ai_engine.py) — forwards transcribed text to the local LLM and maps responses to a predictable JSON action schema.
- **Actuation & UI:** [src/home_simulator.py](src/home_simulator.py) — maintains the simulated device state and renders the GUI.
- **Integration:** [src/main.py](src/main.py) — bootstraps components, runs the application event loop, and wires the Pause/Resume control to the voice loop.

## Project layout

Repository structure (top-level):

```text
AI-Powered-Home-Virtual-Assistant/
├─ README.md
├─ requirements.txt
├─ .gitignore
└─ src/
   ├─ main.py
   ├─ voice_pipeline.py
   ├─ ai_engine.py
   ├─ home_simulator.py
   └─ monitor_resources.py
```

`logs/assistant_execution.log` and `src/resource_log.csv` are both generated at runtime by `main.py` on first run and are not part of the repository — they won't exist until you run the app locally.

Mapping of files:

- [README.md](README.md) — Project documentation and usage notes.
- [requirements.txt](requirements.txt) — Python dependencies.
- [src/main.py](src/main.py) — Application entry point and orchestration.
- [src/voice_pipeline.py](src/voice_pipeline.py) — STT/TTS helpers and audio I/O.
- [src/ai_engine.py](src/ai_engine.py) — LLM communication and intent → JSON conversion.
- [src/home_simulator.py](src/home_simulator.py) — State machine and GUI implementation.
- [src/monitor_resources.py](src/monitor_resources.py) — Self-sampling CPU/RAM tracker used around each voice command.

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

You can also run individual modules for isolated testing:

```powershell
python src/ai_engine.py       # test intent parsing only, no mic needed
python src/voice_pipeline.py  # test mic + TTS round-trip
python src/main.py            # run the full assistant
```

Speak a command when prompted. Example utterances:

- "Set the thermostat to 25 degrees."
- "Turn on the TV and bedroom light."
- "Turn on the lights."
- "Unlock the front door."

Expected runtime behavior:

1. STT prints the transcribed text to console.
2. `src/ai_engine.py` sends the text to Ollama and parses the response into a validated JSON action list.
3. `src/home_simulator.py` applies the actions to the simulated device state and updates the GUI (icons, thermostat dial, history panel).
4. TTS speaks a confirmation aloud.

Use the **Pause Listening** button on the dashboard to stop the microphone without closing the app; click **Resume Listening** to continue.

## JSON action schema

`ai_engine.py` defines the schema; `home_simulator.py` consumes it. Keeping this in one place is what lets the LLM's free-form output become a deterministic state change. The LLM is prompted to return a JSON object matching this exact shape, validated with `pydantic`:

```python
class DeviceAction(BaseModel):
    action: Literal["turn_on", "turn_off", "set_temperature", "lock", "unlock"]
    target: Literal["living_room_light", "kitchen_light", "bedroom_light", "thermostat", "front_door_lock", "tv"]
    value: Optional[float] = None  # used by set_temperature

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

Any response that fails `pydantic` validation is rejected and logged rather than silently applied — this is what keeps a hallucinated field from ever reaching the GUI's state machine.

`DeviceAction` also carries a `model_validator` that does more than check each field in isolation. `action` and `target` are each valid Literal values on their own, but the pairing between them can still be nonsensical (e.g. `set_temperature` on a light), so the validator:

- **Rejects mismatched action/target pairs** — temperature actions (`set_temperature`) are only valid on `thermostat`; `lock`/`unlock` are only valid on `front_door_lock`; `turn_on`/`turn_off` are rejected on `thermostat` (it has no on/off state).
- **Enforces the thermostat's 7–35°C range** on `set_temperature`, rejecting out-of-range values instead of letting them reach the GUI.
- **Normalizes door phrasing** — "turn on the front door" is remapped to `lock`, and "turn off the front door" to `unlock`, since that's what casual speech almost always means, rather than rejecting it.


Invalid individual actions don't take down the rest of the command — `ai_engine.py` validates each action in the model's response independently, keeps the valid ones, and surfaces a warning message for anything rejected (e.g. an out-of-range temperature).

The spoken `response_text` is no longer the model's own sentence. Qwen's free-form confirmation repeatedly described actions that had been filtered out or rejected, so `ai_engine.py` now builds the confirmation directly from the final, validated action list — it can't describe something that didn't actually happen.

`parse_command()` also abstains from calling the model entirely for inputs it can resolve deterministically and more reliably than Qwen: greetings ("hi", "hello"), incomplete/dangling commands ("turn on the"), and thermostat status queries ("thermostat" → reports the current temperature). This also avoids the ~10s Qwen inference cost for those cases.

## Module reference

- **`src/voice_pipeline.py`** — Contains:
  - Microphone calibration and audio capture.
  - Speech-to-text via `SpeechRecognition` (Google Web Speech API by default — requires internet; can be swapped to an offline backend such as `pocketsphinx`).
  - Text-to-speech via `pyttsx3`, re-initializing the engine on every call for reliability on Windows.

- **`src/ai_engine.py`** — Responsible for:
  - Sending transcribed text to the local Ollama API with a system prompt instructing JSON-only output.
  - Stripping stray formatting (e.g. code fences) from the model's response.
  - Validating and normalizing model responses into the `AssistantResponse` schema above, including a `pydantic` `model_validator` that catches action/target mismatches, normalizes door phrasing ("turn on the front door" → `lock`), and enforces the thermostat's 7–35°C range (see JSON action schema).
  - Building the spoken confirmation from the final, validated action list rather than trusting the model's own sentence.
  - Abstaining from calling the model at all for greetings, incomplete/dangling commands, and thermostat status queries.

- **`src/home_simulator.py`** — Implements:
  - A minimal state model for devices (lights, thermostat, lock, TV).
  - A `tkinter`-based GUI with Canvas-drawn device icons, a thermostat dial, a listening indicator, a Pause/Resume control, and a command history panel.
  - APIs for applying validated `DeviceAction` objects to the simulator's state.

- **`src/main.py`** — Bootstraps the system: creates the GUI on the main thread, runs the voice loop on a background thread, and coordinates state via a `threading.Event` for pause/resume. Wraps each command in `monitor_resources.py`'s `ResourceTracker` to log peak CPU/RAM (see Resource monitoring).

## Resource monitoring

`src/monitor_resources.py` provides `ResourceTracker`, which measures the real peak CPU% and RAM used while a voice command is processed. This is what `requirements.txt`'s `psutil` dependency is for.

It's wired into `main.py`'s voice loop: `ResourceTracker.start()` is called right before a command begins processing, and `.stop(label)` right after it finishes (or `.cancel()` if the command failed — e.g. an STT timeout or parse error — so `resource_log.csv` only ever contains real, completed commands). While running, it background-samples `psutil.Process()` — the current process, self-referentially, with no PID lookup involved — at a fixed interval, tracks the peak CPU% and RSS memory observed, and on `.stop()` appends a labeled row (`label`, `peak_cpu_percent`, `peak_ram_mb`, `duration_s`) to `src/resource_log.csv`.

Sampling the current process directly (rather than an externally-supplied PID) is a deliberate fix: on Windows, `venv\Scripts\python.exe` can behave as a thin launcher, so external PID sampling risked measuring an idle stub process instead of the real interpreter running `main.py` — the likely cause of flat 0.0% CPU / 4.1 MB RAM readings seen with the original approach.

`monitor_resources.py` can also be run standalone for ad-hoc testing against an external PID (`python monitor_resources.py <PID> --label "..." --duration 10`), but this legacy path is only useful for testing the file itself — real end-to-end measurements should go through `ResourceTracker` inside `main.py`'s voice loop.

## GUI design — "Home OS" HUD theme

The dashboard was designed around a dark, holographic heads-up-display aesthetic (the kind of glowing, instrument-panel look associated with a fictional AI-butler operating system), built entirely with Tkinter's `Canvas` primitives — no image assets or extra dependencies required.

**Design language:**
- **Palette:** near-black chassis (`#03080B`) with a single cyan accent (`#3CE8FF`) for "energized/active" state, amber for paused, red reserved only for an unlocked door (the one state that should read as an alert).
- **Typography:** monospace (Consolas), uppercase, loosely letter-spaced — reads as instrument-panel labeling rather than app UI.
- **Panels:** each device is a single `Canvas` drawing its own bracketed HUD frame (corner brackets + faint scanline texture) so the border glows cyan only when that specific device is active/on.
- **Status core:** the old plain colored dot was replaced with a small reactor-style indicator — a pulsing core inside a rotating four-segment ring while listening, solid amber while paused, dim while idle.
- **Icons:** bulb, padlock, thermostat dial, and TV are all redrawn as outline/glow strokes on the same palette instead of flat filled shapes, so every card looks like part of one instrument panel rather than separate colored widgets.

**Compatibility:** the public `HomeSimulator` API is unchanged (`__init__(root, on_toggle_pause)`, `.root`, `.set_status()`, `.set_listening_active()`, `.add_history_entry()`, `.apply_action(s)`), so `main.py` required no changes.

## Troubleshooting

- **No audio input / STT fails:**
  - Verify microphone permissions and availability for your OS.
  - On Windows, ensure the correct audio input device is selected as default.

- **`PyAudio` fails to build during `pip install`:**
  - This usually means no prebuilt wheel exists for your Python version. Try `pipwin install pyaudio`, or use a Python 3.11/3.12 virtual environment instead of a very new release, or install the Microsoft C++ Build Tools so pip can compile it locally.

- **TTS only speaks once, then goes silent on later commands:**
  - Known `pyttsx3`/Windows SAPI5 issue. `voice_pipeline.py` works around this by creating a fresh TTS engine instance on every `speak()` call.

- **Ollama connection errors:**
  - Confirm the Ollama app/daemon is running and `ollama pull qwen2.5:1.5b` has completed.
  - Test directly with `ollama run qwen2.5:1.5b` in a terminal.

- **Poor or inconsistent JSON from the LLM (e.g. mismatched action/target pairs):**
  - Improve the prompt template in [src/ai_engine.py](src/ai_engine.py) to be more prescriptive, or add stricter `pydantic` validation rejecting nonsensical action/target combinations.

## License & Academic Use

This repository is an academic prototype for student work; it is not intended for commercial use.

**Last Updated:** August 20, 2026