# ISO-TP OTA Example

This example demonstrates Over-The-Air (OTA) firmware updates using the ISO-TP (ISO 14229) protocol over CAN bus.

## Overview

The example creates a simple OTA receiver that:
- Listens for firmware data via ISO-TP protocol
- Writes received data to the OTA partition
- Automatically restarts with the new firmware when complete

## Hardware Requirements

- ESP32 with CAN transceiver (e.g., MCP2515, SN65HVD230)
- CAN interface on PC (e.g., CAN-USB adapter, PCAN-USB)
- OR use QEMU with virtual CAN for testing

## Configuration

Use `idf.py menuconfig` to configure:
- **TWAI GPIO pins** (TX/RX)
- **CAN bitrate** (default: 500kbps)  
- **ISO-TP CAN IDs** (default: TX=0x7E8, RX=0x7E0)
- **Buffer sizes** for ISO-TP transport

## Building and Running

1. Build and flash:
```bash
idf.py build flash monitor
```

2. The device will show current running partition and wait for OTA data

3. Send firmware using the test script:
```bash
# Install dependencies
pip install python-can can-isotp

# Send firmware (replace with your interface)
python3 pytest_isotp_ota.py vcan0 build/isotp_ota.bin
```

## Testing with QEMU

For testing without physical CAN hardware:

1. Setup virtual CAN interface:
```bash
sudo modprobe vcan
sudo ip link add dev vcan0 type vcan  
sudo ip link set up vcan0
```

2. Install Python dependencies:
```bash
pip3 install python-can can-isotp
```

3. Test ISO-TP communication:
```bash
# Test ISO-TP sending (will show FlowControl timeout - normal without receiver)
python3 test_isotp_send.py vcan0
```

**Note**: Current QEMU ESP32 version doesn't fully support CAN/TWAI emulation, so testing requires physical hardware or dedicated CAN simulation tools.

## How It Works

1. **Initialization**: Sets up TWAI controller and ISO-TP transport
2. **OTA Start**: First received packet triggers `esp_ota_begin()`
3. **Data Reception**: Each ISO-TP message is written to flash via `esp_ota_write()`
4. **OTA Complete**: When last packet received, calls `esp_ota_end()` and restarts
5. **Reboot**: Device starts with new firmware from the updated partition

## Protocol Details

- Uses standard ISO-TP protocol for reliable data transport
- Handles fragmentation automatically (>8 byte payloads)
- Detects end of transmission when packet < 4095 bytes
- Simple state machine: IDLE → RECEIVING → COMPLETE/ERROR

## Partition Layout

See `partitions.csv` for the dual OTA partition setup:
- `ota_0`: First firmware partition  
- `ota_1`: Second firmware partition
- Device alternates between partitions on updates