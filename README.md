# AI-Powered Home Virtual Assistant

A 100% offline, privacy-first smart home hub prototype built for Apex Home Automations' next-gen product line. The system captures voice commands via microphone, parses natural-language intent locally using Ollama (Qwen 2.5 1.5B), updates a simulated smart-home GUI in real time, and responds with synthesized speech — all without any cloud dependency.

Built as a Prelim Mini-Project (Pair Programming) for **BSCS 3112 (9420-AY126) Artificial Intelligence**.

**Team:** 
De Dios, Louise Jeanne T.

Mangubat, Angel Julliane I.

---

## Architecture

```
Mic Input → STT (voice_pipeline.py) → Text
Text → Ollama/Qwen (ai_engine.py) → Structured JSON Action
JSON Action → State Machine + GUI (home_simulator.py) → Visual Update
JSON Action → TTS (voice_pipeline.py) → Spoken Confirmation
```

## Project Structure

```
/src
  main.py            # Entry point, launches GUI + event loop
  voice_pipeline.py  # STT and TTS handling
  ai_engine.py        # Ollama/Qwen intent parser -> structured JSON
  home_simulator.py  # State machine and GUI visual updates
/docs
  Prelim_Project_Report.pdf
/logs
  assistant_execution.log   # auto-generated, gitignored
requirements.txt
README.md
```

## Prerequisites

1. **Python 3.10+**
2. **Ollama** installed and running locally: https://ollama.com/download
3. Pull the model:
   ```
   ollama pull qwen2.5:1.5b
   ```
4. **Microphone access** on your machine (for PyAudio/SpeechRecognition)
5. `tkinter` — usually bundled with Python; on Linux you may need:
   ```
   sudo apt-get install python3-tk
   ```

## Setup

```bash
# Clone the repo
git clone <repo-url>
cd <repo-folder>

# Create a virtual environment
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

> **Note (Windows users):** PyAudio sometimes fails to install via pip directly.
> If it errors out, install via: `pip install pipwin && pipwin install pyaudio`

## Running the App

```bash
python src/main.py
```

Then speak a command, e.g.:
> "Hey Sophia, set the living room thermostat to 22 degrees and turn off the kitchen lights."

Expected flow:
1. Console prints the transcribed text
2. Qwen extracts structured JSON parameters
3. GUI dashboard updates (thermostat dial, light states, lock icons)
4. App speaks back a confirmation

## Team Task Division

| Module | Owner | Status |
|---|---|---|
| `voice_pipeline.py` (STT/TTS) | TBD | Not started |
| `ai_engine.py` (Ollama/Qwen parsing) | TBD | Not started |
| `home_simulator.py` (GUI + state) | TBD | Not started |
| `main.py` (integration) | Both | Not started |
| Report & documentation | Both | Not started |

## License

Academic project — not for commercial use.
