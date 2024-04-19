"""Test the Bang & Olufsen media_player entity."""

from homeassistant.components.bang_olufsen.const import FALLBACK_SOURCES
from homeassistant.components.bang_olufsen.media_player import BangOlufsenMediaPlayer
from homeassistant.core import HomeAssistant

# pytestmark = pytest.mark.usefixtures("mock_setup_entry")


# async def test_initialization(
#     hass: HomeAssistant, mock_mozart_client, mock_config_entry
# ) -> None:
#     """Test the integration is initialized properly in _initialize, async_added_to_hass and __init__."""
#     mock_config_entry.add_to_hass(hass)
#     await hass.config_entries.async_setup(mock_config_entry.entry_id)
#     await hass.async_block_till_done()

#     media_player = BangOlufsenMediaPlayer(mock_config_entry, mock_mozart_client)


async def test_update_sources(
    hass: HomeAssistant, mock_mozart_client, mock_config_entry
) -> None:
    """Test sources are correctly handled in _update_sources."""
    media_player = BangOlufsenMediaPlayer(mock_config_entry, mock_mozart_client)

    assert not media_player._sources
    assert not media_player._audio_sources
    assert not media_player._video_sources

    await media_player._update_sources()

    assert len(media_player._video_sources) == 1
    assert len(media_player._audio_sources) == 1
    assert len(media_player._sources) == (1 + 1)


async def test_update_sources_audio_only(
    hass: HomeAssistant, mock_mozart_client, mock_config_entry
) -> None:
    """Test sources are correctly handled in _update_sources."""
    mock_mozart_client.get_remote_menu.return_value = {}

    media_player = BangOlufsenMediaPlayer(mock_config_entry, mock_mozart_client)

    assert not media_player._sources
    assert not media_player._audio_sources
    assert not media_player._video_sources

    await media_player._update_sources()

    assert not media_player._video_sources
    assert len(media_player._audio_sources) == 1
    assert len(media_player._sources) == (0 + 1)


async def test_update_sources_outdated_api(
    hass: HomeAssistant, mock_mozart_client, mock_config_entry
) -> None:
    """Test fallback sources are correctly handled in _update_sources."""
    mock_mozart_client.get_available_sources.side_effect = ValueError()

    media_player = BangOlufsenMediaPlayer(mock_config_entry, mock_mozart_client)

    assert not media_player._sources
    assert not media_player._audio_sources
    assert not media_player._video_sources

    await media_player._update_sources()

    assert not media_player._video_sources
    assert len(media_player._audio_sources) == len(FALLBACK_SOURCES)
    assert len(media_player._sources) == len(FALLBACK_SOURCES)
