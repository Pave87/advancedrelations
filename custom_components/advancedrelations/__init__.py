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

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.http import HomeAssistantView
from homeassistant.helpers.typing import ConfigType

from .data_loader import (
    get_automations,
    get_entities,
    get_scripts,
    list_automations,
    list_entities,
    list_scripts,
)
from .relations_analyzer import find_comprehensive_relations

_LOGGER = logging.getLogger(__name__)


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
    _LOGGER.warning("Advanced Relations integration setup called")
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
        _LOGGER.warning("POST /api/advancedrelations/trigger called")
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
                "entities": get_entities(),
                "automations": get_automations(),
                "scripts": get_scripts(),
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
            - Success: {"relations": relationship_structure}
            - Error: {"error": error_message} with appropriate HTTP status code

        Raises:
            400: If required query parameters (type or id) are missing
            500: If there's an error during relationship analysis

        Note:
            This method refreshes all cached data before analysis to ensure accuracy,
            then uses the relations analyzer to perform the actual relationship analysis.

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
            # Get comprehensive relationships using the relations analyzer
            relations = find_comprehensive_relations(
                hass, q_type, q_id, max_depth=depth
            )

            # Return the relationship structure
            return self.json({"relations": relations})

        except (ValueError, KeyError, FileNotFoundError) as err:
            # Log the error for debugging and return a user-friendly error response
            _LOGGER.error("Error building relations tree: %s", err)
            return self.json(
                {"error": f"Failed to build relations tree: {err}"}, status_code=500
            )
