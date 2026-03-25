"""Configure Sunrilive BLE integration."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_MAC
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig, TextSelectorType
import voluptuous as vol

from .const import CONF_MANUAL_MACS, DOMAIN, MANUFACTURER, MODEL


STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_MANUAL_MACS, default=""): TextSelector(
            TextSelectorConfig(
                type=TextSelectorType.TEXT,
                multiple=False,
                multiline=True,
            )
        ),
    }
)


class SunriliveBLEConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Sunrilive BLE config flow."""

    VERSION = 1
    MINOR_VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Initial user step."""
        errors = {}

        if user_input is not None:
            macs = []
            line: str
            for line in user_input.get(CONF_MANUAL_MACS, "").strip().splitlines():
                line = line.strip().upper()
                if not line:
                    continue
                if self._is_valid_mac(line):
                    macs.append(line)
                else:
                    errors[CONF_MANUAL_MACS] = "invalid_mac"

            if not errors:
                return self.async_create_entry(
                    title="Sunrilive BLE",
                    data={
                        CONF_MANUAL_MACS: macs,
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
            description_placeholders={
                "manufacturer": MANUFACTURER,
                "model": MODEL,
            },
        )

    def _is_valid_mac(self, mac: str) -> bool:
        """Simple MAC validation."""
        if len(mac) != 17:
            return False
        parts = mac.split(":")
        if len(parts) != 6:
            return False
        for part in parts:
            if len(part) != 2:
                return False
            try:
                int(part, 16)
            except ValueError:
                return False
        return True
