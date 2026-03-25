import argparse
import serial
import sys
import time
import traceback

from cat_yft767gx import (
    YaesuInstruction,
    YaesuCommand,
    yaesu_state,
    cat_command,
    handle_set_freq,
    handle_set_mode,
    handle_get_split_mode,
    handle_set_split_mode,
    parse_status_update_5byte,
    parse_status_update_8byte,
    parse_status_update_26byte,
    parse_status_update_86byte,
    close_serial_port,
)


def main():
    parser = argparse.ArgumentParser(
        description="FT-767GX CAT Command Tester. It enables CAT, runs a single command, and then disables CAT."
    )
    parser.add_argument("--port", default="COM3", help="Serial port for CAT control")

    subparsers = parser.add_subparsers(
        dest="command", required=True, help="The individual command to test."
    )

    subparsers.add_parser("check", help="Get full 86-byte status from the radio.")

    parser_set_freq = subparsers.add_parser(
        "set-freq", help="Set the frequency of the active VFO."
    )
    parser_set_freq.add_argument(
        "frequency", type=float, help="Frequency in Hz (e.g., 14074000)"
    )

    parser_set_mode = subparsers.add_parser(
        "set-mode", help="Set the mode of the active VFO."
    )
    parser_set_mode.add_argument(
        "mode",
        choices=["LSB", "USB", "CW", "AM", "FM", "FSK"],
        help="The desired mode.",
    )

    subparsers.add_parser("toggle-split", help="Toggle the SPLIT function on/off.")
    subparsers.add_parser("swap-vfo", help="Swap VFO A and B.")
    
    subparsers.add_parser(
        "get-split-mode", help="Get the mode of the transmit VFO."
    )
    parser_set_split_mode = subparsers.add_parser(
        "set-split-mode", help="Set the mode of the transmit VFO."
    )
    parser_set_split_mode.add_argument(
        "mode",
        choices=["LSB", "USB", "CW", "AM", "FM", "FSK"],
        help="The desired mode for the TX VFO.",
    )


    args = parser.parse_args()

    ser = None
    try:
        print(f"Attempting to open serial port {args.port}...")
        ser = serial.Serial(
            port=args.port,
            baudrate=4800,
            bytesize=8,
            timeout=2,
            stopbits=serial.STOPBITS_TWO,
        )
        time.sleep(0.5)
        print(f"Port {args.port} opened successfully.")
    except serial.SerialException as e:
        print(f"FATAL: Could not open serial port {args.port}: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        print("Enabling CAT mode...")
        cat_enable_cmd = YaesuCommand(
            "cat enable", YaesuInstruction.CAT_SW, 86, parse_status_update_86byte, data1=0
        )
        cat_command(ser, cat_enable_cmd)
        print("CAT Enabled. Initial State:")
        print(yaesu_state)
        print("-" * 20)

        cmd_to_run = None
        was_run_by_handler = False

        # For commands that have a matching handler in the source file, we call the handler directly.
        # This reduces code duplication and tests the actual logic the server uses.
        if args.command == "set-freq":
            print(f"Executing command '{args.command}' via its handler...")
            handle_set_freq(ser, [str(args.frequency)])
            was_run_by_handler = True
        
        elif args.command == "set-mode":
            print(f"Executing command '{args.command}' via its handler...")
            handle_set_mode(ser, [args.mode])
            was_run_by_handler = True

        elif args.command == "get-split-mode":
            print(f"Executing command '{args.command}' via its handler...")
            # This handler returns the result, which we print
            split_mode_response = handle_get_split_mode(ser, [])
            print(f"Response from rig: {split_mode_response}")
            was_run_by_handler = True

        elif args.command == "set-split-mode":
            print(f"Executing command '{args.command}' via its handler...")
            handle_set_split_mode(ser, [args.mode])
            was_run_by_handler = True

        # For simple commands without handlers or where we want to test the instruction directly,
        # we build the command object manually.
        else:
            if args.command == "check":
                cmd_to_run = YaesuCommand(
                    "check", YaesuInstruction.CHECK, 86, parse_status_update_86byte
                )

            elif args.command == "toggle-split":
                cmd_to_run = YaesuCommand(
                    "toggle split", YaesuInstruction.SPLIT_TOG, 26, parse_status_update_26byte
                )

            elif args.command == "swap-vfo":
                cmd_to_run = YaesuCommand(
                    "swap vfo", YaesuInstruction.SWAP, 26, parse_status_update_26byte
                )

        # Execute the command if it wasn't already run by a handler function
        if cmd_to_run and not was_run_by_handler:
            print(f"Executing command: '{args.command}'...")
            cat_command(ser, cmd_to_run)
        
        print("Command processed. New State:")
        print(yaesu_state)

    except Exception:
        print(f"FATAL: An error occurred during CAT command execution:", file=sys.stderr)
        traceback.print_exc()

    finally:
        if ser and ser.is_open:
            print("-" * 20)
            print("Disabling CAT mode...")
            try:
                cat_disable_cmd = YaesuCommand(
                    "cat disable",
                    YaesuInstruction.CAT_SW,
                    86,
                    parse_status_update_86byte,
                    data1=1,
                )
                cat_command(ser, cat_disable_cmd)
                print("CAT mode disabled.")
            except Exception as e:
                print(f"Warning: Failed to disable CAT mode. May need to power cycle rig. Error: {e}", file=sys.stderr)

            close_serial_port(ser)
            print("Serial port closed.")


if __name__ == "__main__":
    main()
