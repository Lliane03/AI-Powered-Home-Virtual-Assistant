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

# Single, consistent apology used everywhere in the app - previously
# ai_engine.py used "Sorry, I didn't catch a command I can act on." while
# main.py used a differently-worded "Sorry, I didn't catch that. Try
# again." for STT failures. Unified into one phrase so the user hears the
# same thing regardless of which layer couldn't understand them.
FALLBACK_MESSAGE = "Sorry, I didn't catch that. Try again."

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
- The GUI card for "tv" is labeled TV. A command that ONLY refers to the TV (e.g. "turn on the tv", "turn off the tv", "turn on the television") must produce ONLY a "tv" action - never bundle in lights, the thermostat, or the door unless those are ALSO separately, explicitly named in the same command.
- If the command says "the lights" or "all the lights" with no specific room named, include an action for EVERY light target: living_room_light, kitchen_light, AND bedroom_light. Do not silently pick just one.
- If the command mentions no valid device/action, return {{"actions": [], "response_text": "Sorry, I didn't catch that. Try again."}}
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
    seen = set()
    for raw in raw_actions:
        try:
            device_action = DeviceAction.model_validate(raw)
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
            continue

        # Qwen occasionally repeats the exact same action twice in one
        # response (observed 2026-08-20: "turn on bedroom" ->
        # bedroom_light turn_on listed twice). Harmless in effect since
        # applying it twice is idempotent, but it inflates the command log
        # and metrics with a phantom duplicate action - drop repeats.
        dedup_key = (device_action.action, device_action.target, device_action.value)
        if dedup_key in seen:
            logger.warning("Dropped duplicate action %s", device_action.model_dump())
            continue
        seen.add(dedup_key)
        valid.append(device_action)
    return valid, warnings


# ---------------------------------------------------------------------------
# TV isolation backstop
# ---------------------------------------------------------------------------
# Prompting alone was NOT reliable enough on qwen2.5:1.5b: even after adding
# an explicit "TV commands must be isolated" instruction to SYSTEM_PROMPT,
# testing on 2026-08-20 showed the model still bundled in all 3 lights +
# thermostat + door lock on TV-only phrases ("entertainment", "entertain",
# "turn off entertainment") in 4 out of 4 tries. Since this needs to be
# solid for a live demo, back the prompt with a deterministic code-level
# filter: if the transcribed command doesn't mention any other device by
# name, strip out any non-tv actions the model added on its own, no matter
# what it decided to include.
_OTHER_DEVICE_KEYWORDS = [
    "light", "lights",
    "living room", "living", "kitchen", "bedroom",
    "thermostat", "temperature", "degree", "degrees",
    "hot", "cold", "freezing", "warm", "cool",
    "door", "lock", "unlock",
]


def _is_tv_only_command(transcribed_text: str) -> bool:
    """True if the command mentions the TV and names no other device -
    e.g. 'turn on the tv' or 'turn off tv', but NOT 'turn on the tv and
    kitchen light' (that legitimately names two devices and should keep
    both actions)."""
    text = transcribed_text.lower()
    mentions_tv = "tv" in text or "television" in text
    mentions_other = any(kw in text for kw in _OTHER_DEVICE_KEYWORDS)
    return mentions_tv and not mentions_other


def _enforce_tv_isolation(transcribed_text: str, actions: list) -> list:
    if not _is_tv_only_command(transcribed_text):
        return actions
    filtered = [a for a in actions if a.target == "tv"]
    if len(filtered) != len(actions):
        dropped = [a.model_dump() for a in actions if a.target != "tv"]
        logger.warning(
            "TV isolation: command %r named only the TV - dropped bundled actions %s",
            transcribed_text, dropped,
        )
    return filtered


# ---------------------------------------------------------------------------
# Per-room light isolation backstop
# ---------------------------------------------------------------------------
# Same root cause as the TV isolation bug above: naming ONE specific room
# ("kitchen", "living room"/"living") reliably made Qwen bundle in the
# other two rooms' lights too (observed 2026-08-20: "on kitchen light" ->
# all 3 lights; "turn on living light" -> all 3 lights, even while the
# door and TV were also correctly isolated in the same command). Fix the
# same way: deterministically strip any light action for a room that
# wasn't actually named, rather than trust the model to self-restrict.
_ROOM_LIGHT_KEYWORDS = {
    "living_room_light": ["living room", "living"],
    "kitchen_light": ["kitchen"],
    "bedroom_light": ["bedroom", "bed room"],
}
_ROOM_LABELS = {
    "living_room_light": "living room",
    "kitchen_light": "kitchen",
    "bedroom_light": "bedroom",
}


def _mentioned_rooms(transcribed_text: str) -> set:
    text = transcribed_text.lower()
    return {
        target for target, keywords in _ROOM_LIGHT_KEYWORDS.items()
        if any(kw in text for kw in keywords)
    }


def _enforce_room_light_isolation(transcribed_text: str, actions: list) -> list:
    text = transcribed_text.lower()
    if "all" in text:
        # "turn on all the lights" - let every light through as intended.
        return actions
    mentioned = _mentioned_rooms(transcribed_text)
    if not mentioned:
        # No specific room named at all (e.g. "turn off the lights") - the
        # SYSTEM_PROMPT rule handles this case by including every light on
        # purpose, so don't interfere here.
        return actions
    if len(mentioned) == len(_ROOM_LIGHT_KEYWORDS):
        # User genuinely named all three rooms - keep everything.
        return actions

    light_targets = set(_ROOM_LIGHT_KEYWORDS.keys())
    filtered = [a for a in actions if not (a.target in light_targets and a.target not in mentioned)]
    if len(filtered) != len(actions):
        dropped = [a.model_dump() for a in actions if a.target in light_targets and a.target not in mentioned]
        logger.warning(
            "Room isolation: command %r named rooms %s - dropped unrelated light actions %s",
            transcribed_text, mentioned, dropped,
        )
    return filtered


# ---------------------------------------------------------------------------
# Deterministic confirmation text
# ---------------------------------------------------------------------------
# All session, the recurring failure pattern was NOT the actions list being
# wrong (pydantic + the isolation filters above catch that) - it was
# response_text (Qwen's own free-form sentence) describing something
# different from what was actually applied, e.g. claiming "the lights and
# TV have been turned off" when a light was filtered out, or "set to 36
# degrees" when that value was rejected. Rather than keep patching
# individual mismatches, generate the spoken confirmation directly from the
# final, validated action list whenever there IS at least one real action -
# it can never lie about what happened because it's built from what
# actually happened.
def _describe_action(a: "DeviceAction") -> str:
    if a.target in _ROOM_LABELS:
        state = "on" if a.action == "turn_on" else "off"
        return f"The {_ROOM_LABELS[a.target]} light is {state}"
    if a.target == "tv":
        state = "on" if a.action == "turn_on" else "off"
        return f"The TV is {state}"
    if a.target == "front_door_lock":
        state = "locked" if a.action == "lock" else "unlocked"
        return f"The front door is {state}"
    if a.target == "thermostat":
        if a.action == "set_temperature":
            return f"The thermostat is set to {a.value:g} degrees"
        if a.action == "increase_temp":
            return f"The thermostat has been increased by {a.value:g} degrees"
        if a.action == "decrease_temp":
            return f"The thermostat has been decreased by {a.value:g} degrees"
    return f"{a.target.replace('_', ' ')} {a.action.replace('_', ' ')}"  # fallback, shouldn't normally hit


def _describe_actions(actions: list) -> str:
    parts = [_describe_action(a) for a in actions]
    if len(parts) == 1:
        return parts[0] + "."
    return ", ".join(parts[:-1]) + f", and {parts[-1]}."


# ---------------------------------------------------------------------------
# "Not an actionable command" detection
# ---------------------------------------------------------------------------
# Observed 2026-08-20: saying "yes" (a non-command with zero device content)
# still got Qwen to fabricate a full set of actions ("Okay, the lights and
# the thermostat are on...") and apply them for real. If the transcribed
# text doesn't reference ANY recognized device/room/action concept at all,
# skip calling the model entirely - there is nothing here for it to act on,
# so there's no reason to give it the chance to invent something.
NO_ACTION_MESSAGE = "I'm sorry but you didn't set an action for that."

_ALL_DEVICE_KEYWORDS = _OTHER_DEVICE_KEYWORDS + ["tv", "television", "dark"]

# ---------------------------------------------------------------------------
# Greeting exception
# ---------------------------------------------------------------------------
# The no-device-keyword abstain path below (_mentions_any_device) would
# otherwise catch "hello"/"hi" too, since a greeting obviously doesn't name
# any device. Before this exception existed, that meant a friendly "hello"
# got the same "I'm sorry but you didn't set an action for that." reply as
# a genuinely confused command like "yes" - technically correct (there's no
# action in either), but it made the assistant feel less natural for the
# one input type a user is most likely to casually test with. This is
# carved out on purpose: greetings keep the old friendly canned reply,
# every other non-actionable input still falls through to NO_ACTION_MESSAGE.
GREETING_MESSAGE = "Hello! How can I help you today?"

_GREETING_WORDS = {
    "hi", "hello", "hey", "hiya", "yo", "greetings",
    "good morning", "good afternoon", "good evening",
}


def _is_greeting(transcribed_text: str) -> bool:
    """
    True only for a bare greeting (optionally with light trailing address
    like "hey Toto" or punctuation), not for a greeting that also opens
    an actual command (e.g. "hi, turn on the kitchen light" should still
    be treated as a real command, not short-circuited here).
    """
    text = transcribed_text.strip().lower().rstrip(".!?,")
    if not text:
        return False
    if text in _GREETING_WORDS:
        return True
    # Allow a short trailing address after the greeting word itself, e.g.
    # "hey Toto" / "hello there" - but only if nothing device-related
    # follows, so a greeting-prefixed real command still falls through.
    words = text.split()
    if words and words[0] in _GREETING_WORDS and not _mentions_any_device(text):
        return len(words) <= 3
    return False


def _mentions_any_device(transcribed_text: str) -> bool:
    text = transcribed_text.lower()
    return any(kw in text for kw in _ALL_DEVICE_KEYWORDS)


def _should_abstain(transcribed_text: str) -> bool:
    """
    True if the transcribed text is either the deprecated "entertainment"
    wording or looks too incomplete/dangling to safely act on - in both
    cases we skip calling Qwen entirely and ask the user to repeat the
    command, rather than let the model guess.

    This exists because prompting alone was NOT reliable here: testing on
    2026-08-20 showed short/truncated STT results like "turn on the",
    "set", and "the thermostat into" consistently caused Qwen to invent a
    "turn everything on" response (all 3 lights + tv + thermostat + door)
    instead of admitting the command was unclear. Skipping the model call
    for these cases is also faster (~10s saved per abstained command,
    since Qwen's inference is the dominant cost - see latency numbers in
    resource_log.csv), which matters for keeping a live demo responsive.
    """
    text = transcribed_text.strip().lower().rstrip(".!?,")
    if not text:
        return True

    # "entertainment" is a deprecated/unsupported word now that the GUI
    # card and all prompt wording refer only to "tv" - never attempt to
    # interpret it, and never let it fall through to the model (observed:
    # Qwen consistently mapped it to turning all lights + door + thermostat
    # on/off, none of which the user asked for).
    if "entertain" in text:
        return True

    # A grammatically complete command essentially never ends on a bare
    # article/preposition/conjunction - that pattern reliably indicates the
    # STT cut the user off mid-sentence (observed: "turn on the", "the
    # thermostat into").
    dangling_trailing_words = {
        "the", "a", "an", "on", "off", "to", "into", "at", "in", "and", "is", "was",
    }
    last_word = text.split()[-1] if text.split() else ""
    if last_word in dangling_trailing_words:
        return True

    # A bare verb with no object at all (observed: "set" alone triggered
    # the same "turn everything on" hallucination as the trailing-word case
    # above, even though it doesn't end in one of those words).
    bare_verb_only = {
        "set", "turn", "turn on", "turn off", "lock", "unlock",
        "change", "increase", "decrease",
    }
    if text in bare_verb_only:
        return True

    return False


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

    if _should_abstain(transcribed_text):
        logger.warning(
            "Abstaining without calling Qwen - command looks incomplete or "
            "uses deprecated wording: %r", transcribed_text,
        )
        return AssistantResponse(actions=[], response_text=FALLBACK_MESSAGE)

    if _is_greeting(transcribed_text):
        logger.info(
            "Greeting detected - responding without calling Qwen: %r", transcribed_text,
        )
        return AssistantResponse(actions=[], response_text=GREETING_MESSAGE)

    if not _mentions_any_device(transcribed_text):
        logger.warning(
            "Abstaining without calling Qwen - no recognizable device/room/"
            "action keyword in %r, nothing to act on", transcribed_text,
        )
        return AssistantResponse(actions=[], response_text=NO_ACTION_MESSAGE)

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
    actions = _enforce_tv_isolation(transcribed_text, actions)
    actions = _enforce_room_light_isolation(transcribed_text, actions)

    if warnings:
        # An out-of-range value means the model's own response_text is
        # describing something that did NOT actually happen (e.g. "The
        # thermostat has been set to 36 degrees." when 36 was rejected).
        response_text = " ".join(warnings)
    elif actions:
        # Built directly from the final, validated action list - see
        # "Deterministic confirmation text" above. Ignores Qwen's own
        # response_text entirely for real commands, since that sentence
        # has repeatedly described actions that were filtered out above.
        response_text = _describe_actions(actions)
    else:
        response_text = data.get("response_text") or NO_ACTION_MESSAGE

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
        "Turn on the tv",  # regression check: single-device TV command works standalone
        "Turn off the tv",  # regression check: bundled lights/thermostat/lock (if any) get stripped, clean TV-only response
        "Turn on the tv and kitchen light",  # regression check: naming a second device should NOT trigger isolation - both actions must survive
        "Turn off the lights",  # regression check: should include all 3 lights, not just one
        "Turn on the",  # regression check: incomplete/dangling - should abstain, no Qwen call, no actions
        "Turn on entertainment",  # regression check: deprecated word - should abstain entirely, zero actions
        "Set",  # regression check: bare verb, no object - should abstain
        "Turn on kitchen light",  # regression check: only kitchen should change, not living room/bedroom
        "Turn on living light",  # regression check: only living room should change, not kitchen/bedroom
        "Turn on tv lock the front door turn on living light",  # regression check: TV+door+living room only, kitchen/bedroom must NOT change
        "Yes",  # regression check: not an actionable command - must produce zero actions and NO_ACTION_MESSAGE, no Qwen call
        "Hello",  # regression check: greeting exception - must get GREETING_MESSAGE, no Qwen call
        "Hi",  # regression check: same as above, short form
        "Hey Toto",  # regression check: greeting + short trailing address - still treated as a greeting
        "Hi, turn on the kitchen light",  # regression check: greeting-prefixed REAL command - must NOT short-circuit, kitchen light should still turn on
    ]
    for cmd in test_commands:
        print("\n>>>", cmd)
        try:
            print(parse_command(cmd).model_dump_json(indent=2))
        except ValueError as e:
            print("ERROR:", e)