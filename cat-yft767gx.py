import atexit
from dataclasses import dataclass, field
from enum import Enum
import serial
import sys
import time

@dataclass
class YaesuMemoryChannel:
  frequency: int = 0
  ctcss_tone: int = 0
  mode: int = 0

@dataclass
class YaesuState:
  status_flags: int = 0
  operating_frequency: int = 0
  selected_ctcss_tone: int = 0
  selected_mode: int = 0
  selected_memory_channel: int = 0
  clarifier_frequency: int = 0
  clarifier_ctcss_tone: int = 0
  clarifier_mode: int = 0
  vfoa_frequency: int = 0
  vfoa_ctcss_tone: int = 0
  vfoa_mode: int = 0
  vfob_frequency: int = 0
  vfob_ctcss_tone: int = 0
  vfob_mode: int = 0
  memory_channels: list[YaesuMemoryChannel] = field(
      default_factory=lambda: [YaesuMemoryChannel() for _ in range(10)]
    )

# Command Instructions
class YaesuInstruction(Enum):
  CAT_SW    = 0x00
  CHECK     = 0x01
  UP10HZ    = 0x02
  DN10HZ    = 0x03
  PROG_UP   = 0x04
  PROG_DN   = 0x05
  BAND_UP   = 0x06
  BAND_DOWN = 0x07
  FREQ_SET  = 0x08
  VFOMR     = 0x09
  MEMSEL    = 0x0A
  MODESEL   = 0x0A
  HGSEL     = 0x0A
  SPLIT_TOG = 0x0A
  CLAR_TOG  = 0x0A
  MTOV      = 0x0A
  VTOM      = 0x0A
  SWAP      = 0x0A
  ACLR      = 0x0A
  TONE_SET  = 0x0C
  ACK       = 0x0B

class YaesuCommand:
  def __init__(self, friendly_name, instruction, response_size, response_parser, data1=0,data2=0,data3=0,data4=0):
    self.friendly_name = friendly_name
    self.instruction = instruction
    self.response_size = response_size
    self.response_parser = response_parser
    self.data1 = data1 # MSB for data
    self.data2 = data2
    self.data3 = data3
    self.data4 = data4 # LSB for data

  def to_bytes(self):
    return bytes([self.data4,self.data3,self.data2,self.data1,self.instruction.value])

serial_port = None
ack_command = YaesuCommand(friendly_name="ACK", 
                           instruction=YaesuInstruction.ACK, 
                           response_size=0, 
                           response_parser=None)

yaesu_state = YaesuState()

def close_port(serial_port):
  print("Closing port...")
  if (serial_port.is_open):
    serial_port.reset_input_buffer()
    serial_port.reset_output_buffer()
    serial_port.close()
    time.sleep(1)
  return

# frequencies are sent in 4 bytes as binary-coded decimal.
# it's a hex representation of decimal digits.
# E.g. 012.34567 MHz would be an array of
#      [01, 23, 45, 67]
# This takes the list we get back from the yaesu and converts to an integer
def list_to_frequency(freq_list):
  frequency = int(f"{freq_list[0]:02x}{freq_list[1]:02x}{freq_list[2]:02x}{freq_list[3]:02x}")
  return frequency

def parse_status_update_5byte(status_update):
  yaesu_state.status_flags = status_update[0]
  yaesu_state.operating_frequency = list_to_frequency(status_update[1:5])
  return

def parse_status_update_8byte(status_update):
  parse_status_update_5byte(status_update)
  yaesu_state.selected_ctcss_tone = status_update[5]
  yaesu_state.selected_mode = status_update[6]
  yaesu_state.selected_memory_channel = status_update[7]
  return

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
  return

def parse_status_update_86byte(status_update):
  parse_status_update_26byte(status_update)
  freq_index = 26
  for i in range(10):
    yaesu_state.memory_channels[i].frequency = list_to_frequency(status_update[freq_index:freq_index+4])
    yaesu_state.memory_channels[i].ctcss_tone = status_update[freq_index+4]
    yaesu_state.memory_channels[i].mode = status_update[freq_index+5]
    freq_index = freq_index + 6
  return

def cat_command(serial_port, yaesu_command):
  print(f"Sending command: {yaesu_command.friendly_name}")
  command_bytes = yaesu_command.to_bytes()
  serial_port.write(command_bytes)
  time.sleep(0.005)
  echo_bytes = serial_port.read_until(size=5)
  #print(f"command echo response: {command_echo}")

  if command_bytes != echo_bytes:
    raise ValueError(f"cat command error. echo does not match data. data: {command_bytes}, echo: {echo_bytes}")

  serial_port.write(ack_command.to_bytes())
  time.sleep(0.005)

  # reverse the order of the byte array just to make it easier to deal
  # with varying length responses
  status_update = list(serial_port.read_until(size=yaesu_command.response_size))
  status_update.reverse()
  yaesu_command.response_parser(status_update)
  #print(f"Status update: {status_update}\n")

  return

def cleanup(serial_port):
  print("Cleaning up...")
  command = YaesuCommand("cat disable", YaesuInstruction.CAT_SW, 86, parse_status_update_86byte, 
                         data1=1)
  cat_command(serial_port, command)
  time.sleep(0.25)
  close_port(serial_port)

def test(serial_port):
  print("Testing all functions")
  print("Enabling CAT")
  command = YaesuCommand("cat enable", YaesuInstruction.CAT_SW, 86, parse_status_update_86byte, 
                         data1=0)
  cat_command(serial_port, command)
  print(f"state: {yaesu_state}")

  print("Check command")
  command = YaesuCommand("check", YaesuInstruction.CHECK, 86, parse_status_update_86byte, 
                         data1=0)
  cat_command(serial_port, command)

  print("Set Frequency")
  command = YaesuCommand("set frequency", YaesuInstruction.FREQ_SET, 5, parse_status_update_5byte, 
                         data1=0x01,
                         data2=0x40,
                         data3=0x73,
                         data4=0x25)
  cat_command(serial_port, command)

  print("Set Mode to USB")
  command = YaesuCommand("set mode", YaesuInstruction.MODESEL, 8, parse_status_update_8byte, 
                         data1=0x11)
  cat_command(serial_port, command)

def main():
  serial_port = serial.Serial(
    port="COM3", baudrate=4800, bytesize=8, timeout=2, stopbits=serial.STOPBITS_TWO
  )

  time.sleep(2)
  atexit.register(cleanup, serial_port)
  print("opened com port")

  test(serial_port)

  time.sleep(2)

  return 0

if __name__ == "__main__":
  sys.exit(main())