"""Platform for sensor integration."""
from __future__ import annotations

from datetime import date, datetime
import logging

from toshiba_ac.device import ToshibaAcDevice, ToshibaAcDeviceEnergyConsumption

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import UnitOfEnergy, UnitOfTemperature
from homeassistant.helpers.typing import StateType

from .const import DOMAIN
from .entity import ToshibaAcEntity, ToshibaAcStateEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, config_entry, async_add_devices):
    """Add sensor entities for passed config_entry in HA."""
    device_manager = hass.data[DOMAIN][config_entry.entry_id]
    new_entities = []

    devices: list[ToshibaAcDevice] = await device_manager.get_devices()
    for device in devices:
        if device.supported.ac_energy_report:
            new_entities.append(ToshibaPowerSensor(device))
        else:
            _LOGGER.debug(
                "AC device %s does not support energy monitoring", device.name
            )

        # Outdoor temperature sensor - value may be None when outdoor unit is off
        new_entities.append(ToshibaTempSensor(device))

        # --- NEW: Add the 9 Custom Engineering Sensors ---
        new_entities.extend([
            ToshibaEngineeringSensor(device, "ac_compressor_hz", "Compressor Speed", "mdi:engine", "Hz", None),
            ToshibaEngineeringSensor(device, "ac_discharge_temp", "Discharge Temp", "mdi:thermometer-high", "°C", "temperature"),
            ToshibaEngineeringSensor(device, "ac_suction_temp", "Suction Temp", "mdi:thermometer-low", "°C", "temperature"),
            ToshibaEngineeringSensor(device, "ac_outdoor_coil_temp", "Outdoor Coil Temp", "mdi:heating-coil", "°C", "temperature"),
            ToshibaEngineeringSensor(device, "ac_indoor_coil_inlet_temp", "Indoor Coil Inlet Temp", "mdi:air-filter", "°C", "temperature"),
            ToshibaEngineeringSensor(device, "ac_indoor_coil_outlet_temp", "Indoor Coil Outlet Temp", "mdi:air-purifier", "°C", "temperature"),
            ToshibaEngineeringSensor(device, "ac_outdoor_fan_speed", "Outdoor Fan Speed", "mdi:fan", "step", None),
            ToshibaEngineeringSensor(device, "ac_indoor_fan_speed", "Indoor Fan Speed", "mdi:fan", "step", None),
            ToshibaEngineeringSensor(device, "ac_expansion_valve_pulse", "Expansion Valve", "mdi:valve", "pulse", None),
        ])

    if new_entities:
        _LOGGER.info("Adding %d sensor entities", len(new_entities))
        async_add_devices(new_entities)


class ToshibaPowerSensor(ToshibaAcEntity, SensorEntity):
    """Provides a Toshiba Sensors."""

    _attr_native_unit_of_measurement = UnitOfEnergy.WATT_HOUR
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _ac_energy_consumption: ToshibaAcDeviceEnergyConsumption | None = None

    def __init__(self, toshiba_device: ToshibaAcDevice):
        """Initialize the sensor."""
        super().__init__(toshiba_device)
        self._attr_unique_id = f"{self._device.ac_unique_id}_sensor"
        self._attr_name = f"{self._device.name} Power Consumption"

    async def state_changed(self, _dev: ToshibaAcDevice):
        """Call if we need to change the ha state."""
        self._ac_energy_consumption = self._device.ac_energy_consumption
        self.async_write_ha_state()

    async def async_added_to_hass(self):
        """Run when this Entity has been added to HA."""
        # Importantly for a push integration, the module that will be getting updates
        # needs to notify HA of changes. The dummy device has a registercallback
        # method, so to this we add the 'self.async_write_ha_state' method, to be
        # called where ever there are changes.
        # The call back registration is done once this entity is registered with HA
        # (rather than in the __init__)
        # self._device.register_callback(self.async_write_ha_state)
        self._device.on_energy_consumption_changed_callback.add(self.state_changed)

    async def async_will_remove_from_hass(self):
        """Entity being removed from hass."""
        # The opposite of async_added_to_hass. Remove any registered call backs here.
        # self._device.remove_callback(self.async_write_ha_state)
        self._device.on_energy_consumption_changed_callback.remove(self.state_changed)

    @property
    def native_value(self) -> StateType | date | datetime:
        """Return the value reported by the sensor."""
        if self._ac_energy_consumption:
            return self._ac_energy_consumption.energy_wh
        return None

    @property
    def extra_state_attributes(self):
        """Return the state attributes."""
        if self._ac_energy_consumption:
            return {"last_reset": self._ac_energy_consumption.since}
        return {}


class ToshibaTempSensor(ToshibaAcStateEntity, SensorEntity):
    """Provides a Toshiba Temperature Sensors."""

    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_has_entity_name = True

    def __init__(self, device: ToshibaAcDevice):
        """Initialize the sensor."""
        super().__init__(device)
        self._attr_unique_id = f"{device.ac_unique_id}_outdoor_temperature"
        self._attr_translation_key = "outdoor_temperature"

    @property
    def available(self) -> bool:
        """Return True if sensor is available."""
        if self._device.ac_outdoor_temperature is None:
            return False
        return super().available

    @property
    def native_value(self) -> int | None:
        """Return the value reported by the sensor."""
        return self._device.ac_outdoor_temperature

class ToshibaEngineeringSensor(ToshibaAcEntity, SensorEntity):
    """Representation of a Toshiba AC Engineering Sensor."""

    def __init__(self, device, attr_key, name_suffix, icon, unit, device_class):
        """Initialize the generic sensor."""
        super().__init__(device)
        self._attr_key = attr_key
        self._name_suffix = name_suffix
        self._attr_icon = icon
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def name(self):
        """Return the name of the sensor."""
        return f"{self._device.name} {self._name_suffix}"

    @property
    def unique_id(self):
        """Return a unique ID."""
        return f"{self._device.ac_id}_{self._attr_key}"

    @property
    def native_value(self):
        """Return the state of the sensor from the device object."""
        val = getattr(self._device, self._attr_key, None)
        # Filter out the 'Idle/Off' codes from Toshiba
        if val in [127, 254, None]:
            return 0
        return val

    async def async_added_to_hass(self):
        """Register callbacks to update the sensor when the device state changes."""
        self._device.on_state_changed_callback.add(self.async_write_ha_state)

    async def async_will_remove_from_hass(self):
        """Cleanup callback when the sensor is removed."""
        self._device.on_state_changed_callback.remove(self.async_write_ha_state)