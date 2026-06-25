# HCI Log Parser

This project parses Bluetooth HCI log files, detects HCI TX/RX byte sequences, and inserts human-readable annotation lines into an output log file.

It is mainly intended for Bluetooth controller/DUT logs where HCI commands and events are printed as raw hexadecimal bytes. The parser can identify the command or event, decode the opcode, reconstruct split RX events, and decode useful return parameters for common HCI commands.

---

## Files

```text
hci_dictionary.py
parse_hci_log.py
test_parse_hci_log_enhanced.py
README.md
```

### `hci_dictionary.py`

Contains lookup tables and helper functions for:

- HCI packet types
- HCI event codes
- LE Meta Event subevent codes
- HCI command opcodes
- Opcode decoding into `OGF` and `OCF`

### `parse_hci_log.py`

Main script. It reads an input log file, detects HCI lines, and writes a new output file with annotation lines inserted above the original HCI lines.

### `test_parse_hci_log_enhanced.py`

Pytest unit tests for checking that the parser correctly handles TX commands, split RX events, decoded return parameters, and malformed/incomplete RX fragments.

---

## Basic usage

Edit the configuration at the top of `parse_hci_log.py`:

```python
INPUT_FILE  = r"IQTestLogger_2026_06_24_02_09_19_decrypt.txt"
OUTPUT_FILE = r"IQTestLogger_2026_06_24_02_09_19_decrypt_output.txt"
ANNOTATION_PREFIX = ">>> "
```

Then run the script:

```bash
python parse_hci_log.py
```

The script creates a new log file with annotations added above each recognized HCI TX/RX line.

Example output:

```text
>>> TX: HCI Command Packet | Opcode=0x0C03 (Reset) | OGF=0x03, OCF=0x0003 | ParamLen=0 (OK)
[24-Jun-2026 01:20:14.122][HCI] TX: 01 03 0C 00
```

---

## Supported input patterns

The parser currently supports two log formats.

---

### Pattern A: `BT Tx` / `BT Rx` format

This format looks like this:

```text
#2024-3-13-11-19-31-531# BT Tx   4 : 01 09 10 00
#2024-3-13-11-19-31-647# BT Rx   1 : 04
#2024-3-13-11-19-31-648# BT Rx   2 : 0E 0A
#2024-3-13-11-19-31-687# BT Rx  10 : 01 09 10 00 93 76 00 A0 11 47
```

Regex conceptually:

```text
#<timestamp># BT <Tx|Rx> <byte_count> : <hex bytes>
```

The byte count is used only as part of the pattern match. The parser decodes the actual hex bytes after the colon.

---

### Pattern B: `[HCI] TX` / `[HCI] RX` format

This format looks like this:

```text
[24-Jun-2026 01:20:14.122][HCI] TX: 01 03 0C 00
[24-Jun-2026 01:20:14.138][HCI] RX: 04 0E 04
[24-Jun-2026 01:20:14.138][HCI] RX: 01 03 0C 00
```

Regex conceptually:

```text
[<timestamp>][HCI] <TX|RX>: <hex bytes>
```

---

## What the parser does

For every supported HCI line, the parser:

1. Extracts the direction: `TX` or `RX`.
2. Extracts the hexadecimal byte sequence.
3. Converts the hex bytes into integers.
4. Decodes the packet depending on direction.
5. Writes an annotation line above the original log line.

---

## TX decoding

TX lines are interpreted as host-to-controller HCI command packets.

Example:

```text
[24-Jun-2026 01:20:14.122][HCI] TX: 01 03 0C 00
```

Decoded structure:

```text
01        HCI Command Packet
03 0C     Opcode, little-endian = 0x0C03
00        Parameter length = 0
```

The parser decodes:

- Packet type
- Opcode
- OGF
- OCF
- Command name
- Parameter length
- Raw parameters, if present
- Length mismatch, if the header length does not match the actual number of parameter bytes

Example annotation:

```text
>>> TX: HCI Command Packet | Opcode=0x0C03 (Reset) | OGF=0x03, OCF=0x0003 | ParamLen=0 (OK)
```

---

## RX decoding

RX lines are interpreted as controller-to-host HCI event packets.

A complete HCI event has this structure:

```text
04 <Event_Code> <Parameter_Length> <Payload...>
```

Example:

```text
04 0E 04 01 03 0C 00
```

Decoded structure:

```text
04        HCI Event Packet
0E        Command Complete Event
04        Parameter length = 4
01        Num_HCI_Command_Packets
03 0C     Completed command opcode = 0x0C03
00        Status = Success
```

---

## Split RX event reconstruction

Many logs split one HCI RX event across multiple lines. The parser keeps an internal RX buffer so it can reconstruct the full event before decoding it.

### Two-line RX split

Example:

```text
[24-Jun-2026 01:20:14.152][HCI] RX: 04 0E 0C
[24-Jun-2026 01:20:14.152][HCI] RX: 01 01 10 00 0E 40 03 0E 0D 00 40 03
```

The first line contains:

```text
04 0E 0C
```

Meaning:

```text
04        HCI Event Packet
0E        Command Complete Event
0C        Parameter length = 12 bytes
```

The second line contains the 12-byte event payload.

The parser combines both lines and decodes the full event.

---

### Three-line RX split

Example:

```text
#2024-3-13-11-19-31-647# BT Rx   1 : 04
#2024-3-13-11-19-31-648# BT Rx   2 : 0E 0A
#2024-3-13-11-19-31-687# BT Rx  10 : 01 09 10 00 93 76 00 A0 11 47
```

This is also one event:

```text
04                                HCI Event Packet
0E 0A                             Command Complete, payload length 10
01 09 10 00 93 76 00 A0 11 47     Payload
```

The parser reconstructs the event and decodes it as a `Command Complete` response for `Read BD_ADDR`.

Example annotation:

```text
>>> RX: HCI Event Packet | Event=0x0E (Command Complete Event) | ParamLen=10 | Num_HCI_Command_Packets=1 | Command=0x1009 (Read BD_ADDR) | OGF=0x04, OCF=0x0009 | Status=0x00 (Success), BD_ADDR=47:11:A0:00:76:93
```

---

## Events currently decoded

### Command Complete Event `0x0E`

The parser decodes the event header and the completed command opcode.

Structure:

```text
04 0E <len> <Num_HCI_Command_Packets> <Opcode_LSB> <Opcode_MSB> <Return_Parameters...>
```

The parser extracts:

- `Num_HCI_Command_Packets`
- Completed command opcode
- Command name
- OGF / OCF
- Status field, when present
- Decoded return parameters for selected commands

---

### Command Status Event `0x0F`

Structure:

```text
04 0F 04 <Status> <Num_HCI_Command_Packets> <Opcode_LSB> <Opcode_MSB>
```

The parser extracts:

- Status
- `Num_HCI_Command_Packets`
- Command opcode
- Command name
- OGF / OCF

---

### LE Meta Event `0x3E`

For LE Meta Events, the first payload byte is treated as the LE subevent code.

The parser extracts:

- LE subevent code
- LE subevent name, if known
- Raw payload

---

## Command return parameters currently decoded

The parser can decode return parameters for these commands:

| Opcode | Command | Decoded fields |
|---:|---|---|
| `0x1001` | Read Local Version Information | Status, HCI version, HCI revision, LMP/PAL version, manufacturer ID, LMP/PAL subversion |
| `0x1002` | Read Local Supported Commands | Status, supported commands mask, number of enabled command bits |
| `0x1003` | Read Local Supported Features | Status, LMP feature mask |
| `0x1009` | Read BD_ADDR | Status, BD_ADDR |
| `0x0C14` | Read Local Name | Status, local name as ASCII string |
| `0x2002` | LE Read Buffer Size | Status, LE ACL packet length, total number of LE ACL packets |
| `0x201C` | LE Read Supported States | Status, LE states mask |
| `0x201F` | LE Test End | Status, number of received packets |

Commands that do not have a specific decoder still get a generic annotation with raw return parameters.

---

## Example: Read Local Version Information

Input:

```text
[24-Jun-2026 01:20:14.152][HCI] RX: 04 0E 0C
[24-Jun-2026 01:20:14.152][HCI] RX: 01 01 10 00 0E 40 03 0E 0D 00 40 03
```

Decoded full event:

```text
04 0E 0C 01 01 10 00 0E 40 03 0E 0D 00 40 03
```

Meaning:

```text
04        HCI Event Packet
0E        Command Complete Event
0C        Parameter length = 12
01        Num_HCI_Command_Packets
01 10     Opcode = 0x1001, Read Local Version Information
00        Status = Success
0E        HCI Version = Bluetooth 6.0
40 03     HCI Revision = 0x0340
0E        LMP/PAL Version = Bluetooth 6.0
0D 00     Manufacturer ID = 0x000D
40 03     LMP/PAL Subversion = 0x0340
```

Example annotation:

```text
>>> RX: HCI Event Packet | Event=0x0E (Command Complete Event) | ParamLen=12 | Num_HCI_Command_Packets=1 | Command=0x1001 (Read Local Version Information) | OGF=0x04, OCF=0x0001 | Status=0x00 (Success), HCI_Version=0x0E (Bluetooth 6.0), HCI_Revision=0x0340, LMP/PAL_Version=0x0E (Bluetooth 6.0), Manufacturer_Name=0x000D, LMP/PAL_Subversion=0x0340
```

---

## Example: Read BD_ADDR

Input:

```text
#2024-3-13-11-19-31-647# BT Rx   1 : 04
#2024-3-13-11-19-31-648# BT Rx   2 : 0E 0A
#2024-3-13-11-19-31-687# BT Rx  10 : 01 09 10 00 93 76 00 A0 11 47
```

The returned BD_ADDR bytes are little-endian in the event parameters:

```text
93 76 00 A0 11 47
```

The displayed Bluetooth address is reversed:

```text
47:11:A0:00:76:93
```

Example annotation:

```text
>>> RX: HCI Event Packet | Event=0x0E (Command Complete Event) | ParamLen=10 | Num_HCI_Command_Packets=1 | Command=0x1009 (Read BD_ADDR) | OGF=0x04, OCF=0x0009 | Status=0x00 (Success), BD_ADDR=47:11:A0:00:76:93
```

---

## Example: LE Test End

Input:

```text
#2024-3-13-11-19-36-438# BT Rx   1 : 04
#2024-3-13-11-19-36-439# BT Rx   2 : 0E 06
#2024-3-13-11-19-36-474# BT Rx   6 : 01 1F 20 00 DA 12
```

Decoded payload:

```text
01        Num_HCI_Command_Packets
1F 20     Opcode = 0x201F, LE Test End
00        Status = Success
DA 12     Number_Of_Packets = 0x12DA = 4826
```

Example annotation:

```text
>>> RX: HCI Event Packet | Event=0x0E (Command Complete Event) | ParamLen=6 | Num_HCI_Command_Packets=1 | Command=0x201F (LE Test End) | OGF=0x08, OCF=0x001F | Status=0x00 (Success), Number_Of_Packets=4826
```

---

## How incomplete RX events are handled

If the parser sees only the start of an RX event, it does not guess. It keeps the bytes in the RX buffer and reports that it is waiting for more bytes.

Example:

```text
[HCI] RX: 04 0E 0C
```

The parser knows that this event needs 12 payload bytes, so it waits for the next RX line before fully decoding it.

If the parser sees payload-like bytes without a previous event header, it reports the bytes as a fragment without a pending HCI event header.

This avoids false decoding when the log starts in the middle of an RX event.

---

## Unit testing

Run the tests with:

```bash
python -m pytest test_parse_hci_log_enhanced.py -v
```

If your parser has a different filename, set the module name explicitly.

Linux/macOS:

```bash
HCI_PARSER_MODULE=parse_hci_log_enhanced.py python -m pytest test_parse_hci_log_enhanced.py -v
```

Windows PowerShell:

```powershell
$env:HCI_PARSER_MODULE="parse_hci_log_enhanced.py"
python -m pytest test_parse_hci_log_enhanced.py -v
```

The tests check:

- Hex string parsing
- TX command decoding
- TX parameter length mismatch detection
- Two-line RX event reconstruction
- Three-line RX event reconstruction
- `Read Local Version Information` decoding
- `Read BD_ADDR` decoding
- `LE Test End` decoding
- `Command Status` event decoding
- Local name ASCII decoding
- Handling of stray RX fragments
- End-to-end file processing

---

## Adding support for a new command decoder

To add decoding for another command response:

1. Find the opcode.
2. Add the command name to `hci_dictionary.py` or to the parser's supplementary command-name dictionary.
3. Add a new branch in `decode_command_return_params()`.
4. Add a unit test using a real RX event from a log.

Recommended test style:

```python
def test_new_command_decoded():
    ctx = {"rx_buffer": []}

    ann, _ = hci.annotate_line(
        "[timestamp][HCI] RX: 04 0E ...",
        ctx,
    )

    assert "Command=0xXXXX" in ann
    assert "Expected Command Name" in ann
    assert "Expected_Field=value" in ann
```

Prefer checking important substrings instead of comparing the full annotation string. That keeps the tests stable even if the annotation wording changes slightly.

---

## Current limitations

- The parser only processes the two log formats described above.
- It decodes selected HCI command return parameters, not every command in the Bluetooth specification.
- Vendor-specific commands may only be identified generically unless a custom decoder is added.
- The parser does not currently decode every individual bit in large feature masks, such as Supported Commands or LE Supported States. It preserves those masks as hex strings.
- The parser assumes HCI event packets use the standard `04 <event_code> <length> <payload>` structure.

---

## Practical workflow

A good workflow for this parser is:

1. Run the parser on a real log.
2. Inspect unknown or raw return parameters.
3. Add a decoder for the command if the data is useful.
4. Add a unit test based on the real log line.
5. Run the test suite again.

This keeps the parser reliable while gradually increasing the amount of Bluetooth-specific information it can decode.
