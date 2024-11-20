"""Halo client."""

import asyncio
from collections import defaultdict
from collections.abc import Callable, Sequence
import contextlib
from dataclasses import dataclass
from enum import StrEnum
import logging
from typing import Literal, cast
from uuid import uuid4

from aiohttp import (
    ClientSession,
    ClientTimeout,
    ClientWebSocketResponse,
    ClientWSTimeout,
)
from aiohttp.client_exceptions import (
    ClientConnectorError,
    ClientOSError,
    ServerTimeoutError,
)
from inflection import underscore
from mashumaro.mixins.json import DataClassJSONMixin

WEBSOCKET_TIMEOUT = 5.0

logger = logging.getLogger(__name__)


class IconEnum(StrEnum):
    """Available icons for buttons."""

    ALARM = "alarm"
    ALTERNATIVE = "alternative"
    ARM_AWAY = "arm_away"
    ARM_STAY = "arm_stay"
    AUTO = "auto"
    BATH_TUB = "bath_tub"
    BLINDS = "blinds"
    BLISS = "bliss"
    BUTLER = "butler"
    CINEMA = "cinema"
    CLEAN = "clean"
    CLOCK = "clock"
    COFFEE = "coffee"
    COOL = "cool"
    CREATIVE = "creative"
    CURTAINS = "curtains"
    DINNER = "dinner"
    DISARM = "disarm"
    DOOR = "door"
    DOORLOCK = "doorlock"
    ENERGIZE = "energize"
    ENJOY = "enjoy"
    ENTERTAIN = "entertain"
    FAN = "fan"
    FIREPLACE = "fireplace"
    FORCED_ARM = "forced_arm"
    GAMING = "gaming"
    GARAGE = "garage"
    GATE = "gate"
    GOOD_MORNING = "good_morning"
    GOOD_NIGHT = "good_night"
    HEAT = "heat"
    HUMIDITY = "humidity"
    INDULGE = "indulge"
    LEAVING = "leaving"
    LIGHTS = "lights"
    LOCK = "lock"
    MEETING = "meeting"
    MOVIE = "movie"
    MUSIC = "music"
    NOTIFICATION = "notification"
    OFF = "off"
    PARTY = "party"
    POOL = "pool"
    PRIVACY = "privacy"
    PRODUCTIVE = "productive"
    READING = "reading"
    RELAX = "relax"
    REQUEST_CAR = "request_car"
    RGB_LIGHTS = "rgb_lights"
    ROMANTIC = "romantic"
    ROOF_WINDOW = "roof_window"
    ROOM_SERVICE = "room_service"
    SECURITY = "security"
    SHADES = "shades"
    SHOWER = "shower"
    SLEEP = "sleep"
    SMART_GLASS = "smart_glass"
    SPA = "spa"
    SPRINKLER = "sprinkler"
    TRAVEL = "travel"
    TURNTABLE = "turntable"
    UNLOCK = "unlock"
    VACATION = "vacation"
    WARNING = "warning"
    WATERFALL = "waterfall"
    WELCOME = "welcome"
    WINDOW = "window"
    WORK_OUT = "work_out"
    YOGA = "yoga"


@dataclass
class Icon(DataClassJSONMixin):
    """Icon."""

    icon: IconEnum


@dataclass
class Text(DataClassJSONMixin):
    """Icon."""

    text: str


class ButtonState(StrEnum):
    """State enum For Buttons."""

    ACTIVE = "active"
    INACTIVE = "inactive"


@dataclass
class Button(DataClassJSONMixin):
    """Button."""

    title: str
    subtitle: str
    value: int
    state: ButtonState
    # None is allow during serializing, but not during deserializing
    content: Icon | Text | None
    default: bool = False
    id: str = str(uuid4())


@dataclass
class Page(DataClassJSONMixin):
    """Page containing buttons."""

    title: str
    buttons: Sequence[Button]
    id: str = str(uuid4())


@dataclass
class Configuration(DataClassJSONMixin):
    """Configuration of pages."""

    pages: Sequence[Page]
    version: str = "1.0.1"
    id: str = str(uuid4())


@dataclass
class BaseConfiguration(DataClassJSONMixin):
    """Configuration of pages."""

    configuration: Configuration


class ButtonEventState(StrEnum):
    """State enum for ButtonEvent."""

    PRESSED = "pressed"
    RELEASED = "released"


@dataclass
class ButtonEvent(DataClassJSONMixin):
    """ButtonEvent."""

    type: str
    id: str
    state: ButtonEventState


class PowerEventState(StrEnum):
    """State enum for PowerEvent."""

    CHARGING = "charging"
    FULL = "full"
    LOW = "low"
    CRITICAL = "critical"
    FAULT = "fault"
    DISCHARGING = "discharging"


@dataclass
class PowerEvent(DataClassJSONMixin):
    """PowerEvent."""

    type: str
    capacity: int
    state: PowerEventState


class StatusEventState(StrEnum):
    """State enum for StatusEvent."""

    OK = "ok"
    ERROR = "error"


@dataclass
class StatusEvent(DataClassJSONMixin):
    """StatusEvent."""

    type: str
    state: StatusEventState
    message: str | None = None


class SystemEventState(StrEnum):
    """State enum for SystemEvent."""

    ACTIVE = "active"
    STANDBY = "standby"
    SLEEP = "sleep"


@dataclass
class SystemEvent(DataClassJSONMixin):
    """SystemEvent."""

    type: str
    state: SystemEventState


@dataclass
class WheelEvent(DataClassJSONMixin):
    """WheelEvent."""

    type: str
    id: str
    counts: int


@dataclass
class BaseEvent(DataClassJSONMixin):
    """Base Event class."""

    event: WheelEvent | SystemEvent | StatusEvent | PowerEvent | ButtonEvent


@dataclass
class DisplayPage(DataClassJSONMixin):
    """DisplayPage."""

    pageid: str
    buttonid: str
    type: str = "displaypage"


@dataclass
class Notification(DataClassJSONMixin):
    """Notification."""

    id: str
    title: str
    subtitle: str
    type: str = "notification"


@dataclass
class BaseUpdate(DataClassJSONMixin):
    """Base Update Class."""

    update: Button | DisplayPage | Notification


class Halo:
    """User friendly Mozart REST API and WebSocket client."""

    def __init__(self, host: str) -> None:
        """Initialize Mozart client."""
        self.host = host
        self.websocket_connected = False
        self.websocket_reconnect = False

        self._websocket_listener_active = False
        self._websocket_task: asyncio.Task
        self._websocket: ClientWebSocketResponse
        self._on_connection_lost: Callable | None = None
        self._on_connection: Callable | None = None

        self._on_all_notifications: Callable | None = None
        self._on_all_notifications_raw: Callable | None = None

        self._notification_callbacks: dict[str, Callable | None] = defaultdict()
        self._notification_callbacks.default_factory = lambda: None

    async def _check_websocket_connection(
        self,
    ) -> Literal[True] | ClientConnectorError | ClientOSError | ServerTimeoutError:
        """Check if a connection can be made to the device's WebSocket notification channel."""
        try:
            async with (
                ClientSession(
                    timeout=ClientTimeout(connect=WEBSOCKET_TIMEOUT)
                ) as session,
                session.ws_connect(
                    f"ws://{self.host}:8080/",
                    timeout=ClientWSTimeout(ws_receive=WEBSOCKET_TIMEOUT),
                ) as websocket,
            ):
                if await websocket.receive():
                    return True

        except (ClientConnectorError, ClientOSError, ServerTimeoutError) as error:
            return error

    def check_current_websocket_connection(self) -> bool:
        """Check if there is currently a WebSocket connection open."""
        # try:
        return not self._websocket.closed

        # except (ClientConnectorError, ClientOSError, ServerTimeoutError) as error:
        #     raise error

    async def check_device_connection(self, raise_error: bool = False) -> bool:
        """Check WebSocket connection."""
        # Don't use a taskgroup as both tasks should always be checked
        task: asyncio.Task[
            Literal[True] | ClientConnectorError | ClientOSError | ServerTimeoutError
        ] = asyncio.create_task(self._check_websocket_connection(), name="websocket")

        # Wait for tasks to complete
        while not task.done():
            await asyncio.sleep(0)

        # Check status
        if (result := task.result()) is not True:
            if raise_error:
                raise result
            return False

        return result

    async def connect_notifications(self, reconnect: bool = False) -> None:
        """Start the WebSocket task."""
        self.websocket_reconnect = reconnect

        # Always add main WebSocket listener
        if not self._websocket_listener_active:
            self._websocket_task = asyncio.create_task(
                coro=self._websocket_connection(f"ws://{self.host}:8080/"),
                name=f"{self.host} - task",
            )

            self._websocket_listener_active = True

    async def disconnect_notifications(self) -> None:
        """Stop the WebSocket listener tasks."""
        self._websocket_listener_active = False
        await self._websocket.close()
        self._websocket_task.cancel()

    async def _websocket_connection(self, host: str) -> None:
        """WebSocket listener."""
        while True:
            try:
                async with (
                    ClientSession(
                        timeout=ClientTimeout(connect=WEBSOCKET_TIMEOUT)
                    ) as session,
                    session.ws_connect(
                        url=host, heartbeat=WEBSOCKET_TIMEOUT
                    ) as self._websocket,
                ):
                    self.websocket_connected = True

                    if self._on_connection:
                        await self._trigger_callback(self._on_connection)

                    while True:
                        with contextlib.suppress(asyncio.TimeoutError):
                            notification = await asyncio.wait_for(
                                self._websocket.receive_str(),
                                timeout=WEBSOCKET_TIMEOUT,
                            )

                            await self._on_message(notification)

            except (
                ClientConnectorError,
                ClientOSError,
                TypeError,
                ServerTimeoutError,
            ) as error:
                if self.websocket_connected:
                    logger.debug("%s : %s - %s", host, type(error), error)
                    # print(error)
                    # print(type(error))
                    self.websocket_connected = False

                    if self._on_connection_lost:
                        await self._trigger_callback(self._on_connection_lost)

                if not self.websocket_reconnect:
                    logger.error("%s : %s - %s", host, type(error), error)
                    await self.disconnect_notifications()
                    return

                await asyncio.sleep(WEBSOCKET_TIMEOUT)

    async def send(self, data: BaseConfiguration | BaseUpdate) -> None:
        """Send Configuration or Update."""
        self._websocket_task = asyncio.create_task(
            coro=self._send(data),
            name=f"{self.host} - send task",
        )

    async def _send(self, data: BaseConfiguration | BaseUpdate) -> None:
        """Send Configuration or Update."""
        await self._websocket.send_str(cast(str, data.to_json()))

    async def _on_message(self, notification: str) -> None:
        """Handle WebSocket notifications."""
        # print(notification)
        # print(BaseEvent.from_json(notification))

        # Get the object type and deserialized object.
        try:
            # notification_type = notification["event"]

            deserialized_data = BaseEvent.from_json(notification).event
            # print(deserialized_data)
        except (ValueError, AttributeError) as error:
            logger.error(
                "%s unable to deserialize WebSocket notification: (%s) with error: (%s : %s)",
                self.host,
                notification,
                type(error),
                error,
            )
            return

        # Handle all notifications if defined
        if self._on_all_notifications:
            await self._trigger_callback(
                self._on_all_notifications,
                deserialized_data,
                underscore(deserialized_data.type),
            )

        if self._on_all_notifications_raw:
            await self._trigger_callback(self._on_all_notifications_raw, notification)

        # Handle specific notifications if defined
        triggered_notification = self._notification_callbacks[deserialized_data.type]

        if triggered_notification:
            await self._trigger_callback(triggered_notification, deserialized_data)

    async def _trigger_callback(
        self,
        callback: Callable,
        *args: str | WheelEvent | SystemEvent | StatusEvent | PowerEvent | ButtonEvent,
    ) -> None:
        """Trigger async or sync callback correctly."""
        if asyncio.iscoroutinefunction(callback):
            await callback(*args)
        else:
            callback(*args)

    def get_on_connection_lost(self, on_connection_lost: Callable) -> None:
        """Call back for WebSocket connection lost."""
        self._on_connection_lost = on_connection_lost

    def get_on_connection(self, on_connection: Callable) -> None:
        """Call back for WebSocket connection."""
        self._on_connection = on_connection

    def get_all_notifications(self, on_all_notifications: Callable) -> None:
        """Call back for all notifications."""
        self._on_all_notifications = on_all_notifications

    def get_all_notifications_raw(self, on_all_notifications_raw: Callable) -> None:
        """Call back for all notifications as dict."""
        self._on_all_notifications_raw = on_all_notifications_raw

    def get_wheel_event(self, on_wheel_event: Callable) -> None:
        """Call back for WheelEvent."""
        self._notification_callbacks["wheel"] = on_wheel_event

    def get_system_event(self, on_system_event: Callable) -> None:
        """Call back for SystemEvent."""
        self._notification_callbacks["system"] = on_system_event

    def get_status_event(self, on_status_event: Callable) -> None:
        """Call back for StatusEvent."""
        self._notification_callbacks["status"] = on_status_event

    def get_power_event(self, on_power_event: Callable) -> None:
        """Call back for PowerEvent."""
        self._notification_callbacks["power"] = on_power_event

    def get_button_event(self, on_button_event: Callable) -> None:
        """Call back for ButtonEvent."""
        self._notification_callbacks["button"] = on_button_event


# async def main():
#     halo = Halo("192.168.0.128")
#     print(await halo.check_device_connection())
#     await halo.connect_notifications(reconnect=True)
#     await asyncio.sleep(2)
#     # print(halo._check_current_websocket_connection())
#     # await halo._websocket.send_str(configuration.to_json())
#     jsonstr = BaseConfiguration(
#         Configuration(
#             [
#                 Page(
#                     "Kitchen",
#                     [
#                         Button(
#                             "Kitchen Light",
#                             "On",
#                             95,
#                             ButtonState.ACTIVE,
#                             Icon(IconEnum.LIGHTS),
#                         )
#                     ],
#                 ),
#                 Page(
#                     "Living room",
#                     [
#                         Button(
#                             "living room Light",
#                             "On",
#                             95,
#                             ButtonState.ACTIVE,
#                             Text("Test"),
#                         )
#                     ],
#                 ),
#                 Page(
#                     "Living room",
#                     [
#                         Button(
#                             "living room Light",
#                             "Off",
#                             95,
#                             ButtonState.ACTIVE,
#                             Text("Test"),
#                         )
#                     ],
#                 ),
#             ],
#             "1.0.1",
#         )
#     )
#     # print(jsonstr)
#     await halo.send(jsonstr)
#     # await halo._websocket.send_str(jsonstr)

#     while True:
#         await asyncio.sleep(0)


# if __name__ == "__main__":
#     asyncio.run(main())
