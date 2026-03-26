from __future__ import annotations

import logging  # 這個一定要加

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Dict, Optional

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_register_callback,
)
from homeassistant.components.bluetooth.passive_update_processor import PassiveBluetoothProcessorEntity
from homeassistant.components.bluetooth.passive_update_coordinator import PassiveBluetoothDataUpdateCoordinator
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback, Event
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, MANUFACTURER, MODEL, CONF_MANUAL_MACS, uid_from_mac
from .__init__ import SunriliveBleRuntimeData

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from .__init__ import SunriliveBleRuntimeData

_LOGGER = logging.getLogger(__name__)

UPDATE_INTERVAL = 60  # seconds, 這個只是示意，實際上我們是被廣播觸發更新的，不需要定時器

TEMPERATURE_SENSOR = SensorEntityDescription(
    key="temperature",
    device_class=SensorDeviceClass.TEMPERATURE,
    native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    state_class=SensorStateClass.MEASUREMENT,
    name="Temperature",
)

HUMIDITY_SENSOR = SensorEntityDescription(
    key="humidity",
    device_class=SensorDeviceClass.HUMIDITY,
    native_unit_of_measurement=PERCENTAGE,
    state_class=SensorStateClass.MEASUREMENT,
    name="Humidity",
)


def _parse_adv(data: bytes) -> tuple[float | None, int | None] | None:
    """解析 Sunrilive ADV data，回傳 (temp, humid) 或 None."""
    pos = 0
    while pos + 2 <= len(data):
        ad_len = data[pos]
        ad_type = data[pos + 1]
        ad_val = data[pos + 2 : pos + 2 + ad_len]
        pos += 2 + ad_len

        if (
            ad_type == 0xFF
            and len(ad_val) >= 11
            and ad_val[0:2] == bytes([0x01, 0x09])
        ):
            # 01 09 TT HH mm:mac
            temp_raw = (ad_val[2] << 8) | ad_val[3]  # big-endian
            humid_raw = ad_val[4]
            # 你有需要也可以取出 ad_val[5:11] 來驗證 MAC

            temp_c = temp_raw / 10.0
            humid_pct = humid_raw

            return temp_c, humid_pct

    return None


class SunriliveBleDataUpdateCoordinator(PassiveBluetoothDataUpdateCoordinator):
    """處理多個 Sunrilive BLE sensor 的資料更新。"""

    def __init__(
        self,
        hass: HomeAssistant,
        address: str,
    ) -> None:
        super().__init__(
            hass=hass,
            logger=_LOGGER,
            address=address,
            mode="passive",
        )
        # 每個地址有一個 temp + humid
        self._last_temp: float | None = None
        self._last_humid: int | None = None

    @callback
    def _async_handle_bluetooth_event(
        self,
        service_info: BluetoothServiceInfoBleak,
        change: str,
    ) -> None:
        """處理廣播事件。"""
        mfg_data = service_info.advertisement_data.manufacturer_data
        if not mfg_data:
            return

        # 用任意一個 0xFF 且有 01 09 的資料做解析（有多組時可選第一個）
        for _cid, data in mfg_data.items():
            parsed = _parse_adv(data.data)
            if not parsed:
                continue

            temp_c, humid_pct = parsed
            self._last_temp = temp_c
            self._last_humid = humid_pct
            self._async_update_listeners()
            # 保守只用第一個解析成功
            break


class SunriliveSensorBase(PassiveBluetoothProcessorEntity, SensorEntity):
    """Base class for Sunrilive sensors."""

    _attr_attribution = "Data from Sunrilive BLE sensor"
    _attr_has_entity_name = True


class TempSensor(SunriliveSensorBase):
    """溫度 sensor."""

    def __init__(
        self,
        processor: PassiveBluetoothDataUpdateCoordinator,
        entity_key: dict[str, Any],
        description: SensorEntityDescription,
    ) -> None:
        super().__init__(processor, entity_key, description)

    @callback
    def _async_update_from_bluetooth(self) -> None:
        self._attr_native_value = self.coordinator._last_temp


class HumidSensor(SunriliveSensorBase):
    """濕度 sensor."""

    def __init__(
        self,
        processor: PassiveBluetoothDataUpdateCoordinator,
        entity_key: dict[str, Any],
        description: SensorEntityDescription,
    ) -> None:
        super().__init__(processor, entity_key, description)

    @callback
    def _async_update_from_bluetooth(self) -> None:
        self._attr_native_value = self.coordinator._last_humid


@callback
def _async_add_entity(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
    address: str,
) -> None:
    """在 address 上新增 temp / humid sensor。"""
    coord = SunriliveBleDataUpdateCoordinator(hass, address)

    temp_key = {"key": "temperature", "address": address}
    humid_key = {"key": "humidity", "address": address}

    async_add_entities(
        [
            TempSensor(coord, temp_key, TEMPERATURE_SENSOR),
            HumidSensor(coord, humid_key, HUMIDITY_SENSOR),
        ]
    )


@callback
def _async_device_registered(hass: HomeAssistant, entry: ConfigEntry, address: str) -> None:
    """在 device_registry 裡註冊這台 Sunrilive sensor。"""
    dev_reg = dr.async_get(hass)
    dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={("sunrilive_ble", address)},
        name=MODEL,
        manufacturer=MANUFACTURER,
        model=MODEL,
        via_device=(DOMAIN, entry.entry_id),
    )


@callback
def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Setup callback from HA."""
    manual_macs = entry.data.get(CONF_MANUAL_MACS, [])

    # 1. 手動輸入的 MAC
    for addr in manual_macs:
        addr = addr.upper()
        _async_device_registered(hass, entry, addr)
        _async_add_entity(hass, entry, async_add_entities, addr)

    # 2. 自動發現：只要在 manufacturer_data 裡看到 01 09 的，就把它的 address 加進來
    @callback
    def _handle_discovery_for_new_devices(info: BluetoothServiceInfoBleak) -> None:
        mfg_data = info.advertisement_data.manufacturer_data
        if not mfg_data:
            return

        for _cid, data in mfg_data.items():
            # 0x01 0x09 開頭代表 Sunrilive 風格
            if len(data.data) >= 11 and data.data[0:2] == bytes([0x01, 0x09]):
                addr = info.address.upper()
                if addr not in hass.data[DOMAIN].get("entities_per_mac", []):
                    hass.data[DOMAIN].setdefault("entities_per_mac", set()).add(addr)
                    _async_device_registered(hass, entry, addr)
                    _async_add_entity(hass, entry, async_add_entities, addr)
                break

    # 註冊這個 callback，讓 自動發現 產生實體
    async_register_callback(
        hass,
        _handle_discovery_for_new_devices,
        {},
    )
