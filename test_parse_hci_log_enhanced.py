"""
Unit tests for parse_hci_log_enhanced.py

How to use:
  1) Put this file in the same folder as:
       - parse_hci_log_enhanced.py
       - hci_dictionary.py
  2) Run:
       python -m pytest test_parse_hci_log_enhanced.py -v

These tests focus on the important behavior for your parser:
  - TX command decoding
  - RX event reconstruction when split across 2 or 3 lines
  - Command Complete decoding
  - Command Status decoding
  - Specific return-parameter decoding, e.g. local version, BD_ADDR, LE Test End
  - Robust handling of incomplete/stray fragments
"""

import importlib.util
from pathlib import Path


import os

MODULE_FILE = os.environ.get("HCI_PARSER_MODULE", "parse_hci_log_enhanced.py")
SCRIPT = Path(__file__).with_name(MODULE_FILE)
spec = importlib.util.spec_from_file_location("hci_parser_under_test", SCRIPT)
hci = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hci)


def new_context():
    return {"rx_buffer": []}


def test_parse_hex():
    assert hci.parse_hex("01 03 0C 00") == [0x01, 0x03, 0x0C, 0x00]


def test_tx_reset_command_decoded():
    ann = hci.annotate_tx([0x01, 0x03, 0x0C, 0x00])
    assert "TX: HCI Command Packet" in ann
    assert "Opcode=0x0C03" in ann
    assert "Reset" in ann
    assert "ParamLen=0 (OK)" in ann


def test_tx_length_mismatch_is_reported():
    ann = hci.annotate_tx([0x01, 0x01, 0x20, 0x08, 0x00, 0x01])
    assert "Opcode=0x2001" in ann
    assert "Length mismatch" in ann
    assert "header=8" in ann
    assert "actual=2" in ann


def test_two_line_rx_read_local_version_information_decoded():
    ctx = new_context()

    ann1, _ = hci.annotate_line(
        "[24-Jun-2026 01:20:14.152][HCI] RX: 04 0E 0C ", ctx
    )
    ann2, _ = hci.annotate_line(
        "[24-Jun-2026 01:20:14.152][HCI] RX: 01 01 10 00 0E 40 03 0E 0D 00 40 03 ", ctx
    )

    assert "waiting for 12 more byte" in ann1
    assert "Command=0x1001" in ann2
    assert "Read Local Version Information" in ann2
    assert "Status=0x00 (Success)" in ann2
    assert "HCI_Version=0x0E" in ann2
    assert "HCI_Revision=0x0340" in ann2
    assert "LMP/PAL_Version=0x0E" in ann2
    assert "Manufacturer_Name=0x000D" in ann2
    assert "LMP/PAL_Subversion=0x0340" in ann2
    assert ctx["rx_buffer"] == []


def test_three_line_rx_read_bd_addr_decoded():
    ctx = new_context()

    ann1, _ = hci.annotate_line("#2024-3-13-11-19-31-647# BT Rx   1 : 04 ", ctx)
    ann2, _ = hci.annotate_line("#2024-3-13-11-19-31-648# BT Rx   2 : 0E 0A ", ctx)
    ann3, _ = hci.annotate_line(
        "#2024-3-13-11-19-31-687# BT Rx  10 : 01 09 10 00 93 76 00 A0 11 47 ", ctx
    )

    assert "waiting for Event Code" in ann1
    assert "ParamLen=10" in ann2
    assert "waiting for 10 more byte" in ann2
    assert "Command=0x1009" in ann3
    assert "Read BD_ADDR" in ann3
    assert "BD_ADDR=47:11:A0:00:76:93" in ann3
    assert ctx["rx_buffer"] == []


def test_three_line_rx_le_test_end_decoded():
    ctx = new_context()

    hci.annotate_line("#2024-3-13-11-19-36-438# BT Rx   1 : 04 ", ctx)
    hci.annotate_line("#2024-3-13-11-19-36-439# BT Rx   2 : 0E 06 ", ctx)
    ann, _ = hci.annotate_line("#2024-3-13-11-19-36-474# BT Rx   6 : 01 1F 20 00 DA 12 ", ctx)

    assert "Command=0x201F" in ann
    assert "LE Test End" in ann
    assert "Status=0x00 (Success)" in ann
    assert "Number_Of_Packets=4826" in ann


def test_command_status_event_decoded():
    ctx = new_context()

    # Event packet: 04 0F 04 00 01 01 04
    # Event=Command Status, Status=0, Num_HCI_Command_Packets=1, Opcode=0x0401 Inquiry
    ann, _ = hci.annotate_line(
        "#2024-3-13-11-19-31-856# BT Rx   7 : 04 0F 04 00 01 01 04 ", ctx
    )

    assert "Command Status Event" in ann
    assert "Status=0x00 (Success)" in ann
    assert "Command=0x0401" in ann
    assert "Inquiry" in ann


def test_read_local_name_decoded_from_command_complete():
    ctx = new_context()

    # 04 0E 0A: Command Complete, 10 bytes payload
    # 01 14 0C 00: num packets, opcode 0x0C14, status success
    # 54 45 53 54 00 00: ASCII "TEST" + NUL padding
    ann, _ = hci.annotate_line(
        "#2024-3-13-11-19-30-891# BT Rx  13 : 04 0E 0A 01 14 0C 00 54 45 53 54 00 00 ", ctx
    )

    assert "Command=0x0C14" in ann
    assert "Read Local Name" in ann
    assert "Local_Name='TEST'" in ann


def test_rx_fragment_without_pending_header_is_not_guessed():
    ctx = new_context()
    ann, _ = hci.annotate_line(
        "[24-Jun-2026 01:20:14.152][HCI] RX: 01 01 10 00 0E 40 03 ", ctx
    )

    assert "fragment without pending HCI event header" in ann
    assert "Raw=01 01 10 00 0E 40 03" in ann


def test_non_hci_line_is_ignored():
    ctx = new_context()
    ann, original = hci.annotate_line("This is not an HCI line\n", ctx)
    assert ann is None
    assert original == "This is not an HCI line\n"


def test_process_file_integration(tmp_path):
    input_file = tmp_path / "input.log"
    output_file = tmp_path / "output.log"

    input_file.write_text(
        "[24-Jun-2026 01:20:14.138][HCI] TX: 01 03 0C 00 \n"
        "[24-Jun-2026 01:20:14.152][HCI] RX: 04 0E 0C \n"
        "[24-Jun-2026 01:20:14.152][HCI] RX: 01 01 10 00 0E 40 03 0E 0D 00 40 03 \n",
        encoding="utf-8",
    )

    hci.process_file(str(input_file), str(output_file))
    out = output_file.read_text(encoding="utf-8")

    assert ">>> TX: HCI Command Packet" in out
    assert "Reset" in out
    assert ">>> RX: HCI Event Packet" in out
    assert "Read Local Version Information" in out
    assert "HCI_Revision=0x0340" in out
