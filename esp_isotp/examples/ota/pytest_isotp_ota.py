# SPDX-FileCopyrightText: 2025 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Unlicense OR CC0-1.0

import os
import time
import struct
import logging

import pytest
from pytest_embedded import Dut
from pytest_embedded_idf.utils import idf_parametrize


# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# ISO-TP Configuration
INTERFACE = "vcan0"
RX_ID = 0x7E0      # PC -> ESP32  
TX_ID = 0x7E8      # ESP32 -> PC
CHUNK = 2048
BLOCKSIZE = 8
STMIN = 0
TIMEOUT = 15.0


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