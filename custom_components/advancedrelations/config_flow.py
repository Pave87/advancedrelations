"""Config flow for Advanced relations integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import DOMAIN


class AdvancedRelationsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Advanced relations."""

    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None) -> ConfigFlowResult:
        """Handle the initial step."""
        return self.async_create_entry(title="Advanced relations", data={})
