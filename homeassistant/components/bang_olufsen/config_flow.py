"""Config flow for the Bang & Olufsen integration."""

from __future__ import annotations

from ipaddress import AddressValueError, IPv4Address
from typing import Any, TypedDict

from aiohttp.client_exceptions import ClientConnectorError
from mozart_api.exceptions import ApiException
from mozart_api.mozart_client import MozartClient
import voluptuous as vol

from homeassistant.components.zeroconf import ZeroconfServiceInfo
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import (
    ATTR_NAME,
    CONF_ENTITIES,
    CONF_HOST,
    CONF_ICON,
    CONF_MODEL,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    SelectSelector,
    SelectSelectorConfig,
)
from homeassistant.util.ssl import get_default_context

from .const import (
    ATTR_FRIENDLY_NAME,
    ATTR_HALO_SERIAL_NUMBER,
    ATTR_ITEM_NUMBER,
    ATTR_MOZART_SERIAL_NUMBER,
    ATTR_TYPE_NUMBER,
    COMPATIBLE_MODELS,
    CONF_HALO,
    CONF_PAGE_NAME,
    CONF_SERIAL_NUMBER,
    CONF_SUBTITLE,
    CONF_TEXT,
    CONF_TITLE,
    DEFAULT_HALO_CONFIGURATION,
    DEFAULT_MODEL,
    DOMAIN,
    HALO_BUTTON_ICONS,
    HALO_TEXT_LENGTH,
    HALO_TITLE_LENGTH,
    ZEROCONF_HALO,
    ZEROCONF_MOZART,
    BangOlufsenModel,
)
from .halo import BaseConfiguration, Button, ButtonState, Halo, Icon, Page, Text
from .util import get_serial_number_from_jid


class BangOlufsenEntryData(TypedDict, total=False):
    """TypedDict for config_entry data."""

    host: str
    jid: str
    model: str
    name: str
    # Does not seem to handle objects well through restarts
    # halo: BaseConfiguration
    halo: dict


# Map exception types to strings
_exception_map = {
    ApiException: "api_exception",
    ClientConnectorError: "client_connector_error",
    TimeoutError: "timeout_error",
    AddressValueError: "invalid_ip",
}


class BangOlufsenConfigFlowHandler(ConfigFlow, domain=DOMAIN):
    """Handle a config flow."""

    _beolink_jid = ""
    _mozart_client: MozartClient
    _halo_client: Halo
    _host = ""
    _model = ""
    _name = ""
    _serial_number = ""

    def __init__(self) -> None:
        """Init the config flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        data_schema = vol.Schema(
            {
                vol.Required(CONF_HOST): str,
                vol.Required(CONF_MODEL, default=DEFAULT_MODEL): SelectSelector(
                    SelectSelectorConfig(options=COMPATIBLE_MODELS)
                ),
            }
        )

        if user_input is not None:
            self._host = user_input[CONF_HOST]
            self._model = user_input[CONF_MODEL]

            try:
                IPv4Address(self._host)
            except AddressValueError as error:
                return self.async_show_form(
                    step_id="user",
                    data_schema=data_schema,
                    errors={"base": _exception_map[type(error)]},
                )

            self._mozart_client = MozartClient(
                self._host, ssl_context=get_default_context()
            )

            # Try to get information from Beolink self method.
            async with self._mozart_client:
                try:
                    beolink_self = await self._mozart_client.get_beolink_self(
                        _request_timeout=3
                    )
                except (
                    ApiException,
                    ClientConnectorError,
                    TimeoutError,
                ) as error:
                    return self.async_show_form(
                        step_id="user",
                        data_schema=data_schema,
                        errors={"base": _exception_map[type(error)]},
                    )

            self._beolink_jid = beolink_self.jid
            self._serial_number = get_serial_number_from_jid(beolink_self.jid)

            await self.async_set_unique_id(self._serial_number)
            self._abort_if_unique_id_configured()

            return await self._create_entry()

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
        )

    async def async_step_zeroconf(
        self, discovery_info: ZeroconfServiceInfo
    ) -> ConfigFlowResult:
        """Handle discovery using Zeroconf."""

        # Ensure that an IPv4 address is received
        self._host = discovery_info.host

        try:
            IPv4Address(self._host)
        except AddressValueError:
            return self.async_abort(reason="ipv6_address")

        # Default to Mozart products
        name_key = ATTR_FRIENDLY_NAME

        # Handle Mozart based products
        if discovery_info.type == ZEROCONF_MOZART:
            await self._zeroconf_mozart(discovery_info)

        # Handle Beoremote Halo
        elif discovery_info.type == ZEROCONF_HALO:
            self._zeroconf_halo(discovery_info)
            name_key = ATTR_NAME

        await self.async_set_unique_id(self._serial_number)
        self._abort_if_unique_id_configured(updates={CONF_HOST: self._host})

        # Set the discovered device title
        self.context["title_placeholders"] = {
            "name": discovery_info.properties[name_key]
        }

        return await self.async_step_zeroconf_confirm()

    def _zeroconf_halo(
        self, discovery_info: ZeroconfServiceInfo
    ) -> ConfigFlowResult | None:
        """Handle Zeroconf discovery of Halo."""
        self._serial_number = discovery_info.properties[ATTR_HALO_SERIAL_NUMBER]
        self._model = BangOlufsenModel.BEOREMOTE_HALO
        return None

    async def _zeroconf_mozart(
        self, discovery_info: ZeroconfServiceInfo
    ) -> ConfigFlowResult | None:
        """Handle Zeroconf discovery of Mozart products."""
        # Check if the discovered device is a Mozart device
        if ATTR_FRIENDLY_NAME not in discovery_info.properties:
            return self.async_abort(reason="not_mozart_device")

        # Check connection to ensure valid address is received
        self._mozart_client = MozartClient(
            self._host, ssl_context=get_default_context()
        )

        async with self._mozart_client:
            try:
                await self._mozart_client.get_beolink_self(_request_timeout=3)
            except (ClientConnectorError, TimeoutError):
                return self.async_abort(reason="invalid_address")

        self._model = discovery_info.hostname[:-16].replace("-", " ")
        self._serial_number = discovery_info.properties[ATTR_MOZART_SERIAL_NUMBER]
        self._beolink_jid = f"{discovery_info.properties[ATTR_TYPE_NUMBER]}.{discovery_info.properties[ATTR_ITEM_NUMBER]}.{self._serial_number}@products.bang-olufsen.com"

        return None

    async def _create_entry(self) -> ConfigFlowResult:
        """Create the config entry for a discovered or manually configured Bang & Olufsen device."""
        # Ensure that created entities have a unique and easily identifiable id and not a "friendly name"
        self._name = f"{self._model}-{self._serial_number}"

        return self.async_create_entry(
            title=self._name,
            data=BangOlufsenEntryData(
                host=self._host,
                jid=self._beolink_jid,
                model=self._model,
                name=self._name,
                halo=DEFAULT_HALO_CONFIGURATION,
            ),
        )

    async def async_step_zeroconf_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm the configuration of the device."""
        if user_input is not None:
            return await self._create_entry()

        self._set_confirm_only()

        return self.async_show_form(
            step_id="zeroconf_confirm",
            description_placeholders={
                CONF_HOST: self._host,
                CONF_MODEL: self._model,
                CONF_SERIAL_NUMBER: self._serial_number,
            },
            last_step=True,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> OptionsFlow:
        """Create the options flow."""
        # This option should only be available for the Halo,
        # but this is currently not supported by Home Assistant.
        return HaloOptionsFlowHandler()


class HaloOptionsFlowHandler(OptionsFlow):
    """HaloOptionsFlowHandler."""

    def __init__(self) -> None:
        """Initialize options."""
        self._entities: list[str] = []
        self._configuration: BaseConfiguration
        self._page: Page

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if self.config_entry.data[CONF_MODEL] == BangOlufsenModel.BEOREMOTE_HALO:
            self._configuration = BaseConfiguration.from_dict(
                self.config_entry.data[CONF_HALO]
            )

            return self.async_show_menu(
                step_id="init",
                menu_options=["add_page", "delete_page", "modify_page"],
            )
        return self.async_abort(
            reason="invalid_model",
            description_placeholders={"model": self.config_entry.data[CONF_MODEL]},
        )

    async def async_step_add_page(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add new page."""

        if user_input is not None:
            self._page = Page(user_input[CONF_PAGE_NAME], [])
            self._entities = user_input[CONF_ENTITIES]

            return await self.async_step_create_buttons()

        # TO DO filter unsupported entities
        options_schema = vol.Schema(
            {
                vol.Required(CONF_PAGE_NAME): str,
                vol.Required(CONF_ENTITIES): EntitySelector(
                    EntitySelectorConfig(multiple=True)
                ),
            }
        )

        return self.async_show_form(
            step_id="add_page",
            data_schema=options_schema,
        )

    async def async_step_create_buttons(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add new page."""
        if user_input is not None:
            content = (
                Icon(user_input[CONF_ICON])
                if CONF_ICON in user_input
                else Text(user_input[CONF_TEXT])
            )
            self._page.buttons.append(
                Button(
                    title=user_input[CONF_TITLE],
                    subtitle=user_input[CONF_SUBTITLE],
                    value=0,
                    state=ButtonState.INACTIVE,
                    content=content,
                    id=self._entities[-1],
                )
            )

            self._entities.pop()

            if not self._entities:
                self._configuration.configuration.pages.append(self._page)
                return self.async_create_entry(
                    title=f"Page {self._page.title} added to configuration",
                    data=BangOlufsenEntryData(
                        host=self.config_entry.data[CONF_HOST],
                        model=self.config_entry.data[CONF_MODEL],
                        name=self.config_entry.title,
                        halo=self._configuration.to_dict(),
                    ),
                )

        options_schema = vol.Schema(
            {
                vol.Required(CONF_TITLE): vol.All(
                    str,
                    vol.Length(max=HALO_TITLE_LENGTH),
                ),
                vol.Required(CONF_SUBTITLE): vol.All(
                    str,
                    vol.Length(max=HALO_TITLE_LENGTH),
                ),
                vol.Exclusive(CONF_ICON, "content", "Error"): SelectSelector(
                    SelectSelectorConfig(options=HALO_BUTTON_ICONS)
                ),
                vol.Exclusive(CONF_TEXT, "content", "Error"): vol.All(
                    str,
                    vol.Length(max=HALO_TEXT_LENGTH),
                ),
            },
        )

        return self.async_show_form(
            step_id="create_buttons",
            data_schema=options_schema,
            description_placeholders={"entity": self._entities[-1]},
        )
