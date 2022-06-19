"""Module to maintain AVR state information and network interface."""
import asyncio
import logging

__all__ = ["AVR"]

# In Python 3.4.4, `async` was renamed to `ensure_future`.
try:
    ensure_future = asyncio.ensure_future
except AttributeError:
    ensure_future = getattr(asyncio, "async")

CMD_SET_POWER_STATE = "1,01"
POWER_STATE_ON = "1"
POWER_STATE_OFF = "0"
MUTE_STATE_OFF = "00"
MUTE_STATE_ON = "01"
DYNAMIC_RANGE_AUTO = "00"
DYNAMIC_RANGE_OFF = "01"
DYNAMIC_RANGE_ON = "02"

CMD_VOLUME_UP = "1,02"
CMD_VOLUME_DOWN = "1,03"
CMD_BASS_UP = "1,04"
CMD_BASS_DOWN = "1,05"
CMD_TREBLE_UP = "1,06"
CMD_TREBLE_DOWN = "1,07"
CMD_SET_LFE_TRIM = "1,10"
CMD_SET_MUTE_STATE = "1,11"
CMD_SET_DYNAMIC_RANGE = "1,12"
CMD_LIP_SYNC_UP = "1,20"
CMD_LIP_SYNC_DOWN = "1,21"
CMD_SELECT_INPUT = "2,01"
CMD_SET_AUDIO_SOURCE = "2,04"
CMD_SW_VERSION = "5,01"
CMD_PROTOCOL_VERSION = "5,02"

ATTR_POWER_STATE = "#6,01"
ATTR_MUTE_STATE = "#6,11"
ATTR_VOLUME_UP = "#6,02"
ATTR_VOLUME_DOWN = "#6,03"
ATTR_SELECTED_INPUT = "#7,01"
ATTR_AUDIO_SOURCE = "#7,04"
ATTR_MYSTERY = "#7,05"
ATTR_SW_VERSION = "#10,01"
ATTR_PROTOCOL_VERSION = "#10,02"

INPUT_NAMES = {
    1: "BD/DVD",
    2: "Video 1",
    3: "Video 2",
    4: "CD/AUX",
    5: "Tape/MD/CDR",
    6: "Tuner",
    7: "Video 3",
    8: "Direct In",
    9: "TV ARC",
}
INPUT_NUMBERS = {v: k for k, v in INPUT_NAMES.items()}

LOOKUP = {
    ATTR_POWER_STATE: {
        "name": "power_state",
        "description": "Power State",
        "0": "Off",
        "1": "On",
    },
    ATTR_MUTE_STATE: {
        "name": "mute_state",
        "description": "Mute State",
        "00": "Off",
        "01": "On",
    },
    ATTR_VOLUME_UP: {"name": "volume", "description": "Volume (Up)"},
    ATTR_VOLUME_DOWN: {"name": "volume", "description": "Volume (Down)"},
    ATTR_SELECTED_INPUT: {
        "name": "selected_input",
        "description": "Selected Input",
        "01": "BD/DVD",
        "02": "Video 1",
        "03": "Video 2",
        "04": "CD/AUX",
        "05": "Tape/MD/CDR",
        "O6": "Tuner",
        "O7": "Video 3",
        "08": "Direct In",
        "09": "TV ARC",
    },
    ATTR_AUDIO_SOURCE: {
        "name": "audio_source",
        "description": "Audio Source",
        "00": "Analog",
        "01": "Digital",
        "02": "HDMI",
    },
    ATTR_MYSTERY: {
        "name": "mystery",
        "description": "N/A",
    },
    ATTR_SW_VERSION: {
        "name": "software_version",
        "description": "Main Software Version",
    },
    ATTR_PROTOCOL_VERSION: {
        "name": "protocol_version",
        "description": "Protocol Version",
    },
}


#
# Volume and Attenuation handlers. The AVR tracks volume internally as
# an attenuation level ranging from -90dB (silent) to 0dB (bleeding ears)
#
# We expose this in three methods for the convenience of downstream apps
# which will almost certainly be doing things their own way:
#
#   - attenuation (-90 to 0)
#   - volume (0-100)
#   - volume_as_percentage (0-1 floating point)
#


def attenuation_to_volume(value):
    """Convert a native attenuation value to a volume value.

    Takes an attenuation in dB from the AVR (-90 to 0) and converts it
    into a normal volume value (0-100).

        :param value: attenuation in dB (negative integer from -90 to 0)
        :type value: int

    returns an integer value representing volume
    """
    try:
        return round((90.00 + int(value)) / 90 * 100)
    except ValueError:
        return 0


def volume_to_attenuation(value):
    """Convert a volume value to a native attenuation value.

    Takes a volume value and turns it into an attenuation value suitable
    to send to the AVR.

        :param value: volume (integer from 0 to 100)
        :type value: int

    returns a negative integer value representing attenuation in dB
    """
    try:
        return round((value / 100) * 90) - 90
    except ValueError:
        return -90


# pylint: disable=too-many-instance-attributes, too-many-public-methods
class AVR(asyncio.Protocol):
    """The Cambridge Audio Azur 551R AVR control protocol handler."""

    def __init__(self, update_callback=None, loop=None, connection_lost_callback=None):
        """Protocol handler that handles all status and changes on AVR.

        This class is expected to be wrapped inside a Connection class object
        which will maintain the socket and handle auto-reconnects.

            :param update_callback:
                called if any state information changes in device (optional)
            :param connection_lost_callback:
                called when connection is lost to device (optional)
            :param loop:
                asyncio event loop (optional)

            :type update_callback:
                callable
            :type: connection_lost_callback:
                callable
            :type loop:
                asyncio.loop
        """
        self._loop = loop
        self.log = logging.getLogger(__name__)
        self._connection_lost_callback = connection_lost_callback
        self._update_callback = update_callback
        self.buffer = ""
        self._input_names = {}
        self._input_numbers = {}
        self._poweron_refresh_successful = False
        self._volume_update_state = 0  # 0 = Idle, 1 = Requested, 2 = Completed
        self._volume_update_success = False
        self._volume_target = None
        self.transport = None

        for key in LOOKUP:
            setattr(self, f"_{LOOKUP[key]['name']}", "")

    def _refresh_volume(self, tries=0):
        # IDLE
        if self._volume_update_state == 0:
            self.log.debug("Start Refresh Volume")
            self._volume_update_state = 1

        # REQUESTED
        if self._volume_update_state == 1:
            if tries < 10:
                self.log.debug("Refresh Volume Try %s", tries + 1)
                self.send_command(CMD_VOLUME_DOWN)
                self._loop.call_later(2, self._refresh_volume, tries + 1)
            else:
                self.log.warning("Refresh Volume timed out!")

        # COMPLETED
        if self._volume_update_state == 2:
            self.log.debug("Refresh Volume successful.")
            self._volume_update_state = 0

    def _poweron_callback(self):
        self.log.debug("AVR Powered on")
        self._refresh_volume()

        self._poweron_refresh_successful = True

    def _get_attribute_value(self, attr):
        attr_name = f"_{LOOKUP[attr]['name']}"
        if attr_name:
            return getattr(self, attr_name)
        else:
            self.log.error("No attribute name defined for %s", attr)

    def _set_attribute_value(self, attr, value):
        attr_name = f"_{LOOKUP[attr]['name']}"
        if attr_name:
            return setattr(self, attr_name, value)
        else:
            self.log.error("No attribute name defined for %s", attr)

    def _get_integer(self, attr):
        try:
            value = self._get_attribute_value(attr)
            return int(value)
        except ValueError:
            return 0

    def _get_boolean(self, attr):
        try:
            value = self._get_attribute_value(attr)
            return bool(int(value))
        except ValueError:
            return False

    def _get_multiprop(self, attr, mode="raw"):
        value = self._get_attribute_value(attr)

        if mode == "raw":
            return value

        if attr in LOOKUP and value in LOOKUP[attr]:
            return LOOKUP[attr][value]

        return value

    #
    # asyncio network functions
    #

    def connection_made(self, transport):
        """Called when asyncio.Protocol establishes the network connection."""
        self.log.debug("Connection established to AVR")
        self.transport = transport

        # self.transport.set_write_buffer_limits(0)
        limit_low, limit_high = self.transport.get_write_buffer_limits()
        self.log.debug("Write buffer limits %d to %d", limit_low, limit_high)

    def data_received(self, data):
        """Called when asyncio.Protocol detects received data from network."""
        self.buffer += data.decode()
        self.log.debug("Received %d bytes from AVR: %s", len(self.buffer), self.buffer)
        self._assemble_buffer()

    def connection_lost(self, exc):
        """Called when asyncio.Protocol loses the network connection."""
        self.log.warning("Lost connection to receiver")

        if exc is not None:
            self.log.debug(exc)

        self.transport = None

        if self._connection_lost_callback:
            self._loop.call_soon(self._connection_lost_callback)

    def _assemble_buffer(self):
        """Split up received data from device into individual commands.

        Data sent by the device is a sequence of datagrams separated by
        semicolons.  It's common to receive a burst of them all in one
        submission when there's a lot of device activity.  This function
        disassembles the chain of datagrams into individual messages which
        are then passed on for interpretation.
        """
        self.transport.pause_reading()

        for message in self.buffer.split("\r"):
            if message != "":
                self.log.debug("assembled message %s", message)
                self._parse_message(message)

        self.buffer = ""

        self.transport.resume_reading()
        return

    def _parse_message(self, data):
        """Interpret each message datagram from device and do the needful.

        This function receives datagrams from _assemble_buffer and inerprets
        what they mean.  It's responsible for maintaining the internal state
        table for each device attribute and also for firing the update_callback
        function (if one was supplied)
        """
        recognized = False
        newdata = False

        if data.startswith("#11,01"):
            self.log.warning("Command Group Unknown")
            recognized = True
        elif data.startswith("#11,02"):
            self.log.warning("Command Number in Group Unknown")
            recognized = True
        elif data.startswith("#11,03"):
            self.log.warning("Command Data Error")
            recognized = True
        else:
            for key in LOOKUP:
                if data.startswith(key):
                    recognized = True

                    value = data[len(key) + 1 :]
                    oldvalue = self._get_attribute_value(key)
                    if oldvalue != value:
                        changeindicator = "New Value"
                        newdata = True
                    else:
                        changeindicator = "Unchanged"

                    if key in LOOKUP:
                        if "description" in LOOKUP[key]:
                            if value in LOOKUP[key]:
                                self.log.debug(
                                    "%s: %s (%s) -> %s (%s)",
                                    changeindicator,
                                    LOOKUP[key]["description"],
                                    key,
                                    LOOKUP[key][value],
                                    value,
                                )
                            else:
                                self.log.debug(
                                    "%s: %s (%s) -> %s",
                                    changeindicator,
                                    LOOKUP[key]["description"],
                                    key,
                                    value,
                                )
                    else:
                        self.log.debug("%s: %s -> %s", changeindicator, key, value)

                    self._set_attribute_value(key, value)
                    break

            # Poweron update
            if self.power and not self._poweron_refresh_successful:
                self._loop.call_soon(self._poweron_callback)

            # Volume update
            if data.startswith(ATTR_VOLUME_UP) or data.startswith(ATTR_VOLUME_DOWN):
                volume = self._get_integer(ATTR_VOLUME_UP)
                if self._volume_target:
                    if volume != self._volume_target:
                        self.send_command(
                            CMD_VOLUME_UP
                            if self._volume_target > volume
                            else CMD_VOLUME_DOWN
                        )
                    else:
                        self._volume_target = None

                if self._volume_update_state == 1:
                    self.send_command(CMD_VOLUME_UP)
                    self._volume_update_state = 2

                newdata = True
                recognized = True

        if newdata:
            if self._update_callback:
                self._loop.call_soon(self._update_callback, data)
        else:
            self.log.debug("No new data encountered")

        if not recognized:
            self.log.debug("Unrecognized response: %s", data)

    def send_command(self, command, data=""):
        command = f"#{command},{data}\r"
        command = command.encode()

        self.log.debug("> %s", command)
        try:
            self.transport.write(command)
            # time.sleep(0.01)
        except Exception:
            self.log.warning("No transport found, unable to send command")

    @property
    def attenuation(self):
        """Current volume attenuation in dB (read/write).

        You can get or set the current attenuation value on the device with this
        property.  Valid range from -90 to 0.

        :Examples:

        >>> attvalue = attenuation
        >>> attenuation = -50
        """
        try:
            return int(self._get_attribute_value(ATTR_VOLUME_UP))
        except ValueError:
            return -90
        except NameError:
            return -90

    @attenuation.setter
    def attenuation(self, value):
        volume = self._get_integer(ATTR_VOLUME_UP)
        if isinstance(value, int) and -90 <= value <= 0 and value != volume:
            self.log.debug("Setting attenuation to " + str(value))
            self._volume_target = value
            self.send_command(
                CMD_VOLUME_UP if self._volume_target > volume else CMD_VOLUME_DOWN
            )

    @property
    def volume(self):
        """Current volume level (read/write).

        You can get or set the current volume value on the device with this
        property.  Valid range from 0 to 100.

        :Examples:

        >>> volvalue = volume
        >>> volume = 20
        """
        return attenuation_to_volume(self.attenuation)

    @volume.setter
    def volume(self, value):
        if isinstance(value, int) and 0 <= value <= 100:
            self.attenuation = volume_to_attenuation(value)

    @property
    def volume_as_percentage(self):
        """Current volume as percentage (read/write).

        You can get or set the current volume value as a percentage.  Valid
        range from 0 to 1 (float).

        :Examples:

        >>> volper = volume_as_percentage
        >>> volume_as_percentage = 0.20
        """
        volume_per = self.volume / 100
        return volume_per

    @volume_as_percentage.setter
    def volume_as_percentage(self, value):
        if isinstance(value, float) or isinstance(value, int):
            if 0 <= value <= 1:
                value = round(value * 100)
                self.volume = value

    #
    # Boolean properties and corresponding setters
    #
    @property
    def power(self):
        """Report if device powered on or off (read/write).

        Returns and expects a boolean value.
        """
        return self._get_boolean(ATTR_POWER_STATE)

    @power.setter
    def power(self, value):
        self.send_command(
            CMD_SET_POWER_STATE, POWER_STATE_ON if value else POWER_STATE_OFF
        )

    @property
    def mute(self):
        """Mute on or off (read/write)."""
        return self._get_boolean(ATTR_MUTE_STATE)

    @mute.setter
    def mute(self, value):
        self.send_command(
            CMD_SET_MUTE_STATE, MUTE_STATE_ON if value else MUTE_STATE_OFF
        )

    #
    # Read-only text properties
    #

    @property
    def sw_version(self):
        """Software version (read-only)."""
        return self._get_attribute_value(ATTR_SW_VERSION) or "Unknown Version"

    @property
    def protocol_version(self):
        """Protocol version (read-only)."""
        return self._get_attribute_value(ATTR_PROTOCOL_VERSION) or "Unknown Version"

    #
    # Input number and lists
    #

    @property
    def input_list(self):
        """List of all enabled inputs."""
        return list(INPUT_NAMES.values())

    @property
    def input_name(self):
        """Name of currently active input (read-write)."""
        return INPUT_NAMES.get(self.input_number, "Unknown")

    @input_name.setter
    def input_name(self, value):
        number = INPUT_NUMBERS.get(value, 0)
        if number > 0:
            self.input_number = number

    @property
    def input_number(self):
        """Number of currently active input (read-write)."""
        return self._get_integer(ATTR_SELECTED_INPUT)

    @input_number.setter
    def input_number(self, number):
        if isinstance(number, int):
            if 1 <= number <= 99:
                self.log.debug("Switching input to " + f"{number:02d}")
                self.send_command(CMD_SELECT_INPUT, f"{number:02d}")
