"""
ai_engine.py
Sends transcribed text to a local Ollama instance running Qwen 2.5 (1.5b)
and parses the response into a validated, structured action list using pydantic.

This is the "brain" of the assistant: natural language in, structured
smart-home commands out.
"""

import json
import logging
from typing import List, Literal, Optional

import ollama
from pydantic import BaseModel, ValidationError, model_validator

logger = logging.getLogger("assistant")

MODEL_NAME = "qwen2.5:1.5b"

# ---------------------------------------------------------------------------
# Supported devices / actions - keep this in sync with home_simulator.py
# ---------------------------------------------------------------------------
VALID_TARGETS = [
    "living_room_light",
    "kitchen_light",
    "bedroom_light",
    "thermostat",
    "front_door_lock",
    "tv",
]

VALID_ACTIONS = [
    "turn_on",
    "turn_off",
    "set_temperature",
    "increase_temp",
    "decrease_temp",
    "lock",
    "unlock",
]


# ---------------------------------------------------------------------------
# Schema (shared contract between ai_engine.py and home_simulator.py)
# ---------------------------------------------------------------------------
class DeviceAction(BaseModel):
    action: Literal[
        "turn_on",
        "turn_off",
        "set_temperature",
        "increase_temp",
        "decrease_temp",
        "lock",
        "unlock",
    ]
    target: Literal[
        "living_room_light",
        "kitchen_light",
        "bedroom_light",
        "thermostat",
        "front_door_lock",
        "tv",
    ]
    value: Optional[float] = None  # used for set_temperature / increase_temp / decrease_temp

    # ------------------------------------------------------------------
    # pydantic's Literal fields only validate each field in isolation -
    # "turn_on" is a valid action, "front_door_lock" is a valid target,
    # so {"action": "turn_on", "target": "front_door_lock"} passes even
    # though it's a nonsensical *pairing*. Qwen reaches for turn_on/
    # turn_off on the door fairly often (it's the most common verb pair
    # in the prompt), which silently re-locks the door instead of
    # unlocking it. This validator catches and fixes/rejects the
    # combinations we've actually observed.
    # ------------------------------------------------------------------
    @model_validator(mode="after")
    def _validate_action_target_pairing(self):
        # Temperature-style actions only make sense on the thermostat.
        if self.action in ("set_temperature", "increase_temp", "decrease_temp") \
                and self.target != "thermostat":
            raise ValueError(
                f"'{self.action}' is not valid for target '{self.target}' "
                "(temperature actions only apply to 'thermostat')"
            )

        # The door is locked/unlocked, not turned on/off. Normalize
        # rather than reject, since "turn on the front door" almost
        # always means "engage the lock" in casual speech.
        if self.target == "front_door_lock":
            if self.action == "turn_on":
                self.action = "lock"
            elif self.action == "turn_off":
                self.action = "unlock"

        # Lock/unlock only make sense on the door.
        if self.action in ("lock", "unlock") and self.target != "front_door_lock":
            raise ValueError(
                f"'{self.action}' is not valid for target '{self.target}' "
                "(lock/unlock only apply to 'front_door_lock')"
            )

        return self


class AssistantResponse(BaseModel):
    actions: List[DeviceAction]
    response_text: str  # what gets spoken back via TTS


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = f"""You are the intent-parsing engine for an offline smart home assistant.

Convert the user's spoken command into a JSON object with this EXACT shape:
{{
  "actions": [
    {{"action": "<one of {VALID_ACTIONS}>", "target": "<one of {VALID_TARGETS}>", "value": <number or null>}}
  ],
  "response_text": "<a short, natural spoken confirmation of what you did>"
}}

Rules:
- Output ONLY valid JSON. No markdown, no code fences, no explanation.
- A single command can map to multiple actions (e.g. "turn off the kitchen lights and set the thermostat to 22").
- "value" is required for set_temperature (target temp), increase_temp / decrease_temp (degrees to change), and null for everything else.
- "set_temperature", "increase_temp", and "decrease_temp" are ONLY valid with target "thermostat". Never use them on a light or the TV.
- "lock" and "unlock" are ONLY valid with target "front_door_lock". The door is always locked/unlocked, never turned on/off:
  "lock the door" -> {{"action": "lock", "target": "front_door_lock", "value": null}}
  "unlock the front door" -> {{"action": "unlock", "target": "front_door_lock", "value": null}}
- Interpret vague/ambiguous phrasing sensibly, e.g. "it's getting dark" -> turn_on a light; "I'm freezing" -> increase_temp.
- If the command mentions no valid device/action, return {{"actions": [], "response_text": "Sorry, I didn't catch a command I can act on."}}
"""


def _extract_json(raw_text: str) -> dict:
    """Qwen sometimes wraps JSON in code fences or adds stray text - strip that out."""
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.replace("json\n", "", 1).replace("json", "", 1)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON object found in model output: {raw_text!r}")
    return json.loads(text[start : end + 1])


def parse_command(transcribed_text: str) -> AssistantResponse:
    """
    Send transcribed_text to the local Qwen model via Ollama and return a
    validated AssistantResponse. Raises ValueError on unrecoverable parse failure
    (caller should catch this and fall back gracefully).
    """
    logger.info("Sending to Qwen: %s", transcribed_text)

    result = ollama.chat(
        model=MODEL_NAME,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": transcribed_text},
        ],
        options={"temperature": 0.2},
    )

    raw_content = result["message"]["content"]
    logger.info("Raw Qwen output: %s", raw_content)

    try:
        data = _extract_json(raw_content)
        response = AssistantResponse.model_validate(data)
    except (json.JSONDecodeError, ValidationError, ValueError) as exc:
        logger.error("Failed to parse/validate model output: %s", exc)
        raise ValueError(f"Could not parse a valid action from model output: {exc}") from exc

    logger.info("Parsed actions: %s", response.model_dump())
    return response


if __name__ == "__main__":
    # Quick manual test: python ai_engine.py
    logging.basicConfig(level=logging.INFO)
    test_commands = [
        "Set the living room thermostat to 22 degrees and turn off the kitchen lights",
        "It's getting dark in here and I'm freezing",
        "Lock the front door",
        "Unlock the front door",
        "Turn on the front door",  # regression check: should normalize to lock, not stay turn_on
    ]
    for cmd in test_commands:
        print("\n>>>", cmd)
        try:
            print(parse_command(cmd).model_dump_json(indent=2))
        except ValueError as e:
            print("ERROR:", e)