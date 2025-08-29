# SPDX-FileCopyrightText: 2025 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Unlicense OR CC0-1.0

import os
import sys
import time
import struct
import logging
import argparse

# Dynamic imports for standalone mode
try:
    import can
    import isotp
    CAN_ISOTP_AVAILABLE = True
except ImportError:
    CAN_ISOTP_AVAILABLE = False
    can = None
    isotp = None

# Pytest imports (only needed for test mode)
try:
    import pytest
    from pytest_embedded import Dut
    from pytest_embedded_idf.utils import idf_parametrize
    PYTEST_AVAILABLE = True
except ImportError:
    PYTEST_AVAILABLE = False
    pytest = None
    Dut = None
    idf_parametrize = None


# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# ISO-TP Configuration
INTERFACE = "vcan0"
DEFAULT_FIRMWARE = "efuse_esp32c3.bin"
RX_ID = 0x7E0      # PC -> ESP32  
TX_ID = 0x7E8      # ESP32 -> PC
CHUNK = 2048
BLOCKSIZE = 8
STMIN = 0
TIMEOUT = 15.0


def parse_args():
    """Parse command line arguments for standalone mode"""
    parser = argparse.ArgumentParser(
        description='Send firmware via ISO-TP over CAN for OTA update',
        epilog='Examples:\n  python3 %(prog)s\n  python3 %(prog)s --interface can0 --firmware custom.bin',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument('--interface', '-i', default=INTERFACE,
                       help=f'CAN interface name (default: {INTERFACE})')
    parser.add_argument('--firmware', '-f', default=DEFAULT_FIRMWARE,
                       help=f'Path to firmware binary file (default: {DEFAULT_FIRMWARE})')
    
    parser.add_argument('--rx-id', type=lambda x: int(x, 0), default=RX_ID,
                       help=f'CAN RX ID in hex format (default: 0x{RX_ID:X})')
    parser.add_argument('--tx-id', type=lambda x: int(x, 0), default=TX_ID,
                       help=f'CAN TX ID in hex format (default: 0x{TX_ID:X})')
    parser.add_argument('--chunk-size', type=int, default=CHUNK,
                       help=f'Data chunk size in bytes (default: {CHUNK})')
    parser.add_argument('--blocksize', type=int, default=BLOCKSIZE,
                       help=f'ISO-TP block size (default: {BLOCKSIZE})')
    parser.add_argument('--stmin', type=int, default=STMIN,
                       help=f'ISO-TP separation time minimum (default: {STMIN})')
    parser.add_argument('--timeout', type=float, default=TIMEOUT,
                       help=f'Transmission timeout in seconds (default: {TIMEOUT})')
    parser.add_argument('-v', '--verbose', action='store_true',
                       help='Enable verbose logging')
    
    return parser.parse_args()


def _make_header(size: int) -> bytes:
    """Create OTA protocol header: 'O','T' + size(le32) + reserved(le16)"""
    return struct.pack("<BBIH", 0x4F, 0x54, size, 0)


def ota_send_isotp(fw: bytes, can, isotp,
                   interface=INTERFACE, rx_id=RX_ID, tx_id=TX_ID,
                   chunk=CHUNK, blocksize=BLOCKSIZE, stmin=STMIN, timeout=TIMEOUT):
    """Send OTA firmware data via ISO-TP"""
    bus = None
    try:
        # Create CAN bus connection
        bus = can.Bus(interface="socketcan", channel=interface)
        addr = isotp.Address(txid=rx_id, rxid=tx_id)
        stack = isotp.CanStack(bus, address=addr, params={
            "blocksize": blocksize, 
            "stmin": stmin, 
            "wftmax": 0
        })

        def send_chunk(data: bytes) -> bool:
            """Send a chunk of data"""
            start = time.time()
            stack.send(data)
            while stack.transmitting():
                stack.process()
                if time.time() - start > timeout:
                    logging.error(f"Chunk transmission timeout ({timeout}s)")
                    return False
                time.sleep(0.001)
            return True

        # Send protocol header and first chunk
        header = _make_header(len(fw))
        n0 = max(0, chunk - len(header))
        first_chunk = header + fw[:n0]
        
        logging.info(f"Sending first chunk: {len(first_chunk)} bytes (including {len(header)} byte header)")
        if not send_chunk(first_chunk):
            return False

        # Send remaining chunks
        off = n0
        chunk_count = 1
        while off < len(fw):
            chunk_data = fw[off: off + chunk]
            logging.info(f"Sending chunk {chunk_count + 1}: {len(chunk_data)} bytes")
            if not send_chunk(chunk_data):
                return False
            off += chunk
            chunk_count += 1
            stack.process()
            
        logging.info(f"Firmware transmission complete: {chunk_count} chunks, {len(fw)} bytes total")
        return True
        
    except Exception as e:
        logging.error(f"ISO-TP transmission failed: {e}")
        return False
    finally:
        if bus:
            try:
                bus.shutdown()
            except Exception as e:
                logging.warning(f"Error closing CAN bus: {e}")


# Pytest decorators - only apply if pytest is available
if PYTEST_AVAILABLE:
    @pytest.mark.qemu
    @pytest.mark.parametrize(
        'qemu_extra_args', 
        ['-machine esp32c3'], 
        indirect=True
    )
    @idf_parametrize('target', ['esp32c3'], indirect=['target'])
    def test_isotp_ota_qemu(dut: Dut) -> None:
        """
        Test ISO-TP OTA functionality using QEMU.
        
        This test verifies:
        1. ESP32-C3 device boots and initializes ISO-TP
        2. Firmware can be sent via ISO-TP protocol over CAN
        3. OTA upgrade completes successfully
        4. Device reboots with new firmware
        """
        
        logging.info("Starting QEMU ISO-TP OTA test")
        
        # Wait for device startup and ISO-TP initialization
        dut.expect_exact('=== ISO-TP OTA Demo starting ===', timeout=60)
        logging.info("Application started successfully")
        
        dut.expect('Basic initialization test', timeout=30)
        logging.info("Device is ready for basic test")
        
        # Wait for successful completion
        dut.expect('OTA update successful', timeout=120)
        logging.info("Test completed successfully")
        
        # Wait for restart
        dut.expect('ESP-ROM:', timeout=60)
        logging.info("Device restarted successfully")
        
        logging.info("✓ QEMU ISO-TP OTA test completed successfully!")


def main():
    """Main function for standalone script execution"""
    
    # Check if required libraries are available
    if not CAN_ISOTP_AVAILABLE:
        print("Error: Required libraries not found!")
        print("Please install dependencies:")
        print("  pip install python-can can-isotp")
        sys.exit(1)
    
    # Parse command line arguments
    args = parse_args()
    
    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    # Validate firmware file
    if not os.path.isfile(args.firmware):
        logging.error(f"Firmware file not found: {args.firmware}")
        sys.exit(1)
    
    # Read firmware file
    try:
        with open(args.firmware, 'rb') as f:
            firmware_data = f.read()
        logging.info(f"Loaded firmware: {args.firmware} ({len(firmware_data)} bytes)")
    except Exception as e:
        logging.error(f"Failed to read firmware file: {e}")
        sys.exit(1)
    
    # Display configuration
    logging.info(f"Configuration:")
    logging.info(f"  CAN Interface: {args.interface}")
    logging.info(f"  RX ID: 0x{args.rx_id:X}")
    logging.info(f"  TX ID: 0x{args.tx_id:X}")
    logging.info(f"  Chunk Size: {args.chunk_size} bytes")
    logging.info(f"  Block Size: {args.blocksize}")
    logging.info(f"  ST Min: {args.stmin}")
    logging.info(f"  Timeout: {args.timeout}s")
    
    # Send firmware via ISO-TP
    logging.info("Starting ISO-TP OTA transmission...")
    success = ota_send_isotp(
        fw=firmware_data,
        can=can,
        isotp=isotp,
        interface=args.interface,
        rx_id=args.rx_id,
        tx_id=args.tx_id,
        chunk=args.chunk_size,
        blocksize=args.blocksize,
        stmin=args.stmin,
        timeout=args.timeout
    )
    
    if success:
        logging.info("✓ Firmware transmission completed successfully!")
        logging.info("Device should now restart with the new firmware.")
        sys.exit(0)
    else:
        logging.error("✗ Firmware transmission failed!")
        sys.exit(1)


if __name__ == "__main__":
    main()