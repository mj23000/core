"""Various utilities for the Bang & Olufsen integration."""

from __future__ import annotations

from typing import cast

from mozart_api.models import PairedRemote
from mozart_api.mozart_client import MozartClient

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_MODEL

from .const import MOZART_MODELS, BangOlufsenModel


def get_serial_number_from_jid(jid: str) -> str:
    """Get serial number from Beolink JID."""
    return jid.split(".")[2].split("@")[0]


def is_halo(config_entry: ConfigEntry) -> bool:
    """Return if device is a Halo."""

    if config_entry.data[CONF_MODEL] == BangOlufsenModel.BEOREMOTE_HALO:
        return True
    return False


def is_mozart(config_entry: ConfigEntry) -> bool:
    """Return if device is Mozart based."""

    if config_entry.data[CONF_MODEL] in MOZART_MODELS:
        return True
    return False


async def get_remote(client: MozartClient) -> PairedRemote | None:
    """Get remote status easier."""
    remote: PairedRemote | None = None

    # Get if a remote control is connected and the remote
    bluetooth_remote_list = await client.get_bluetooth_remotes()

    if bool(len(cast(list[PairedRemote], bluetooth_remote_list.items))):
        # Support only the first remote for now.
        temp_remote = cast(list[PairedRemote], bluetooth_remote_list.items)[0]

        # Remotes that been unpaired on the remote may still be available on the device,
        # But should not be treated as available.
        if temp_remote.serial_number is not None:
            remote = temp_remote

    return remote
