from dataclasses import dataclass, field
import math
import re
import socketserver
import sys
import traceback

from rig_utils import RigUtils, YaesuCommand, YaesuInstruction


# ---------------------------------------------------------------------------
# State dataclasses (owned here; rig_utils has no state of its own)
# ---------------------------------------------------------------------------

@dataclass
class YaesuMemoryChannel:
  frequency: int = 0
  ctcss_tone: int = 0
  mode: int = 0

# what's with the shadow stuff? These are cases
# where the radio's precision doesn't match what
# callers expect, so when we do a "set" we keep
# the shadow copy to fool the caller.
@dataclass
class YaesuState:
  status_flags: int = 0
  operating_frequency: int = 0
  operating_frequency_shadow: int = 0
  selected_ctcss_tone: int = 0
  selected_mode: int = 0
  selected_memory_channel: int = 0
  clarifier_frequency: int = 0
  clarifier_ctcss_tone: int = 0
  clarifier_mode: int = 0
  vfoa_frequency: int = 0
  vfoa_frequency_shadow: int = 0
  vfoa_ctcss_tone: int = 0
  vfoa_mode: int = 0
  vfob_frequency: int = 0
  vfob_frequency_shadow: int = 0
  vfob_ctcss_tone: int = 0
  vfob_mode: int = 0
  memory_channels: list[YaesuMemoryChannel] = field(
      default_factory=lambda: [YaesuMemoryChannel() for _ in range(10)]
    )

@dataclass
class RigctlState:
  tx_vfo: str = ""

yaesu_state = YaesuState()
rigctl_state = RigctlState()


# ---------------------------------------------------------------------------
# Frequency helpers
# ---------------------------------------------------------------------------

# frequencies are sent in 4 bytes as binary-coded decimal.
# it's a hex representation of decimal digits.
# E.g. 012.34567 MHz would be an array of
#      [01, 23, 45, 67]
# This takes the list we get back from the yaesu and converts to an integer.
# The Yaesu also returns in decahertz instead of hertz, so multiply by 10.
def list_to_frequency(freq_list):
  frequency = int(f"{freq_list[0]:02x}{freq_list[1]:02x}{freq_list[2]:02x}{freq_list[3]:02x}") * 10
  return frequency

def frequency_to_list(frequency):
  val = int(frequency) // 10  # convert to decahertz

  s = f"{val:08d}"  # turn into 8-digit string

  # convert to BCD bytes
  freq_list = [
      int(s[0:2], 16),  # 100MHz & 10MHz
      int(s[2:4], 16),  # 1MHz & 100kHz
      int(s[4:6], 16),  # 10kHz & 1kHz
      int(s[6:8], 16)   # 100Hz & 10Hz
  ]

  return freq_list

# yaesu precision is less than hamlib's, so we keep
# the value hamlib tried to set. we respond with hamlib's
# if the values are equal at the yaesu precision.
def get_shadow_frequency(yaesu_frequency, shadow_frequency):
  truncated = math.floor(shadow_frequency / 10) * 10
  return shadow_frequency if yaesu_frequency == truncated else yaesu_frequency


# ---------------------------------------------------------------------------
# Status update parsers — write into the module-level yaesu_state
# ---------------------------------------------------------------------------

def parse_status_update_5byte(status_update):
  yaesu_state.status_flags = status_update[0]
  yaesu_state.operating_frequency = list_to_frequency(status_update[1:5])

def parse_status_update_8byte(status_update):
  parse_status_update_5byte(status_update)
  yaesu_state.selected_ctcss_tone = status_update[5]
  yaesu_state.selected_mode = status_update[6]
  yaesu_state.selected_memory_channel = status_update[7]

def parse_status_update_26byte(status_update):
  parse_status_update_8byte(status_update)
  yaesu_state.clarifier_frequency = list_to_frequency(status_update[8:12])
  yaesu_state.clarifier_ctcss_tone = status_update[12]
  yaesu_state.clarifier_mode = status_update[13]
  yaesu_state.vfoa_frequency = list_to_frequency(status_update[14:18])
  yaesu_state.vfoa_ctcss_tone = status_update[18]
  yaesu_state.vfoa_mode = status_update[19]
  yaesu_state.vfob_frequency = list_to_frequency(status_update[20:24])
  yaesu_state.vfob_ctcss_tone = status_update[24]
  yaesu_state.vfob_mode = status_update[25]

def parse_status_update_86byte(status_update):
  parse_status_update_26byte(status_update)
  freq_index = 26
  for i in range(10):
    yaesu_state.memory_channels[i].frequency = list_to_frequency(status_update[freq_index:freq_index+4])
    yaesu_state.memory_channels[i].ctcss_tone = status_update[freq_index+4]
    yaesu_state.memory_channels[i].mode = status_update[freq_index+5]
    freq_index = freq_index + 6


# ---------------------------------------------------------------------------
# Hamlib error codes
# ---------------------------------------------------------------------------

class HamlibError:
  # Success
  RIG_OK           = 0    # No error, operation completed successfully

  # Common Errors
  RIG_EINVAL       = -1   # Invalid parameter (e.g. freq out of range)
  RIG_ECONF        = -2   # Invalid configuration
  RIG_ENOMEM       = -3   # Internal memory allocation error
  RIG_ETIMEOUT     = -5   # Radio did not respond within timeout period
  RIG_EIO          = -6   # Input/Output error (Serial port/USB failure)
  RIG_EINTERNAL    = -8   # Internal Hamlib/Server error
  RIG_EPROTO       = -11  # Protocol error (Radio sent garbled data)
  RIG_ENAVAIL      = -12  # Feature not available on this specific rig
  RIG_ENOTIMPL     = -13  # Feature not implemented in this server yet
  RIG_EBUSY        = -16  # VFO or Radio is busy
  RIG_ENYI         = -17  # Not Yet Implemented
  RIG_EVFO         = -18  # Invalid VFO
  RIG_EREJECTED    = -19  # Command rejected by the rig

  @classmethod
  def to_response(cls, code):
    return f"RPRT {code}"


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

def handle_get_powerstat(rig_utils, cmd_args):
  try:
    status = yaesu_state.status_flags & 0b10000000
    # 00=ON, 01=OFF for yaesu, opposite for rigctl
    response = "0" if status != 0 else "1"
  except Exception as e:
    print("Error checking CAT status, responding with power off")
    traceback.print_exc()
    response = "0"
  return response

def handle_chk_vfo(rig_utils, cmd_args):
  return "CHKVFO 1"

def handle_dump_state(rig_utils, cmd_args):
  # this is a straight dump of what rigctld returns for yaesu ft767gx
  response = "\n".join([
    "dump_state:"
    "1",           # Protocol version
    "1009",        # Rig model (FT-767GX)
    "2",           # ITU Region
    # RX Ranges
    "1500000.000000 1999900.000000 0xf 5000 100000 0x3 0x80000000",
    "3500000.000000 3999900.000000 0xf 5000 100000 0x3 0x80000000",
    "7000000.000000 7499900.000000 0xf 5000 100000 0x3 0x80000000",
    "10000000.000000 10499900.000000 0xf 5000 100000 0x3 0x80000000",
    "14000000.000000 14499900.000000 0xf 5000 100000 0x3 0x80000000",
    "18000000.000000 18499900.000000 0xf 5000 100000 0x3 0x80000000",
    "21000000.000000 21499900.000000 0xf 5000 100000 0x3 0x80000000",
    "24500000.000000 24999900.000000 0xf 5000 100000 0x3 0x80000000",
    "28000000.000000 29999900.000000 0xf 5000 100000 0x3 0x80000000",
    "50000000.000000 59999900.000000 0x102f 5000 10000 0x3 0x80000000",
    "144000000.000000 147999900.000000 0x102f 5000 10000 0x3 0x80000000",
    "430000000.000000 449999990.000000 0x102f 5000 10000 0x3 0x80000000",
    "0 0 0 0 0 0 0", # End RX list
    "100000.000000 29999999.000000 0x102f -1 -1 0x0 0x0", # TX range
    "0 0 0 0 0 0 0", # End TX list
    "0 0 0 0 0",     # Filters
    "0x102f 10",     # Tuning step 1
    "0x102f 100",    # Tuning step 2
    "0 0",           # End tuning steps
    "0xffffffff 0",  # Attenuator
    "0 0",           # Preamp
    "9999",          # Max RIT
    "0",             # Max XIT
    "0",             # Max IF Shift
    "0",             # Announces
    "", "", "",      # The 3 blank spacers
    "0x0",           # Get level mask
    "0x0",           # Set level mask
    "0x2000000000000", # Get parm mask
    "0x2000000000000", # Set parm mask
    "0x0",           # Get func mask
    "0x0",           # Set func mask
    "RPRT 0"         # Final terminator
  ])
  return response

def handle_get_vfo(rig_utils, cmd_args):
  status = yaesu_state.status_flags & 0b00010000
  response = "VFOA" if status == 0 else "VFOB"
  return response

def handle_set_vfo(rig_utils, cmd_args):
  vfo_arg = cmd_args[0]

  vfo = -1
  match vfo_arg:
    case "VFOA":
      vfo = 0
    case "VFOB":
      vfo = 1
    case "MEM":
      vfo = 2

  if vfo == -1:
    return HamlibError.to_response(HamlibError.RIG_EINVAL)

  command = YaesuCommand("set vfo", YaesuInstruction.VFOMR, 5, parse_status_update_5byte,
                         data1=vfo)
  rig_utils.cat_command(command)

  return HamlibError.to_response(HamlibError.RIG_OK)

def handle_get_freq(rig_utils, cmd_args):
  frequency = get_shadow_frequency(yaesu_state.operating_frequency, yaesu_state.operating_frequency_shadow)
  return f"{frequency}"

def handle_set_freq(rig_utils, cmd_args):
  freq = int(float(cmd_args[0]))
  yaesu_state.operating_frequency_shadow = freq
  freq_list = frequency_to_list(freq)

  command = YaesuCommand("set freq", YaesuInstruction.FREQ_SET, 5, parse_status_update_5byte,
                         data1=freq_list[0],
                         data2=freq_list[1],
                         data3=freq_list[2],
                         data4=freq_list[3])
  rig_utils.cat_command(command)

  return HamlibError.to_response(HamlibError.RIG_OK)

def handle_get_mode(rig_utils, cmd_args):
  modes = {
    0: ("LSB", 2400),
    1: ("USB", 2400),
    2: ("CW", 500),
    3: ("AM", 6000),
    4: ("FM", 15000),
    5: ("FSK", 500)
  }
  mode = modes[yaesu_state.selected_mode & 0b00000111]
  return f"{mode[0]}\n{mode[1]}"

def handle_set_mode(rig_utils, cmd_args):
  requested_mode = cmd_args[0]

  match requested_mode:
    case "LSB":
      mode_num = 0x10
    case "USB":
      mode_num = 0x11
    case "CW":
      mode_num = 0x12
    case "AM":
      mode_num = 0x13
    case "FM":
      mode_num = 0x14
    case "FSK":
      mode_num = 0x15
    case _:
      return HamlibError.to_response(HamlibError.RIG_EINVAL)

  command = YaesuCommand("set mode", YaesuInstruction.MODESEL, 8, parse_status_update_8byte,
                         data1=mode_num)
  rig_utils.cat_command(command)

  return HamlibError.to_response(HamlibError.RIG_OK)

def handle_get_split_vfo(rig_utils, cmd_args):
  split = (yaesu_state.status_flags & 0b00001000) >> 3
  tx_vfo = rigctl_state.tx_vfo
  return f"{split}\n{tx_vfo}"

def handle_set_split_vfo(rig_utils, cmd_args):
  target_split = int(cmd_args[0])
  tx_vfo = cmd_args[1]

  current_split = 1 if (yaesu_state.status_flags & 0b00001000) else 0
  if target_split != current_split:
    command = YaesuCommand("toggle split", YaesuInstruction.SPLIT_TOG, 26, parse_status_update_26byte,
                           data1=0x30)
    rig_utils.cat_command(command)

  rigctl_state.tx_vfo = tx_vfo

  return HamlibError.to_response(HamlibError.RIG_OK)

def handle_get_split_freq(rig_utils, cmd_args):
  tx_freq = yaesu_state.vfob_frequency if rigctl_state.tx_vfo == "VFOB" else yaesu_state.vfoa_frequency
  tx_freq_shadow = yaesu_state.vfob_frequency_shadow if rigctl_state.tx_vfo == "VFOB" else yaesu_state.vfoa_frequency_shadow
  freq = get_shadow_frequency(tx_freq, tx_freq_shadow)
  return f"{freq}"

def handle_set_split_freq(rig_utils, cmd_args):
  freq = int(float(cmd_args[0]))

  # first check to see if the frequency needs to change for tx freq
  current_tx_freq = yaesu_state.vfoa_frequency_shadow if rigctl_state.tx_vfo == "VFOA" else yaesu_state.vfob_frequency_shadow
  if current_tx_freq == freq:
    return HamlibError.to_response(HamlibError.RIG_OK)

  # need to swap VFOs if we are setting transmit VFO but that VFO is not active
  active_vfo = (yaesu_state.status_flags & 0b00010000) >> 4
  tx_vfo = 0 if rigctl_state.tx_vfo == "VFOA" else 1
  if active_vfo != tx_vfo:
    vfo_str = "VFOA" if tx_vfo == 0 else "VFOB"
    handle_set_vfo(rig_utils, [vfo_str])

  # set the shadow frequency
  if tx_vfo == 0:
    yaesu_state.vfoa_frequency_shadow = freq
  else:
    yaesu_state.vfob_frequency_shadow = freq

  # set the tx vfo frequency
  freq_list = frequency_to_list(freq)
  command = YaesuCommand("set freq", YaesuInstruction.FREQ_SET, 5, parse_status_update_5byte,
                         data1=freq_list[0],
                         data2=freq_list[1],
                         data3=freq_list[2],
                         data4=freq_list[3])
  rig_utils.cat_command(command)

  # if we swapped VFOs, swap back to original VFO
  if active_vfo != tx_vfo:
    vfo_str = "VFOA" if active_vfo == 0 else "VFOB"
    handle_set_vfo(rig_utils, [vfo_str])

  return HamlibError.to_response(HamlibError.RIG_OK)

def handle_get_split_mode(rig_utils, cmd_args):
  modes = {
    0: ("LSB", 2400),
    1: ("USB", 2400),
    2: ("CW", 500),
    3: ("AM", 6000),
    4: ("FM", 15000),
    5: ("FSK", 500)
  }
  tx_mode = yaesu_state.vfob_mode if rigctl_state.tx_vfo == "VFOB" else yaesu_state.vfoa_mode
  mode = modes[tx_mode & 0b00000111]
  return f"{mode[0]}\n{mode[1]}"

def handle_set_split_mode(rig_utils, cmd_args):
  requested_mode = cmd_args[0]

  match requested_mode:
    case "LSB":
      mode_num = 0x10
    case "USB":
      mode_num = 0x11
    case "CW":
      mode_num = 0x12
    case "AM":
      mode_num = 0x13
    case "FM":
      mode_num = 0x14
    case "FSK":
      mode_num = 0x15
    case _:
      return HamlibError.to_response(HamlibError.RIG_EINVAL)

  # first check to see if the mode needs to change for tx mode
  current_tx_mode = yaesu_state.vfoa_mode if rigctl_state.tx_vfo == "VFOA" else yaesu_state.vfob_mode
  if current_tx_mode == mode_num:
    return HamlibError.to_response(HamlibError.RIG_OK)

  # need to swap VFOs if we are setting transmit VFO but that VFO is not active
  active_vfo = (yaesu_state.status_flags & 0b00010000) >> 4
  tx_vfo = 0 if rigctl_state.tx_vfo == "VFOA" else 1
  if active_vfo != tx_vfo:
    vfo_str = "VFOA" if tx_vfo == 0 else "VFOB"
    handle_set_vfo(rig_utils, [vfo_str])

  command = YaesuCommand("set mode", YaesuInstruction.MODESEL, 5, parse_status_update_5byte,
                         data1=mode_num)
  rig_utils.cat_command(command)

  # if we swapped VFOs, swap back to original VFO
  if active_vfo != tx_vfo:
    vfo_str = "VFOA" if active_vfo == 0 else "VFOB"
    handle_set_vfo(rig_utils, [vfo_str])

  return HamlibError.to_response(HamlibError.RIG_OK)

def handle_get_lock_mode(rig_utils, cmd_args):
  return "2"


# ---------------------------------------------------------------------------
# TCP server
# ---------------------------------------------------------------------------

class FakeRigctld(socketserver.StreamRequestHandler):
  def setup(self):
    super().setup()
    self.commands = {
      "get_powerstat" : handle_get_powerstat,
      "chk_vfo"       : handle_chk_vfo,
      "dump_state"    : handle_dump_state,
      "v"             : handle_get_vfo,
      "V"             : handle_set_vfo,
      "f"             : handle_get_freq,
      "F"             : handle_set_freq,
      "m"             : handle_get_mode,
      "M"             : handle_set_mode,
      "s"             : handle_get_split_vfo,
      "S"             : handle_set_split_vfo,
      "i"             : handle_get_split_freq,
      "I"             : handle_set_split_freq,
      "x"             : handle_get_split_mode,
      "X"             : handle_set_split_mode,
      "get_lock_mode" : handle_get_lock_mode
    }

  def handle(self):
    print(f"Connection from: {self.client_address}")
    while True:
      line = self.rfile.readline()

      if not line:  # disconnection
        break

      parts = line.decode("utf-8").strip().split()
      if not parts:
        continue

      cmd_name = parts[0]
      cmd_args = parts[1:]

      if cmd_name.startswith("\\"):
        cmd_name = cmd_name[1:]

      handler = self.commands.get(cmd_name)

      if handler:
        try:
          response = handler(self.server.rig_utils, cmd_args)
        except Exception as e:
          print(f"Error executing: {cmd_name}: {e}")
          traceback.print_exc()
          response = HamlibError.to_response(HamlibError.RIG_EINTERNAL)
      else:
        response = HamlibError.to_response(HamlibError.RIG_ENYI)

      one_line_response = repr(re.sub(r'[^\S ]', '\n', response))
      print(f"Finished command: {cmd_name}, args: {cmd_args}, response: {one_line_response}")

      response = f"{response}\n"
      self.wfile.write(response.encode("utf-8"))
      self.wfile.flush()


def main():
  rig = RigUtils()
  try:
    rig.open_serial_port()
    rig.start_cat(parse_status_update_86byte)

    host = "127.0.0.1"
    port = 4532

    with socketserver.TCPServer((host, port), FakeRigctld) as server:
      server.rig_utils = rig
      print(f"Fake rigctld server started on {host}:{port}")
      try:
        server.serve_forever()
      except KeyboardInterrupt:
        print("\nKeyboardInterrupt received")
      except ConnectionResetError:
        print("\nTCP Client disconnected unexpectedly")
      finally:
        server.shutdown()
        server.server_close()
        print("TCP port released.")

  except Exception as e:
    print(f"An error occurred: {e}")
    traceback.print_exc()

  finally:
    rig.stop_cat()
    rig.close_serial_port()

  return 0


if __name__ == "__main__":
  sys.exit(main())