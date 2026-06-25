# Parse a log file, find HCI command/event bytes, and insert human-readable
# annotation lines ABOVE each HCI line.
#
# Enhanced version:
# - Handles RX events split across multiple log lines.
# - Decodes Command Complete / Command Status return parameters for common HCI commands.
# - Works with both formats shown in your examples:
#     [..][HCI] TX: 01 03 0C 00
#     #...# BT Rx  10 : 01 09 10 00 ...
#
# Run directly from VS Code. All config is at the top.

from hci_dictionary import (
    HCI_PACKET_TYPES,
    lookup_command,
    lookup_event,
    lookup_le_subevent,
    decode_opcode,
)
import re

# ============================ CONFIG (edit me) ==============================
INPUT_FILE  = r"Log_all-RELOAD_DUT_DLL=1 (w RESET_DLL - 03132024)_decrypt.txt"
OUTPUT_FILE = r"Log_all-RELOAD_DUT_DLL=1 (w RESET_DLL - 03132024)_decrypt_output.txt"
ANNOTATION_PREFIX = ">>> "
# ============================================================================

# Pattern A: "#2024-...# BT Tx|Rx N : XX XX XX ..."
PATTERN_A = re.compile(
    r"(?P<prefix>#[^#]+#\s*BT\s+(?P<dir>Tx|Rx)\s+\d+\s*:\s*)"
    r"(?P<hex>(?:[0-9A-Fa-f]{2}\s*)+)\s*$"
)

# Pattern B: "[...][HCI] TX:|RX: XX XX XX ..."
PATTERN_B = re.compile(
    r"(?P<prefix>\[[^\]]+\]\[HCI\]\s+(?P<dir>TX|RX):\s*)"
    r"(?P<hex>(?:[0-9A-Fa-f]{2}\s*)+)\s*$"
)

# A small supplement in case your dictionary does not contain every command yet.
# Opcode = OCF | (OGF << 10), shown little-endian in the logs.
EXTRA_COMMAND_NAMES = {
    0x0C01: "Set Event Mask",
    0x0C03: "Reset",
    0x0C14: "Read Local Name",
    0x1001: "Read Local Version Information",
    0x1002: "Read Local Supported Commands",
    0x1003: "Read Local Supported Features",
    0x1009: "Read BD_ADDR",
    0x2001: "LE Set Event Mask",
    0x2002: "LE Read Buffer Size",
    0x2003: "LE Read Local Supported Features",
    0x201C: "LE Read Supported States",
    0x201D: "LE Receiver Test",
    0x201E: "LE Transmitter Test",
    0x201F: "LE Test End",
    0x2034: "LE Set Extended Advertising Parameters / extended LE command depending on spec revision",
    0x2089: "LE vendor/supplemental command 0x2089 depending on controller/spec revision",
}

STATUS_NAMES = {
    0x00: "Success",
    0x01: "Unknown HCI Command",
    0x02: "Unknown Connection Identifier",
    0x03: "Hardware Failure",
    0x04: "Page Timeout",
    0x05: "Authentication Failure",
    0x06: "PIN or Key Missing",
    0x07: "Memory Capacity Exceeded",
    0x08: "Connection Timeout",
    0x0C: "Command Disallowed",
    0x12: "Invalid HCI Command Parameters",
    0x1A: "Unsupported Remote Feature / Unsupported LMP Feature",
    0x1E: "Invalid LMP Parameters / Invalid LL Parameters",
    0x20: "Unsupported LMP Parameter Value / Unsupported LL Parameter Value",
}

HCI_VERSION_NAMES = {
    0x06: "Bluetooth 4.0",
    0x07: "Bluetooth 4.1",
    0x08: "Bluetooth 4.2",
    0x09: "Bluetooth 5.0",
    0x0A: "Bluetooth 5.1",
    0x0B: "Bluetooth 5.2",
    0x0C: "Bluetooth 5.3",
    0x0D: "Bluetooth 5.4",
    0x0E: "Bluetooth 6.0",
}

# Small useful subset. Add more company IDs here if you need them.
COMPANY_IDS = {
    0x000D: "Texas Instruments Inc.",
    0x000F: "Broadcom Corporation",
    0x004C: "Apple, Inc.",
    0x0059: "Nordic Semiconductor ASA",
    0x005D: "Realtek Semiconductor Corporation",
    0x00E0: "Google",
    0x0131: "LitePoint",
    0x02E5: "Qualcomm Technologies International, Ltd. (QTIL)",
}


def parse_hex(hex_str: str) -> list[int]:
    return [int(b, 16) for b in hex_str.strip().split()]


def hex_bytes(data: list[int]) -> str:
    return " ".join(f"{b:02X}" for b in data)


def le16(data: list[int], offset: int = 0) -> int:
    return data[offset] | (data[offset + 1] << 8)


def status_text(status: int) -> str:
    return f"0x{status:02X} ({STATUS_NAMES.get(status, 'Unknown status')})"


def command_name(opcode: int) -> str:
    name = EXTRA_COMMAND_NAMES.get(opcode)
    if name:
        return name
    return lookup_command(opcode)


def version_text(v: int) -> str:
    return f"0x{v:02X}" + (f" ({HCI_VERSION_NAMES[v]})" if v in HCI_VERSION_NAMES else "")


def company_text(company_id: int) -> str:
    return f"0x{company_id:04X}" + (f" ({COMPANY_IDS[company_id]})" if company_id in COMPANY_IDS else "")


def ascii_null_terminated(data: list[int]) -> str:
    raw = bytes(data).split(b"\x00", 1)[0]
    return raw.decode("ascii", errors="replace")


def decode_command_return_params(opcode: int, ret: list[int]) -> str:
    """Decode return parameters inside Command Complete after Num_HCI_Command_Packets + Opcode."""
    if not ret:
        return "Return parameters: none"

    status = ret[0]
    parts = [f"Status={status_text(status)}"]

    if opcode == 0x1001 and len(ret) >= 9:  # Read Local Version Information
        hci_version = ret[1]
        hci_revision = le16(ret, 2)
        lmp_pal_version = ret[4]
        manufacturer = le16(ret, 5)
        lmp_pal_subversion = le16(ret, 7)
        parts += [
            f"HCI_Version={version_text(hci_version)}",
            f"HCI_Revision=0x{hci_revision:04X}",
            f"LMP/PAL_Version={version_text(lmp_pal_version)}",
            f"Manufacturer_Name={company_text(manufacturer)}",
            f"LMP/PAL_Subversion=0x{lmp_pal_subversion:04X}",
        ]

    elif opcode == 0x1002 and len(ret) >= 65:  # Read Local Supported Commands
        mask = ret[1:65]
        enabled = sum(bin(b).count("1") for b in mask)
        parts += [
            f"Supported_Commands_Mask={hex_bytes(mask)}",
            f"Enabled_Command_Bits={enabled}",
        ]

    elif opcode == 0x1003 and len(ret) >= 9:  # Read Local Supported Features
        features = ret[1:9]
        parts.append(f"LMP_Features={hex_bytes(features)}")

    elif opcode == 0x1009 and len(ret) >= 7:  # Read BD_ADDR
        # BD_ADDR is returned least-significant octet first.
        addr = ":".join(f"{b:02X}" for b in reversed(ret[1:7]))
        parts.append(f"BD_ADDR={addr}")

    elif opcode == 0x0C14 and len(ret) >= 2:  # Read Local Name
        parts.append(f"Local_Name='{ascii_null_terminated(ret[1:])}'")

    elif opcode == 0x2002 and len(ret) >= 4:  # LE Read Buffer Size
        parts += [
            f"HC_LE_ACL_Data_Packet_Length={le16(ret, 1)}",
            f"HC_Total_Num_LE_ACL_Data_Packets={ret[3]}",
        ]

    elif opcode == 0x201C and len(ret) >= 9:  # LE Read Supported States
        parts.append(f"LE_States_Mask={hex_bytes(ret[1:9])}")

    elif opcode == 0x201F and len(ret) >= 3:  # LE Test End
        parts.append(f"Number_Of_Packets={le16(ret, 1)}")

    elif len(ret) > 1:
        parts.append(f"Raw_Return_Params={hex_bytes(ret[1:])}")

    return ", ".join(parts)


def annotate_tx(data: list[int]) -> str:
    if not data:
        return "TX: empty"

    pkt_type = data[0]
    pkt_name = HCI_PACKET_TYPES.get(pkt_type, f"Unknown packet type 0x{pkt_type:02X}")

    if pkt_type == 0x01 and len(data) >= 4:  # HCI Command Packet
        opcode = le16(data, 1)
        ogf, ocf = decode_opcode(opcode)
        plen = data[3]
        params = data[4:]
        length_note = "OK" if len(params) == plen else f"Length mismatch: header={plen}, actual={len(params)}"
        extra = f", Params={hex_bytes(params)}" if params else ""
        return (
            f"TX: {pkt_name} | Opcode=0x{opcode:04X} ({command_name(opcode)}) "
            f"| OGF=0x{ogf:02X}, OCF=0x{ocf:04X} | ParamLen={plen} ({length_note}){extra}"
        )

    return f"TX: {pkt_name} | Raw={hex_bytes(data)}"


def decode_complete_event(packet: list[int]) -> str:
    """Decode a complete HCI event packet: 04 <event_code> <param_len> <params...>."""
    if len(packet) < 3:
        return f"RX: incomplete event fragment | Raw={hex_bytes(packet)}"

    pkt_type, evt, plen = packet[0], packet[1], packet[2]
    payload = packet[3:3 + plen]
    pkt_name = HCI_PACKET_TYPES.get(pkt_type, f"Unknown packet type 0x{pkt_type:02X}")
    evt_name = lookup_event(evt)
    base = f"RX: {pkt_name} | Event=0x{evt:02X} ({evt_name}) | ParamLen={plen}"

    if pkt_type != 0x04:
        return f"RX: {pkt_name} | Raw={hex_bytes(packet)}"

    # Command Complete Event:
    # payload = Num_HCI_Command_Packets, Command_Opcode LSB, Command_Opcode MSB, Return_Parameters...
    if evt == 0x0E and len(payload) >= 3:
        num_cmd_pkts = payload[0]
        opcode = le16(payload, 1)
        ogf, ocf = decode_opcode(opcode)
        ret = payload[3:]
        return (
            f"{base} | Num_HCI_Command_Packets={num_cmd_pkts} "
            f"| Command=0x{opcode:04X} ({command_name(opcode)}) "
            f"| OGF=0x{ogf:02X}, OCF=0x{ocf:04X} "
            f"| {decode_command_return_params(opcode, ret)}"
        )

    # Command Status Event:
    # payload = Status, Num_HCI_Command_Packets, Command_Opcode LSB, Command_Opcode MSB
    if evt == 0x0F and len(payload) >= 4:
        status = payload[0]
        num_cmd_pkts = payload[1]
        opcode = le16(payload, 2)
        ogf, ocf = decode_opcode(opcode)
        return (
            f"{base} | Status={status_text(status)} "
            f"| Num_HCI_Command_Packets={num_cmd_pkts} "
            f"| Command=0x{opcode:04X} ({command_name(opcode)}) "
            f"| OGF=0x{ogf:02X}, OCF=0x{ocf:04X}"
        )

    # LE Meta Event: first payload byte is the LE subevent code.
    if evt == 0x3E and len(payload) >= 1:
        sub = payload[0]
        return f"{base} | LE_SubEvent=0x{sub:02X} ({lookup_le_subevent(sub)}) | Payload={hex_bytes(payload)}"

    return f"{base} | Payload={hex_bytes(payload)}"


def annotate_rx_fragment(data: list[int], context: dict) -> str:
    """
    RX data may be split as:
      04 0E 0C
      01 01 10 00 ...

    Or even:
      04
      0E 0C
      01 01 10 00 ...

    This function accumulates fragments until a full HCI event packet is available.
    """
    if not data:
        return "RX: empty"

    # Start a new HCI event packet when we see packet type 0x04.
    if data[0] == 0x04:
        context["rx_buffer"] = data[:]
    else:
        # Continue an existing split RX event, if present.
        if context.get("rx_buffer"):
            context["rx_buffer"].extend(data)
        else:
            # Payload without a visible header. Leave it raw rather than guessing incorrectly.
            return f"RX: fragment without pending HCI event header | Raw={hex_bytes(data)}"

    buf = context["rx_buffer"]

    if len(buf) == 1:
        return "RX: HCI Event Packet fragment | waiting for Event Code and Parameter Length"

    if len(buf) == 2:
        return f"RX: HCI Event Packet fragment | Event=0x{buf[1]:02X} ({lookup_event(buf[1])}) | waiting for Parameter Length"

    event_code = buf[1]
    param_len = buf[2]
    total_len = 3 + param_len

    if len(buf) < total_len:
        return (
            f"RX: HCI Event Packet header | Event=0x{event_code:02X} ({lookup_event(event_code)}) "
            f"| ParamLen={param_len} | waiting for {total_len - len(buf)} more byte(s)"
        )

    packet = buf[:total_len]
    extra = buf[total_len:]
    annotation = decode_complete_event(packet)

    # Clear completed packet. If there are extra bytes, keep them visible in the annotation.
    context["rx_buffer"] = []
    if extra:
        annotation += f" | Extra_Trailing_Bytes={hex_bytes(extra)}"
    return annotation


def match_hci_line(line: str):
    m = PATTERN_A.match(line) or PATTERN_B.match(line)
    if not m:
        return None
    direction = m.group("dir").upper()
    data = parse_hex(m.group("hex"))
    return direction, data


def annotate_line(line: str, context: dict):
    parsed = match_hci_line(line)
    if not parsed:
        return None, line

    direction, data = parsed
    if direction == "TX":
        # A TX command starts a new transaction; clear any stale RX fragment.
        context["rx_buffer"] = []
        return annotate_tx(data), line

    if direction == "RX":
        return annotate_rx_fragment(data, context), line

    return None, line


def process_file(input_path: str, output_path: str):
    context = {"rx_buffer": []}
    written = 0
    annotated = 0

    with open(input_path, "r", encoding="utf-8", errors="replace") as fin, \
         open(output_path, "w", encoding="utf-8") as fout:
        for line in fin:
            annotation, original = annotate_line(line, context)
            if annotation:
                fout.write(f"{ANNOTATION_PREFIX}{annotation}\n")
                annotated += 1
            fout.write(original)
            written += 1

    print(f"Done. Lines written: {written}. Annotation lines added: {annotated}.")
    print(f"Output: {output_path}")


if __name__ == "__main__":
    process_file(INPUT_FILE, OUTPUT_FILE)
