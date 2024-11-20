"""The Bang & Olufsen integration."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

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
from .util import get_remote, is_halo
from .websocket import BangOlufsenHaloWebsocket, BangOlufsenMozartWebsocket

MOZART_PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.EVENT,
    Platform.MEDIA_PLAYER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.TEXT,
]

HALO_PLATFORMS = [Platform.SENSOR]


@dataclass
class BangOlufsenMozartData:
    """Dataclass for API client, WebSocket listener and WebSocket initialization variables."""

    websocket: BangOlufsenMozartWebsocket
    client: MozartClient
    platforms_initialized: int = 0


@dataclass
class BangOlufsenHaloData:
    """Dataclass for API client, WebSocket listener and WebSocket initialization variables."""

    websocket: BangOlufsenHaloWebsocket
    client: Halo


type BangOlufsenMozartConfigEntry = ConfigEntry[BangOlufsenMozartData]
type BangOlufsenHaloConfigEntry = ConfigEntry[BangOlufsenHaloData]


def set_platform_initialized(data: BangOlufsenMozartData) -> None:
    """Increment platforms_initialized to indicate that a platform has been initialized."""
    data.platforms_initialized += 1


async def _start_websocket_listener(data: BangOlufsenMozartData) -> None:
    """Start WebSocket listener when all platforms have been initialized."""

    while True:
        # Check if all platforms have been initialized and start WebSocket listener
        if len(MOZART_PLATFORMS) == data.platforms_initialized:
            break

        await asyncio.sleep(0)

    await data.client.connect_notifications(remote_control=True, reconnect=True)


async def _setup_mozart(
    hass: HomeAssistant, config_entry: BangOlufsenMozartConfigEntry
) -> bool:
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
    websocket = BangOlufsenMozartWebsocket(hass, config_entry, client)

    # Add the coordinator and API client
    config_entry.runtime_data = BangOlufsenMozartData(websocket, client)

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
        _start_websocket_listener(config_entry.runtime_data),
        f"{DOMAIN}-{config_entry.unique_id}-websocket_starter",
    )

    return True


async def _setup_halo(
    hass: HomeAssistant, config_entry: BangOlufsenHaloConfigEntry
) -> bool:
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
    websocket = BangOlufsenHaloWebsocket(hass, config_entry, client)

    # Add the coordinator and API client
    config_entry.runtime_data = BangOlufsenHaloData(websocket, client)

    await hass.config_entries.async_forward_entry_setups(config_entry, HALO_PLATFORMS)

    await client.connect_notifications()

    return True


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


async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Unload a config entry."""

    # Close the API client and WebSocket notification listener
    if is_halo(config_entry):
        await config_entry.runtime_data.client.disconnect_notifications()
        platforms = HALO_PLATFORMS
    else:
        config_entry.runtime_data.client.disconnect_notifications()
        await config_entry.runtime_data.client.close_api_client()
        platforms = MOZART_PLATFORMS

    return await hass.config_entries.async_unload_platforms(config_entry, platforms)
