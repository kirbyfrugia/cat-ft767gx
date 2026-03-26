import argparse
import sys
import traceback

from run_rig import (
    yaesu_state,
    rigctl_state,
    handle_get_freq,
    handle_set_freq,
    handle_get_mode,
    handle_set_mode,
    handle_get_vfo,
    handle_set_vfo,
    handle_get_split_vfo,
    handle_set_split_vfo,
    handle_get_split_freq,
    handle_set_split_freq,
    handle_get_split_mode,
    handle_set_split_mode,
    parse_status_update_5byte,
    parse_status_update_8byte,
    parse_status_update_26byte,
    parse_status_update_86byte,
)
from rig_utils import RigUtils, YaesuCommand, YaesuInstruction


def main():
    parser = argparse.ArgumentParser(
        description="FT-767GX CAT Command Tester. It enables CAT, runs a single command, and then disables CAT."
    )
    parser.add_argument("--port", default="COM3", help="Serial port for CAT control")

    subparsers = parser.add_subparsers(
        dest="command", required=True, help="The individual command to test."
    )

    subparsers.add_parser("check", help="Get full 86-byte status from the radio.")
    subparsers.add_parser("get-freq", help="Get the frequency of the active VFO.")

    parser_set_freq = subparsers.add_parser(
        "set-freq", help="Set the frequency of the active VFO."
    )
    parser_set_freq.add_argument(
        "frequency", type=float, help="Frequency in Hz (e.g., 14074000)"
    )

    subparsers.add_parser("get-mode", help="Get the mode of the active VFO.")
    parser_set_mode = subparsers.add_parser(
        "set-mode", help="Set the mode of the active VFO."
    )
    parser_set_mode.add_argument(
        "mode",
        choices=["LSB", "USB", "CW", "AM", "FM", "FSK"],
        help="The desired mode.",
    )
    subparsers.add_parser("get-vfo", help="Get the active VFO.")
    parser_set_vfo = subparsers.add_parser("set-vfo", help="Set the active VFO.")
    parser_set_vfo.add_argument(
        "vfo",
        choices=["VFOA", "VFOB", "MEM"],
        help="The desired VFO.",
    )

    subparsers.add_parser("toggle-split", help="Toggle the SPLIT function on/off.")
    
    parser_get_split_vfo = subparsers.add_parser("get-split-vfo", help="Get the split status and transmit VFO.")
    parser_get_split_vfo.add_argument(
        "tx_vfo", choices=["VFOA", "VFOB"], help="The VFO to check for transmit status."
    )
    parser_set_split_vfo = subparsers.add_parser(
        "set-split-vfo", help="Set the split status and transmit VFO."
    )
    parser_set_split_vfo.add_argument(
        "split", choices=["0", "1"], help="0 for OFF, 1 for ON"
    )
    parser_set_split_vfo.add_argument(
        "tx_vfo", choices=["VFOA", "VFOB"], help="The VFO to use for transmit."
    )
    
    parser_get_split_freq = subparsers.add_parser(
        "get-split-freq", help="Get the frequency of the transmit VFO."
    )
    parser_get_split_freq.add_argument(
        "tx_vfo", choices=["VFOA", "VFOB"], help="The VFO to use for transmit."
    )
    parser_set_split_freq = subparsers.add_parser(
        "set-split-freq", help="Set the frequency of the transmit VFO."
    )
    parser_set_split_freq.add_argument(
        "frequency", type=float, help="Frequency in Hz (e.g., 14074000)"
    )
    parser_set_split_freq.add_argument(
        "tx_vfo", choices=["VFOA", "VFOB"], help="The VFO to use for transmit."
    )

    parser_get_split_mode = subparsers.add_parser(
        "get-split-mode", help="Get the mode of the transmit VFO."
    )
    parser_get_split_mode.add_argument(
        "tx_vfo", choices=["VFOA", "VFOB"], help="The VFO to use for transmit."
    )
    parser_set_split_mode = subparsers.add_parser(
        "set-split-mode", help="Set the mode of the transmit VFO."
    )
    parser_set_split_mode.add_argument(
        "mode",
        choices=["LSB", "USB", "CW", "AM", "FM", "FSK"],
        help="The desired mode for the TX VFO.",
    )
    parser_set_split_mode.add_argument(
        "tx_vfo", choices=["VFOA", "VFOB"], help="The VFO to use for transmit."
    )


    args = parser.parse_args()
    
    rig_utils = RigUtils(port=args.port)
    try:
        rig_utils.open_serial_port()
        rig_utils.start_cat(parse_status_update_86byte)
        
        print("CAT Enabled. Initial State:")
        print(yaesu_state)
        print("-" * 20)

        cmd_to_run = None
        was_run_by_handler = False

        # For commands that have a matching handler in the source file, we call the handler directly.
        # This reduces code duplication and tests the actual logic the server uses.
        if args.command == "get-freq":
            print(f"Executing command :{args.command} ...")
            freq_response = handle_get_freq(rig_utils, [])
            print(f"Response from rig: {freq_response}")
            was_run_by_handler = True
        elif args.command == "set-freq":
            print(f"Executing command :{args.command} ...")
            handle_set_freq(rig_utils, [str(args.frequency)])
            was_run_by_handler = True
        elif args.command == "get-mode":
            print(f"Executing command: {args.command}...")
            mode_response = handle_get_mode(rig_utils, [])
            print(f"Response from rig: {mode_response}")
            was_run_by_handler = True
        elif args.command == "set-mode":
            print(f"Executing command: {args.command}...")
            handle_set_mode(rig_utils, [args.mode])
            was_run_by_handler = True
        elif args.command == "get-vfo":
            print(f"Executing command: {args.command}...")
            vfo_response = handle_get_vfo(rig_utils, [])
            print(f"Response from rig: {vfo_response}")
            was_run_by_handler = True
        elif args.command == "set-vfo":
            print(f"Executing command: {args.command}...")
            handle_set_vfo(rig_utils, [args.vfo])
            was_run_by_handler = True
        elif args.command == "get-split-vfo":
            print(f"Executing command: {args.command}...")
            rigctl_state.tx_vfo = args.tx_vfo
            split_vfo_response = handle_get_split_vfo(rig_utils, [])
            print(f"Response from rig: {split_vfo_response}")
            was_run_by_handler = True
        elif args.command == "set-split-vfo":
            print(f"Executing command: {args.command}...")
            handle_set_split_vfo(rig_utils, [args.split, args.tx_vfo])
            was_run_by_handler = True
        elif args.command == "get-split-freq":
            print(f"Executing command: {args.command}...")
            rigctl_state.tx_vfo = args.tx_vfo
            split_freq_response = handle_get_split_freq(rig_utils, [])
            print(f"Response from rig: {split_freq_response}")
            was_run_by_handler = True
        elif args.command == "set-split-freq":
            print(f"Executing command: {args.command}...")
            rigctl_state.tx_vfo = args.tx_vfo
            handle_set_split_freq(rig_utils, [str(args.frequency)])
            was_run_by_handler = True
        elif args.command == "get-split-mode":
            print(f"Executing command: {args.command}...")
            rigctl_state.tx_vfo = args.tx_vfo
            # This handler returns the result, which we print
            split_mode_response = handle_get_split_mode(rig_utils, [])
            print(f"Response from rig: {split_mode_response}")
            was_run_by_handler = True

        elif args.command == "set-split-mode":
            print(f"Executing command: {args.command}...")
            rigctl_state.tx_vfo = args.tx_vfo
            handle_set_split_mode(rig_utils, [args.mode])
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
                    "toggle split", YaesuInstruction.SPLIT_TOG, 26, parse_status_update_26byte,
                    data1=0x30
                )

        # Execute the command if it wasn't already run by a handler function
        if cmd_to_run and not was_run_by_handler:
            print(f"Executing command: '{args.command}'...")
            rig_utils.cat_command(cmd_to_run)
        
    except Exception:
        print(f"FATAL: An error occurred during CAT command execution:", file=sys.stderr)
        traceback.print_exc()

    finally:
        if rig_utils.serial_port and rig_utils.serial_port.is_open:
            print("-" * 20)
            rig_utils.stop_cat()
            rig_utils.close_serial_port()


if __name__ == "__main__":
    main()
