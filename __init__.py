"""Sunrilive BLE integration."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType

from .const import CONF_MANUAL_MACS, DOMAIN, MANUFACTURER, MODEL, uid_from_mac


if TYPE_CHECKING:
    from .sensor import SunriliveBleDataUpdateCoordinator

PLATFORMS = [Platform.SENSOR]

@dataclass
class SunriliveBleRuntimeData:
    """Runtime data for sunrilive_ble."""

    coordinators: dict[str, SunriliveBleDataUpdateCoordinator] = None
    address_to_mac: dict[str, str] = None


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up from a config entry."""
    # 用 runtime data 放 coordinator 清單
    hass.data.setdefault(DOMAIN, {}).update(
        {
            entry.entry_id: SunriliveBleRuntimeData(
                coordinators={},
                address_to_mac={},
            )
        }
    )

    runtime_data: SunriliveBleRuntimeData = hass.data[DOMAIN][entry.entry_id]
    manual_macs = entry.data.get(CONF_MANUAL_MACS, [])

    manual_addresses = [mac.upper() for mac in manual_macs]

    # 如果你之後加 HA 自動 Discovery，也可以在這裡額外加
    # 例如：從 passive BLE 事件裡拿到地址，再加進 list

    async for_macs in (manual_addresses,):
        for addr in for_macs:
            uid = uid_from_mac(addr)
            runtime_data.address_to_mac[addr] = addr
            # 會在 `async_setup_platform` + `sensor` 裡，用 `BluetoothServiceInfoBleak` 事件綁定
            # 這邊先只做資料結構管理

    # forward entry
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    runtime_data: SunriliveBleRuntimeData = hass.data[DOMAIN][entry.entry_id]
    # 关闭所有協調器（如果之後實作）
    runtime_data.coordinators.clear()
    hass.data[DOMAIN].pop(entry.entry_id, None)

    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_setup_platform(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
    discovery_info: dict[str, Any] | None = None,
) -> None:
    """Platform setup callback (向後相容，我們主要用 config_flow + Passive Update Processor)."""
    pass
