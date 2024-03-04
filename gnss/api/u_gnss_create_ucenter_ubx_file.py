#!/usr/bin/env python

'''Parse a ubxlib log to obtain the GNSS traffic and write it to a uCenter .ubx file.'''

from multiprocessing import Process, freeze_support # Needed to make Windows behave
                                                    # when run under multiprocessing,
from signal import signal, SIGINT   # For CTRL-C handling
import os
import sys # For exit() and stdout
import argparse

# This script can be fed ubxib log output and will find in it
# the traffic between ubxlib and the GNSS device which it
# can dump into a .ubx file which the u-blox uCenter tool
# is able to open.
#
# ubxlib will emit log output by default and, if you have
# opened the GNSS device/network with the `uDevice`/`uNetwork`
# API, this will include the GNSS traffic by default; otherwise
# you should enable logging of GNSS traffic by calling
# uGnssSetUbxMessagePrint() with true.

# The characters at the start of a GNSS message received from
# the GNSS device.
FROM_GNSS_LOG_LINE_MARKER = "U_GNSS: decoded UBX response"

# The characters at the start of a GNSS message transmitted to
# the GNSS device.
TO_GNSS_LOG_LINE_MARKER = "U_GNSS: sent command"

# Default output file extension
OUTPUT_FILE_EXTENSION = "ubx"

def signal_handler(sig, frame):
    '''CTRL-C Handler'''
    del sig
    del frame
    sys.stdout.write('\n')
    print("CTRL-C received, EXITING.")
    sys.exit(-1)

def line_parse_from_gnss_message(line_number, input_line, start_index):
    '''Parse a log line containing UBX message received from a GNSS device'''
    message = bytearray()

    # A "from GNSS" line looks like this:
    #
    # U_GNSS: decoded UBX response 0x0a 0x06: 01 05 00 ...[body 120 byte(s)].
    #
    # ...i.e. the message class/ID followed by the body, missing out the header, the
    # length and the FCS
    #
    input_string = input_line[start_index:]
    # Capture the message class and ID
    class_and_id = []
    try:
        class_and_id = [int(i, 16) for i in input_string[:10].split(" 0x") if i]
    except ValueError:
        pass
    if len(class_and_id) == 2:
        # Find the length
        body_length = []
        body_index = input_string.find("body ")
        if body_index >= 0:
            body_length = [int(i) for i in input_string[body_index:].split() if i.isdigit()]
            if len(body_length) == 1:
                # Assemble the binary message, starting with the header
                message.append(0xb5)
                message.append(0x62)
                # Then the class and ID
                message.append(int(class_and_id[0]))
                message.append(int(class_and_id[1]))
                # Then the little-endian body length
                message.append(body_length[0] % 256)
                message.append(int(body_length[0] / 256))
                # Now the body
                try:
                    message.extend([int(i, 16) for i in input_string[11:11 + (body_length[0] * 3)].split() if i])
                except ValueError:
                    print(f"Warning: found non-hex value in body of decoded line {line_number}: \"{input_line}\".")
                # Having done all that, work out the FCS and append it
                fcs_ca = 0
                fcs_cb = 0
                for integer in message[2:]:
                    fcs_ca += integer
                    fcs_cb += fcs_ca
                message.append(int(fcs_ca) & 0xFF)
                message.append(int(fcs_cb) & 0xFF)
            else:
                print(f"Warning: couldn't find body length in decoded line {line_number}: \"{input_line}\".")
        else:
            print(f"Warning: couldn't find \"body\" in decoded line {line_number}: \"{input_line}\".")
    else:
        print(f"Warning: couldn't find message class/ID in decoded line {line_number}: \"{input_line}\".")

    return message

def line_parse_to_gnss_message(line_number, input_line, start_index):
    '''Parse a log line containing UBX message sent to a GNSS device'''
    message = bytearray()

    # A "to GNSS" line looks like this:
    #
    # U_GNSS: sent command b5 62 06 8a 09 00 00 01 00 00 21 00 11 20 08 f4 51.
    #
    # ...i.e. it contains the whole thing, raw, so nice and easy
    input_string = input_line[start_index:]
    try:
        message.extend([int(i[:2], 16) for i in input_string.split() if i])
    except ValueError:
        print(f"Warning: found non-hex value in body of sent line {line_number}: \"{input_line}\".")

    return message

def main(input_file, output_file, responses_only):
    '''Main as a function'''
    input_line_list = []
    message_list = []
    return_value = 1

    signal(SIGINT, signal_handler)

    if os.path.isfile(input_file):
        with open(input_file, "r", encoding="utf8") as input_file_handle:
            # Read the lot in
            print(f"Reading file {input_file}...")
            input_line_list = input_file_handle.readlines()
        if input_line_list:
            # Look for the wanted lines
            print_text = f"Looking for lines containing \"{FROM_GNSS_LOG_LINE_MARKER}\""
            if not responses_only:
                print_text += f" and \"{TO_GNSS_LOG_LINE_MARKER}\""
            print_text += "..."
            print(print_text)
            line_number = 0
            for input_line in input_line_list:
                line_number += 1
                message = None
                start_index = input_line.find(FROM_GNSS_LOG_LINE_MARKER)
                if start_index >= 0:
                    start_index += len(FROM_GNSS_LOG_LINE_MARKER)
                    message = line_parse_from_gnss_message(line_number,
                                                           input_line[:len(input_line) - 1],
                                                           start_index)
                else:
                    if not responses_only:
                        start_index = input_line.find(TO_GNSS_LOG_LINE_MARKER)
                        if start_index >= 0:
                            start_index += len(TO_GNSS_LOG_LINE_MARKER)
                            message = line_parse_to_gnss_message(line_number,
                                                                 input_line[:len(input_line) - 1],
                                                                 start_index)
                if message:
                    message_list.append(message)
            if message_list:
                # Write the lot out
                if not os.path.splitext(output_file)[1]:
                    output_file += "." + OUTPUT_FILE_EXTENSION
                print(f"Writing {len(message_list)} UBX messages(s) to file {output_file}...")
                with open(output_file, "wb") as output_file_handle:
                    for message in message_list:
                        output_file_handle.write(message)
                    print(f"File {output_file} has been written: you may open it in uCenter.")
                    return_value = 0
            else:
                print(f"No GNSS traffic found in {input_file}.")
    else:
        print(f"\"{input_file}\" is not a file.")

    return return_value

if __name__ == "__main__":
    PARSER = argparse.ArgumentParser(description="A script to"      \
                                     " find GNSS traffic in ubxlib" \
                                     " log output and write it to"  \
                                     " a file that uCenter can"     \
                                     " open.\n")
    PARSER.add_argument("input_file", help="a file containing the"  \
                        " ubxlib log output.")
    PARSER.add_argument("output_file", help="the output file name;" \
                        " if the file exists it will be overwritten.")
    PARSER.add_argument("-r", action="store_true", help="include"   \
                        " only the responses from the GNSS device"  \
                        " (i.e. leave out any commands sent to the" \
                        " GNSS device).")

    ARGS = PARSER.parse_args()

    # Call main()
    RETURN_VALUE = main(ARGS.input_file, ARGS.output_file, ARGS.r)

    sys.exit(RETURN_VALUE)

# A main is required because Windows needs it in order to
# behave when this module is called during multiprocessing
# see https://docs.python.org/2/library/multiprocessing.html#windows
if __name__ == '__main__':
    freeze_support()
    PROCESS = Process(target=main)
    PROCESS.start()
