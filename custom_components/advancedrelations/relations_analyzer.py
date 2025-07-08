"""Relations analysis module for Advanced Relations integration.

This module provides relationship analysis functionality to find how different
Home Assistant components (entities, automations, scripts) relate to each other.
"""

from __future__ import annotations

import json
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


def _read_storage_file(storage_dir: Path, filename: str) -> dict[str, Any]:
    """Read a storage file and return its data."""
    storage_file = storage_dir / filename
    if storage_file.exists():
        try:
            with storage_file.open(encoding="utf-8") as file:
                return json.load(file) or {}
        except (FileNotFoundError, json.JSONDecodeError, OSError) as e:
            _LOGGER.debug("Error reading %s storage: %s", filename, e)
    return {}


def _process_template_entity(storage_dir: Path, unique_id: str) -> list[str]:
    """Process template entity and return conditions."""
    conditions = []

    # Template entities are stored in config entries, not separate storage files
    config_entries_data = _read_storage_file(storage_dir, "core.config_entries")

    for entry in config_entries_data.get("data", {}).get("entries", []):
        if entry.get("domain") == "template":
            # Check if this config entry corresponds to our entity
            # Template entities use entry_id as unique_id in entity registry
            entry_id = entry.get("entry_id", "")
            if entry_id == unique_id:
                options = entry.get("options", {})
                template_str = options.get("state", "")
                if template_str:
                    import re

                    # Extract entity references from template
                    entity_refs = re.findall(
                        r'states\([\'"]([^\'\"]+)[\'\"]\)', template_str
                    )
                    entity_refs.extend(
                        re.findall(
                            r"states\.([a-zA-Z0-9_]+\.[a-zA-Z0-9_]+)", template_str
                        )
                    )
                    conditions.extend(entity_refs)
                break
    return conditions


def _process_utility_meter_entity(storage_dir: Path, unique_id: str) -> list[str]:
    """Process utility meter entity and return triggers."""
    triggers = []

    # Check if utility meter is stored in config entries
    config_entries_data = _read_storage_file(storage_dir, "core.config_entries")

    for entry in config_entries_data.get("data", {}).get("entries", []):
        if entry.get("domain") == "utility_meter":
            entry_id = entry.get("entry_id", "")
            if entry_id == unique_id:
                options = entry.get("options", {})
                source_entity = options.get("source_entity", "")
                if source_entity:
                    triggers.append(source_entity)
                break

    return triggers


def _process_statistics_entity(storage_dir: Path, unique_id: str) -> list[str]:
    """Process statistics entity and return triggers."""
    triggers = []

    # Check if statistics is stored in config entries
    config_entries_data = _read_storage_file(storage_dir, "core.config_entries")

    for entry in config_entries_data.get("data", {}).get("entries", []):
        if entry.get("domain") == "statistics":
            entry_id = entry.get("entry_id", "")
            if entry_id == unique_id:
                options = entry.get("options", {})
                source_entity = options.get("source_entity", "")
                if source_entity:
                    triggers.append(source_entity)
                break

    return triggers


def _process_min_max_entity(storage_dir: Path, unique_id: str) -> list[str]:
    """Process min/max entity and return triggers."""
    triggers = []

    # Check if min_max is stored in config entries
    config_entries_data = _read_storage_file(storage_dir, "core.config_entries")

    for entry in config_entries_data.get("data", {}).get("entries", []):
        if entry.get("domain") == "min_max":
            entry_id = entry.get("entry_id", "")
            if entry_id == unique_id:
                options = entry.get("options", {})
                entity_ids = options.get("entity_ids", [])
                if isinstance(entity_ids, str):
                    entity_ids = [entity_ids]
                triggers.extend(entity_ids)
                break

    return triggers


def _process_group_entity(storage_dir: Path, unique_id: str) -> list[str]:
    """Process group entity and return triggers."""
    triggers = []

    # Check if group is stored in config entries
    config_entries_data = _read_storage_file(storage_dir, "core.config_entries")

    for entry in config_entries_data.get("data", {}).get("entries", []):
        if entry.get("domain") == "group":
            entry_id = entry.get("entry_id", "")
            if entry_id == unique_id:
                options = entry.get("options", {})
                entity_ids = options.get("entities", [])
                if isinstance(entity_ids, str):
                    entity_ids = [entity_ids]
                triggers.extend(entity_ids)
                break

    return triggers


def preprocess_entities(hass: HomeAssistant) -> dict[str, Any]:
    """Preprocess entities to extract relevant information for relationship analysis.

    Args:
        hass: The Home Assistant instance

    Returns:
        Dictionary containing processed entity information

    """
    _LOGGER.debug("Preprocessing entities")

    entities_data = []

    # Get the config directory path
    config_dir = Path(hass.config.config_dir)
    storage_dir = config_dir / ".storage"

    try:
        # Read entity registry to get UI-created entities
        entity_registry_data = _read_storage_file(storage_dir, "core.entity_registry")
        entities = entity_registry_data.get("data", {}).get("entities", [])

        for entity_entry in entities:
            if not isinstance(entity_entry, dict):
                continue

            entity_id = entity_entry.get("entity_id", "")
            platform = entity_entry.get("platform", "")
            unique_id = entity_entry.get("unique_id", "")

            entity_type = None
            triggers = []
            conditions = []

            # Process different entity types
            if platform == "template":
                entity_type = "template"
                template_conditions = _process_template_entity(storage_dir, unique_id)
                conditions.extend(template_conditions)
                _LOGGER.debug(
                    "Template entity %s has conditions: %s",
                    entity_id,
                    template_conditions,
                )
            elif platform == "utility_meter":
                entity_type = "utility_meter"
                triggers.extend(_process_utility_meter_entity(storage_dir, unique_id))
            elif platform == "statistics":
                entity_type = "statistics"
                triggers.extend(_process_statistics_entity(storage_dir, unique_id))
            elif platform == "min_max":
                entity_type = "min_max"
                triggers.extend(_process_min_max_entity(storage_dir, unique_id))
            elif platform == "group":
                entity_type = "group"
                triggers.extend(_process_group_entity(storage_dir, unique_id))

            # Only include entities that have dependencies
            if triggers or conditions:
                # Get friendly name from Home Assistant state
                state = hass.states.get(entity_id)
                friendly_name = (
                    state.attributes.get("friendly_name", entity_id)
                    if state
                    else entity_id
                )

                entity_data = {
                    "id": entity_id,
                    "friendly_name": friendly_name,
                    "entity_type": entity_type or platform,
                    "triggers": triggers,
                    "conditions": conditions,
                    "outputs": [],  # Entities don't have outputs
                }
                entities_data.append(entity_data)

    except (FileNotFoundError, yaml.YAMLError, OSError) as e:
        _LOGGER.error("Error reading entity storage files: %s", e)

    return {"entities": entities_data}


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

    upstream = process_upstream(
        max_depth, automations, scripts, entities, item_type, item_id, hass
    )
    downstream = process_downstream(
        max_depth, automations, scripts, entities, item_type, item_id, hass
    )

    # Get friendly name for the main item
    friendly_name = _get_friendly_name(item_id, automations, scripts, entities, hass)

    # Placeholder implementation - returns empty structure matching the documented format
    return {
        "relations": {
            "item_type": item_type,
            "item_id": item_id,
            "friendly_name": friendly_name,
            "upstream": upstream,
            "downstream": downstream,
        }
    }


def process_upstream(
    max_depth: int,
    automations: dict[str, Any],
    scripts: dict[str, Any],
    entities: dict[str, Any],
    item_type: str,
    item_id: str,
    hass: HomeAssistant,
    current_depth: int = 0,
    visited: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Process upstream relations for a given item recursively.

    Args:
        max_depth: Maximum depth for relationship traversal
        automations: Preprocessed automations data
        scripts: Preprocessed scripts data
        entities: Preprocessed entities data
        item_type: Type of item to analyze ('entity', 'automation', or 'script')
        item_id: Unique identifier of the item to analyze
        hass: Home Assistant instance for accessing current state
        current_depth: Current depth in the recursion
        visited: Set of visited items to prevent circular references

    Returns:
        List of upstream relations

    """
    if visited is None:
        visited = set()

    # Create unique identifier for this item
    unique_key = f"{item_type}:{item_id}"

    # Check for circular reference
    if unique_key in visited:
        return []

    # Add to visited set
    visited = visited.copy()  # Create new copy to avoid modifying parent's set
    visited.add(unique_key)

    upstream = []

    # Stop recursion if we've reached max depth
    if max_depth > 0 and current_depth >= max_depth:
        return upstream

    # Find upstream relations for any item type
    if item_type in ("entity", "automation", "script"):
        upstream.extend(
            _find_upstream_for_item(
                item_id,
                item_type,
                automations,
                scripts,
                entities,
                max_depth,
                current_depth,
                visited,
                hass,
            )
        )

    return upstream


def _find_upstream_for_item(
    item_id: str,
    item_type: str,
    automations: dict[str, Any],
    scripts: dict[str, Any],
    entities: dict[str, Any],
    max_depth: int,
    current_depth: int,
    visited: set[str],
    hass: HomeAssistant,
) -> list[dict[str, Any]]:
    """Find upstream relations for any item type."""
    upstream = []

    # Get the data collection based on item type
    if item_type == "entity":
        data_collection = entities.get("entities", [])
    elif item_type == "automation":
        data_collection = automations.get("automations", [])
    elif item_type == "script":
        data_collection = scripts.get("scripts", [])
    else:
        return upstream

    # Find the specific item
    for item_data in data_collection:
        if item_data["id"] == item_id:
            # Add triggers as upstream (entities and automations have triggers, scripts don't)
            if item_type in ("entity", "automation"):
                for trigger_entity in item_data.get("triggers", []):
                    # Skip time-based and device triggers for automations
                    if item_type == "automation" and trigger_entity.startswith(
                        ("trigger:", "device:")
                    ):
                        continue

                    friendly_name = _get_friendly_name(
                        trigger_entity, automations, scripts, entities, hass
                    )
                    upstream_item = {
                        "item_type": "entity",
                        "item_id": trigger_entity,
                        "friendly_name": friendly_name,
                        "relation_type": "trigger",
                        "upstream": [],
                        "downstream": [],
                    }

                    # Recursively process upstream for this trigger entity
                    if max_depth == 0 or current_depth < max_depth - 1:
                        upstream_item["upstream"] = process_upstream(
                            max_depth,
                            automations,
                            scripts,
                            entities,
                            "entity",
                            trigger_entity,
                            hass,
                            current_depth + 1,
                            visited,
                        )

                    upstream.append(upstream_item)

            # Add conditions as upstream (all item types can have conditions)
            for condition_entity in item_data.get("conditions", []):
                # Skip device conditions
                if condition_entity.startswith("device:"):
                    continue

                friendly_name = _get_friendly_name(
                    condition_entity, automations, scripts, entities, hass
                )
                upstream_item = {
                    "item_type": "entity",
                    "item_id": condition_entity,
                    "friendly_name": friendly_name,
                    "relation_type": "condition",
                    "upstream": [],
                    "downstream": [],
                }

                # Recursively process upstream for this condition entity
                if max_depth == 0 or current_depth < max_depth - 1:
                    upstream_item["upstream"] = process_upstream(
                        max_depth,
                        automations,
                        scripts,
                        entities,
                        "entity",
                        condition_entity,
                        hass,
                        current_depth + 1,
                        visited,
                    )

                upstream.append(upstream_item)
            break

    # For entities, check what controls/creates this entity (upstream)
    if item_type == "entity":
        # Check automations that OUTPUT TO this entity (controls it)
        for automation_data in automations.get("automations", []):
            if item_id in automation_data.get("outputs", []):
                friendly_name = automation_data.get(
                    "friendly_name", automation_data["id"]
                )
                upstream_item = {
                    "item_type": "automation",
                    "item_id": automation_data["id"],
                    "friendly_name": friendly_name,
                    "relation_type": "output",  # This automation outputs to this entity
                    "upstream": [],
                    "downstream": [],
                }

                # Add direct upstream relationships for this automation (its triggers and conditions)
                for trigger_entity in automation_data.get("triggers", []):
                    if trigger_entity != item_id and not trigger_entity.startswith(
                        ("service:", "device:")
                    ):
                        trigger_friendly_name = _get_friendly_name(
                            trigger_entity, automations, scripts, entities, hass
                        )
                        upstream_item["upstream"].append(
                            {
                                "item_type": "entity",
                                "item_id": trigger_entity,
                                "friendly_name": trigger_friendly_name,
                                "relation_type": "trigger",
                                "upstream": [],
                                "downstream": [],
                            }
                        )

                    for condition_entity in automation_data.get("conditions", []):
                        if condition_entity != item_id and not condition_entity.startswith(
                            "device:"
                        ):
                            condition_friendly_name = _get_friendly_name(
                                condition_entity, automations, scripts, entities, hass
                            )
                            upstream_item["upstream"].append(
                            {
                                "item_type": "entity",
                                "item_id": condition_entity,
                                "friendly_name": condition_friendly_name,
                                "relation_type": "condition",
                                "upstream": [],
                                "downstream": [],
                            }
                        )                    # Add direct downstream relationships for this automation (its outputs)
                    for output_item in automation_data.get("outputs", []):
                        if output_item != item_id and not output_item.startswith(
                            ("service:", "device:")
                        ):
                            # Determine if this is a script call or entity
                            if output_item.startswith("script."):
                                output_item_type = "script"
                            else:
                                output_item_type = "entity"

                            output_friendly_name = _get_friendly_name(
                                output_item, automations, scripts, entities, hass
                            )
                            upstream_item["downstream"].append(
                            {
                                "item_type": output_item_type,
                                "item_id": output_item,
                                "friendly_name": output_friendly_name,
                                "relation_type": "output",
                                "upstream": [],
                                "downstream": [],
                            }
                        )

                # Recursively process upstream for this automation
                if max_depth == 0 or current_depth < max_depth - 1:
                    recursive_upstream = process_upstream(
                        max_depth,
                        automations,
                        scripts,
                        entities,
                        "automation",
                        automation_data["id"],
                        hass,
                        current_depth + 1,
                        visited,
                    )
                    # Extend instead of replace to keep direct relationships
                    upstream_item["upstream"].extend(recursive_upstream)

                upstream.append(upstream_item)

        # Check scripts that OUTPUT TO this entity (controls it)
        for script_data in scripts.get("scripts", []):
            if item_id in script_data.get("outputs", []):
                friendly_name = script_data.get("friendly_name", script_data["id"])
                upstream_item = {
                    "item_type": "script",
                    "item_id": script_data["id"],
                    "friendly_name": friendly_name,
                    "relation_type": "output",  # This script outputs to this entity
                    "upstream": [],
                    "downstream": [],
                }

                # Add direct upstream relationships for this script (its conditions)
                # Scripts don't typically have triggers, but they can have conditions
                for condition_entity in script_data.get("conditions", []):
                    if condition_entity != item_id and not condition_entity.startswith(
                        "device:"
                    ):
                        condition_friendly_name = _get_friendly_name(
                            condition_entity, automations, scripts, entities, hass
                        )
                        upstream_item["upstream"].append(
                            {
                                "item_type": "entity",
                                "item_id": condition_entity,
                                "friendly_name": condition_friendly_name,
                                "relation_type": "condition",
                                "upstream": [],
                                "downstream": [],
                            }
                        )

                # Add direct downstream relationships for this script (its outputs)
                for output_item in script_data.get("outputs", []):
                    if output_item != item_id and not output_item.startswith(
                        ("service:", "device:")
                    ):
                        # Determine if this is a script call or entity
                        if output_item.startswith("script."):
                            output_item_type = "script"
                        else:
                            output_item_type = "entity"

                        output_friendly_name = _get_friendly_name(
                            output_item, automations, scripts, entities, hass
                        )
                        upstream_item["downstream"].append(
                            {
                                "item_type": output_item_type,
                                "item_id": output_item,
                                "friendly_name": output_friendly_name,
                                "relation_type": "output",
                                "upstream": [],
                                "downstream": [],
                            }
                        )

                # Recursively process upstream for this script
                if max_depth == 0 or current_depth < max_depth - 1:
                    recursive_upstream = process_upstream(
                        max_depth,
                        automations,
                        scripts,
                        entities,
                        "script",
                        script_data["id"],
                        hass,
                        current_depth + 1,
                        visited,
                    )
                    # Extend instead of replace to keep direct relationships
                    upstream_item["upstream"].extend(recursive_upstream)

                upstream.append(upstream_item)

    return upstream


def process_downstream(
    max_depth: int,
    automations: dict[str, Any],
    scripts: dict[str, Any],
    entities: dict[str, Any],
    item_type: str,
    item_id: str,
    hass: HomeAssistant | None = None,
    current_depth: int = 0,
    visited: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Process downstream relations for a given item recursively.

    Args:
        max_depth: Maximum depth for relationship traversal
        automations: Preprocessed automations data
        scripts: Preprocessed scripts data
        entities: Preprocessed entities data
        item_type: Type of item to analyze ('entity', 'automation', or 'script')
        item_id: Unique identifier of the item to analyze
        hass: Home Assistant instance for accessing current state
        current_depth: Current depth in the recursion
        visited: Set of visited items to prevent circular references

    Returns:
        List of downstream relations

    """
    if visited is None:
        visited = set()

    # Create unique identifier for this item
    unique_key = f"{item_type}:{item_id}"

    # Check for circular reference
    if unique_key in visited:
        return []

    # Add to visited set
    visited = visited.copy()  # Create new copy to avoid modifying parent's set
    visited.add(unique_key)

    downstream = []

    # Stop recursion if we've reached max depth
    if max_depth > 0 and current_depth >= max_depth:
        return downstream

    # Find downstream relations for any item type
    if item_type in ("entity", "automation", "script"):
        downstream.extend(
            _find_downstream_for_item(
                item_id,
                item_type,
                automations,
                scripts,
                entities,
                max_depth,
                current_depth,
                visited,
                hass,
            )
        )

    return downstream


def _find_downstream_for_item(
    item_id: str,
    item_type: str,
    automations: dict[str, Any],
    scripts: dict[str, Any],
    entities: dict[str, Any],
    max_depth: int,
    current_depth: int,
    visited: set[str],
    hass: HomeAssistant | None = None,
) -> list[dict[str, Any]]:
    """Find downstream relations for any item type."""
    downstream = []

    # For entities: find automations/scripts that use this entity, and entities that depend on this entity
    if item_type == "entity":
        # Find automations that use this entity in triggers or conditions
        for automation_data in automations.get("automations", []):
            # Determine relation type based on how entity is used
            relation_type = "trigger"
            if item_id in automation_data.get("conditions", []):
                relation_type = "condition"
            elif item_id in automation_data.get("triggers", []):
                relation_type = "trigger"
            else:
                continue  # Entity not used by this automation

            friendly_name = automation_data.get("friendly_name", automation_data["id"])
            downstream_item = {
                "item_type": "automation",
                "item_id": automation_data["id"],
                "friendly_name": friendly_name,
                "relation_type": relation_type,  # How the entity is used by this automation
                "upstream": [],
                "downstream": [],
            }

            # Add direct upstream relationships for this automation (its triggers and conditions)
            # excluding the current item to avoid immediate circular reference
            for trigger_entity in automation_data.get("triggers", []):
                if trigger_entity != item_id and not trigger_entity.startswith(
                    ("service:", "device:")
                ):
                    trigger_friendly_name = _get_friendly_name(
                        trigger_entity, automations, scripts, entities, hass
                    )
                    downstream_item["upstream"].append(
                        {
                            "item_type": "entity",
                            "item_id": trigger_entity,
                            "friendly_name": trigger_friendly_name,
                            "relation_type": "trigger",
                            "upstream": [],
                            "downstream": [],
                        }
                    )

            for condition_entity in automation_data.get("conditions", []):
                if condition_entity != item_id and not condition_entity.startswith(
                    "device:"
                ):
                    condition_friendly_name = _get_friendly_name(
                        condition_entity, automations, scripts, entities, hass
                    )
                    downstream_item["upstream"].append(
                        {
                            "item_type": "entity",
                            "item_id": condition_entity,
                            "friendly_name": condition_friendly_name,
                            "relation_type": "condition",
                            "upstream": [],
                            "downstream": [],
                        }
                    )

            # Add direct downstream relationships for this automation (its outputs)
            for output_item in automation_data.get("outputs", []):
                if output_item != item_id and not output_item.startswith(
                    ("service:", "device:")
                ):
                    # Determine if this is a script call or entity
                    if output_item.startswith("script."):
                        output_item_type = "script"
                    else:
                        output_item_type = "entity"

                    output_friendly_name = _get_friendly_name(
                        output_item, automations, scripts, entities, hass
                    )
                    downstream_item["downstream"].append(
                        {
                            "item_type": output_item_type,
                            "item_id": output_item,
                            "friendly_name": output_friendly_name,
                            "relation_type": "output",
                            "upstream": [],
                            "downstream": [],
                        }
                    )

            # Recursively process downstream for this automation
            if max_depth == 0 or current_depth < max_depth - 1:
                recursive_downstream = process_downstream(
                    max_depth,
                    automations,
                    scripts,
                    entities,
                    "automation",
                    automation_data["id"],
                    hass,
                    current_depth + 1,
                    visited,
                )
                # Extend instead of replace to keep direct relationships
                downstream_item["downstream"].extend(recursive_downstream)

            downstream.append(downstream_item)

        # Find scripts that use this entity in conditions/triggers
        for script_data in scripts.get("scripts", []):
            relation_type = None
            if item_id in script_data.get("conditions", []):
                relation_type = "condition"
            elif item_id in script_data.get(
                "triggers", []
            ):  # Scripts can have triggers too
                relation_type = "trigger"
            else:
                continue  # Entity not used by this script

            friendly_name = script_data.get("friendly_name", script_data["id"])
            downstream_item = {
                "item_type": "script",
                "item_id": script_data["id"],
                "friendly_name": friendly_name,
                "relation_type": relation_type,  # How the entity is used by this script
                "upstream": [],
                "downstream": [],
            }

            # Add direct upstream relationships for this script (its conditions)
            # Scripts don't typically have triggers, but they can have conditions
            for condition_entity in script_data.get("conditions", []):
                if condition_entity != item_id and not condition_entity.startswith(
                    "device:"
                ):
                    condition_friendly_name = _get_friendly_name(
                        condition_entity, automations, scripts, entities, hass
                    )
                    downstream_item["upstream"].append(
                        {
                            "item_type": "entity",
                            "item_id": condition_entity,
                            "friendly_name": condition_friendly_name,
                            "relation_type": "condition",
                            "upstream": [],
                            "downstream": [],
                        }
                    )

            # Add direct downstream relationships for this script (its outputs)
            for output_item in script_data.get("outputs", []):
                if output_item != item_id and not output_item.startswith(
                    ("service:", "device:")
                ):
                    # Determine if this is a script call or entity
                    if output_item.startswith("script."):
                        output_item_type = "script"
                    else:
                        output_item_type = "entity"

                    output_friendly_name = _get_friendly_name(
                        output_item, automations, scripts, entities, hass
                    )
                    downstream_item["downstream"].append(
                        {
                            "item_type": output_item_type,
                            "item_id": output_item,
                            "friendly_name": output_friendly_name,
                            "relation_type": "output",
                            "upstream": [],
                            "downstream": [],
                        }
                    )

            # Recursively process downstream for this script
            if max_depth == 0 or current_depth < max_depth - 1:
                recursive_downstream = process_downstream(
                    max_depth,
                    automations,
                    scripts,
                    entities,
                    "script",
                    script_data["id"],
                    hass,
                    current_depth + 1,
                    visited,
                )
                # Extend instead of replace to keep direct relationships
                downstream_item["downstream"].extend(recursive_downstream)

            downstream.append(downstream_item)

        # Find entities that depend on this entity (template sensors, utility meters, etc.)
        for entity_data in entities.get("entities", []):
            relation_type = None
            if item_id in entity_data.get("triggers", []):
                relation_type = "trigger"
            elif item_id in entity_data.get("conditions", []):
                relation_type = "condition"
            else:
                continue  # Entity doesn't depend on this entity

            friendly_name = entity_data.get("friendly_name", entity_data["id"])
            downstream_item = {
                "item_type": "entity",
                "item_id": entity_data["id"],
                "friendly_name": friendly_name,
                "relation_type": relation_type,  # How this entity depends on the source entity
                "upstream": [],
                "downstream": [],
            }

            # Recursively process downstream for this entity
            if max_depth == 0 or current_depth < max_depth - 1:
                downstream_item["downstream"] = process_downstream(
                    max_depth,
                    automations,
                    scripts,
                    entities,
                    "entity",
                    entity_data["id"],
                    hass,
                    current_depth + 1,
                    visited,
                )

            downstream.append(downstream_item)

    # For automations/scripts: find their outputs (entities they control and scripts they call)
    elif item_type in ("automation", "script"):
        # Get the data collection based on item type
        if item_type == "automation":
            data_collection = automations.get("automations", [])
        else:
            data_collection = scripts.get("scripts", [])

        # Find the specific item
        for item_data in data_collection:
            if item_data["id"] == item_id:
                # Add outputs as downstream
                for output_item in item_data.get("outputs", []):
                    # Skip service calls and device outputs for now
                    if output_item.startswith(("service:", "device:")):
                        continue

                    # Determine if this is a script call or entity
                    if output_item.startswith("script."):
                        downstream_item_type = "script"
                    else:
                        downstream_item_type = "entity"

                    friendly_name = _get_friendly_name(
                        output_item, automations, scripts, entities, hass
                    )
                    downstream_item = {
                        "item_type": downstream_item_type,
                        "item_id": output_item,
                        "friendly_name": friendly_name,
                        "relation_type": "output",
                        "upstream": [],
                        "downstream": [],
                    }

                    # Recursively process downstream for this output
                    if max_depth == 0 or current_depth < max_depth - 1:
                        downstream_item["downstream"] = process_downstream(
                            max_depth,
                            automations,
                            scripts,
                            entities,
                            downstream_item_type,
                            output_item,
                            hass,
                            current_depth + 1,
                            visited,
                        )

                    downstream.append(downstream_item)
                break

    return downstream


def _get_friendly_name(
    item_id: str,
    automations: dict[str, Any],
    scripts: dict[str, Any],
    entities: dict[str, Any],
    hass: HomeAssistant | None = None,
) -> str:
    """Get friendly name for an item."""
    # Check entities first
    for entity_data in entities.get("entities", []):
        if entity_data["id"] == item_id:
            return entity_data.get("friendly_name", item_id)

    # If not found in processed entities and we have hass, try getting from state
    if hass and item_id.count(".") == 1:  # Looks like an entity ID
        state = hass.states.get(item_id)
        if state:
            return state.attributes.get("friendly_name", item_id)

    # Check automations
    for automation_data in automations.get("automations", []):
        if automation_data["id"] == item_id:
            return automation_data.get("friendly_name", item_id)

    # Check scripts
    for script_data in scripts.get("scripts", []):
        if script_data["id"] == item_id:
            return script_data.get("friendly_name", item_id)

    # Return the item_id as fallback
    return item_id
