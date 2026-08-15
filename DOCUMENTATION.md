# Project Documentation — AI-Powered Home Virtual Assistant

**Course:** BSCS 3112 (9420-AY126) Artificial Intelligence — Prelim Mini-Project
**Team:** Mangubat, Angel Julliane I. · De Dios, Louise Jeanne T. (LJ)
**Repository:** https://github.com/Lliane03/AI-Powered-Home-Virtual-Assistant
**Due:** August 21, 2026

This document is the technical reference for the project: what it does, how
the pieces fit together, how to run it, and what to check before submission.
It complements (does not replace) the 3-page academic report deliverable.

---

## 1. Overview

The AI-Powered Home Virtual Assistant is an offline, privacy-first smart-home
prototype. A person speaks a command; the system transcribes it locally,
sends the text to a **locally hosted LLM (Qwen 2.5 1.5B, via Ollama)** for
intent parsing, converts the model's response into a validated structured
action, applies that action to a simulated smart-home state machine, updates
a live GUI dashboard, and speaks a confirmation back — with no cloud
dependency for the reasoning step.

The project satisfies four required modules:

| # | Module | File | Responsibility |
|---|--------|------|-----------------|
| 1 | Speech-to-Text | `src/voice_pipeline.py` | Capture mic audio, transcribe to text |
| 2 | AI Intent Extraction | `src/ai_engine.py` | Turn text into a structured JSON action via Qwen |
| 3 | GUI Simulation | `src/home_simulator.py` | Hold device state, render the dashboard |
| 4 | Text-to-Speech | `src/voice_pipeline.py` | Speak a natural-language confirmation |

`src/main.py` is the integration layer that wires all four together and
keeps the GUI responsive while the voice loop runs on a background thread.

---

## 2. System Architecture

```
                    ┌─────────────────────────┐
                    │        Microphone         │
                    └────────────┬─────────────┘
                                 │ raw audio
                                 ▼
                 ┌───────────────────────────────┐
                 │   voice_pipeline.py — STT       │
                 │   (SpeechRecognition/Google)     │
                 └────────────┬──────────────────┘
                                 │ transcribed text
                                 ▼
                 ┌───────────────────────────────┐
                 │   ai_engine.py — Intent Engine   │
                 │   Ollama + Qwen2.5:1.5b           │
                 │   → validated DeviceAction JSON   │
                 └────────────┬──────────────────┘
                                 │ AssistantResponse
                                 ▼
                 ┌───────────────────────────────┐
                 │ home_simulator.py — State + GUI  │
                 │  applies actions, redraws HUD    │
                 └────────────┬──────────────────┘
                                 │ response_text
                                 ▼
                 ┌───────────────────────────────┐
                 │   voice_pipeline.py — TTS        │
                 │   (pyttsx3, fresh engine/call)   │
                 └───────────────────────────────┘
```

`main.py` runs the Tkinter GUI on the main thread and the
listen → parse → apply → speak loop on a daemon background thread, using
`root.after(...)` to push every GUI mutation back onto the main thread
(Tkinter is not thread-safe). A `threading.Event` links the dashboard's
Pause/Resume button to the voice loop so the microphone can be paused
without closing the app.

---

## 3. Repository Layout

```
AI-Powered-Home-Virtual-Assistant/
├─ README.md              # setup/usage reference
├─ DOCUMENTATION.md        # this file
├─ requirements.txt
├─ .gitignore
├─ logs/
│  └─ assistant_execution.log   (generated at runtime, gitignored)
└─ src/
   ├─ main.py              # entry point, event loop, pause/resume wiring
   ├─ voice_pipeline.py     # STT + TTS
   ├─ ai_engine.py           # Ollama/Qwen prompt + pydantic schema
   └─ home_simulator.py     # state machine + GUI dashboard
```

---

## 4. Shared JSON Contract

`ai_engine.py` defines the schema; `home_simulator.py` consumes it. Keeping
this in one place is what lets the LLM's free-form output become a
deterministic state change.

```python
class DeviceAction(BaseModel):
    action: Literal["turn_on", "turn_off", "set_temperature",
                     "increase_temp", "decrease_temp", "lock", "unlock"]
    target: Literal["living_room_light", "kitchen_light", "bedroom_light",
                     "thermostat", "front_door_lock", "tv"]
    value: Optional[float] = None

class AssistantResponse(BaseModel):
    actions: List[DeviceAction]
    response_text: str
```

Example — command *"turn on the tv and kitchen lights"*:

```json
{
  "actions": [
    {"action": "turn_on", "target": "tv", "value": null},
    {"action": "turn_on", "target": "kitchen_light", "value": null}
  ],
  "response_text": "The TV and kitchen lights have been turned on."
}
```

Any response that fails `pydantic` validation is rejected and logged rather
than silently applied — this is what keeps a hallucinated field from ever
reaching the GUI's state machine.

---

## 5. GUI Design — "Home OS" HUD Theme

The dashboard was redesigned around a dark, holographic heads-up-display
aesthetic (the kind of glowing, instrument-panel look associated with a
fictional AI-butler operating system), built entirely with Tkinter's
`Canvas` primitives — no image assets or extra dependencies required.

**Design language:**
- **Palette:** near-black chassis (`#03080B`) with a single cyan accent
  (`#3CE8FF`) for "energized/active" state, amber for paused, red reserved
  only for an unlocked door (the one state that should read as an alert).
- **Typography:** monospace (Consolas), uppercase, loosely letter-spaced —
  reads as instrument-panel labeling rather than app UI.
- **Panels:** each device is a single `Canvas` drawing its own bracketed
  HUD frame (corner brackets + faint scanline texture) so the border glows
  cyan only when that specific device is active/on.
- **Status core:** the old plain colored dot was replaced with a small
  reactor-style indicator — a pulsing core inside a rotating four-segment
  ring while listening, solid amber while paused, dim while idle.
- **Icons:** bulb, padlock, thermostat dial, and TV are all redrawn as
  outline/glow strokes on the same palette instead of flat filled shapes,
  so every card looks like part of one instrument panel rather than
  separate colored widgets.

**Compatibility:** the public `HomeSimulator` API is unchanged
(`__init__(root, on_toggle_pause)`, `.root`, `.set_status()`,
`.set_listening_active()`, `.add_history_entry()`, `.apply_action(s)`), so
`main.py` required no changes.

> Insert before/after screenshots here for the report: capture the previous
> flat-card dashboard and the new HUD dashboard in the same state (e.g.
> after "turn on the tv and kitchen lights") for a direct comparison.

---

## 6. Setup & Running

See `README.md` for the full walkthrough (Python version pitfalls, PyAudio
build issues on Windows, Ollama installation). Quick reference:

```powershell
venv\Scripts\activate
pip install -r requirements.txt
ollama pull qwen2.5:1.5b

python src/ai_engine.py       # test intent parsing only, no mic needed
python src/voice_pipeline.py  # test mic + TTS round-trip
python src/main.py            # run the full assistant
```

---

## 7. Known Issues & Rubric-Relevant Notes

1. **Action/target hallucination (highest priority — 30% of grade is Intent
   Extraction).** Qwen occasionally pairs a valid action with an invalid
   target for it (e.g. `set_temperature` on a light). Each field is
   individually valid, so plain `pydantic` `Literal` validation doesn't
   catch the combination. Fix options: tighten the system prompt with an
   explicit action→target mapping, and/or add a `pydantic`
   `@model_validator` that rejects `set_temperature` /
   `increase_temp` / `decrease_temp` on any target other than
   `thermostat`.
2. **Latency.** Observed end-to-end round trips of ~9.7s–13.9s, above the
   rubric's "<2s Outstanding" band. Likely dominated by Qwen inference
   and/or the Google STT network round trip. Worth profiling each stage
   separately (log timestamps are already written to
   `logs/assistant_execution.log`).
3. **Not fully offline yet.** The brief specifies a fully offline,
   software-simulated system; STT currently uses `SpeechRecognition`'s
   Google Web Speech backend, which requires internet. `RECOGNIZER_BACKEND`
   in `voice_pipeline.py` can be swapped to `"sphinx"` with `pocketsphinx`
   installed for a true offline path — not yet done.

---

## 8. Testing Performed

| Test | Command | Result |
|------|---------|--------|
| Intent parsing (no mic) | `python src/ai_engine.py` | 3/3 sample commands parsed to valid JSON (one exposed the hallucination issue above) |
| Voice pipeline (mic + speaker) | `python src/voice_pipeline.py` | Round trip confirmed working |
| Full pipeline | `python src/main.py` | GUI opens, continuous listening, multiple real voice commands correctly updated dashboard state, all logged with timestamps/latency to `assistant_execution.log` |
| GUI visual check | manual, screenshot-verified 2026-08-15 | Icons render correctly, Pause/Resume toggles and is log-confirmed, thermostat dial sweeps correctly, "turn on the tv and kitchen" correctly toggled both devices in one command, history panel populated with real entries |

---

## 9. Task Division

*(Fill in with final numbers before packaging — this table is meant to
match the pair-programming task division matrix required in the report.)*

| Area | Owner | Notes |
|------|-------|-------|
| Core pipeline (STT/TTS, AI engine, GUI, main loop) | Angel | Built all four modules end-to-end; confirmed working together |
| HUD GUI redesign | _fill in_ | Canvas-based redraw, no new dependencies |
| Offline STT backend | _fill in_ | `pocketsphinx`/`vosk` swap, not yet done |
| Action/target validator fix | _fill in_ | Prompt tightening and/or pydantic validator |
| Report (`Prelim_Project_Report.pdf`) | LJ | Architecture diagram, screenshots, CPU/RAM metrics, task matrix |

---

## 10. Submission Checklist

- [ ] Action/target hallucination fix applied and re-tested
- [ ] Latency profiled and noted (or improved)
- [ ] Offline STT decision made (switch to `pocketsphinx`/`vosk`, or document why Google STT was kept)
- [ ] Before/after GUI screenshots captured for 3 distinct voice commands
- [ ] `Prelim_Project_Report.pdf` (3 pages) completed
- [ ] Task division matrix finalized above and mirrored in the report
- [ ] Zipped as `AI_PrelimExam_Group_[LastName1]_[LastName2].zip`
- [ ] Each member submits their own output to MS Teams by Aug 21, 11:59 PM
