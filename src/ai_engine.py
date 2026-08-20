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

# Thermostat's supported target-temperature range, in Celsius. Keep in sync
# with home_simulator.py's dial-drawing clamp (_draw_thermostat).
THERMOSTAT_MIN_C = 7.0
THERMOSTAT_MAX_C = 35.0

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

        # The thermostat's state is a float (a target temperature), not a
        # boolean - it doesn't have an "on/off" concept in the schema or the
        # GUI. Qwen occasionally still reaches for turn_on/turn_off on it
        # (observed 2026-08-16 23:31:50: a bare "turn off" command produced
        # a turn_off action against the thermostat alongside the lights).
        # Reject rather than silently normalize, since there's no sensible
        # "on" state to map it to.
        if self.action in ("turn_on", "turn_off") and self.target == "thermostat":
            raise ValueError(
                f"'{self.action}' is not valid for target 'thermostat' "
                "(thermostat has no on/off state - use set_temperature/increase_temp/decrease_temp)"
            )

        # set_temperature had no range check at all (observed 2026-08-20:
        # "change the thermostat into 50°" was accepted and applied with
        # no complaint). home_simulator.py's own dial-drawing code already
        # clamps the VISUAL arc to a fixed range - it never validated the
        # underlying state value, so an absurd target temperature silently
        # reached the GUI as text ("50°") even though the dial maxed out.
        # Reject here so both files agree on the same range instead of only
        # fixing the symptom in one place. (Caller decides what to tell the
        # user when this is raised - see _build_actions in parse_command.)
        if self.action == "set_temperature" and self.value is not None:
            if not (THERMOSTAT_MIN_C <= self.value <= THERMOSTAT_MAX_C):
                raise ValueError(
                    f"set_temperature value {self.value} is out of range "
                    f"(thermostat supports {THERMOSTAT_MIN_C:.0f}-{THERMOSTAT_MAX_C:.0f} degrees C)"
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
- set_temperature values must be between {THERMOSTAT_MIN_C:.0f} and {THERMOSTAT_MAX_C:.0f} (degrees C) - the thermostat cannot go outside that range.
- "set_temperature", "increase_temp", and "decrease_temp" are ONLY valid with target "thermostat". Never use them on a light or the TV.
- "lock" and "unlock" are ONLY valid with target "front_door_lock". The door is always locked/unlocked, never turned on/off:
  "lock the door" -> {{"action": "lock", "target": "front_door_lock", "value": null}}
  "unlock the front door" -> {{"action": "unlock", "target": "front_door_lock", "value": null}}
- Interpret vague/ambiguous phrasing sensibly, e.g. "it's getting dark" -> turn_on a light; "I'm freezing" -> increase_temp.
- The GUI card for "tv" is labeled ENTERTAINMENT, so the user may say "entertainment", "entertainment system", "entertainment center", "television", or "TV" - all of these mean target "tv". There is only ONE entertainment device in this system, not one per room - never invent targets like "living_room_tv" or "bedroom_audio", they do not exist. If a command only refers to "the entertainment" with no other device named, emit ONLY a "tv" action - do not also turn lights on/off.
- If the command says "the lights" or "all the lights" with no specific room named, include an action for EVERY light target: living_room_light, kitchen_light, AND bedroom_light. Do not silently pick just one.
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


def _build_actions(raw_actions: list) -> tuple[list, list]:
    """
    Validate each raw action dict independently rather than validating the
    whole list at once. Previously, one invalid action (e.g. an out-of-range
    thermostat value) raised a ValidationError for the ENTIRE response,
    silently dropping every other valid action from the same command too
    (e.g. "turn on the tv and set thermostat to 100" would lose the TV
    action as collateral damage). Returns (valid_actions, warning_messages)
    so the caller can keep the good actions and still tell the user what
    was rejected and why.
    """
    valid = []
    warnings = []
    for raw in raw_actions:
        try:
            valid.append(DeviceAction.model_validate(raw))
        except ValidationError as exc:
            action = raw.get("action") if isinstance(raw, dict) else None
            target = raw.get("target") if isinstance(raw, dict) else None
            value = raw.get("value") if isinstance(raw, dict) else None
            if action == "set_temperature" and target == "thermostat" and value is not None:
                warnings.append(
                    f"Sorry, {value:g} degrees is out of range. "
                    f"You can only set the thermostat between "
                    f"{THERMOSTAT_MIN_C:.0f} and {THERMOSTAT_MAX_C:.0f} degrees."
                )
            else:
                logger.warning("Dropped invalid action %s: %s", raw, exc)
    return valid, warnings


def parse_command(transcribed_text: str) -> AssistantResponse:
    """
    Send transcribed_text to the local Qwen model via Ollama and return a
    validated AssistantResponse. Raises ValueError on unrecoverable parse
    failure - i.e. the model's output wasn't even parseable JSON at all
    (caller should catch this and fall back gracefully). Individual invalid
    actions within an otherwise-valid response are handled internally (see
    _build_actions) rather than raised, so they don't take down the rest of
    the command.
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
    except (json.JSONDecodeError, ValueError) as exc:
        logger.error("Failed to parse model output as JSON: %s", exc)
        raise ValueError(f"Could not parse a valid action from model output: {exc}") from exc

    raw_actions = data.get("actions", [])
    if not isinstance(raw_actions, list):
        raw_actions = []

    actions, warnings = _build_actions(raw_actions)

    response_text = data.get("response_text") or ""
    if warnings:
        # An out-of-range value means the model's own response_text is
        # describing something that did NOT actually happen (e.g. "The
        # thermostat has been set to 36 degrees." when 36 was rejected).
        # Replace it entirely with the warning rather than appending, so
        # the user never hears a false success claim before the correction.
        response_text = " ".join(warnings)
    elif not actions and not response_text:
        response_text = "Sorry, I didn't catch a command I can act on."

    response = AssistantResponse(actions=actions, response_text=response_text)
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
        "Turn off the thermostat",  # regression check: should be rejected, not silently applied
        "Set the thermostat to 50 degrees",  # regression check: out-of-range -> warning, no crash
        "Turn on the tv and set the thermostat to 100",  # regression check: TV action should survive even though the temp is rejected
        "Turn on the entertainment",  # regression check: should map to tv, not living_room_light
        "Turn off the lights",  # regression check: should include all 3 lights, not just one
    ]
    for cmd in test_commands:
        print("\n>>>", cmd)
        try:
            print(parse_command(cmd).model_dump_json(indent=2))
        except ValueError as e:
            print("ERROR:", e)