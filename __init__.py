"""Integration for Advanced relations."""

from __future__ import annotations

import itertools
import logging
from pathlib import Path

import yaml

from .const import DOMAIN
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.http import HomeAssistantView

_LOGGER = logging.getLogger(__name__)


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
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry for Advanced relations."""
    return True


async def read_automations_and_scripts(hass):
    """Read and process automations.yaml and scripts.yaml when called."""
    _LOGGER.info(
        "=== Read and process automations.yaml and scripts.yaml when called. ==="
    )
    automations_path = Path(hass.config.path("automations.yaml"))
    scripts_path = Path(hass.config.path("scripts.yaml"))
    processed = {"automations": [], "scripts": []}
    # Process automations.yaml
    if automations_path.exists():
        try:
            content = await hass.async_add_executor_job(automations_path.read_text)
            processed["automations"] = parse_automations_entities(content)
        except yaml.YAMLError:
            pass
    # Process scripts.yaml (parsing for scripts can be added similarly if needed)
    if scripts_path.exists():
        try:
            content = await hass.async_add_executor_job(scripts_path.read_text)
            processed["scripts"] = parse_scripts_entities(content)  # Placeholder for future
        except yaml.YAMLError:
            pass
    _LOGGER.info("Parsed automations: %s", processed["automations"])
    return processed


def extract_entities_from_trigger(trigger):
    """Extract entity_ids from a trigger dict or list."""
    entities = set()
    if isinstance(trigger, dict):
        if "entity_id" in trigger:
            val = trigger["entity_id"]
            if isinstance(val, str):
                entities.add(val)
            elif isinstance(val, list):
                entities.update(val)
    elif isinstance(trigger, list):
        for t in trigger:
            entities.update(extract_entities_from_trigger(t))
    return entities


def extract_entities_from_condition(condition):
    """Extract entity_ids from a condition dict or list."""
    entities = set()
    if isinstance(condition, dict):
        if "entity_id" in condition:
            val = condition["entity_id"]
            if isinstance(val, str):
                entities.add(val)
            elif isinstance(val, list):
                entities.update(val)
    elif isinstance(condition, list):
        for c in condition:
            entities.update(extract_entities_from_condition(c))
    return entities


def extract_entities_from_action(action):
    """Recursively extract output entity_ids from an action dict or list, including nested if/then/else."""
    entities = set()
    if isinstance(action, dict):
        # Check for target/entity_id
        if "target" in action and isinstance(action["target"], dict):
            target = action["target"]
            if "entity_id" in target:
                val = target["entity_id"]
                if isinstance(val, str):
                    entities.add(val)
                elif isinstance(val, list):
                    entities.update(val)
        if "entity_id" in action:
            val = action["entity_id"]
            if isinstance(val, str):
                entities.add(val)
            elif isinstance(val, list):
                entities.update(val)
        # Recursively handle 'if', 'then', 'else', and 'sequence' keys
        for key in ("if", "then", "else", "sequence", "actions"):
            if key in action:
                entities.update(extract_entities_from_action(action[key]))
    elif isinstance(action, list):
        for a in action:
            entities.update(extract_entities_from_action(a))
    return entities


def parse_automations_entities(automations_yaml: str):
    """Parse automations.yaml and extract triggers, conditions, outputs, and original YAML. Supports singular and plural keys."""
    import yaml

    automations = yaml.safe_load(automations_yaml)
    result = []
    if not isinstance(automations, list):
        return result
    for automation in automations:
        # Support both singular and plural keys
        triggers = automation.get("trigger") or automation.get("triggers") or []
        conditions = automation.get("condition") or automation.get("conditions") or []
        actions = automation.get("action") or automation.get("actions") or []
        # Store all triggers as-is (supporting any trigger type)
        trigger_list = triggers if isinstance(triggers, list) else [triggers]
        # Extract entity_ids from triggers (if present)
        trigger_entities = []
        for trig in trigger_list:
            if isinstance(trig, dict) and "entity_id" in trig:
                val = trig["entity_id"]
                if isinstance(val, str):
                    trigger_entities.append(val)
                elif isinstance(val, list):
                    trigger_entities.extend(val)
        condition_entities = list(extract_entities_from_condition(conditions))
        output_entities = list(extract_entities_from_action(actions))
        try:
            import yaml as _yaml

            original_yaml = _yaml.dump(automation, sort_keys=False, allow_unicode=True)
        except Exception:
            original_yaml = None
        result.append(
            {
                "id": automation.get("id"),
                "alias": automation.get("alias"),
                "triggers": trigger_list,  # Store all triggers, not just entity-based
                "trigger_entities": trigger_entities,
                "condition_entities": condition_entities,
                "output_entities": output_entities,
                "original_yaml": original_yaml,
            }
        )
    return result


def parse_scripts_entities(scripts_yaml: str):
    """Parse scripts.yaml and extract entities for conditions, outputs, and original YAML. Reuse automation parsing logic."""
    import yaml

    scripts = yaml.safe_load(scripts_yaml)
    result = []
    if not isinstance(scripts, dict):
        return result
    for script_id, script in scripts.items():
        # Support both singular and plural keys
        conditions = script.get("condition") or script.get("conditions") or []
        actions = script.get("action") or script.get("actions") or []
        condition_entities = list(extract_entities_from_condition(conditions))
        output_entities = list(extract_entities_from_action(actions))
        try:
            import yaml as _yaml

            original_yaml = _yaml.dump(script, sort_keys=False, allow_unicode=True)
        except Exception:
            original_yaml = None
        result.append(
            {
                "id": script_id,
                "alias": script.get("alias"),
                "condition_entities": condition_entities,
                "output_entities": output_entities,
                "original_yaml": original_yaml,
            }
        )
    return result


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
        await read_automations_and_scripts(hass)
        return self.json({"status": "triggered"})
