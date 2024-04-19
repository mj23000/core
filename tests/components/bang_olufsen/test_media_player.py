"""Test the Bang & Olufsen media_player entity."""

from homeassistant.core import HomeAssistant

# pytestmark = pytest.mark.usefixtures("mock_setup_entry")


def test_initialize(hass: HomeAssistant, mock_mozart_client) -> None:
    """Test the integration is initialized properly in _initialize."""


def test_update_sources(hass: HomeAssistant, mock_mozart_client) -> None:
    """Test sources are correctly handled in _update_sources."""
