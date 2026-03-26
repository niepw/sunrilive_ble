from __future__ import annotations

import logging  # 這個一定要加

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.components.bluetooth.passive_update_processor import PassiveBluetoothProcessorEntity
from homeassistant.components.bluetooth.passive_update_coordinator import PassiveBluetoothDataUpdateCoordinator
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfTemperature,
)
from homeassistant.core import callback, HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN, MANUFACTURER, MODEL, CONF_MANUAL_MACS, uid_from_mac
from .__init__ import SunriliveBleRuntimeData

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)

def _parse_adv(data: bytes) -> tuple[float | None, int | None]:
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

    return None, None


class SunriliveBleDataUpdateCoordinator(PassiveBluetoothDataUpdateCoordinator):
    """處理多個 Sunrilive BLE sensor 的資料更新。"""

    def __init__(
        self,
        hass: HomeAssistant,
        address: str,
        config_entry: ConfigEntry,
        entry_data: SunriliveBleRuntimeData,
    ) -> None:
        super().__init__(
            hass=hass,
            logger=_LOGGER,
            address=address,
            device_type=None,
        )
        self._address = address
        self._config_entry = config_entry
        self._entry_data = entry_data
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
        for cid, data in mfg_data.items():
            temp_c, humid_pct = _parse_adv(data.data)
            if temp_c is None or humid_pct is None:
                continue

            self._last_temp = temp_c
            self._last_humid = humid_pct
            self._async_update_listeners()
            # 保守只用第一個解析成功
            break


class SunriliveSensorBase(PassiveBluetoothProcessorEntity, SensorEntity):
    """Base class for Sunrilive sensors."""

    _attr_attribution = "Data from Sunrilive BLE sensor"
    _attr_has_entity_name = True

    def _device_info(self, address: str) -> DeviceInfo:
        uid = uid_from_mac(address)
        return DeviceInfo(
            identifiers={(DOMAIN, uid)},
            name=MODEL,
            manufacturer=MANUFACTURER,
            model=MODEL,
            configuration_url="https://github.com/niepw/sunrilive_ble",
        )


class TempSensor(SunriliveSensorBase):
    """溫度 sensor."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_name = "Temperature"

    @property
    def unique_id(self) -> str:
        address = self.coordinator._address
        return f"{uid_from_mac(address)}_temp"

    @callback
    def _async_update_from_bluetooth(self) -> None:
        self._attr_native_value = self.coordinator._last_temp


class HumidSensor(SunriliveSensorBase):
    """濕度 sensor."""

    _attr_device_class = SensorDeviceClass.HUMIDITY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_name = "Humidity"

    @property
    def unique_id(self) -> str:
        address = self.coordinator._address
        return f"{uid_from_mac(address)}_humidity"

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
    """在 address 上新增 temp / humid sensor."""
    runtime_data: SunriliveBleRuntimeData = hass.data[DOMAIN][entry.entry_id]
    coord = SunriliveBleDataUpdateCoordinator(
        hass, address, entry, runtime_data
    )
    runtime_data.coordinators[address] = coord

    async_add_entities(
        [
            TempSensor(
                coord,
                address,
                entry,
            ),
            HumidSensor(
                coord,
                address,
                entry,
            ),
        ]
    )


@callback
def _device_key(address: str) -> str:
    """在設備註冊中用 key 標示這台裝置。"""
    return f"{DOMAIN}_{address}"


@callback
def _async_device_registered(
    hass: HomeAssistant,
    entry: ConfigEntry,
    address: str,
) -> None:
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
    runtime_data: SunriliveBleRuntimeData = hass.data[DOMAIN][entry.entry_id]
    manual_macs = entry.data.get(CONF_MANUAL_MACS, [])

    # 1. 手動輸入的 MAC
    for addr in manual_macs:
        addr = addr.upper()
        _async_device_registered(hass, entry, addr)
        _async_add_entity(hass, entry, async_add_entities, addr)

    # 2. 自動發現：只要在 manufacturer_data 裡看到 01 09 的，就把它的 address 加進來
    # 這邊假設你用 HA 內建的 BLE passive listener，只需要在初始化時，註冊一個 listener

    @callback
    def _handle_discovery(info: BluetoothServiceInfoBleak) -> None:
        mfg_data = info.advertisement_data.manufacturer_data
        if not mfg_data:
            return

        for cid, data in mfg_data.items():
            # 0x01 0x09 開頭代表 Sunrilive 風格
            if len(data.data) >= 11 and data.data[0:2] == bytes([0x01, 0x09]):
                addr = info.address.upper()
                if addr not in runtime_data.coordinators:
                    _async_device_registered(hass, entry, addr)
                    _async_add_entity(hass, entry, async_add_entities, addr)
                break

    # 依你用的 HA 版本，你可以在這邊註冊一个 BLE 事件 Listener
    # 例如:
    # from homeassistant.components.bluetooth import async_get_scanner
    # scanner = async_get_scanner(hass)
    # scanner.register_advertisement_listener(_handle_discovery)

    # 這邊只是示意；如果你只用「手動輸入 MAC」也足夠，可以先跳過自動發現的部分
