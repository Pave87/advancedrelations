"""Relations analysis module for Advanced Relations integration.

This module provides relationship analysis functionality to find how different
Home Assistant components (entities, automations, scripts) relate to each other.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


def preprocess_automations(hass: HomeAssistant) -> dict[str, Any]:
    """Preprocess automations to extract relevant information for relationship analysis.

    Args:
        hass: The Home Assistant instance

    Returns:
        Dictionary containing processed automation information

    """
    _LOGGER.debug("Preprocessing automations")

    # Get the config directory path
    config_dir = Path(hass.config.config_dir)
    automations_file = config_dir / "automations.yaml"

    automations_data = []

    try:
        if automations_file.exists():
            with automations_file.open(encoding="utf-8") as file:
                automations = yaml.safe_load(file) or []

            for automation in automations:
                if not isinstance(automation, dict):
                    continue

                automation_id = automation.get("id", "")
                friendly_name = automation.get("alias", automation_id)

                # Extract triggers
                triggers = []
                trigger_list = automation.get("triggers", automation.get("trigger", []))
                if not isinstance(trigger_list, list):
                    trigger_list = [trigger_list]

                for trigger in trigger_list:
                    if isinstance(trigger, dict):
                        # Entity-based triggers
                        if "entity_id" in trigger:
                            entity_ids = trigger["entity_id"]
                            if isinstance(entity_ids, str):
                                entity_ids = [entity_ids]
                            triggers.extend(entity_ids)

                        # Device triggers
                        if "device_id" in trigger:
                            triggers.append(f"device:{trigger['device_id']}")

                        # Time-based triggers (time, time_pattern, sun)
                        trigger_type = trigger.get("trigger")
                        if trigger_type in ["time", "time_pattern", "sun"]:
                            # For time-based triggers, we include the trigger type as identifier
                            trigger_info = f"trigger:{trigger_type}"
                            if trigger_type == "time" and "at" in trigger:
                                trigger_info += f":{trigger['at']}"
                            elif trigger_type == "time_pattern":
                                parts = []
                                if "hours" in trigger:
                                    parts.append(f"hours={trigger['hours']}")
                                if "minutes" in trigger:
                                    parts.append(f"minutes={trigger['minutes']}")
                                if "seconds" in trigger:
                                    parts.append(f"seconds={trigger['seconds']}")
                                if parts:
                                    trigger_info += f":{','.join(parts)}"
                            elif trigger_type == "sun" and "event" in trigger:
                                trigger_info += f":{trigger['event']}"
                            triggers.append(trigger_info)

                        # Other trigger types that might not have entity_id
                        elif (
                            trigger_type
                            and "entity_id" not in trigger
                            and "device_id" not in trigger
                        ):
                            triggers.append(f"trigger:{trigger_type}")

                # Extract conditions
                conditions = []
                condition_list = automation.get(
                    "conditions", automation.get("condition", [])
                )
                if not isinstance(condition_list, list):
                    condition_list = [condition_list]

                conditions.extend(_extract_conditions_from_list(condition_list))

                # Extract outputs from actions
                outputs = []
                action_list = automation.get("actions", automation.get("action", []))
                if not isinstance(action_list, list):
                    action_list = [action_list]

                outputs.extend(_extract_outputs_from_actions(action_list))

                # Also extract conditions from actions (building block conditions)
                conditions.extend(_extract_conditions_from_actions(action_list))

                automation_data = {
                    "id": automation_id,
                    "friendly_name": friendly_name,
                    "triggers": triggers,
                    "conditions": conditions,
                    "outputs": outputs,
                }

                automations_data.append(automation_data)

    except (FileNotFoundError, yaml.YAMLError, OSError) as e:
        _LOGGER.error("Error reading automations.yaml: %s", e)

    return {"automations": automations_data}


def _extract_conditions_from_list(condition_list: list) -> list[str]:
    """Extract entity references from condition list."""
    conditions = []

    for condition in condition_list:
        if not isinstance(condition, dict):
            continue

        # Entity condition
        if "entity_id" in condition:
            entity_ids = condition["entity_id"]
            if isinstance(entity_ids, str):
                entity_ids = [entity_ids]
            conditions.extend(entity_ids)

        # Device condition
        if "device_id" in condition:
            conditions.append(f"device:{condition['device_id']}")

        # Template condition - try to extract entity references
        if "value_template" in condition:
            template = condition["value_template"]
            if isinstance(template, str):
                # Simple regex to find entity references in templates
                import re

                entity_refs = re.findall(r'states\([\'"]([^\'\"]+)[\'\"]\)', template)
                conditions.extend(entity_refs)

    return conditions


def _extract_outputs_from_actions(action_list: list) -> list[str]:
    """Extract entity/service references from action list."""
    outputs = []

    for action in action_list:
        if not isinstance(action, dict):
            continue

        # Track if we found specific targets for this action
        found_specific_targets = False

        # Target entities
        if "target" in action and isinstance(action["target"], dict):
            if "entity_id" in action["target"]:
                entity_ids = action["target"]["entity_id"]
                if isinstance(entity_ids, str):
                    entity_ids = [entity_ids]
                outputs.extend(entity_ids)
                found_specific_targets = True

        # Direct entity_id
        if "entity_id" in action:
            entity_ids = action["entity_id"]
            if isinstance(entity_ids, str):
                entity_ids = [entity_ids]
            outputs.extend(entity_ids)
            found_specific_targets = True

        # Device actions
        if "device_id" in action:
            outputs.append(f"device:{action['device_id']}")
            found_specific_targets = True

        # Script calls - handle both old 'service' and new 'action' formats
        service_name = action.get("service") or action.get("action", "")
        if service_name.startswith("script."):
            script_name = service_name.replace("script.", "")
            outputs.append(f"script.{script_name}")
            found_specific_targets = True

        # Automation calls - handle both old 'service' and new 'action' formats
        if service_name == "automation.trigger":
            if "target" in action and "entity_id" in action["target"]:
                entity_ids = action["target"]["entity_id"]
                if isinstance(entity_ids, str):
                    entity_ids = [entity_ids]
                outputs.extend(entity_ids)
                found_specific_targets = True

        # If we have a service/action call but no specific targets, add the service itself
        if not found_specific_targets and service_name:
            outputs.append(f"service:{service_name}")

        # Process nested actions in control structures
        # If-then-else blocks
        if "then" in action:
            then_actions = action["then"]
            if isinstance(then_actions, list):
                outputs.extend(_extract_outputs_from_actions(then_actions))

        if "else" in action:
            else_actions = action["else"]
            if isinstance(else_actions, list):
                outputs.extend(_extract_outputs_from_actions(else_actions))

        # Repeat blocks
        if "repeat" in action:
            repeat_block = action["repeat"]
            if isinstance(repeat_block, dict) and "sequence" in repeat_block:
                sequence_actions = repeat_block["sequence"]
                if isinstance(sequence_actions, list):
                    outputs.extend(_extract_outputs_from_actions(sequence_actions))

    return outputs


def _extract_conditions_from_actions(action_list: list) -> list[str]:
    """Extract conditions from building block conditions within actions."""
    conditions = []

    for action in action_list:
        if not isinstance(action, dict):
            continue

        # If-then-else conditions
        if "if" in action:
            if_conditions = action["if"]
            if isinstance(if_conditions, list):
                conditions.extend(_extract_conditions_from_list(if_conditions))
            elif isinstance(if_conditions, dict):
                conditions.extend(_extract_conditions_from_list([if_conditions]))

        # Process else block conditions
        if "else" in action:
            else_actions = action["else"]
            if isinstance(else_actions, list):
                conditions.extend(_extract_conditions_from_actions(else_actions))

        # Process then block conditions
        if "then" in action:
            then_actions = action["then"]
            if isinstance(then_actions, list):
                conditions.extend(_extract_conditions_from_actions(then_actions))

        # Repeat block conditions
        if "repeat" in action:
            repeat_block = action["repeat"]
            if isinstance(repeat_block, dict):
                # While conditions in repeat blocks
                if "while" in repeat_block:
                    while_conditions = repeat_block["while"]
                    if isinstance(while_conditions, list):
                        conditions.extend(
                            _extract_conditions_from_list(while_conditions)
                        )
                    elif isinstance(while_conditions, dict):
                        conditions.extend(
                            _extract_conditions_from_list([while_conditions])
                        )

                # Process sequence actions in repeat blocks
                if "sequence" in repeat_block:
                    sequence_actions = repeat_block["sequence"]
                    if isinstance(sequence_actions, list):
                        conditions.extend(
                            _extract_conditions_from_actions(sequence_actions)
                        )

        # Choose conditions
        if "choose" in action:
            choose_list = action["choose"]
            if isinstance(choose_list, list):
                for choice in choose_list:
                    if isinstance(choice, dict) and "conditions" in choice:
                        choice_conditions = choice["conditions"]
                        if isinstance(choice_conditions, list):
                            conditions.extend(
                                _extract_conditions_from_list(choice_conditions)
                            )
                        elif isinstance(choice_conditions, dict):
                            conditions.extend(
                                _extract_conditions_from_list([choice_conditions])
                            )

    return conditions


def preprocess_scripts(hass: HomeAssistant) -> dict[str, Any]:
    """Preprocess scripts to extract relevant information for relationship analysis.

    Args:
        hass: The Home Assistant instance

    Returns:
        Dictionary containing processed script information

    """
    _LOGGER.debug("Preprocessing scripts")

    # Get the config directory path
    config_dir = Path(hass.config.config_dir)
    scripts_file = config_dir / "scripts.yaml"

    scripts_data = []

    try:
        if scripts_file.exists():
            with scripts_file.open(encoding="utf-8") as file:
                scripts = yaml.safe_load(file) or {}

            for script_key, script_config in scripts.items():
                if not isinstance(script_config, dict):
                    continue

                script_id = f"script.{script_key}"
                friendly_name = script_config.get("alias", script_id)

                # Scripts don't have triggers, only conditions and outputs
                # Extract conditions from the script sequence
                conditions = []
                sequence = script_config.get("sequence", [])
                if not isinstance(sequence, list):
                    sequence = [sequence]

                conditions.extend(_extract_conditions_from_actions(sequence))

                # Extract outputs from the script sequence
                outputs = []
                outputs.extend(_extract_outputs_from_actions(sequence))

                script_data = {
                    "id": script_id,
                    "friendly_name": friendly_name,
                    "triggers": [],  # Scripts don't have triggers
                    "conditions": conditions,
                    "outputs": outputs,
                }

                scripts_data.append(script_data)

    except (FileNotFoundError, yaml.YAMLError, OSError) as e:
        _LOGGER.error("Error reading scripts.yaml: %s", e)

    return {"scripts": scripts_data}


def preprocess_entities(hass: HomeAssistant) -> dict[str, Any]:
    """Preprocess entities to extract relevant information for relationship analysis.

    Args:
        hass: The Home Assistant instance

    Returns:
        Dictionary containing processed entity information

    """
    _LOGGER.debug("Preprocessing entities")
    # TODO: Implement entity preprocessing logic
    return {}


def find_comprehensive_relations(
    hass: HomeAssistant, item_type: str, item_id: str, max_depth: int = 3
) -> dict[str, Any]:
    """Find comprehensive relationships for a given Home Assistant component.

    This function analyzes the relationships between the specified component and other
    Home Assistant entities, automations, and scripts. It returns a structured representation
    of how components interact with each other.

    Args:
        hass: The Home Assistant instance
        item_type: Type of item to analyze ('entity', 'automation', or 'script')
        item_id: Unique identifier of the item to analyze
        max_depth: Maximum depth for relationship traversal

    Returns:
        A dictionary containing the relationship analysis results in the format:
        {
            "relations": {
                "item_type": item_type,
                "item_id": item_id,
                "friendly_name": "Human readable name",
                "upstream": [ # List of items that this item uses typically items from triggers and conditions
                {
                    "item_type": "entity",
                    "item_id": "sensor.temperature",
                    "friendly_name": "Temperature Sensor",
                    "relation_type": "trigger",  # or "condition"
                    "upstream": [],  # Items that this item uses (limited by max_depth)
                    "downstream": []  # Items that use this item (limited to direct relationships only when nested)
                },
                ],
                "downstream": [ # List of items that use this item (outputs and dependencies)
                {
                    "item_type": "automation",
                    "item_id": "automation.lights_on",
                    "friendly_name": "Lights On Automation",
                    "relation_type": "output",  # Always "output" in downstream
                    "upstream": [],  # Items that this item uses (limited to direct relationships only when nested)
                    "downstream": [  # Items that use this item (limited by max_depth)
                    {
                        "item_type": "script",
                        "item_id": "script.turn_on_lights",
                        "friendly_name": "Turn On Lights Script",
                        "relation_type": "output",
                        "upstream": [],  # Items that this item uses (limited to direct relationships only when nested)
                        "downstream": [] # Items that use this item (limited by max_depth)
                        }]
                },
                ],
            }
        }

    Definitions of terms:
        - **upstream**: Items that the specified item uses, such as entities in triggers or conditions.
          Anything that affects this item directly. For entities, this is typically empty unless
          it's a template sensor (which depends on other entities), utility meter (which depends on source entity) etc.

        - **downstream**: Items that use the specified item, such as automations or scripts that depend on it.
          Anything that is affected by this item directly.

        - **relation_type**: Indicates the type of relationship:
          - 'trigger': Item is used as a trigger (in automation triggers, or as a source for utility meters)
          - 'condition': Item is used in conditions (automation/script conditions, template sensor dependencies)
          - 'output': Item is affected/controlled by the parent (entity controlled by automation, script called by automation)

        - **max_depth behavior**:
          - At root level: Follow relationships up to max_depth levels deep
          - In nested items: Follow relationships up to max depth but only for same direction (upstream or downstream)
          - depth=0 means unlimited depth (might lead to loops in circular dependencies)

        - **Special cases**:
          - Template sensors: Entities used in template go in upstream with relation_type="condition"
          - Utility meters: Source entity goes in upstream with relation_type="trigger"
          - Automations calling scripts: Script appears in automation's downstream with relation_type="output"
          - Scripts calling other scripts: Similar to automation->script relationship

    Note:
        This is a placeholder implementation that returns an empty structure.
        The actual relationship analysis logic will be implemented later.

    """
    _LOGGER.info(
        "Finding comprehensive relations for %s: %s (max_depth: %d)",
        item_type,
        item_id,
        max_depth,
    )

    automations = preprocess_automations(hass)
    scripts = preprocess_scripts(hass)
    entities = preprocess_entities(hass)

    # Placeholder implementation - returns empty structure matching the documented format
    return {
        "relations": {
            "item_type": item_type,
            "item_id": item_id,
            "friendly_name": item_id,  # TODO: Get actual friendly name from data_loader
            "upstream": [],
            "downstream": [],
        }
    }
