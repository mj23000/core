"""Test the Bang & Olufsen media_player entity."""

from unittest.mock import patch

from homeassistant.components.bang_olufsen.const import WebsocketNotification
from homeassistant.components.media_player.const import (
    ATTR_INPUT_SOURCE,
    ATTR_INPUT_SOURCE_LIST,
    ATTR_MEDIA_ALBUM_ARTIST,
    ATTR_MEDIA_ALBUM_NAME,
    ATTR_MEDIA_CHANNEL,
    ATTR_MEDIA_DURATION,
    ATTR_MEDIA_POSITION,
    ATTR_MEDIA_TITLE,
    ATTR_MEDIA_TRACK,
    MediaPlayerState,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import (
    TEST_AUDIO_SOURCES,
    TEST_FALLBACK_SOURCES,
    TEST_MEDIA_PLAYER_ENTITY_ID,
    TEST_PLAYBACK_ERROR,
    TEST_PLAYBACK_METADATA,
    TEST_PLAYBACK_PROGRESS,
    TEST_PLAYBACK_STATE,
    TEST_SERIAL_NUMBER,
    TEST_SOURCE_CHANGE,
    TEST_SOURCE_CHANGE_SPDIF,
    TEST_SOURCES,
    TEST_VIDEO_SOURCES,
)


async def test_initialization(
    hass: HomeAssistant, mock_config_entry, mock_mozart_client
) -> None:
    """Test the integration is initialized properly in _initialize, async_added_to_hass and __init__."""

    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)

    # Get state
    states = hass.states.get(TEST_MEDIA_PLAYER_ENTITY_ID)
    assert states

    # Check sources
    assert states.attributes[ATTR_INPUT_SOURCE_LIST] == TEST_SOURCES


async def test_update_sources_audio_only(
    hass: HomeAssistant, mock_config_entry, mock_mozart_client
) -> None:
    """Test sources are correctly handled in _update_sources."""
    mock_mozart_client.get_remote_menu.return_value = {}

    # Setup entity
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)

    # Get state
    states = hass.states.get(TEST_MEDIA_PLAYER_ENTITY_ID)
    assert states

    # Check sources
    assert states.attributes[ATTR_INPUT_SOURCE_LIST] == TEST_AUDIO_SOURCES


async def test_update_sources_outdated_api(
    hass: HomeAssistant, mock_mozart_client, mock_config_entry
) -> None:
    """Test fallback sources are correctly handled in _update_sources."""
    mock_mozart_client.get_available_sources.side_effect = ValueError()

    # Setup entity
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)

    # Get state
    states = hass.states.get(TEST_MEDIA_PLAYER_ENTITY_ID)
    assert states

    # Check sources
    assert (
        states.attributes[ATTR_INPUT_SOURCE_LIST]
        == TEST_FALLBACK_SOURCES + TEST_VIDEO_SOURCES
    )


async def test_update_playback_metadata(
    hass: HomeAssistant, mock_mozart_client, mock_config_entry
) -> None:
    """Test _update_playback_metadata."""

    # Setup entity
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)

    # Check states
    states = hass.states.get(TEST_MEDIA_PLAYER_ENTITY_ID)
    assert states

    assert ATTR_MEDIA_DURATION not in states.attributes
    assert ATTR_MEDIA_TITLE not in states.attributes
    assert ATTR_MEDIA_ALBUM_NAME not in states.attributes
    assert ATTR_MEDIA_ALBUM_ARTIST not in states.attributes
    assert ATTR_MEDIA_TRACK not in states.attributes
    assert ATTR_MEDIA_CHANNEL not in states.attributes

    # Send the dispatch
    async_dispatcher_send(
        hass,
        f"{TEST_SERIAL_NUMBER}_{WebsocketNotification.PLAYBACK_METADATA}",
        TEST_PLAYBACK_METADATA,
    )
    # Check new states
    states = hass.states.get(TEST_MEDIA_PLAYER_ENTITY_ID)
    assert states

    assert (
        states.attributes[ATTR_MEDIA_DURATION]
        == TEST_PLAYBACK_METADATA.total_duration_seconds
    )
    assert states.attributes[ATTR_MEDIA_TITLE] == TEST_PLAYBACK_METADATA.title
    assert states.attributes[ATTR_MEDIA_ALBUM_NAME] == TEST_PLAYBACK_METADATA.album_name
    assert (
        states.attributes[ATTR_MEDIA_ALBUM_ARTIST] == TEST_PLAYBACK_METADATA.artist_name
    )
    assert states.attributes[ATTR_MEDIA_TRACK] == TEST_PLAYBACK_METADATA.track
    assert states.attributes[ATTR_MEDIA_CHANNEL] == TEST_PLAYBACK_METADATA.organization

    await hass.async_block_till_done()


async def test_update_playback_error(
    hass: HomeAssistant, mock_mozart_client, mock_config_entry
) -> None:
    """Test _update_playback_error."""

    # Setup entity
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)

    # Send the dispatch
    with patch(
        "homeassistant.components.bang_olufsen.media_player._LOGGER.error"
    ) as mock_logger:
        async_dispatcher_send(
            hass,
            f"{TEST_SERIAL_NUMBER}_{WebsocketNotification.PLAYBACK_ERROR}",
            TEST_PLAYBACK_ERROR,
        )
        # Ensure that the logger has been called with the error message
        mock_logger.assert_called_once_with(TEST_PLAYBACK_ERROR.error)

    await hass.async_block_till_done()


async def test_update_playback_progress(
    hass: HomeAssistant, mock_mozart_client, mock_config_entry
) -> None:
    """Test _update_playback_progress."""

    # Setup entity
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)

    # Check states
    states = hass.states.get(TEST_MEDIA_PLAYER_ENTITY_ID)
    assert states

    assert ATTR_MEDIA_POSITION not in states.attributes

    # Send the dispatch
    async_dispatcher_send(
        hass,
        f"{TEST_SERIAL_NUMBER}_{WebsocketNotification.PLAYBACK_PROGRESS}",
        TEST_PLAYBACK_PROGRESS,
    )
    # Check new states
    states = hass.states.get(TEST_MEDIA_PLAYER_ENTITY_ID)
    assert states

    assert states.attributes[ATTR_MEDIA_POSITION] == TEST_PLAYBACK_PROGRESS.progress


async def test_update_playback_state(
    hass: HomeAssistant, mock_mozart_client, mock_config_entry
) -> None:
    """Test _update_playback_state."""

    # Setup entity
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)

    # Check states
    states = hass.states.get(TEST_MEDIA_PLAYER_ENTITY_ID)
    assert states

    assert states.state == MediaPlayerState.PLAYING

    # Send the dispatch
    async_dispatcher_send(
        hass,
        f"{TEST_SERIAL_NUMBER}_{WebsocketNotification.PLAYBACK_STATE}",
        TEST_PLAYBACK_STATE,
    )

    # Check new states
    states = hass.states.get(TEST_MEDIA_PLAYER_ENTITY_ID)
    assert states

    assert states.state == TEST_PLAYBACK_STATE.value


async def test_update_source_change(
    hass: HomeAssistant, mock_mozart_client, mock_config_entry
) -> None:
    """Test _update_source_change."""

    # Setup entity
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)

    # Check states
    states = hass.states.get(TEST_MEDIA_PLAYER_ENTITY_ID)
    assert states

    assert ATTR_INPUT_SOURCE not in states.attributes

    # Send the dispatch
    async_dispatcher_send(
        hass,
        f"{TEST_SERIAL_NUMBER}_{WebsocketNotification.SOURCE_CHANGE}",
        TEST_SOURCE_CHANGE,
    )

    # Check new states
    states = hass.states.get(TEST_MEDIA_PLAYER_ENTITY_ID)
    assert states

    assert states.attributes[ATTR_INPUT_SOURCE] == TEST_SOURCE_CHANGE.name


async def test_update_source_change_spdif(
    hass: HomeAssistant, mock_mozart_client, mock_config_entry
) -> None:
    """Test _update_source_change with spdif as source."""

    # Setup entity
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)

    # Check states
    states = hass.states.get(TEST_MEDIA_PLAYER_ENTITY_ID)
    assert states

    assert ATTR_INPUT_SOURCE not in states.attributes
    assert ATTR_MEDIA_POSITION not in states.attributes

    # Send the dispatch
    async_dispatcher_send(
        hass,
        f"{TEST_SERIAL_NUMBER}_{WebsocketNotification.SOURCE_CHANGE}",
        TEST_SOURCE_CHANGE_SPDIF,
    )

    # Check new states
    states = hass.states.get(TEST_MEDIA_PLAYER_ENTITY_ID)
    assert states

    assert states.attributes[ATTR_INPUT_SOURCE] == TEST_SOURCE_CHANGE_SPDIF.name
    assert states.attributes[ATTR_MEDIA_POSITION] == 0
