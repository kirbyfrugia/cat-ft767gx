import serial
import time
import traceback
from enum import Enum

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

ack_command = YaesuCommand("ACK", YaesuInstruction.ACK, 0, None)

class RigUtils:
    def __init__(self, port="COM3", baudrate=4800, bytesize=8, timeout=2, stopbits=serial.STOPBITS_TWO):
        self.serial_port = None
        self.port = port
        self.baudrate = baudrate
        self.bytesize = bytesize
        self.timeout = timeout
        self.stopbits = stopbits

    def open_serial_port(self):
        try:
            print(f"Attempting to open serial port {self.port}...")
            self.serial_port = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                bytesize=self.bytesize,
                timeout=self.timeout,
                stopbits=self.stopbits,
            )
            time.sleep(0.5)
            print(f"Port {self.port} opened successfully.")
            return self.serial_port
        except serial.SerialException as e:
            print(f"FATAL: Could not open serial port {self.port}: {e}")
            raise

    def close_serial_port(self):
        print("Closing serial port...")
        if self.serial_port and self.serial_port.is_open:
            self.serial_port.reset_input_buffer()
            self.serial_port.reset_output_buffer()
            self.serial_port.close()
            time.sleep(0.1)
        print("Serial port closed.")

    def start_cat(self, status_parser):
        if not self.serial_port or not self.serial_port.is_open:
            raise Exception("Serial port not open.")

        print("Enabling CAT mode...")
        # data1=0 means ON
        command = YaesuCommand("cat enable", YaesuInstruction.CAT_SW, 86, status_parser, data1=0)
        self.cat_command(command)
        print("CAT Enabled.")

    def stop_cat(self):
        if not self.serial_port or not self.serial_port.is_open:
            print("Serial port not open, cannot disable CAT.")
            return

        print("Disabling CAT mode...")
        try:
            command = YaesuCommand("cat disable", YaesuInstruction.CAT_SW, 0, None, data1=1)
            self.cat_command(command, expect_status_update=False)
            print("CAT mode disabled.")
        except Exception as e:
            print(f"Warning: Failed to disable CAT mode. May need to power cycle rig. Error: {e}")

    def write_command_bytes(self, yaesu_command):
        self.serial_port.write(yaesu_command.to_bytes())
        time.sleep(0.005)
        self.serial_port.flush()
        return

    def cat_command(self, yaesu_command, expect_status_update=True):
        max_retries = 3
        last_exception = None

        for attempt in range(max_retries):
            try:
                print(f"Sending command: {yaesu_command.friendly_name} (Attempt {attempt + 1}/{max_retries})")
                command_bytes = yaesu_command.to_bytes()

                self.write_command_bytes(yaesu_command)
                echo_bytes = self.serial_port.read_until(size=5)

                if command_bytes != echo_bytes:
                    raise ValueError(f"cat command error. echo does not match data. data: {command_bytes}, echo: {echo_bytes}")

                self.write_command_bytes(ack_command)

                last_exception = None
                break

            except Exception as e:
                last_exception = e
                print(f"Command failed on attempt {attempt + 1}: {e}")
                time.sleep(0.05)
        
        if last_exception:
            raise last_exception

        if expect_status_update:
            status_update = list(self.serial_port.read_until(size=yaesu_command.response_size))
            status_update.reverse()
            yaesu_command.response_parser(status_update)

        return
