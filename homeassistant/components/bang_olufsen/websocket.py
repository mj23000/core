"""WebSocket listener(s) for the Bang & Olufsen integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from mozart_api.models import (
    BatteryState,
    BeoRemoteButton,
    ButtonEvent,
    ListeningModeProps,
    PlaybackContentMetadata,
    PlaybackError,
    PlaybackProgress,
    RenderingState,
    SoftwareUpdateState,
    Source,
    SpeakerGroupOverview,
    VolumeState,
    WebsocketNotificationTag,
)
from mozart_api.mozart_client import BaseWebSocketResponse, MozartClient

from homeassistant.components.button import DOMAIN as BUTTON_DOMAIN, SERVICE_PRESS
from homeassistant.components.input_button import DOMAIN as INPUT_BUTTON_DOMAIN
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID, CONF_ENTITY_ID, Platform
from homeassistant.core import Event, EventStateChangedData, HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util.enum import try_parse_enum

from .const import (
    BANG_OLUFSEN_HALO_WEBSOCKET_EVENT,
    BANG_OLUFSEN_WEBSOCKET_EVENT,
    CONF_ENTITY_MAP,
    CONF_HALO,
    CONNECTION_STATUS,
    EVENT_TRANSLATION_MAP,
    WebsocketNotification,
)
from .entity import HaloBase, MozartBase
from .halo import (
    BaseConfiguration,
    BaseUpdate,
    BaseWebSocketResponse as HaloBaseWebSocketResponse,
    Button,
    ButtonEvent as HaloButtonEvent,
    ButtonEventState,
    ButtonState,
    Halo,
    PowerEvent,
    StatusEvent,
    SystemEvent,
    UpdateButton,
    WheelEvent,
)

_LOGGER = logging.getLogger(__name__)


class HaloWebsocket(HaloBase):
    """WebSocket for Halo."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        client: Halo,
    ) -> None:
        """Initialize the entity coordinator."""
        super().__init__(config_entry, client)

        self.hass = hass
        self._device = self.get_device(hass, self._unique_id)
        self._entity_registry = er.async_get(self.hass)
        self._entity_map: dict[str, str] = {}
        self._configuration: BaseConfiguration | None = None

        if TYPE_CHECKING:
            assert isinstance(self._client, Halo)

        self._client.get_button_event(self.on_button_event)
        self._client.get_on_connection_lost(self.on_connection_lost)
        self._client.get_on_connection(self.on_connection)
        self._client.get_power_event(self.on_power_event)
        self._client.get_status_event(self.on_status_event)
        self._client.get_system_event(self.on_system_event)
        self._client.get_wheel_event(self.on_wheel_event)

        self._client.get_all_notifications_raw(self.on_all_notifications_raw)

        # Track entity changes to sync with Halo configuration
        if config_entry.options:
            self._entity_map = config_entry.options[CONF_ENTITY_MAP]

            entities = list(self._entity_map.values())
            async_track_state_change_event(
                self.hass,
                entities,
                self._handle_entity_state_change,
            )

    async def _handle_entity_state_change(
        self,
        event: Event[EventStateChangedData],
    ) -> None:
        """Handle state change of entities."""
        entity_id = event.data[CONF_ENTITY_ID]

        entity_type = entity_id.split(".")[0]

        if not self._entity_map:
            return

        # Get the button ids
        button_ids = []
        for mapped_button_id, mapped_entity_id in self._entity_map.items():
            if mapped_entity_id == entity_id:
                button_ids.append(mapped_button_id)

        for button_id in button_ids:
            # Add event for testing
            if entity_type == Platform.SENSOR:
                await self._handle_sensor(entity_id, button_id)
            # elif entity_type == Platform.BUTTON:
            #     await self._handle_button(entity_id, button_id)

        # TO DO handle entity deletion

    def _get_button_from_id(self, button_id: str) -> Button | None:
        """Get Button from button_id."""
        if self._configuration is not None:
            for page in self._configuration.configuration.pages:
                for button in page.buttons:
                    if button.id == button_id:
                        return button
        return None

    async def _handle_sensor(self, entity_id: str, button_id: str) -> None:
        """Handle state change events of Sensor entities."""
        state = self.hass.states.get(entity_id)
        if state is None:
            _LOGGER.error("Unable to update state of %s", entity_id)
            return

        try:
            button_state = int(state.state)
        except ValueError:
            _LOGGER.error("Invalid state %s", state.state)
            if state.state == "playing":
                button_state = 1
            else:
                button_state = 0

        button = self._get_button_from_id(button_id)

        if button is None:
            return

        await self._client.send(
            BaseUpdate(
                update=UpdateButton(
                    button.id,
                    ButtonState.ACTIVE if button_state > 0 else ButtonState.INACTIVE,
                )
            )
        )

    async def _handle_button(self, event: HaloButtonEvent) -> None:
        """Handle state change events of Button entities."""

        if event.state == ButtonEventState.RELEASED:
            return

        entity_id = self._entity_map[event.id]
        domain = (
            INPUT_BUTTON_DOMAIN
            if entity_id.startswith(INPUT_BUTTON_DOMAIN)
            else BUTTON_DOMAIN
        )

        try:
            await self.hass.services.async_call(
                domain,
                SERVICE_PRESS,
                {ATTR_ENTITY_ID: entity_id},
            )
            # logging.warning("Pressing button for %s", entity_id)
        except HomeAssistantError:
            logging.exception("Error triggering %s", entity_id)
        # try:
        #     button_state = state.state
        # except ValueError:
        #     _LOGGER.error("Invalid state %s", state.state)
        #     if state.state == "playing":
        #         button_state = 1
        #     else:
        #         button_state = 0

        # button = self._get_button_from_id(button_id)

        # if button is None:
        #     return

        # await self._client.send(
        #     BaseUpdate(
        #         update=HaloButtonEvent(
        #             button.id,
        #             ButtonState.ACTIVE if button_state > 0 else ButtonState.INACTIVE,
        #         )
        #     )
        # )

    def _update_connection_status(self) -> None:
        """Update all entities of the connection status."""
        async_dispatcher_send(
            self.hass,
            f"{self._unique_id}_{CONNECTION_STATUS}",
            self._client.websocket_connected,
        )

    async def on_connection(self) -> None:
        """Handle WebSocket connection made."""
        _LOGGER.debug(
            "Connected to the %s notification channel. Sending configuration",
            self._entry.title,
        )
        if self._entry.options:
            configuration = self._entry.options[CONF_HALO]
        else:
            configuration = self._entry.data[CONF_HALO]

        self._configuration = BaseConfiguration.from_dict(configuration)

        await self._client.send(self._configuration)
        self._update_connection_status()

    def on_connection_lost(self) -> None:
        """Handle WebSocket connection lost."""
        _LOGGER.error("Lost connection to the %s", self._entry.title)
        self._update_connection_status()

    async def on_button_event(self, event: HaloButtonEvent) -> None:
        """Send halo_button dispatch."""
        await self._handle_button(event=event)

        async_dispatcher_send(
            self.hass,
            f"{self._unique_id}_{WebsocketNotification.HALO_BUTTON}",
            event,
        )

    def on_power_event(self, event: PowerEvent) -> None:
        """Send halo_power dispatch."""
        async_dispatcher_send(
            self.hass,
            f"{self._unique_id}_{WebsocketNotification.HALO_POWER}",
            event,
        )

    def on_status_event(self, event: StatusEvent) -> None:
        """Send halo_status dispatch."""
        async_dispatcher_send(
            self.hass,
            f"{self._unique_id}_{WebsocketNotification.HALO_STATUS}",
            event,
        )

    def on_system_event(self, event: SystemEvent) -> None:
        """Send halo_system dispatch."""
        async_dispatcher_send(
            self.hass,
            f"{self._unique_id}_{WebsocketNotification.HALO_SYSTEM}",
            event,
        )

    def on_wheel_event(self, event: WheelEvent) -> None:
        """Send halo_wheel dispatch."""
        async_dispatcher_send(
            self.hass,
            f"{self._unique_id}_{WebsocketNotification.HALO_WHEEL}",
            event,
        )

    def on_all_notifications_raw(self, event: HaloBaseWebSocketResponse) -> None:
        """Receive all events."""
        debug_event = {
            "device_id": self._device.id,
            "serial_number": int(self._unique_id),
            **event,
        }

        _LOGGER.debug("%s", debug_event)
        self.hass.bus.async_fire(BANG_OLUFSEN_HALO_WEBSOCKET_EVENT, debug_event)


class MozartWebsocket(MozartBase):
    """WebSocket listener(s) for Mozart products."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        client: MozartClient,
    ) -> None:
        """Initialize the entity coordinator."""
        super().__init__(config_entry, client)

        self.hass = hass
        self._device = self.get_device(hass, self._unique_id)

        if TYPE_CHECKING:
            assert isinstance(self._client, MozartClient)

        # WebSocket callbacks
        self._client.get_active_listening_mode_notifications(
            self.on_active_listening_mode
        )
        self._client.get_active_speaker_group_notifications(
            self.on_active_speaker_group
        )
        self._client.get_battery_notifications(self.on_battery_notification)
        self._client.get_beo_remote_button_notifications(
            self.on_beo_remote_button_notification
        )
        self._client.get_button_notifications(self.on_button_notification)
        self._client.get_notification_notifications(self.on_notification_notification)
        self._client.get_on_connection_lost(self.on_connection_lost)
        self._client.get_on_connection(self.on_connection)
        self._client.get_playback_error_notifications(
            self.on_playback_error_notification
        )
        self._client.get_playback_metadata_notifications(
            self.on_playback_metadata_notification
        )
        self._client.get_playback_progress_notifications(
            self.on_playback_progress_notification
        )
        self._client.get_playback_source_notifications(
            self.on_playback_source_notification
        )
        self._client.get_playback_state_notifications(
            self.on_playback_state_notification
        )
        self._client.get_software_update_state_notifications(
            self.on_software_update_state
        )
        self._client.get_source_change_notifications(self.on_source_change_notification)
        self._client.get_volume_notifications(self.on_volume_notification)

        # Used for firing events and debugging
        self._client.get_all_notifications_raw(self.on_all_notifications_raw)

    def _update_connection_status(self) -> None:
        """Update all entities of the connection status."""
        async_dispatcher_send(
            self.hass,
            f"{self._unique_id}_{CONNECTION_STATUS}",
            self._client.websocket_connected,
        )

    def on_connection(self) -> None:
        """Handle WebSocket connection made."""
        _LOGGER.debug("Connected to the %s notification channel", self._entry.title)
        self._update_connection_status()

    def on_connection_lost(self) -> None:
        """Handle WebSocket connection lost."""
        _LOGGER.error("Lost connection to the %s", self._entry.title)
        self._update_connection_status()

    def on_active_listening_mode(self, notification: ListeningModeProps) -> None:
        """Send active_listening_mode dispatch."""
        async_dispatcher_send(
            self.hass,
            f"{self._unique_id}_{WebsocketNotification.ACTIVE_LISTENING_MODE}",
            notification,
        )

    def on_active_speaker_group(self, notification: SpeakerGroupOverview) -> None:
        """Send active_speaker_group dispatch."""
        async_dispatcher_send(
            self.hass,
            f"{self._unique_id}_{WebsocketNotification.ACTIVE_SPEAKER_GROUP}",
            notification,
        )

    def on_battery_notification(self, notification: BatteryState) -> None:
        """Send battery dispatch."""
        async_dispatcher_send(
            self.hass,
            f"{self._unique_id}_{WebsocketNotification.BATTERY}",
            notification,
        )

    def on_beo_remote_button_notification(self, notification: BeoRemoteButton) -> None:
        """Send beo_remote_button dispatch."""
        assert notification.type
        # Send to event entity
        async_dispatcher_send(
            self.hass,
            f"{self._unique_id}_{WebsocketNotification.BEO_REMOTE_BUTTON}_{notification.key}",
            EVENT_TRANSLATION_MAP[notification.type],
        )

    def on_button_notification(self, notification: ButtonEvent) -> None:
        """Send button dispatch."""
        assert notification.state
        # Send to event entity
        async_dispatcher_send(
            self.hass,
            f"{self._unique_id}_{WebsocketNotification.BUTTON}_{notification.button}",
            EVENT_TRANSLATION_MAP[notification.state],
        )

    def on_notification_notification(
        self, notification: WebsocketNotificationTag
    ) -> None:
        """Send notification dispatch."""
        assert notification.value

        # Try to match the notification type with available WebsocketNotification members
        notification_type = try_parse_enum(WebsocketNotification, notification.value)

        if notification_type in (
            WebsocketNotification.PROXIMITY_PRESENCE_DETECTED,
            WebsocketNotification.PROXIMITY_PRESENCE_NOT_DETECTED,
        ):
            async_dispatcher_send(
                self.hass,
                f"{self._unique_id}_{WebsocketNotification.PROXIMITY}",
                EVENT_TRANSLATION_MAP[notification.value],
            )

        elif notification_type is WebsocketNotification.REMOTE_MENU_CHANGED:
            async_dispatcher_send(
                self.hass,
                f"{self._unique_id}_{WebsocketNotification.REMOTE_MENU_CHANGED}",
            )

        elif notification_type is WebsocketNotification.CONFIGURATION:
            async_dispatcher_send(
                self.hass,
                f"{self._unique_id}_{WebsocketNotification.CONFIGURATION}",
            )

        elif notification_type is WebsocketNotification.REMOTE_CONTROL_DEVICES:
            # Reinitialize the config entry to update Beoremote One entities and device
            # Wait 5 seconds for the remote to be properly available to the device
            _LOGGER.warning("Remote control has been modified. Reloading integration")
            self.hass.loop.call_later(
                5,
                self.hass.config_entries.async_schedule_reload,
                self._entry.entry_id,
            )

        elif notification_type in (
            WebsocketNotification.BEOLINK_PEERS,
            WebsocketNotification.BEOLINK_LISTENERS,
            WebsocketNotification.BEOLINK_AVAILABLE_LISTENERS,
        ):
            async_dispatcher_send(
                self.hass,
                f"{self._unique_id}_{WebsocketNotification.BEOLINK}",
            )

    def on_playback_error_notification(self, notification: PlaybackError) -> None:
        """Send playback_error dispatch."""
        async_dispatcher_send(
            self.hass,
            f"{self._unique_id}_{WebsocketNotification.PLAYBACK_ERROR}",
            notification,
        )

    def on_playback_metadata_notification(
        self, notification: PlaybackContentMetadata
    ) -> None:
        """Send playback_metadata dispatch."""
        async_dispatcher_send(
            self.hass,
            f"{self._unique_id}_{WebsocketNotification.PLAYBACK_METADATA}",
            notification,
        )

    def on_playback_progress_notification(self, notification: PlaybackProgress) -> None:
        """Send playback_progress dispatch."""
        async_dispatcher_send(
            self.hass,
            f"{self._unique_id}_{WebsocketNotification.PLAYBACK_PROGRESS}",
            notification,
        )

    def on_playback_source_notification(self, notification: Source) -> None:
        """Send playback_source dispatch."""
        async_dispatcher_send(
            self.hass,
            f"{self._unique_id}_{WebsocketNotification.PLAYBACK_SOURCE}",
            notification,
        )

    def on_playback_state_notification(self, notification: RenderingState) -> None:
        """Send playback_state dispatch."""
        async_dispatcher_send(
            self.hass,
            f"{self._unique_id}_{WebsocketNotification.PLAYBACK_STATE}",
            notification,
        )

    def on_source_change_notification(self, notification: Source) -> None:
        """Send source_change dispatch."""
        async_dispatcher_send(
            self.hass,
            f"{self._unique_id}_{WebsocketNotification.SOURCE_CHANGE}",
            notification,
        )

    def on_volume_notification(self, notification: VolumeState) -> None:
        """Send volume dispatch."""
        async_dispatcher_send(
            self.hass,
            f"{self._unique_id}_{WebsocketNotification.VOLUME}",
            notification,
        )

    async def on_software_update_state(self, _: SoftwareUpdateState) -> None:
        """Check device sw version."""
        software_status = await self._client.get_softwareupdate_status()

        # Update the HA device if the sw version does not match
        if software_status.software_version != self._device.sw_version:
            device_registry = dr.async_get(self.hass)

            device_registry.async_update_device(
                device_id=self._device.id,
                sw_version=software_status.software_version,
            )

    def on_all_notifications_raw(self, notification: BaseWebSocketResponse) -> None:
        """Receive all notifications."""

        debug_notification = {
            "device_id": self._device.id,
            "serial_number": int(self._unique_id),
            **notification,
        }

        _LOGGER.debug("%s", debug_notification)
        self.hass.bus.async_fire(BANG_OLUFSEN_WEBSOCKET_EVENT, debug_notification)
