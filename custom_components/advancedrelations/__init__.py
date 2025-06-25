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

        def get_entity_friendly_name(entity_id):
            for ent in _Entities:
                if ent["entity_id"] == entity_id:
                    return ent.get("friendly_name", entity_id)
            return entity_id

        def get_automation_label(automation):
            return f"{automation.get('alias', automation.get('id', '?'))} ({automation.get('id', '?')})"

        def get_script_label(script_id, script):
            return f"{script.get('alias', script_id)} ({script_id})"

        def find_automations_with_entity(entity_id):
            automations = []
            automations_path = Path(hass.config.path("automations.yaml"))
            if automations_path.exists():
                try:
                    content = automations_path.read_text()
                    yaml_data = yaml.safe_load(content)
                    if isinstance(yaml_data, list):
                        for automation in yaml_data:
                            found = False
                            # Check triggers
                            for trig in automation.get("trigger", []) + automation.get(
                                "triggers", []
                            ):
                                if isinstance(trig, dict) and entity_id in str(
                                    trig.get("entity_id", "")
                                ):
                                    found = True
                            # Check conditions
                            for cond in automation.get(
                                "condition", []
                            ) + automation.get("conditions", []):
                                if isinstance(cond, dict) and entity_id in str(
                                    cond.get("entity_id", "")
                                ):
                                    found = True
                            # Check actions
                            for act in automation.get("action", []) + automation.get(
                                "actions", []
                            ):
                                if isinstance(act, dict) and entity_id in str(
                                    act.get("entity_id", "")
                                ):
                                    found = True
                            if found:
                                automations.append(automation)
                except Exception as err:
                    _LOGGER.error(
                        "Failed to parse automations.yaml for related: %s", err
                    )
            return automations

        def find_scripts_with_entity(entity_id):
            scripts = []
            scripts_path = Path(hass.config.path("scripts.yaml"))
            if scripts_path.exists():
                try:
                    content = scripts_path.read_text()
                    yaml_data = yaml.safe_load(content)
                    if isinstance(yaml_data, dict):
                        for script_id, script in yaml_data.items():
                            found = False
                            # Check sequence for entity_id
                            for step in script.get("sequence", []):
                                # Check for direct entity_id or target.entity_id
                                if isinstance(step, dict):
                                    if "entity_id" in step and entity_id in str(
                                        step["entity_id"]
                                    ):
                                        found = True
                                    if (
                                        "target" in step
                                        and isinstance(step["target"], dict)
                                        and entity_id
                                        in str(step["target"].get("entity_id", ""))
                                    ):
                                        found = True
                            if found:
                                scripts.append((script_id, script))
                except Exception as err:
                    _LOGGER.error("Failed to parse scripts.yaml for related: %s", err)
            return scripts

        def find_entities_in_automation(automation):
            entities = set()
            for trig in automation.get("trigger", []) + automation.get("triggers", []):
                if isinstance(trig, dict) and "entity_id" in trig:
                    val = trig["entity_id"]
                    if isinstance(val, str):
                        entities.add(val)
                    elif isinstance(val, list):
                        entities.update(val)
            for cond in automation.get("condition", []) + automation.get(
                "conditions", []
            ):
                if isinstance(cond, dict) and "entity_id" in cond:
                    val = cond["entity_id"]
                    if isinstance(val, str):
                        entities.add(val)
                    elif isinstance(val, list):
                        entities.update(val)
            for act in automation.get("action", []) + automation.get("actions", []):
                if isinstance(act, dict) and "entity_id" in act:
                    val = act["entity_id"]
                    if isinstance(val, str):
                        entities.add(val)
                    elif isinstance(val, list):
                        entities.update(val)
                if (
                    isinstance(act, dict)
                    and "target" in act
                    and isinstance(act["target"], dict)
                ):
                    val = act["target"].get("entity_id")
                    if isinstance(val, str):
                        entities.add(val)
                    elif isinstance(val, list):
                        entities.update(val)
            return list(entities)

        def find_entities_in_script(script):
            entities = set()
            for step in script.get("sequence", []):
                if isinstance(step, dict):
                    if "entity_id" in step:
                        val = step["entity_id"]
                        if isinstance(val, str):
                            entities.add(val)
                        elif isinstance(val, list):
                            entities.update(val)
                    if "target" in step and isinstance(step["target"], dict):
                        val = step["target"].get("entity_id")
                        if isinstance(val, str):
                            entities.add(val)
                        elif isinstance(val, list):
                            entities.update(val)
            return list(entities)

        def build_tree_for_entity(entity_id):
            root = {
                "label": get_entity_friendly_name(entity_id),
                "type": "entity",
                "children": [],
            }
            # Automations
            for automation in find_automations_with_entity(entity_id):
                auto_node = {
                    "label": get_automation_label(automation),
                    "type": "automation",
                    "children": [],
                }
                for affected in find_entities_in_automation(automation):
                    auto_node["children"].append(
                        {
                            "label": get_entity_friendly_name(affected),
                            "type": "entity",
                            "children": [],
                        }
                    )
                root["children"].append(auto_node)
            # Scripts
            for script_id, script in find_scripts_with_entity(entity_id):
                script_node = {
                    "label": get_script_label(script_id, script),
                    "type": "script",
                    "children": [],
                }
                for affected in find_entities_in_script(script):
                    script_node["children"].append(
                        {
                            "label": get_entity_friendly_name(affected),
                            "type": "entity",
                            "children": [],
                        }
                    )
                root["children"].append(script_node)
            return {"root": root}

        def build_tree_for_automation(automation_id):
            automations_path = Path(hass.config.path("automations.yaml"))
            if automations_path.exists():
                try:
                    content = automations_path.read_text()
                    yaml_data = yaml.safe_load(content)
                    if isinstance(yaml_data, list):
                        for automation in yaml_data:
                            if str(automation.get("id")) == automation_id:
                                root = {
                                    "label": get_automation_label(automation),
                                    "type": "automation",
                                    "children": [],
                                }
                                for affected in find_entities_in_automation(automation):
                                    root["children"].append(
                                        {
                                            "label": get_entity_friendly_name(affected),
                                            "type": "entity",
                                            "children": [],
                                        }
                                    )
                                return {"root": root}
                except Exception as err:
                    _LOGGER.error(
                        "Failed to parse automations.yaml for automation tree: %s", err
                    )
            return {
                "root": {"label": automation_id, "type": "automation", "children": []}
            }

        def build_tree_for_script(script_id):
            scripts_path = Path(hass.config.path("scripts.yaml"))
            if scripts_path.exists():
                try:
                    content = scripts_path.read_text()
                    yaml_data = yaml.safe_load(content)
                    if isinstance(yaml_data, dict):
                        script = yaml_data.get(script_id)
                        if script:
                            root = {
                                "label": get_script_label(script_id, script),
                                "type": "script",
                                "children": [],
                            }
                            for affected in find_entities_in_script(script):
                                root["children"].append(
                                    {
                                        "label": get_entity_friendly_name(affected),
                                        "type": "entity",
                                        "children": [],
                                    }
                                )
                            return {"root": root}
                except Exception as err:
                    _LOGGER.error(
                        "Failed to parse scripts.yaml for script tree: %s", err
                    )
            return {"root": {"label": script_id, "type": "script", "children": []}}

        if q_type == "entity":
            return self.json(build_tree_for_entity(q_id))
        if q_type == "automation":
            return self.json(build_tree_for_automation(q_id))
        if q_type == "script":
            return self.json(build_tree_for_script(q_id))
        return self.json({"root": {"label": q_id, "type": q_type, "children": []}})
