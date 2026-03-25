"""Constants for Sunrilive BLE integration."""

DOMAIN = "sunrilive_ble"
VERSION = "0.1.0"
MANUFACTURER = "Sunrilive / Tuya"
MODEL = "XL0801_BLE"
CONF_MANUAL_MACS = "manual_macs"

# 用 UUID 降低重複
def uid_from_mac(mac: str) -> str:
    return f"sunrilive_ble_{mac.replace(':', '').lower()}"
