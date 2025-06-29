"""Integration for Advanced relations."""

from __future__ import annotations
from pathlib import Path
import logging
import yaml
from typing import Any

from .const import DOMAIN
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.http import HomeAssistantView


_LOGGER = logging.getLogger(__name__)


_Entities: list[dict[str, Any]] = []
_Automations: list[dict[str, str]] = []  # Each dict: {"id": ..., "alias": ...}
_Scripts: list[dict[str, str]] = []  # Each dict: {"id": ..., "alias": ...}
_Templates: list[dict[str, Any]]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Advanced relations integration from yaml (noop)."""
    _LOGGER.warning("=== ADVANCED RELATIONS INTEGRATION SETUP CALLED ===")
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Advanced relations from a config entry."""
    from homeassistant.components import frontend

    hass.http.register_static_path(
        "/advancedrelations-panel",
        hass.config.path("custom_components/advancedrelations/www"),
        cache_headers=True,
    )
    frontend.async_register_built_in_panel(
        hass,
        component_name="iframe",
        sidebar_title="Advanced Relations",
        sidebar_icon="mdi:graph",
        frontend_url_path="advancedrelations-panel",
        config={"url": "/advancedrelations-panel/index.html"},
        require_admin=True,
    )
    hass.http.register_view(AdvancedRelationsTriggerView)
    hass.http.register_view(AdvancedRelationsDataView)
    hass.http.register_view(AdvancedRelationsRelatedView)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry for Advanced relations."""
    return True


async def list_entities(hass):
    """List all entities with their entity_id and friendly_name."""
    _Entities.clear()
    for state in hass.states.async_all():
        friendly_name = state.attributes.get("friendly_name", state.entity_id)
        _Entities.append({"entity_id": state.entity_id, "friendly_name": friendly_name})
    _LOGGER.info("=== Entities with friendly names read and stored in _Entities ===")


async def list_automations(hass):
    """List all automations as dicts with id and alias, and keep id->alias mapping for fast lookup."""
    _Automations.clear()
    automations_path = Path(hass.config.path("automations.yaml"))
    if automations_path.exists():
        try:
            content = await hass.async_add_executor_job(automations_path.read_text)
            yaml_data = yaml.safe_load(content)
            if isinstance(yaml_data, list):
                for automation in yaml_data:
                    if isinstance(automation, dict) and "id" in automation:
                        alias = automation.get("alias", str(automation["id"]))
                        entry = {"id": str(automation["id"]), "alias": alias}
                        _Automations.append(entry)
        except yaml.YAMLError as err:
            _LOGGER.error("Failed to parse automations.yaml: %s", err)
    _LOGGER.info(
        "=== Automations read and stored in _Automations and _AutomationIdToAlias ==="
    )


async def list_scripts(hass):
    """List all scripts as dicts with id and alias."""
    _Scripts.clear()
    scripts_path = Path(hass.config.path("scripts.yaml"))
    if scripts_path.exists():
        try:
            content = await hass.async_add_executor_job(scripts_path.read_text)
            yaml_data = yaml.safe_load(content)
            if isinstance(yaml_data, dict):
                for script_id, script in yaml_data.items():
                    if isinstance(script, dict):
                        alias = script.get("alias", script_id)
                        entry = {"id": script_id, "alias": alias}
                        _Scripts.append(entry)
        except yaml.YAMLError as err:
            _LOGGER.error("Failed to parse scripts.yaml: %s", err)
    _LOGGER.info("=== Scripts read and stored in _Scripts ===")


class AdvancedRelationsTriggerView(HomeAssistantView):
    """View to trigger backend processing when the page is opened."""

    url = "/api/advancedrelations/trigger"
    name = "api:advancedrelations:trigger"
    requires_auth = False  # Allow unauthenticated access for internal panel use

    async def post(self, request):
        """Trigger backend processing when called from the frontend."""
        _LOGGER.warning("=== POST /api/advancedrelations/trigger called ===")
        hass = request.app["hass"]
        # Call your backend processing function
        await list_entities(hass)
        await list_automations(hass)
        await list_scripts(hass)
        return self.json({"status": "triggered"})


class AdvancedRelationsDataView(HomeAssistantView):
    """View to provide entities, automations, and scripts as JSON."""

    url = "/api/advancedrelations/data"
    name = "api:advancedrelations:data"
    requires_auth = False

    async def get(self, request):
        hass = request.app["hass"]
        await list_entities(hass)
        await list_automations(hass)
        await list_scripts(hass)
        return self.json(
            {
                "entities": _Entities,
                "automations": _Automations,
                "scripts": _Scripts,
            }
        )


class AdvancedRelationsRelatedView(HomeAssistantView):
    """View to provide related automations/scripts/entities for a selected item."""

    url = "/api/advancedrelations/related"
    name = "api:advancedrelations:related"
    requires_auth = False

    async def get(self, request):
        """Return a tree of related items for the selected entity/automation/script."""
        hass = request.app["hass"]
        await list_entities(hass)
        await list_automations(hass)
        await list_scripts(hass)
        q_type = request.query.get("type")
        q_id = request.query.get("id")
        if not q_type or not q_id:
            return self.json({"error": "Missing type or id"}, status_code=400)

        try:
            builder = RelationsTreeBuilder(hass)
            tree = builder.build_relations_tree(q_type, q_id)
            return self.json({"root": tree})
        except (yaml.YAMLError, FileNotFoundError, KeyError) as err:
            _LOGGER.error("Error building relations tree: %s", err)
            return self.json(
                {"error": f"Failed to build relations tree: {err}"}, status_code=500
            )


class RelationsTreeBuilder:
    """Helper class to build relations trees."""

    def __init__(self, hass):
        """Initialize the builder."""
        self.hass = hass
        self._automations_data = None
        self._scripts_data = None

    def _safe_get_list(self, data, key, default=None):
        """Safely get a list from dict, handling None values."""
        if default is None:
            default = []
        value = data.get(key, default)
        return value if value is not None else default

    def get_automations_data(self):
        """Get cached automations data."""
        if self._automations_data is None:
            automations_path = Path(self.hass.config.path("automations.yaml"))
            if automations_path.exists():
                try:
                    content = automations_path.read_text()
                    self._automations_data = yaml.safe_load(content) or []
                except (yaml.YAMLError, FileNotFoundError) as err:
                    _LOGGER.error("Failed to parse automations.yaml: %s", err)
                    self._automations_data = []
            else:
                self._automations_data = []
        return self._automations_data

    def get_scripts_data(self):
        """Get cached scripts data."""
        if self._scripts_data is None:
            scripts_path = Path(self.hass.config.path("scripts.yaml"))
            if scripts_path.exists():
                try:
                    content = scripts_path.read_text()
                    self._scripts_data = yaml.safe_load(content) or {}
                except (yaml.YAMLError, FileNotFoundError) as err:
                    _LOGGER.error("Failed to parse scripts.yaml: %s", err)
                    self._scripts_data = {}
            else:
                self._scripts_data = {}
        return self._scripts_data

    def get_entity_friendly_name(self, entity_id):
        """Get friendly name for entity."""
        for ent in _Entities:
            if ent["entity_id"] == entity_id:
                return ent.get("friendly_name", entity_id)
        return entity_id

    def get_automation_label(self, automation):
        """Get label for automation."""
        return f"{automation.get('alias', automation.get('id', '?'))} ({automation.get('id', '?')})"

    def get_script_label(self, script_id, script):
        """Get label for script."""
        return f"{script.get('alias', script_id)} ({script_id})"

    def extract_entities_from_value(self, value):
        """Recursively extract entity IDs from any YAML structure."""
        entities = set()
        if isinstance(value, str):
            # Check if it looks like an entity ID (domain.entity_name)
            if (
                "." in value
                and not value.startswith("{{")
                and not value.startswith("{%")
            ):
                # Basic entity ID pattern check
                parts = value.split(".")
                if len(parts) == 2 and parts[0] and parts[1]:
                    # Avoid false positives like file paths, URLs, etc.
                    if not any(char in value for char in ["/", "://", "@", " "]):
                        entities.add(value)
            # Also extract from templates (basic extraction)
            elif "{{" in value or "{%" in value:
                import re

                # Extract entity IDs from templates like {{ states('sensor.temperature') }}
                template_entities = re.findall(r'states\([\'"]([^\'")]+)[\'"]\)', value)
                for entity_id in template_entities:
                    if "." in entity_id:
                        entities.add(entity_id)
                # Extract from state_attr calls
                state_attr_entities = re.findall(
                    r'state_attr\([\'"]([^\'")]+)[\'"]\s*,', value
                )
                for entity_id in state_attr_entities:
                    if "." in entity_id:
                        entities.add(entity_id)
                # Extract from is_state calls
                is_state_entities = re.findall(
                    r'is_state\([\'"]([^\'")]+)[\'"]\s*,', value
                )
                for entity_id in is_state_entities:
                    if "." in entity_id:
                        entities.add(entity_id)
        elif isinstance(value, list):
            for item in value:
                entities.update(self.extract_entities_from_value(item))
        elif isinstance(value, dict):
            for key, val in value.items():
                if key in ["entity_id", "entity_ids"]:
                    entities.update(self.extract_entities_from_value(val))
                elif key == "target" and isinstance(val, dict):
                    entities.update(
                        self.extract_entities_from_value(val.get("entity_id", []))
                    )
                elif key in ["device_id", "area_id"]:
                    # Skip device and area IDs
                    continue
                else:
                    # Recursively check nested structures
                    entities.update(self.extract_entities_from_value(val))
        return entities

    def find_triggers_in_automation(self, automation):
        """Find all trigger entities in an automation."""
        triggers = set()
        for trigger_list in [
            automation.get("trigger", []),
            automation.get("triggers", []),
        ]:
            for trig in (
                trigger_list if isinstance(trigger_list, list) else [trigger_list]
            ):
                if isinstance(trig, dict):
                    triggers.update(self.extract_entities_from_value(trig))
        return triggers

    def find_conditions_in_automation(self, automation):
        """Find all condition entities in an automation."""
        conditions = set()
        for condition_list in [
            automation.get("condition", []),
            automation.get("conditions", []),
        ]:
            for cond in (
                condition_list if isinstance(condition_list, list) else [condition_list]
            ):
                if isinstance(cond, dict):
                    conditions.update(self.extract_entities_from_value(cond))

        # Also check conditions in action blocks (like choose, if, etc.)
        for action_list in [
            automation.get("action", []),
            automation.get("actions", []),
        ]:
            for action in (
                action_list if isinstance(action_list, list) else [action_list]
            ):
                if isinstance(action, dict):
                    conditions.update(self.find_conditions_in_action_block(action))
        return conditions

    def find_conditions_in_action_block(self, action):
        """Recursively find conditions in action blocks."""
        conditions = set()
        if isinstance(action, dict):
            # Check if this action has conditions
            for cond in action.get("condition", []):
                if isinstance(cond, dict):
                    conditions.update(self.extract_entities_from_value(cond))

            # Check choose/if blocks
            if "choose" in action:
                for choice in action["choose"]:
                    if isinstance(choice, dict):
                        for cond in choice.get("conditions", []):
                            conditions.update(self.extract_entities_from_value(cond))
                        # Recursively check sequence actions
                        sequence = self._safe_get_list(choice, "sequence")
                        for seq_action in sequence:
                            conditions.update(
                                self.find_conditions_in_action_block(seq_action)
                            )

            # Check if blocks
            if "if" in action:
                conditions.update(self.extract_entities_from_value(action["if"]))
                then_actions = self._safe_get_list(action, "then")
                for seq_action in then_actions:
                    conditions.update(self.find_conditions_in_action_block(seq_action))
                else_actions = self._safe_get_list(action, "else")
                for seq_action in else_actions:
                    conditions.update(self.find_conditions_in_action_block(seq_action))

            # Check repeat blocks
            if "repeat" in action:
                repeat_block = action["repeat"]
                if isinstance(repeat_block, dict):
                    conditions.update(
                        self.extract_entities_from_value(repeat_block.get("until", {}))
                    )
                    conditions.update(
                        self.extract_entities_from_value(repeat_block.get("while", {}))
                    )
                    sequence = self._safe_get_list(repeat_block, "sequence")
                    for seq_action in sequence:
                        conditions.update(
                            self.find_conditions_in_action_block(seq_action)
                        )

        return conditions

    def find_outputs_in_automation(self, automation):
        """Find all output entities in an automation."""
        outputs = set()
        for action_list in [
            automation.get("action", []),
            automation.get("actions", []),
        ]:
            for action in (
                action_list if isinstance(action_list, list) else [action_list]
            ):
                if isinstance(action, dict):
                    outputs.update(self.find_outputs_in_action_block(action))
        return outputs

    def find_outputs_in_action_block(self, action):
        """Recursively find outputs in action blocks."""
        outputs = set()
        if isinstance(action, dict):
            # Services that modify entities
            service_actions = ["service", "action"]
            for service_key in service_actions:
                if service_key in action:
                    service = action[service_key]
                    # Check for entity modifications
                    service_keywords = [
                        "turn_on",
                        "turn_off",
                        "toggle",
                        "set_",
                        "call",
                        "trigger",
                        "start",
                        "stop",
                        "pause",
                        "play",
                    ]
                    if any(
                        keyword in str(service).lower() for keyword in service_keywords
                    ):
                        outputs.update(
                            self.extract_entities_from_value(
                                action.get("entity_id", [])
                            )
                        )
                        outputs.update(
                            self.extract_entities_from_value(action.get("target", {}))
                        )

                    # Script and automation calls
                    service_str = str(service).lower()
                    if "script." in service_str or "automation." in service_str:
                        if "entity_id" in action:
                            entity_ids = action["entity_id"]
                            if isinstance(entity_ids, str):
                                outputs.add(f"script_call:{entity_ids}")
                            elif isinstance(entity_ids, list):
                                for eid in entity_ids:
                                    outputs.add(f"script_call:{eid}")
                        if "target" in action and isinstance(action["target"], dict):
                            target_entities = self._safe_get_list(
                                action["target"], "entity_id"
                            )
                            if isinstance(target_entities, str):
                                outputs.add(f"script_call:{target_entities}")
                            elif isinstance(target_entities, list):
                                for eid in target_entities:
                                    outputs.add(f"script_call:{eid}")

            # Direct entity_id assignments (for any service call)
            outputs.update(
                self.extract_entities_from_value(action.get("entity_id", []))
            )
            outputs.update(self.extract_entities_from_value(action.get("target", {})))

            # Check nested blocks
            if "choose" in action:
                for choice in action["choose"]:
                    if isinstance(choice, dict):
                        for seq_action in self._safe_get_list(choice, "sequence"):
                            outputs.update(
                                self.find_outputs_in_action_block(seq_action)
                            )

            if "if" in action:
                for seq_action in self._safe_get_list(action, "then"):
                    outputs.update(self.find_outputs_in_action_block(seq_action))
                for seq_action in self._safe_get_list(action, "else"):
                    outputs.update(self.find_outputs_in_action_block(seq_action))

            if "repeat" in action:
                repeat_block = action["repeat"]
                if isinstance(repeat_block, dict):
                    for seq_action in self._safe_get_list(repeat_block, "sequence"):
                        outputs.update(self.find_outputs_in_action_block(seq_action))

        return outputs

    def find_conditions_in_script(self, script):
        """Find all condition entities in a script."""
        conditions = set()
        for step in self._safe_get_list(script, "sequence"):
            if isinstance(step, dict):
                conditions.update(self.find_conditions_in_action_block(step))
        return conditions

    def find_outputs_in_script(self, script):
        """Find all output entities in a script."""
        outputs = set()
        for step in self._safe_get_list(script, "sequence"):
            if isinstance(step, dict):
                outputs.update(self.find_outputs_in_action_block(step))
        return outputs

    def build_relations_tree(
        self, start_type, start_id, visited=None, max_depth=5, current_depth=0
    ):
        """Build a comprehensive relations tree with triggers, conditions, and outputs."""
        if visited is None:
            visited = set()

        # Create unique key for this item
        item_key = f"{start_type}:{start_id}"

        # If we've already processed this item or reached max depth, return a reference
        if item_key in visited or current_depth >= max_depth:
            label = self._get_item_label(start_type, start_id)
            return {
                "label": f"{label} (already shown above)"
                if item_key in visited
                else label,
                "type": start_type,
                "id": start_id,
                "children": [],
                "is_reference": item_key in visited,
            }

        # Add to visited set
        visited.add(item_key)

        if start_type == "entity":
            return self._build_entity_node(start_id, visited, max_depth, current_depth)

        if start_type == "automation":
            return self._build_automation_node(
                start_id, visited, max_depth, current_depth
            )

        if start_type == "script":
            return self._build_script_node(start_id, visited, max_depth, current_depth)

        return {"label": start_id, "type": start_type, "id": start_id, "children": []}

    def _get_item_label(self, start_type, start_id):
        """Get label for any item type."""
        if start_type == "entity":
            return self.get_entity_friendly_name(start_id)

        if start_type == "automation":
            for auto in self.get_automations_data():
                if str(auto.get("id")) == start_id:
                    return self.get_automation_label(auto)
            return start_id

        if start_type == "script":
            scripts_data = self.get_scripts_data()
            script = scripts_data.get(start_id, {})
            return self.get_script_label(start_id, script)

        return start_id

    def _build_entity_node(self, start_id, visited, max_depth, current_depth):
        """Build node for entity."""
        label = self.get_entity_friendly_name(start_id)
        node = {
            "label": label,
            "type": "entity",
            "id": start_id,
            "children": [],
            "triggers": [],
            "conditions": [],
            "outputs": [],
        }

        # Find automations where this entity is involved
        for automation in self.get_automations_data():
            auto_id = str(automation.get("id", ""))
            if not auto_id:
                continue

            triggers = self.find_triggers_in_automation(automation)
            conditions = self.find_conditions_in_automation(automation)
            outputs = self.find_outputs_in_automation(automation)

            if start_id in triggers:
                child_node = self.build_relations_tree(
                    "automation", auto_id, visited.copy(), max_depth, current_depth + 1
                )
                child_node["relationship"] = "trigger"
                node["triggers"].append(child_node)

            if start_id in conditions:
                child_node = self.build_relations_tree(
                    "automation", auto_id, visited.copy(), max_depth, current_depth + 1
                )
                child_node["relationship"] = "condition"
                node["conditions"].append(child_node)

            if start_id in outputs:
                child_node = self.build_relations_tree(
                    "automation", auto_id, visited.copy(), max_depth, current_depth + 1
                )
                child_node["relationship"] = "output"
                node["outputs"].append(child_node)

        # Find scripts where this entity is involved
        scripts_data = self.get_scripts_data()
        for script_id, script in scripts_data.items():
            conditions = self.find_conditions_in_script(script)
            outputs = self.find_outputs_in_script(script)

            if start_id in conditions:
                child_node = self.build_relations_tree(
                    "script", script_id, visited.copy(), max_depth, current_depth + 1
                )
                child_node["relationship"] = "condition"
                node["conditions"].append(child_node)

            if start_id in outputs:
                child_node = self.build_relations_tree(
                    "script", script_id, visited.copy(), max_depth, current_depth + 1
                )
                child_node["relationship"] = "output"
                node["outputs"].append(child_node)

        # Flatten children for display
        node["children"] = node["triggers"] + node["conditions"] + node["outputs"]
        return node

    def _build_automation_node(self, start_id, visited, max_depth, current_depth):
        """Build node for automation."""
        # Find the automation
        automation = None
        for auto in self.get_automations_data():
            if str(auto.get("id")) == start_id:
                automation = auto
                break

        if not automation:
            return {
                "label": start_id,
                "type": "automation",
                "id": start_id,
                "children": [],
            }

        label = self.get_automation_label(automation)
        node = {
            "label": label,
            "type": "automation",
            "id": start_id,
            "children": [],
            "triggers": [],
            "conditions": [],
            "outputs": [],
        }

        # Find other automations that trigger this automation
        for other_automation in self.get_automations_data():
            other_id = str(other_automation.get("id", ""))
            if other_id != start_id:
                outputs = self.find_outputs_in_automation(other_automation)
                automation_calls = [
                    f"script_call:automation.{start_id}",
                    f"automation.{start_id}",
                ]
                if any(call in outputs for call in automation_calls):
                    child_node = self.build_relations_tree(
                        "automation",
                        other_id,
                        visited.copy(),
                        max_depth,
                        current_depth + 1,
                    )
                    child_node["relationship"] = "trigger"
                    node["triggers"].append(child_node)

        # Find scripts that trigger this automation
        scripts_data = self.get_scripts_data()
        for script_id, script in scripts_data.items():
            outputs = self.find_outputs_in_script(script)
            automation_calls = [
                f"script_call:automation.{start_id}",
                f"automation.{start_id}",
            ]
            if any(call in outputs for call in automation_calls):
                child_node = self.build_relations_tree(
                    "script", script_id, visited.copy(), max_depth, current_depth + 1
                )
                child_node["relationship"] = "trigger"
                node["triggers"].append(child_node)

        # Get all entities involved in this automation
        trigger_entities = self.find_triggers_in_automation(automation)
        condition_entities = self.find_conditions_in_automation(automation)
        output_entities = self.find_outputs_in_automation(automation)

        # Add trigger entities
        for entity_id in trigger_entities:
            if not entity_id.startswith("script_call:"):
                child_node = self.build_relations_tree(
                    "entity", entity_id, visited.copy(), max_depth, current_depth + 1
                )
                child_node["relationship"] = "trigger"
                node["triggers"].append(child_node)

        # Add condition entities
        for entity_id in condition_entities:
            if not entity_id.startswith("script_call:"):
                child_node = self.build_relations_tree(
                    "entity", entity_id, visited.copy(), max_depth, current_depth + 1
                )
                child_node["relationship"] = "condition"
                node["conditions"].append(child_node)

        # Add output entities and called scripts/automations
        for entity_id in output_entities:
            if entity_id.startswith("script_call:"):
                called_item = entity_id.replace("script_call:", "")
                if called_item.startswith("script."):
                    called_script_id = called_item.replace("script.", "")
                    child_node = self.build_relations_tree(
                        "script",
                        called_script_id,
                        visited.copy(),
                        max_depth,
                        current_depth + 1,
                    )
                    child_node["relationship"] = "output"
                    node["outputs"].append(child_node)
                elif called_item.startswith("automation."):
                    called_auto_id = called_item.replace("automation.", "")
                    child_node = self.build_relations_tree(
                        "automation",
                        called_auto_id,
                        visited.copy(),
                        max_depth,
                        current_depth + 1,
                    )
                    child_node["relationship"] = "output"
                    node["outputs"].append(child_node)
                else:
                    # Assume it's a script if no domain prefix
                    child_node = self.build_relations_tree(
                        "script",
                        called_item,
                        visited.copy(),
                        max_depth,
                        current_depth + 1,
                    )
                    child_node["relationship"] = "output"
                    node["outputs"].append(child_node)
            else:
                child_node = self.build_relations_tree(
                    "entity", entity_id, visited.copy(), max_depth, current_depth + 1
                )
                child_node["relationship"] = "output"
                node["outputs"].append(child_node)

        # Flatten children for display
        node["children"] = node["triggers"] + node["conditions"] + node["outputs"]
        return node

    def _build_script_node(self, start_id, visited, max_depth, current_depth):
        """Build node for script."""
        scripts_data = self.get_scripts_data()
        script = scripts_data.get(start_id, {})

        label = self.get_script_label(start_id, script)
        node = {
            "label": label,
            "type": "script",
            "id": start_id,
            "children": [],
            "triggers": [],
            "conditions": [],
            "outputs": [],
        }

        # Find automations that trigger this script
        for automation in self.get_automations_data():
            outputs = self.find_outputs_in_automation(automation)
            script_calls = [
                f"script_call:script.{start_id}",
                f"script_call:{start_id}",
                f"script.{start_id}",
            ]
            if any(call in outputs for call in script_calls):
                auto_id = str(automation.get("id", ""))
                if auto_id:
                    child_node = self.build_relations_tree(
                        "automation",
                        auto_id,
                        visited.copy(),
                        max_depth,
                        current_depth + 1,
                    )
                    child_node["relationship"] = "trigger"
                    node["triggers"].append(child_node)

        # Find other scripts that trigger this script
        for script_id, other_script in scripts_data.items():
            if script_id != start_id:
                outputs = self.find_outputs_in_script(other_script)
                script_calls = [
                    f"script_call:script.{start_id}",
                    f"script_call:{start_id}",
                    f"script.{start_id}",
                ]
                if any(call in outputs for call in script_calls):
                    child_node = self.build_relations_tree(
                        "script",
                        script_id,
                        visited.copy(),
                        max_depth,
                        current_depth + 1,
                    )
                    child_node["relationship"] = "trigger"
                    node["triggers"].append(child_node)

        # Get entities involved in this script
        condition_entities = self.find_conditions_in_script(script)
        output_entities = self.find_outputs_in_script(script)

        # Add condition entities
        for entity_id in condition_entities:
            if not entity_id.startswith("script_call:"):
                child_node = self.build_relations_tree(
                    "entity", entity_id, visited.copy(), max_depth, current_depth + 1
                )
                child_node["relationship"] = "condition"
                node["conditions"].append(child_node)

        # Add output entities and called scripts/automations
        for entity_id in output_entities:
            if entity_id.startswith("script_call:"):
                called_item = entity_id.replace("script_call:", "")
                if called_item.startswith("script."):
                    called_script_id = called_item.replace("script.", "")
                    child_node = self.build_relations_tree(
                        "script",
                        called_script_id,
                        visited.copy(),
                        max_depth,
                        current_depth + 1,
                    )
                    child_node["relationship"] = "output"
                    node["outputs"].append(child_node)
                elif called_item.startswith("automation."):
                    called_auto_id = called_item.replace("automation.", "")
                    child_node = self.build_relations_tree(
                        "automation",
                        called_auto_id,
                        visited.copy(),
                        max_depth,
                        current_depth + 1,
                    )
                    child_node["relationship"] = "output"
                    node["outputs"].append(child_node)
                else:
                    # Assume it's a script if no domain prefix
                    child_node = self.build_relations_tree(
                        "script",
                        called_item,
                        visited.copy(),
                        max_depth,
                        current_depth + 1,
                    )
                    child_node["relationship"] = "output"
                    node["outputs"].append(child_node)
            else:
                child_node = self.build_relations_tree(
                    "entity", entity_id, visited.copy(), max_depth, current_depth + 1
                )
                child_node["relationship"] = "output"
                node["outputs"].append(child_node)

        # Flatten children for display
        node["children"] = node["triggers"] + node["conditions"] + node["outputs"]
        return node
