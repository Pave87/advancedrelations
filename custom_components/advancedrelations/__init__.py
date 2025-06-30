"""Integration for Advanced Relations.

This integration provides a comprehensive view of relationships between Home Assistant entities,
automations, and scripts. It analyzes YAML configurations to build interactive relationship trees
showing how different components trigger, condition, and affect each other.

Key Features:
- Entity relationship mapping (what triggers/uses/modifies each entity)
- Automation dependency analysis (trigger chains, condition dependencies)
- Script call hierarchies and entity interactions
- Interactive web panel for visualization
- Deep YAML parsing with template extraction

The integration exposes HTTP endpoints for frontend communication and maintains cached
data structures for efficient relationship analysis.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import yaml

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.http import HomeAssistantView
from homeassistant.helpers.typing import ConfigType


_LOGGER = logging.getLogger(__name__)


# Global cache variables for storing parsed Home Assistant configuration data
# These are populated by the list_* functions and used by the relationship builder

# Cache for all entities in the system with their friendly names
_Entities: list[dict[str, Any]] = []

# Cache for all automations with their IDs and aliases for quick lookup
_Automations: list[dict[str, str]] = []  # Each dict: {"id": ..., "alias": ...}

# Cache for all scripts with their IDs and aliases for quick lookup
_Scripts: list[dict[str, str]] = []  # Each dict: {"id": ..., "alias": ...}

# Placeholder for future template analysis functionality
_Templates: list[dict[str, Any]]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Advanced Relations integration from YAML configuration.

    This function is called when the integration is configured via YAML in configuration.yaml.
    Currently this integration is designed to work primarily through config entries (UI setup),
    so this function serves mainly as a placeholder and logs a warning for debugging purposes.

    Args:
        hass: The Home Assistant instance
        config: The YAML configuration data for this integration

    Returns:
        bool: Always returns True to indicate successful setup

    """
    _LOGGER.warning("=== ADVANCED RELATIONS INTEGRATION SETUP CALLED ===")
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Advanced Relations from a config entry.

    This is the main setup function that configures the integration when added through the UI.
    It performs the following setup tasks:

    1. Registers static file serving for the web panel assets
    2. Creates and registers the iframe panel in the Home Assistant frontend
    3. Registers all HTTP API endpoints for data access and relationship analysis

    The integration creates a custom panel accessible from the sidebar that provides
    an interactive interface for exploring entity relationships.

    Args:
        hass: The Home Assistant instance
        entry: The config entry containing integration configuration

    Returns:
        bool: True if setup was successful

    """
    # Import frontend here to avoid circular imports during HA startup
    from homeassistant.components import frontend

    # Register static file serving for the web panel
    # This serves HTML, CSS, JS files from the www directory to the frontend
    hass.http.register_static_path(
        "/advancedrelations-panel",  # URL path where files will be served
        hass.config.path(
            "custom_components/advancedrelations/www"
        ),  # Local filesystem path
        cache_headers=True,  # Enable browser caching for better performance
    )

    # Register the Advanced Relations panel in the Home Assistant sidebar
    # This creates an iframe panel that loads our custom web interface
    frontend.async_register_built_in_panel(
        hass,
        component_name="iframe",  # Use iframe panel type to embed custom HTML
        sidebar_title="Advanced Relations",  # Text shown in the sidebar
        sidebar_icon="mdi:graph",  # Material Design Icon for the sidebar
        frontend_url_path="advancedrelations-panel",  # URL path for the panel
        config={"url": "/advancedrelations-panel/index.html"},  # URL to load in iframe
        require_admin=True,  # Restrict access to admin users only
    )

    # Register HTTP API endpoints for frontend communication
    # These endpoints provide data access and relationship analysis functionality
    hass.http.register_view(AdvancedRelationsTriggerView)  # Trigger backend processing
    hass.http.register_view(
        AdvancedRelationsDataView
    )  # Get entities/automations/scripts data
    hass.http.register_view(AdvancedRelationsRelatedView)  # Get relationship trees

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry for Advanced Relations.

    Called when the integration is being removed or reloaded. Currently this integration
    doesn't maintain any persistent state or background tasks that need cleanup, so this
    function simply returns True to indicate successful unload.

    Args:
        hass: The Home Assistant instance
        entry: The config entry being unloaded

    Returns:
        bool: True indicating successful unload

    """
    return True


async def list_entities(hass):
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

    _LOGGER.info("=== Entities with friendly names read and stored in _Entities ===")


async def list_automations(hass):
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

    _LOGGER.info(
        "=== Automations read and stored in _Automations and _AutomationIdToAlias ==="
    )


async def list_scripts(hass):
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

    _LOGGER.info("=== Scripts read and stored in _Scripts ===")


class AdvancedRelationsTriggerView(HomeAssistantView):
    """HTTP endpoint for triggering backend data processing when the frontend panel loads.

    This view provides a POST endpoint that the frontend can call to trigger the backend
    to refresh its cached data. This is useful when the user opens the panel to ensure
    they're working with the most current entity, automation, and script data.

    The endpoint performs the following operations:
    1. Refreshes the entities cache from the current Home Assistant state
    2. Re-parses automations.yaml to update automation data
    3. Re-parses scripts.yaml to update script data

    Attributes:
        url: The HTTP endpoint path for this view
        name: The internal name for this view (used for routing)
        requires_auth: Set to False to allow unauthenticated access for internal panel use

    """

    url = "/api/advancedrelations/trigger"
    name = "api:advancedrelations:trigger"
    requires_auth = False  # Allow unauthenticated access for internal panel use

    async def post(self, request):
        """Handle POST requests to trigger backend data processing.

        This method is called when the frontend sends a POST request to refresh backend data.
        It calls all the data loading functions to ensure the cached data is current.

        Args:
            request: The HTTP request object containing Home Assistant context

        Returns:
            JSON response indicating the trigger was successful

        Note:
            This method logs a warning for debugging purposes to track when data
            refresh operations are triggered by the frontend.

        """
        _LOGGER.warning("=== POST /api/advancedrelations/trigger called ===")
        hass = request.app["hass"]

        # Refresh all cached data by calling the data loading functions
        await list_entities(hass)  # Refresh entity cache
        await list_automations(hass)  # Refresh automation cache
        await list_scripts(hass)  # Refresh script cache

        return self.json({"status": "triggered"})


class AdvancedRelationsDataView(HomeAssistantView):
    """HTTP endpoint for providing entity, automation, and script data to the frontend.

    This view exposes a GET endpoint that returns all currently cached data about
    entities, automations, and scripts in JSON format. The frontend uses this data
    to populate dropdown lists and provide item selection interfaces.

    The returned JSON structure contains:
    - entities: List of all entities with their IDs and friendly names
    - automations: List of all automations with their IDs and aliases
    - scripts: List of all scripts with their IDs and aliases

    Attributes:
        url: The HTTP endpoint path for this view
        name: The internal name for this view (used for routing)
        requires_auth: Set to False to allow unauthenticated access for internal panel use

    """

    url = "/api/advancedrelations/data"
    name = "api:advancedrelations:data"
    requires_auth = False

    async def get(self, request):
        """Handle GET requests for cached entity, automation, and script data.

        This method refreshes all cached data and returns it in JSON format for
        consumption by the frontend. The data is refreshed on each request to
        ensure the frontend always receives current information.

        Args:
            request: The HTTP request object containing Home Assistant context

        Returns:
            JSON response containing entities, automations, and scripts data in the format:
            {
                "entities": [{"entity_id": "...", "friendly_name": "..."}],
                "automations": [{"id": "...", "alias": "..."}],
                "scripts": [{"id": "...", "alias": "..."}]
            }

        """
        hass = request.app["hass"]

        # Refresh all cached data before returning it
        await list_entities(hass)  # Ensure entity data is current
        await list_automations(hass)  # Ensure automation data is current
        await list_scripts(hass)  # Ensure script data is current

        # Return the cached data in JSON format
        return self.json(
            {
                "entities": _Entities,
                "automations": _Automations,
                "scripts": _Scripts,
            }
        )


class AdvancedRelationsRelatedView(HomeAssistantView):
    """HTTP endpoint for generating relationship trees for selected entities, automations, or scripts.

    This is the core functionality endpoint that analyzes relationships between Home Assistant
    components and returns comprehensive relationship trees. The endpoint accepts query parameters
    specifying the type (entity/automation/script) and ID of the item to analyze.

    The relationship analysis includes:
    - Triggers: What causes this item to activate or change
    - Conditions: What this item depends on or checks
    - Outputs: What this item affects or modifies

    The analysis works by parsing YAML configurations and building a tree structure that
    shows direct and indirect relationships between components, helping users understand
    the complex interdependencies in their Home Assistant setup.

    Attributes:
        url: The HTTP endpoint path for this view
        name: The internal name for this view (used for routing)
        requires_auth: Set to False to allow unauthenticated access for internal panel use

    """

    url = "/api/advancedrelations/related"
    name = "api:advancedrelations:related"
    requires_auth = False

    async def get(self, request):
        """Handle GET requests for relationship tree analysis.

        This method analyzes the relationships for a specified entity, automation, or script
        and returns a comprehensive tree structure showing all related components and how
        they interact.

        Query Parameters:
            type (str): The type of item to analyze ('entity', 'automation', or 'script')
            id (str): The ID of the item to analyze

        Args:
            request: The HTTP request object containing query parameters and Home Assistant context

        Returns:
            JSON response containing either:
            - Success: {"root": relationship_tree_object}
            - Error: {"error": error_message} with appropriate HTTP status code

        Raises:
            400: If required query parameters (type or id) are missing
            500: If there's an error during relationship analysis (YAML parsing, file access, etc.)

        Note:
            This method refreshes all cached data before analysis to ensure accuracy,
            then uses the RelationsTreeBuilder to perform the actual relationship analysis.

        """
        hass = request.app["hass"]

        # Refresh all cached data to ensure we're working with current information
        await list_entities(hass)  # Refresh entity cache
        await list_automations(hass)  # Refresh automation cache
        await list_scripts(hass)  # Refresh script cache

        # Extract and validate query parameters
        q_type = request.query.get("type")  # Type of item (entity/automation/script)
        q_id = request.query.get("id")  # ID of the specific item to analyze
        q_depth = request.query.get("depth", "3")  # Recursion depth (default: 3)

        # Validate that required parameters are present
        if not q_type or not q_id:
            return self.json({"error": "Missing type or id"}, status_code=400)

        # Validate and parse depth parameter
        try:
            depth = int(q_depth)
            if depth < 0:
                return self.json(
                    {"error": "Depth must be 0 or a positive number"}, status_code=400
                )
            # Convert 0 to a very large number to represent "infinite" depth
            if depth == 0:
                depth = 999  # Effectively infinite for practical purposes
        except ValueError:
            return self.json({"error": "Invalid depth parameter"}, status_code=400)

        try:
            # Create relationship tree builder and analyze the specified item
            builder = RelationsTreeBuilder(hass)

            if q_type == "entity":
                # For entities, find upstream relationships (what uses this entity)
                relations = builder.find_entity_upstream_relations(
                    q_id, max_depth=depth
                )
            else:
                # For automations/scripts, find downstream relationships (what they affect)
                relations = builder.find_automation_script_downstream_relations(
                    q_type, q_id, max_depth=depth
                )

            # Return the new relationship structure
            return self.json({"relations": relations})

        except (yaml.YAMLError, FileNotFoundError, KeyError) as err:
            # Log the error for debugging and return a user-friendly error response
            _LOGGER.error("Error building relations tree: %s", err)
            return self.json(
                {"error": f"Failed to build relations tree: {err}"}, status_code=500
            )


class RelationsTreeBuilder:
    """Advanced relationship analysis engine for Home Assistant configurations.

    This class provides comprehensive analysis of relationships between entities, automations,
    and scripts in a Home Assistant installation. It parses YAML configuration files to
    understand how different components interact with each other through triggers, conditions,
    and actions.

    Key Capabilities:
    - Entity relationship mapping (what triggers/uses/modifies each entity)
    - Automation dependency analysis (trigger chains, condition dependencies)
    - Script call hierarchies and entity interactions
    - Template parsing to extract entity references from Jinja2 templates
    - Recursive relationship tree building with cycle detection
    - Support for complex automation structures (choose/if/repeat blocks)

    The builder maintains caches of parsed YAML data to improve performance and provides
    various utility methods for extracting entity references from different YAML structures.

    Attributes:
        hass: The Home Assistant instance for accessing configuration paths
        _automations_data: Cached parsed automations.yaml content
        _scripts_data: Cached parsed scripts.yaml content

    """

    def __init__(self, hass):
        """Initialize the relationship tree builder.

        Args:
            hass: The Home Assistant instance for accessing configuration and state data

        """
        self.hass = hass
        self._automations_data = None  # Lazy-loaded cache for automation configurations
        self._scripts_data = None  # Lazy-loaded cache for script configurations

    def _safe_get_list(self, data, key, default=None):
        """Safely extract a list from a dictionary, handling None values gracefully.

        This utility method provides safe access to list values in dictionaries, which is
        essential when parsing YAML configurations that may have optional or missing keys.
        It ensures that calling code always receives a list, preventing iteration errors.

        Args:
            data (dict): The dictionary to extract the list from
            key (str): The key to look up in the dictionary
            default (list, optional): Default value to return if key is missing or None.
                                     Defaults to an empty list if not specified.

        Returns:
            list: The list value from the dictionary, or the default if key is missing/None

        Examples:
            # Safe access to automation triggers
            triggers = self._safe_get_list(automation, "trigger", [])

            # Safe access to script sequence steps
            steps = self._safe_get_list(script, "sequence", [])

        """
        if default is None:
            default = []
        value = data.get(key, default)
        return value if value is not None else default

    def get_automations_data(self):
        """Get cached automations configuration data with lazy loading.

        This method provides access to parsed automations.yaml content with caching
        to improve performance. The data is loaded once on first access and reused
        for subsequent calls within the same analysis session.

        Returns:
            list: Parsed automations data from automations.yaml, or empty list if file
                  doesn't exist or has parsing errors

        Note:
            The cache is instance-specific and will be recreated for each new
            RelationsTreeBuilder instance to ensure data freshness.

        """
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
        """Get cached scripts configuration data with lazy loading.

        This method provides access to parsed scripts.yaml content with caching
        to improve performance. The data is loaded once on first access and reused
        for subsequent calls within the same analysis session.

        Returns:
            dict: Parsed scripts data from scripts.yaml (keys are script IDs),
                  or empty dict if file doesn't exist or has parsing errors

        Note:
            The cache is instance-specific and will be recreated for each new
            RelationsTreeBuilder instance to ensure data freshness.

        """
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
        """Get the friendly name for an entity from the cached entity data.

        This method looks up the friendly name for a given entity ID from the
        global _Entities cache that was populated by list_entities().

        Args:
            entity_id (str): The entity ID to look up (e.g., 'sensor.temperature')

        Returns:
            str: The friendly name of the entity if found, otherwise returns the
                 entity_id as fallback

        Examples:
            name = builder.get_entity_friendly_name('sensor.temperature')
            # Returns: "Living Room Temperature" or "sensor.temperature" if no friendly name

        """
        for ent in _Entities:
            if ent["entity_id"] == entity_id:
                return ent.get("friendly_name", entity_id)
        return entity_id

    def get_automation_label(self, automation):
        """Generate a human-readable label for an automation.

        Creates a descriptive label combining the automation's alias and ID for
        display in the relationship tree. This helps users identify automations
        even when they have generic aliases.

        Args:
            automation (dict): Automation configuration dictionary containing 'alias' and 'id' keys

        Returns:
            str: Formatted label in the format "Alias (ID)" or just "ID" if no alias

        Examples:
            label = builder.get_automation_label({"alias": "Turn on lights", "id": "123"})
            # Returns: "Turn on lights (123)"

        """
        return f"{automation.get('alias', automation.get('id', '?'))} ({automation.get('id', '?')})"

    def get_script_label(self, script_id, script):
        """Generate a human-readable label for a script.

        Creates a descriptive label combining the script's alias and ID for
        display in the relationship tree. This helps users identify scripts
        even when they have generic aliases.

        Args:
            script_id (str): The script's unique identifier
            script (dict): Script configuration dictionary that may contain 'alias' key

        Returns:
            str: Formatted label in the format "Alias (ID)" or just "ID" if no alias

        Examples:
            label = builder.get_script_label("morning_routine", {"alias": "Morning Setup"})
            # Returns: "Morning Setup (morning_routine)"

        """
        return f"{script.get('alias', script_id)} ({script_id})"

    def extract_entities_from_value(self, value):
        """Recursively extract entity IDs from any YAML structure or template.

        This is one of the most critical methods in the relationship analysis system.
        It intelligently parses various types of YAML values to identify entity references,
        including plain entity IDs, template expressions, and nested data structures.

        The method handles multiple formats:
        1. Direct entity IDs (e.g., "sensor.temperature")
        2. Jinja2 templates with entity references (e.g., "{{ states('sensor.temp') }}")
        3. Lists and dictionaries containing entity references
        4. Special keys like entity_id, target, etc.

        Entity ID Detection Rules:
        - Must contain exactly one dot (domain.entity_name format)
        - Must not start with template markers ({{ or {%)
        - Must not contain common non-entity patterns (/, ://, @, spaces)
        - Both domain and entity parts must be non-empty

        Template Parsing:
        - Extracts entities from states() function calls
        - Extracts entities from state_attr() function calls
        - Extracts entities from is_state() function calls
        - Uses regex patterns to handle various template formats

        Args:
            value: The YAML value to analyze (can be str, list, dict, or other types)

        Returns:
            set: A set of unique entity IDs found in the value

        Examples:
            # Direct entity ID
            entities = extract_entities_from_value("light.living_room")
            # Returns: {"light.living_room"}

            # Template with entity reference
            entities = extract_entities_from_value("{{ states('sensor.temp') }}")
            # Returns: {"sensor.temp"}

            # Dictionary with entity_id key
            entities = extract_entities_from_value({"entity_id": "switch.fan"})
            # Returns: {"switch.fan"}

        Note:
            This method is recursive and will traverse complex nested structures
            to find all entity references at any depth.

        """
        entities = set()

        if isinstance(value, str):
            # Handle direct entity ID detection
            if (
                "." in value
                and not value.startswith("{{")
                and not value.startswith("{%")
            ):
                # Basic entity ID pattern check (domain.entity_name)
                parts = value.split(".")
                if len(parts) == 2 and parts[0] and parts[1]:
                    # Avoid false positives like file paths, URLs, etc.
                    if not any(char in value for char in ["/", "://", "@", " "]):
                        entities.add(value)

            # Handle Jinja2 template parsing for entity references
            elif "{{" in value or "{%" in value:
                # Extract entity IDs from states() function calls
                # Pattern matches: states('entity.id') or states("entity.id")
                template_entities = re.findall(r'states\([\'"]([^\'")]+)[\'"]\)', value)
                for entity_id in template_entities:
                    if "." in entity_id:
                        entities.add(entity_id)

                # Extract entity IDs from state_attr() function calls
                # Pattern matches: state_attr('entity.id', 'attribute')
                state_attr_entities = re.findall(
                    r'state_attr\([\'"]([^\'")]+)[\'"]\s*,', value
                )
                for entity_id in state_attr_entities:
                    if "." in entity_id:
                        entities.add(entity_id)

                # Extract entity IDs from is_state() function calls
                # Pattern matches: is_state('entity.id', 'state_value')
                is_state_entities = re.findall(
                    r'is_state\([\'"]([^\'")]+)[\'"]\s*,', value
                )
                for entity_id in is_state_entities:
                    if "." in entity_id:
                        entities.add(entity_id)

        elif isinstance(value, list):
            # Recursively process all items in lists
            for item in value:
                entities.update(self.extract_entities_from_value(item))

        elif isinstance(value, dict):
            # Handle dictionary structures with special processing for known keys
            for key, val in value.items():
                if key in ["entity_id", "entity_ids"]:
                    # Direct entity ID references
                    entities.update(self.extract_entities_from_value(val))
                elif key == "target" and isinstance(val, dict):
                    # Service call targets (common in actions)
                    entities.update(
                        self.extract_entities_from_value(val.get("entity_id", []))
                    )
                elif key in ["device_id", "area_id"]:
                    # Skip device and area IDs as they're not entity IDs
                    continue
                else:
                    # Recursively check all other nested structures
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
            # Check for service calls
            service_actions = ["service", "action"]
            for service_key in service_actions:
                if service_key in action:
                    service = action[service_key]
                    service_str = str(service).lower()

                    # Detect script and automation calls
                    self._detect_script_automation_calls(action, service_str, outputs)

            # Always add direct entity_id and target entities as outputs
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
        """Build a comprehensive relationship tree for the specified Home Assistant component.

        This is the main entry point for relationship analysis. It creates a hierarchical tree
        structure showing how the specified entity, automation, or script relates to other
        components in the Home Assistant system. The tree includes trigger relationships,
        condition dependencies, and output effects.

        The method implements cycle detection to prevent infinite recursion when components
        have circular dependencies. It also enforces a maximum depth limit to keep the
        analysis manageable and prevent performance issues.

        Tree Structure:
        Each node in the tree contains:
        - label: Human-readable name/description of the component
        - type: Component type ('entity', 'automation', or 'script')
        - id: Unique identifier for the component
        - children: List of related components
        - relationship: How this component relates to its parent ('trigger', 'condition', 'output')
        - is_reference: Boolean indicating if this is a reference to avoid circular display

        Args:
            start_type (str): Type of the starting component ('entity', 'automation', 'script')
            start_id (str): Unique identifier of the starting component
            visited (set, optional): Set of already-processed components for cycle detection.
                                   Defaults to None (creates new set).
            max_depth (int, optional): Maximum depth to traverse. Defaults to 5.
            current_depth (int, optional): Current recursion depth. Defaults to 0.

        Returns:
            dict: A tree node dictionary containing the relationship analysis results

        Examples:
            # Analyze relationships for a sensor
            tree = builder.build_relations_tree('entity', 'sensor.temperature')

            # Analyze relationships for an automation
            tree = builder.build_relations_tree('automation', 'turn_on_lights')

        Note:
            The method delegates to specialized builders (_build_entity_node,
            _build_automation_node, _build_script_node) for type-specific analysis.

        """
        if visited is None:
            visited = set()

        # Create unique key for this component to track processed items
        item_key = f"{start_type}:{start_id}"

        # Prevent infinite recursion by checking if already processed or at max depth
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

        # Mark this component as visited to prevent cycles
        visited.add(item_key)

        # Delegate to specialized builders based on component type
        if start_type == "entity":
            return self._build_entity_node(start_id, visited, max_depth, current_depth)

        if start_type == "automation":
            return self._build_automation_node(
                start_id, visited, max_depth, current_depth
            )

        if start_type == "script":
            return self._build_script_node(start_id, visited, max_depth, current_depth)

        # Fallback for unknown types
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

    def _get_automation_details(self, automation, automation_id, max_depth, visited):
        """Get detailed information about an automation including triggers, conditions, and outputs.

        Args:
            automation (dict): The automation configuration
            automation_id (str): The automation ID
            max_depth (int): Remaining depth to traverse
            visited (set): Set of visited items to prevent loops

        Returns:
            dict: Detailed automation information with triggers, conditions, and outputs
        """
        # Get basic automation info
        triggers = []
        conditions = []
        outputs = []

        # Find trigger entities
        trigger_entities = self.find_triggers_in_automation(automation)
        for entity_id in trigger_entities:
            if not entity_id.startswith("script_call:"):
                triggers.append(
                    {
                        "entity_id": entity_id,
                        "friendly_name": self.get_entity_friendly_name(entity_id),
                    }
                )

        # Find condition entities
        condition_entities = self.find_conditions_in_automation(automation)
        for entity_id in condition_entities:
            if not entity_id.startswith("script_call:"):
                conditions.append(
                    {
                        "entity_id": entity_id,
                        "friendly_name": self.get_entity_friendly_name(entity_id),
                    }
                )

        # Find outputs - both entities and called scripts/automations
        output_entities = self.find_outputs_in_automation(automation)
        for entity_id in output_entities:
            if entity_id.startswith("script_call:"):
                called_item = entity_id.replace("script_call:", "")
                if called_item.startswith("script."):
                    called_script_id = called_item.replace("script.", "")
                    if called_script_id not in visited and max_depth > 0:
                        scripts_data = self.get_scripts_data()
                        script = scripts_data.get(called_script_id, {})
                        if script:
                            script_details = self._get_script_details(
                                script, called_script_id, max_depth - 1, visited.copy()
                            )
                            outputs.append(script_details)
                elif called_item.startswith("automation."):
                    called_auto_id = called_item.replace("automation.", "")
                    if called_auto_id not in visited and max_depth > 0:
                        for auto in self.get_automations_data():
                            if str(auto.get("id")) == called_auto_id:
                                auto_details = self._get_automation_details(
                                    auto, called_auto_id, max_depth - 1, visited.copy()
                                )
                                outputs.append(auto_details)
                                break
                elif called_item not in visited and max_depth > 0:
                    # Assume it's a script if no domain prefix
                    scripts_data = self.get_scripts_data()
                    script = scripts_data.get(called_item, {})
                    if script:
                        script_details = self._get_script_details(
                            script, called_item, max_depth - 1, visited.copy()
                        )
                        outputs.append(script_details)
            elif entity_id not in visited and max_depth > 0:
                # This automation affects an entity - add basic entity info
                entity_info = {
                    "type": "entity",
                    "entity_id": entity_id,
                    "friendly_name": self.get_entity_friendly_name(entity_id),
                    "used_as_trigger_by": [],
                    "used_as_condition_by": [],
                }
                # If we have remaining depth, get entity's relationships
                if max_depth > 1:
                    entity_relations = self.find_entity_upstream_relations(
                        entity_id, max_depth - 1, visited.copy()
                    )
                    entity_info["used_as_trigger_by"] = entity_relations["trigger_in"]
                    entity_info["used_as_condition_by"] = entity_relations[
                        "condition_in"
                    ]
                outputs.append(entity_info)
            else:
                # Just add entity info without further relationships
                entity_info = {
                    "type": "entity",
                    "entity_id": entity_id,
                    "friendly_name": self.get_entity_friendly_name(entity_id),
                    "used_as_trigger_by": [],
                    "used_as_condition_by": [],
                }
                outputs.append(entity_info)

        return {
            "type": "automation",
            "id": automation_id,
            "name": self.get_automation_label(automation),
            "triggers": triggers,
            "conditions": conditions,
            "outputs": outputs,
        }

    def _get_script_details(self, script, script_id, max_depth, visited):
        """Get detailed information about a script including conditions and outputs.

        Args:
            script (dict): The script configuration
            script_id (str): The script ID
            max_depth (int): Remaining depth to traverse
            visited (set): Set of visited items to prevent loops

        Returns:
            dict: Detailed script information with conditions and outputs
        """
        # Scripts don't have triggers, only conditions and outputs
        conditions = []
        outputs = []

        # Find condition entities
        condition_entities = self.find_conditions_in_script(script)
        for entity_id in condition_entities:
            if not entity_id.startswith("script_call:"):
                conditions.append(
                    {
                        "entity_id": entity_id,
                        "friendly_name": self.get_entity_friendly_name(entity_id),
                    }
                )

        # Find outputs - both entities and called scripts/automations
        output_entities = self.find_outputs_in_script(script)
        for entity_id in output_entities:
            if entity_id.startswith("script_call:"):
                called_item = entity_id.replace("script_call:", "")
                if called_item.startswith("script."):
                    called_script_id = called_item.replace("script.", "")
                    if called_script_id not in visited and max_depth > 0:
                        scripts_data = self.get_scripts_data()
                        other_script = scripts_data.get(called_script_id, {})
                        if other_script:
                            script_details = self._get_script_details(
                                other_script,
                                called_script_id,
                                max_depth - 1,
                                visited.copy(),
                            )
                            outputs.append(script_details)
                elif called_item.startswith("automation."):
                    called_auto_id = called_item.replace("automation.", "")
                    if called_auto_id not in visited and max_depth > 0:
                        for auto in self.get_automations_data():
                            if str(auto.get("id")) == called_auto_id:
                                auto_details = self._get_automation_details(
                                    auto, called_auto_id, max_depth - 1, visited.copy()
                                )
                                outputs.append(auto_details)
                                break
                elif called_item not in visited and max_depth > 0:
                    # Assume it's a script if no domain prefix
                    scripts_data = self.get_scripts_data()
                    other_script = scripts_data.get(called_item, {})
                    if other_script:
                        script_details = self._get_script_details(
                            other_script, called_item, max_depth - 1, visited.copy()
                        )
                        outputs.append(script_details)
            elif entity_id not in visited and max_depth > 0:
                # This script affects an entity - add basic entity info
                entity_info = {
                    "type": "entity",
                    "entity_id": entity_id,
                    "friendly_name": self.get_entity_friendly_name(entity_id),
                    "used_as_trigger_by": [],
                    "used_as_condition_by": [],
                }
                # If we have remaining depth, get entity's relationships
                if max_depth > 1:
                    entity_relations = self.find_entity_upstream_relations(
                        entity_id, max_depth - 1, visited.copy()
                    )
                    entity_info["used_as_trigger_by"] = entity_relations["trigger_in"]
                    entity_info["used_as_condition_by"] = entity_relations[
                        "condition_in"
                    ]
                outputs.append(entity_info)
            else:
                # Just add entity info without further relationships
                entity_info = {
                    "type": "entity",
                    "entity_id": entity_id,
                    "friendly_name": self.get_entity_friendly_name(entity_id),
                    "used_as_trigger_by": [],
                    "used_as_condition_by": [],
                }
                outputs.append(entity_info)

        return {
            "type": "script",
            "id": script_id,
            "name": self.get_script_label(script_id, script),
            "triggers": [],  # Scripts don't have triggers
            "conditions": conditions,
            "outputs": outputs,
        }

    def find_entity_upstream_relations(self, entity_id, max_depth=3, visited=None):
        """Find upstream relationships for an entity (what uses this entity as trigger/condition).

        For entities, we look for automations and scripts that reference this entity
        in their triggers or conditions - i.e., what depends on or is activated by this entity.
        Then we recursively follow the chain to see what those automations/scripts affect.

        Args:
            entity_id (str): The entity ID to find upstream relationships for
            max_depth (int): Maximum depth to traverse the relationship chain
            visited (set): Set of already visited items to prevent infinite loops

        Returns:
            dict: Relations data in the format:
            {
                "entity_id": str,
                "friendly_name": str,
                "trigger_in": [{"type": "automation/script", "id": str, "name": str, "details": {...}}],
                "condition_in": [{"type": "automation/script", "id": str, "name": str, "details": {...}}]
            }

        """
        if visited is None:
            visited = set()

        # Prevent infinite loops
        if entity_id in visited or max_depth <= 0:
            return {
                "entity_id": entity_id,
                "friendly_name": self.get_entity_friendly_name(entity_id),
                "trigger_in": [],
                "condition_in": [],
            }

        visited.add(entity_id)

        relations = {
            "entity_id": entity_id,
            "friendly_name": self.get_entity_friendly_name(entity_id),
            "trigger_in": [],
            "condition_in": [],
        }

        # Check automations for this entity
        for automation in self.get_automations_data():
            auto_id = str(automation.get("id", ""))
            if not auto_id:
                continue

            triggers = self.find_triggers_in_automation(automation)
            conditions = self.find_conditions_in_automation(automation)

            if entity_id in triggers:
                automation_details = self._get_automation_details(
                    automation, auto_id, max_depth - 1, visited.copy()
                )
                relations["trigger_in"].append(automation_details)

            if entity_id in conditions:
                automation_details = self._get_automation_details(
                    automation, auto_id, max_depth - 1, visited.copy()
                )
                relations["condition_in"].append(automation_details)

        # Check scripts for this entity
        scripts_data = self.get_scripts_data()
        for script_id, script in scripts_data.items():
            conditions = self.find_conditions_in_script(script)

            if entity_id in conditions:
                script_details = self._get_script_details(
                    script, script_id, max_depth - 1, visited.copy()
                )
                relations["condition_in"].append(script_details)

        return relations

    def find_automation_script_downstream_relations(
        self, item_type, item_id, max_depth=3
    ):
        """Find downstream relationships for automation/script (what it triggers/conditions/affects).

        For automations and scripts, we show detailed information about what they do:
        triggers, conditions, and outputs.

        Args:
            item_type (str): Either "automation" or "script"
            item_id (str): The ID of the automation or script
            max_depth (int): Maximum depth for recursive analysis

        Returns:
            dict: Detailed relations data showing triggers, conditions, and outputs

        """
        if item_type == "automation":
            # Find the automation
            automation = None
            for auto in self.get_automations_data():
                if str(auto.get("id")) == item_id:
                    automation = auto
                    break

            if not automation:
                return {"error": f"Automation {item_id} not found"}

            return self._get_automation_details(automation, item_id, max_depth, set())

        elif item_type == "script":
            scripts_data = self.get_scripts_data()
            script = scripts_data.get(item_id, {})

            if not script:
                return {"error": f"Script {item_id} not found"}

            return self._get_script_details(script, item_id, max_depth, set())

        else:
            return {"error": f"Unknown item type: {item_type}"}

    def _detect_script_automation_calls(self, action, service_str, outputs):
        """Detect script and automation calls in action and add them to outputs."""
        # Direct service calls to specific scripts/automations (e.g., "script.my_script")
        if service_str.startswith("script.") and service_str not in [
            "script.turn_on",
            "script.turn_off",
            "script.toggle",
            "script.reload",
        ]:
            script_name = service_str[7:]  # Remove "script." prefix
            outputs.add(f"script_call:{script_name}")

        elif service_str.startswith("automation.") and service_str not in [
            "automation.trigger",
            "automation.turn_on",
            "automation.turn_off",
            "automation.toggle",
            "automation.reload",
        ]:
            automation_name = service_str[11:]  # Remove "automation." prefix
            outputs.add(f"automation_call:{automation_name}")

        # Check entity_id field for script/automation entities
        if "entity_id" in action:
            entity_ids = action["entity_id"]
            if isinstance(entity_ids, str):
                if entity_ids.startswith("script."):
                    outputs.add(f"script_call:{entity_ids[7:]}")
                elif entity_ids.startswith("automation."):
                    outputs.add(f"automation_call:{entity_ids[11:]}")
            elif isinstance(entity_ids, list):
                for eid in entity_ids:
                    if isinstance(eid, str):
                        if eid.startswith("script."):
                            outputs.add(f"script_call:{eid[7:]}")
                        elif eid.startswith("automation."):
                            outputs.add(f"automation_call:{eid[11:]}")

        # Check target field for script/automation entities
        if "target" in action and isinstance(action["target"], dict):
            target_entities = self._safe_get_list(action["target"], "entity_id")
            if isinstance(target_entities, str):
                if target_entities.startswith("script."):
                    outputs.add(f"script_call:{target_entities[7:]}")
                elif target_entities.startswith("automation."):
                    outputs.add(f"automation_call:{target_entities[11:]}")
            elif isinstance(target_entities, list):
                for eid in target_entities:
                    if isinstance(eid, str):
                        if eid.startswith("script."):
                            outputs.add(f"script_call:{eid[7:]}")
                        elif eid.startswith("automation."):
                            outputs.add(f"automation_call:{eid[11:]}")
