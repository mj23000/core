"""The Bang & Olufsen integration."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from aiohttp import ClientConnectorError, ClientOSError, ServerTimeoutError
from mozart_api.exceptions import ApiException
from mozart_api.mozart_client import MozartClient

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_MODEL, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.util.ssl import get_default_context

from .const import BEO_REMOTE_MODEL, DOMAIN
from .halo import Halo
from .util import get_remote, is_halo, is_mozart
from .websocket import HaloWebsocket, MozartWebsocket

MOZART_PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.EVENT,
    Platform.MEDIA_PLAYER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.TEXT,
]

HALO_PLATFORMS = [Platform.EVENT, Platform.SENSOR]


@dataclass
class MozartData:
    """Dataclass for API client, WebSocket listener and WebSocket initialization variables."""

    websocket: MozartWebsocket
    client: MozartClient
    platforms_initialized: int = 0


@dataclass
class HaloData:
    """Dataclass for API client, WebSocket listener and WebSocket initialization variables."""

    websocket: HaloWebsocket
    client: Halo
    platforms_initialized: int = 0


type MozartConfigEntry = ConfigEntry[MozartData]
type HaloConfigEntry = ConfigEntry[HaloData]


def set_platform_initialized(data: MozartData) -> None:
    """Increment platforms_initialized to indicate that a platform has been initialized."""
    data.platforms_initialized += 1


async def _start_websocket_listener(
    config_entry: HaloConfigEntry | MozartConfigEntry,
    platforms: list[Platform],
) -> None:
    """Start WebSocket listener when all platforms have been initialized."""

    while True:
        # Check if all platforms have been initialized and start WebSocket listener
        if len(platforms) == config_entry.runtime_data.platforms_initialized:
            break

        await asyncio.sleep(0)

    if is_mozart(config_entry):
        if TYPE_CHECKING:
            assert isinstance(config_entry.runtime_data, MozartData)
        await config_entry.runtime_data.client.connect_notifications(
            remote_control=True, reconnect=True
        )
    else:
        await config_entry.runtime_data.client.connect_notifications(reconnect=True)


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Set up from a config entry."""

    # Remove casts to str
    assert config_entry.unique_id

    # Create device now as BangOlufsenWebsocket needs a device for debug logging, firing events etc.
    # And in order to ensure entity platforms (button, binary_sensor) have device name before the primary (media_player) is initialized
    device_registry = dr.async_get(hass)
    device_registry.async_get_or_create(
        config_entry_id=config_entry.entry_id,
        identifiers={(DOMAIN, config_entry.unique_id)},
        name=config_entry.title,
        model=config_entry.data[CONF_MODEL],
        serial_number=config_entry.unique_id,
        manufacturer="Bang & Olufsen",
    )

    if is_halo(config_entry):
        return await _setup_halo(hass, config_entry)

    # Mozart based products
    return await _setup_mozart(hass, config_entry)


async def _setup_mozart(hass: HomeAssistant, config_entry: MozartConfigEntry) -> bool:
    """Set up a Mozart based product."""
    client = MozartClient(
        host=config_entry.data[CONF_HOST], ssl_context=get_default_context()
    )

    # Check API and WebSocket connection
    try:
        await client.check_device_connection(True)
    except* (
        ClientConnectorError,
        ClientOSError,
        ServerTimeoutError,
        ApiException,
        TimeoutError,
    ) as error:
        await client.close_api_client()
        raise ConfigEntryNotReady(
            f"Unable to connect to {config_entry.title}"
        ) from error

    # Initialize coordinator
    websocket = MozartWebsocket(hass, config_entry, client)

    # Add the coordinator and API client
    config_entry.runtime_data = MozartData(websocket, client)

    # Check for connected Beoremote One
    if remote := await get_remote(client):
        assert remote.serial_number

        # Create Beoremote One device
        assert config_entry.unique_id
        device_registry = dr.async_get(hass)
        device_registry.async_get_or_create(
            config_entry_id=config_entry.entry_id,
            identifiers={(DOMAIN, remote.serial_number)},
            name=f"{BEO_REMOTE_MODEL}-{remote.serial_number}",
            model=BEO_REMOTE_MODEL,
            serial_number=remote.serial_number,
            sw_version=remote.app_version,
            manufacturer="Bang & Olufsen",
            via_device=(DOMAIN, config_entry.unique_id),
        )
    else:
        # If the remote is no longer available, then delete the device.
        # The remote may appear as being available to the device after is has been unpaired on the remote
        # As it has to be removed from the device on the app.

        device_registry = dr.async_get(hass)
        devices = device_registry.devices.get_devices_for_config_entry_id(
            config_entry.entry_id
        )
        for device in devices:
            assert device.model is not None
            if device.model == BEO_REMOTE_MODEL:
                device_registry.async_remove_device(device.id)

    await hass.config_entries.async_forward_entry_setups(config_entry, MOZART_PLATFORMS)

    # Start WebSocket connection when all entities have been initialized
    config_entry.async_create_background_task(
        hass,
        _start_websocket_listener(config_entry, MOZART_PLATFORMS),
        f"{DOMAIN}-{config_entry.unique_id}-mozart-websocket_starter",
    )

    return True


async def _setup_halo(hass: HomeAssistant, config_entry: HaloConfigEntry) -> bool:
    """Set up a Halo."""
    client = Halo(host=config_entry.data[CONF_HOST])

    # Check API and WebSocket connection
    try:
        await client.check_device_connection()
    except Exception as error:
        raise ConfigEntryNotReady(
            f"Unable to connect to {config_entry.title}"
        ) from error

    # Initialize coordinator
    websocket = HaloWebsocket(hass, config_entry, client)

    # Add the coordinator and API client
    config_entry.runtime_data = HaloData(websocket, client)

    await hass.config_entries.async_forward_entry_setups(config_entry, HALO_PLATFORMS)

    # Start WebSocket connection when all entities have been initialized
    config_entry.async_create_background_task(
        hass,
        _start_websocket_listener(config_entry, HALO_PLATFORMS),
        f"{DOMAIN}-{config_entry.unique_id}-halo-websocket_starter",
    )

    config_entry.async_on_unload(config_entry.add_update_listener(async_update_options))

    return True


async def async_update_options(hass: HomeAssistant, entry: HaloConfigEntry) -> None:
    """Update options."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Unload a config entry."""

    # Close the API client and WebSocket notification listener
    if is_halo(config_entry):
        if TYPE_CHECKING:
            assert isinstance(config_entry.runtime_data, HaloData)
        await config_entry.runtime_data.client.disconnect_notifications()
        platforms = HALO_PLATFORMS
    else:
        config_entry.runtime_data.client.disconnect_notifications()
        await config_entry.runtime_data.client.close_api_client()
        platforms = MOZART_PLATFORMS

    return await hass.config_entries.async_unload_platforms(config_entry, platforms)
