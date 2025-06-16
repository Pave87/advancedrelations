"""Config flow for Your Integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigFlow
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN


class YourIntegrationConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Your Integration."""

    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None) -> FlowResult:
        """Handle the initial step."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        return self.async_create_entry(title="Your Integration", data={})
