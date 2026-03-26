"""Sunrilive BLE Temperature & Humidity sensor entities."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.bluetooth import (
    BluetoothScanningMode,
    BluetoothServiceInfoBleak,
    async_register_callback,
)
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_MANUAL_MACS, DOMAIN, MANUFACTURER, MODEL, uid_from_mac

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)


def _parse_manufacturer_payload(payload: bytes) -> tuple[float, int] | None:
    """解析 Sunrilive manufacturer payload（已去除 company ID 的部分）。
    
    格式：[01][09][TT_hi][TT_lo][HH][MAC 6 bytes] = 共 11 bytes
    """
    if len(payload) < 5:
        return None
    if payload[0:2] != bytes([0x01, 0x09]):
        return None

    temp_raw = (payload[2] << 8) | payload[3]
    humid_raw = payload[4]
    temp_c = temp_raw / 10.0
    return temp_c, humid_raw


class SunriliveBLESensor(SensorEntity):
    """Base Sunrilive BLE sensor."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, address: str) -> None:
        self._address = address
        self._uid = uid_from_mac(address)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._uid)},
            name=MODEL,
            manufacturer=MANUFACTURER,
            model=MODEL,
        )

    @callback
    def _handle_update(self, temp: float | None, humid: int | None) -> None:
        raise NotImplementedError

    def _push_update(self) -> None:
        self.async_write_ha_state()


class TempSensor(SunriliveBLESensor):
    """溫度 sensor."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_name = "Temperature"

    def __init__(self, address: str) -> None:
        super().__init__(address)
        self._attr_unique_id = f"{self._uid}_temp"
        self._attr_native_value: float | None = None

    @callback
    def _handle_update(self, temp: float | None, humid: int | None) -> None:
        self._attr_native_value = temp
        self._push_update()


class HumidSensor(SunriliveBLESensor):
    """濕度 sensor."""

    _attr_device_class = SensorDeviceClass.HUMIDITY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_name = "Humidity"

    def __init__(self, address: str) -> None:
        super().__init__(address)
        self._attr_unique_id = f"{self._uid}_humidity"
        self._attr_native_value: int | None = None

    @callback
    def _handle_update(self, temp: float | None, humid: int | None) -> None:
        self._attr_native_value = humid
        self._push_update()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Setup sensor platform."""
    manual_macs = entry.data.get(CONF_MANUAL_MACS, [])
    tracked: dict[str, list[SunriliveBLESensor]] = {}

    def _register_device(address: str) -> None:
        dev_reg = dr.async_get(hass)
        dev_reg.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, uid_from_mac(address))},
            name=MODEL,
            manufacturer=MANUFACTURER,
            model=MODEL,
        )

    def _add_address(address: str) -> None:
        if address in tracked:
            return
        _register_device(address)
        temp = TempSensor(address)
        humid = HumidSensor(address)
        tracked[address] = [temp, humid]
        async_add_entities([temp, humid])
        _LOGGER.debug("Added Sunrilive BLE sensor: %s", address)

    # 1. 先加手動輸入的 MAC
    for mac in manual_macs:
        _add_address(mac.upper())

    @callback
    def _ble_callback(
        service_info: BluetoothServiceInfoBleak,
        change: str,
    ) -> None:
        """處理 BLE 廣播，更新實體數值。"""
        # manufacturer_data 是 dict[int, bytes]
        # key = company ID (int)，value = payload bytes（不是物件）
        mfg_data = service_info.advertisement.manufacturer_data
        if not mfg_data:
            return

        for _company_id, payload in mfg_data.items():
            # payload 直接是 bytes，不需要 .data
            parsed = _parse_manufacturer_payload(payload)
            if not parsed:
                continue

            temp_c, humid_pct = parsed
            addr = service_info.address.upper()

            _LOGGER.debug(
                "Sunrilive BLE [%s] temp=%.1f humid=%d",
                addr, temp_c, humid_pct,
            )

            # 2. 自動發現：新裝置自動加入
            if addr not in tracked:
                _add_address(addr)

            # 3. 推送更新到實體
            for entity in tracked.get(addr, []):
                entity._handle_update(temp_c, humid_pct)
            break

    # 4. 用 entry.async_on_unload 確保 HA unload 時自動取消 callback
    entry.async_on_unload(
        async_register_callback(
            hass,
            _ble_callback,
            {},
            BluetoothScanningMode.PASSIVE,
        )
    )
