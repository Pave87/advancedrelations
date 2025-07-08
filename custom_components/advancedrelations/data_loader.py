"""Data loading utilities for Advanced Relations integration.

This module handles loading and caching of Home Assistant configuration data
including entities, automations, and scripts.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# Global cache variables for storing parsed Home Assistant configuration data
# These are populated by the list_* functions and used by the relationship builder

# Cache for all entities in the system with their friendly names
_Entities: list[dict[str, Any]] = []

# Cache for all automations with their IDs and aliases for quick lookup
_Automations: list[dict[str, str]] = []  # Each dict: {"id": ..., "alias": ...}

# Cache for all scripts with their IDs and aliases for quick lookup
_Scripts: list[dict[str, str]] = []  # Each dict: {"id": ..., "alias": ...}


async def list_entities(hass: HomeAssistant) -> None:
    """Populate the global _Entities cache with all current Home Assistant entities.

    This function queries the Home Assistant state machine to get all currently registered
    entities and extracts their entity_id and friendly_name for use in relationship analysis.
    The data is stored in the global _Entities list for efficient access by other functions.

    The function clears any existing cached data and rebuilds it from scratch to ensure
    data freshness, which is important since entities can be added/removed/renamed at runtime.

    Args:
        hass: The Home Assistant instance to query for entity states

    Note:
        This function modifies the global _Entities variable and logs the operation
        for debugging purposes.

    """
    _Entities.clear()  # Clear any existing cached entity data

    # Iterate through all current entity states in Home Assistant
    for state in hass.states.async_all():
        # Extract friendly name from attributes, fallback to entity_id if not set
        friendly_name = state.attributes.get("friendly_name", state.entity_id)

        # Store entity information as a dictionary for easy JSON serialization
        _Entities.append({"entity_id": state.entity_id, "friendly_name": friendly_name})

    _LOGGER.info("Entities with friendly names read and stored in _Entities")


async def list_automations(hass: HomeAssistant) -> None:
    """Populate the global _Automations cache by parsing the automations.yaml file.

    This function reads and parses the automations.yaml configuration file to extract
    automation metadata (ID and alias) for use in relationship analysis. The data is
    stored in the global _Automations list as dictionaries containing 'id' and 'alias' keys.

    The function handles various error conditions gracefully:
    - Missing automations.yaml file (silently continues)
    - YAML parsing errors (logs error and continues)
    - Malformed automation entries (skips invalid entries)

    Args:
        hass: The Home Assistant instance (used to get config path)

    Note:
        This function modifies the global _Automations variable and uses the executor
        to perform file I/O operations asynchronously.

    """
    _Automations.clear()  # Clear any existing cached automation data

    # Construct path to the automations configuration file
    automations_path = Path(hass.config.path("automations.yaml"))

    # Only proceed if the automations file exists
    if automations_path.exists():
        try:
            # Read file content using executor to avoid blocking the event loop
            content = await hass.async_add_executor_job(automations_path.read_text)

            # Parse YAML content safely (prevents code execution attacks)
            yaml_data = yaml.safe_load(content)

            # Automations are stored as a list in the YAML file
            if isinstance(yaml_data, list):
                for automation in yaml_data:
                    # Validate that each automation is a dict with an ID
                    if isinstance(automation, dict) and "id" in automation:
                        # Use alias if available, otherwise fall back to ID as string
                        alias = automation.get("alias", str(automation["id"]))

                        # Store automation metadata for quick lookup
                        entry = {
                            "id": str(automation["id"]),  # Ensure ID is always a string
                            "alias": alias,
                        }
                        _Automations.append(entry)

        except yaml.YAMLError as err:
            # Log YAML parsing errors but don't crash the integration
            _LOGGER.error("Failed to parse automations.yaml: %s", err)

    _LOGGER.info("Automations read and stored in _Automations")


async def list_scripts(hass: HomeAssistant) -> None:
    """Populate the global _Scripts cache by parsing the scripts.yaml file.

    This function reads and parses the scripts.yaml configuration file to extract
    script metadata (ID and alias) for use in relationship analysis. The data is
    stored in the global _Scripts list as dictionaries containing 'id' and 'alias' keys.

    Scripts in Home Assistant are stored differently than automations - they use a
    dictionary format where the key is the script ID and the value contains the script
    configuration including the optional alias.

    The function handles various error conditions gracefully:
    - Missing scripts.yaml file (silently continues)
    - YAML parsing errors (logs error and continues)
    - Malformed script entries (skips invalid entries)

    Args:
        hass: The Home Assistant instance (used to get config path)

    Note:
        This function modifies the global _Scripts variable and uses the executor
        to perform file I/O operations asynchronously.

    """
    _Scripts.clear()  # Clear any existing cached script data

    # Construct path to the scripts configuration file
    scripts_path = Path(hass.config.path("scripts.yaml"))

    # Only proceed if the scripts file exists
    if scripts_path.exists():
        try:
            # Read file content using executor to avoid blocking the event loop
            content = await hass.async_add_executor_job(scripts_path.read_text)

            # Parse YAML content safely (prevents code execution attacks)
            yaml_data = yaml.safe_load(content)

            # Scripts are stored as a dictionary where keys are script IDs
            if isinstance(yaml_data, dict):
                for script_id, script in yaml_data.items():
                    # Validate that each script configuration is a dictionary
                    if isinstance(script, dict):
                        # Use alias if available, otherwise fall back to script ID
                        alias = script.get("alias", script_id)

                        # Store script metadata for quick lookup
                        entry = {"id": script_id, "alias": alias}
                        _Scripts.append(entry)

        except yaml.YAMLError as err:
            # Log YAML parsing errors but don't crash the integration
            _LOGGER.error("Failed to parse scripts.yaml: %s", err)

    _LOGGER.info("Scripts read and stored in _Scripts")


def get_entities() -> list[dict[str, Any]]:
    """Get the cached entities data."""
    return _Entities


def get_automations() -> list[dict[str, str]]:
    """Get the cached automations data."""
    return _Automations


def get_scripts() -> list[dict[str, str]]:
    """Get the cached scripts data."""
    return _Scripts
