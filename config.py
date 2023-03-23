"""Configuration module."""

import os
from configparser import ConfigParser

config = ConfigParser()

config.read(os.path.join(os.path.dirname(__file__), 'sten.conf'))

config_default = {
    (section_preferences := 'PREFERENCES'): {
        (option_confirm_exit := 'ConfirmExit'): '1',
        (option_mask_key := 'MaskKey'): '*',
        (option_mode_zoomed := 'ModeZoomed'): '0',
    },
}

for section, option_default in config_default.items():
    if not config.has_section(section):
        config[section] = option_default
    else:
        for option, default in option_default.items():
            if not config.has_option(section, option):
                config[section][option] = default

CONFIRM_EXIT = config[section_preferences][option_confirm_exit] == '1'
MASK_KEY = config[section_preferences][option_mask_key]
MODE_ZOOMED = config[section_preferences][option_mode_zoomed] == '1'
