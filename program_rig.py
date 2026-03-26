import csv
import argparse
import sys
import traceback

from run_rig import (
    yaesu_state,
    handle_set_freq,
    handle_set_mode,
    handle_set_vfo,
    parse_status_update_5byte,
    parse_status_update_8byte,
    parse_status_update_26byte,
    parse_status_update_86byte,
)
from rig_utils import RigUtils, YaesuCommand, YaesuInstruction

def tone_frequency_to_bcd(frequency):
  freq_str = f"{int(float(frequency) * 10):04d}"
  hex_bytes = bytes.fromhex(freq_str)
  print(hex_bytes)
  p1, p2 = list(hex_bytes)

  print(f"frequency: {frequency}, freq_str: {freq_str}, p1: {p1}, p2: {p2}")
  return [p1, p2]

def parse_memory_channels_csv(file_path):
  """
  Parses a CSV file containing memory channel data.
  """
  memory_channels = []
  with open(file_path, mode='r', newline='') as csvfile:
    reader = csv.DictReader(csvfile)

    expected_headers = [
      'Memory Channel', 'Frequency', 'Offset (Ignored)', 'CTCSS Tone', 'CTCSS Tone(LowQ=0 HighQ=1)', 'Mode', 'Description'
    ]

    fieldnames = reader.fieldnames
    if fieldnames is None:
      raise ValueError("CSV file is empty or has no headers.")

    missing_headers = set(expected_headers) - set(fieldnames)
    if missing_headers:
      raise ValueError(f"CSV file is missing expected headers: {', '.join(missing_headers)}")

    for row in reader:
      memory_channels.append(row)

  return memory_channels

def process_memory_channel(rig, memory_channel):
  print(f"Programming Channel {memory_channel['Memory Channel']}: {memory_channel['Frequency']} Hz, Mode: {memory_channel['Mode']}, Tone: {memory_channel['CTCSS Tone']}")
  freq = memory_channel['Frequency']
  mode = memory_channel['Mode']
  handle_set_freq(rig, [freq])
  handle_set_mode(rig, [mode])

  tone_bcd = tone_frequency_to_bcd(memory_channel["CTCSS Tone"])
  tone_q = int(memory_channel["CTCSS Tone(LowQ=0 HighQ=1)"])

  print(f"tone_q: {tone_q}, tone_bcd: {tone_bcd}")
  command = YaesuCommand("tone set", YaesuInstruction.TONE_SET, 26, parse_status_update_26byte, 
                         data1=tone_bcd[0],
                         data2=tone_bcd[1],
                         data3=tone_q
                         )
  rig.cat_command(command)

  # command = YaesuCommand("select mr", YaesuInstruction.VFOMR, 5, parse_status_update_5byte, data1=0x02)
  # rig.cat_command(command)

  mem_channel = int(memory_channel['Memory Channel'])
  command = YaesuCommand("mem sel", YaesuInstruction.MEMSEL, 8, parse_status_update_8byte, data1=mem_channel)
  rig.cat_command(command)

  command = YaesuCommand("vfo to mem", YaesuInstruction.VTOM, 86, parse_status_update_86byte, data1=0x60)
  rig.cat_command(command)
  
  return

def process_memory_channels(rig, memory_channels):
  handle_set_vfo(rig, ["VFOA"])

  for channel in memory_channels:
    process_memory_channel(rig, channel)

  handle_set_vfo(rig, ["VFOA"])

def main():
  parser = argparse.ArgumentParser(description="Parse a CSV file to program Yaesu FT-767GX memory channels.")
  parser.add_argument("file_path", help="The path to the CSV file.")
  parser.add_argument("--port", default="COM3", help="Serial port for CAT control")
  args = parser.parse_args()

  rig = RigUtils(port=args.port)
  try:
    channels = parse_memory_channels_csv(args.file_path)

    rig.open_serial_port()
    rig.start_cat(parse_status_update_86byte)

    print("CAT Enabled. Initial rig state:")
    print(yaesu_state)
    print("-" * 20)

    print(f"Successfully parsed {len(channels)} memory channels from '{args.file_path}'.")
    process_memory_channels(rig, channels)

    print("-" * 20)
    print("Memory channel programming complete.")

  except FileNotFoundError:
    print(f"FATAL: The file '{args.file_path}' was not found.", file=sys.stderr)
  except ValueError as e:
    print(f"FATAL: {e}", file=sys.stderr)
  except Exception:
    print(f"FATAL: An unexpected error occurred during execution:", file=sys.stderr)
    traceback.print_exc()

  finally:
    rig.stop_cat()
    rig.close_serial_port()

if __name__ == '__main__':
  main()