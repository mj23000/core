"""Constants for the Beoremote Halo client."""

from typing import Final

VERSION: Final = "1.0.2"

WEBSOCKET_TIMEOUT: Final = 5.0

MIN_VALUE: Final = 0
MAX_VALUE: Final = 100

# This is a deviation from the API spec, which specifies 1 as the minimum amount of pages and buttons
# This change makes setup of a new configuration easier
# For validation outside of initial object creation, use the VALIDATION constants
MIN_PAGES: Final = 0
MIN_PAGES_VALIDATION: Final = 1
MAX_PAGES: Final = 3

MIN_BUTTONS: Final = 0
MIN_BUTTONS_VALIDATION: Final = 1
MAX_BUTTONS: Final = 8

TEXT_MAX_LENGTH: Final = 6
TITLE_MAX_LENGTH: Final = 15
SUBTITLE_MAX_LENGTH: Final = 15

WHEEL_COUNTS_MIN: Final = -5
WHEEL_COUNTS_MAX: Final = 5

HALO_PAGE_LENGTH: Final = 35
