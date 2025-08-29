# ISO-TP (ISO 15765-2) — Basics

ISO-TP is a transport protocol over CAN that enables messages larger than a single CAN frame by **segmenting** at the sender and **reassembling** at the receiver. It defines four frame types and a simple flow-control mechanism so that large payloads can be exchanged reliably on both Classical CAN (8-byte frames) and CAN FD (up to 64-byte frames).

## Frame Types & PCI Layout

ISO-TP frames are identified by the **PCI (Protocol Control Information)** in byte 0 (upper nibble = type):

* **SF — Single Frame (`0x0`)**: whole message fits in one CAN frame
* **FF — First Frame (`0x1`)**: begins a multi-frame message; carries total length
* **CF — Consecutive Frame (`0x2`)**: continues a multi-frame message; carries SN
* **FC — Flow Control (`0x3`)**: receiver → sender, governs pacing (FS/BS/STmin)

| N\_PDU            | Applicability           | PCI b0\[7:4] |      PCI b0\[3:0] |            Byte 1 |         Byte 2 |         Byte 3 |        Byte 4 |       Byte 5 |
| ----------------- | ----------------------- | -----------: | ----------------: | ----------------: | -------------: | -------------: | ------------: | -----------: |
| **SF**            | Classical CAN (≤8)      |       `0000` |    `SF_DL` (0..7) |                 — |              — |              — |             — |            — |
| **SF**            | CAN FD (>8)             |       `0000` |            `0000` | `SF_DL` (8..4095) |              — |              — |             — |            — |
| **FF**            | `FF_DL ≤ 4095`          |       `0001` |     `FF_DL[11:8]` |      `FF_DL[7:0]` |              — |              — |             — |            — |
| **FF (extended)** | `FF_DL > 4095` (CAN FD) |       `0001` |            `0000` |            `0000` | `FF_DL[31:24]` | `FF_DL[23:16]` | `FF_DL[15:8]` | `FF_DL[7:0]` |
| **CF**            | segmented payload       |       `0010` | `SN` (0..F, wrap) |                 — |              — |              — |             — |            — |
| **FC**            | receiver → sender       |       `0011` |              `FS` |              `BS` |        `STmin` |              — |             — |            — |

**Fields**

* `SF_DL`: data length in SF. For CAN FD when length >7, set b0\[3:0]=0 and put length in byte 1.
* `FF_DL`: total message length in bytes (12-bit, or 32-bit extended for CAN FD).
* `SN`: CF sequence number (0..15), increments and wraps.
* `FS` (Flow Status): `0=CTS` (Clear-to-Send), `1=WT` (Wait), `2=OVFLW` (Overflow/Abort).
* `BS` (Block Size): number of CFs allowed before next FC; `0 = unlimited`.
* `STmin` (Separation Time min): `0x00..0x7F` → 0..127 **ms**; `0xF1..0xF9` → 100..900 **µs**. Other values reserved.

> **Padding**: Frames are typically padded (e.g., `0x00` or `0xCC`) to the CAN DLC. Padding bytes are ignored by ISO-TP.

## How It Works (in short)

1. **If payload ≤7 bytes (or ≤64 with CAN FD SF):** send **SF** and done.
2. **If payload >7 bytes:**

   * Sender sends **FF** with total length + first data bytes.
   * Receiver replies **FC** with `FS/BS/STmin`.
   * Sender sends **CF** frames: SN=1..F, then wrap to 0, respecting `BS` windows and `STmin`.
   * Repeat FC/CF as needed until all bytes are delivered.

## Flow Control Parameters

* **FS** controls sender behavior: CTS=continue, WT=pause, OVFLW=abort.
* **BS** limits how many CFs can be sent before another FC is required (`0` means no windowing).
* **STmin** enforces a minimum gap between **CF → CF** transmissions.

## Timers & Timeouts (N\_\*)

Implementations use well-known timers. Names below follow common practice; exact values are implementation-specific.

| Name      | Enforced by  | Applies when                                                                                                                                                                  | Typical default |
| --------- | ------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------- |
| **N\_As** | **Sender**   | Max time to **put an ISO-TP frame on the bus** (e.g., after upper layer requests a send, for SF/FF/CF). If the stack cannot transmit within N\_As (bus blocked, etc.), abort. | \~1000 ms       |
| **N\_Bs** | **Sender**   | Max time **waiting for FC** after sending an FF (or after completing a BS-sized CF block). If no FC within N\_Bs, abort.                                                      | \~1000 ms       |
| **N\_Cs** | **Sender**   | Max time between **consecutive CF transmissions** once permitted (e.g., due to pacing or scheduling). If next CF isn’t sent within N\_Cs, abort.                              | \~1000 ms       |
| **N\_Ar** | **Receiver** | Max time to **send an FC** after receiving an FF (or when a new FC is due after BS CFs). If exceeded, the sender will hit its N\_Bs and abort.                                | \~1000 ms       |
| **N\_Cr** | **Receiver** | Max time **waiting for the next CF** after sending FC(CTS) or after any CF while more data is expected. If expired, abort reception.                                          | \~1000 ms       |

> Notes
> • Use one set of timers per ISO-TP channel/connection.
> • Values above are common defaults; tune for bus speed, load, and platform scheduling.
> • STmin is **not** a timeout; it’s a pacing constraint the **sender** must respect when emitting CFs.

## Example Frames (payload shown as generic application data)

### Single Frame (SF)

```
CAN ID: 0x7E0  Data: [03 22 F1 90 00 00 00 00]
             └─ PCI=0x03 → SF with SF_DL=3; payload bytes = 22 F1 90
```

### First Frame (FF)

```
CAN ID: 0x7E8  Data: [10 0A 62 F1 90 AA BB CC]
             └─ PCI=0x10 → FF, total length = 0x000A (10 bytes),
                first 6 data bytes = 62 F1 90 AA BB CC
```

### Flow Control (FC)

```
CAN ID: 0x7E0  Data: [30 08 14 00 00 00 00 00]
             └─ PCI=0x30 → FC (FS=CTS), BS=0x08, STmin=0x14 (20 ms)
```

### Consecutive Frame (CF)

```
CAN ID: 0x7E8  Data: [21 DD EE FF 00 00 00 00]
             └─ PCI=0x21 → CF with SN=1; next data bytes (padding ignored)
```

## Communication Flows

### SF flow (fits in one frame)

* **Node A → Node B:** `[03 22 F1 90 00 00 00 00]` (SF, 3 data bytes)
* **Node B → Node A:** `[04 62 F1 90 42 00 00 00]` (SF, 4 data bytes)

### Multi-frame flow (12-byte message)

1. **A → B (FF):** `[10 0C 62 F1 B0 01 02 03]` — total length 12, first 6 bytes
2. **B → A (FC):** `[30 00 00 00 00 00 00 00]` — FS=CTS, BS=0 (unlimited), STmin=0
3. **A → B (CF #1):** `[21 04 05 06 07 08 09 CC]` — SN=1, next bytes (+ padding)
4. *(If needed)* **A → B (CF #2):** `[22 DD EE FF 00 00 00 00]` — SN=2, remaining bytes

Reassembled payload (concatenate FF+CF data):
`62 F1 B0 01 02 03 04 05 06 07 08 09` (12 bytes)

> If B needed to slow A down or limit buffering, it would set `BS>0` and/or a non-zero `STmin` in the FC.

## Worked Example (Classical CAN, DLC=8)


```text
# Step 1: Single Frame (A → B)
CAN ID: 0x7E0, Data: [03 22 F1 B3 00 00 00 00]

# Step 2: First Frame (B → A)
CAN ID: 0x7E8, Data: [10 08 62 F1 B3 15 15 16]

# Step 3: Flow Control (A → B)
CAN ID: 0x7E0, Data: [30 08 14 00 00 00 00 00]

# Step 4: Consecutive Frame #1 (B → A)
CAN ID: 0x7E8, Data: [21 51 36 36 CC CC CC CC]
```

**Why it works**

* **Step 1**: `0x03` → SF, `SF_DL=3`, payload `22 F1 B3`.
* **Step 2**: `0x10` → FF, total `0x0008` (=8 bytes), carries first 6 payload bytes.
* **Step 3**: `0x30` → FC(CTS), `BS=8`, `STmin=0x14` (20 ms).
* **Step 4**: `0x21` → CF with `SN=1`, provides remaining bytes (padding ignored).
* Reassembly yields exactly 8 bytes (= `FF_DL`).

**Timing sketch**

```
t0: A sends SF request
t0+Δ1: B replies FF
t0+Δ2: A replies FC(CTS, BS=8, STmin=20ms)
t0+Δ2+STmin: B sends CF#1
```

## Errors & Recovery

### Timeout Handling

| Timer | Condition | Action |
|-------|-----------|--------|
| **N\_As** | Cannot transmit frame within timeout | Abort transmission, notify upper layer |
| **N\_Bs** | No FC received after FF or block | Abort transmission |
| **N\_Cs** | Cannot send next CF within timeout | Abort transmission |
| **N\_Ar** | Cannot send FC within timeout | Reception fails at sender side |
| **N\_Cr** | No CF received within timeout | Abort reception |

### Error Recovery Strategies

**Sequence Number Errors:**
```
Expected SN=3, received SN=5 → Send FC(OVFLW), abort reception
Sender receives FC(OVFLW) → Abort transmission, report error
```

**Buffer Overflow:**
```
Receiver buffer full → Send FC(OVFLW) immediately
Sender continues sending → Protocol violation, connection lost
```

**Unexpected Frame Types:**
```
Expecting CF, received FF → Abort current reception, start new
Expecting FC, received SF → Process SF, continue with current transmission
```

## Protocol Compliance Notes

### Mandatory Requirements

**Sequence Number Rules:**
- Consecutive Frame sequence numbers start at 1, increment to 15, then wrap to 0
- Receiver must validate sequence continuity and abort on mismatch
- Single Frame and First Frame do not use sequence numbers

**Timing Constraints:**
- STmin enforcement: Sender must wait specified time between Consecutive Frames
- STmin encoding: 0x00-0x7F = 0-127ms, 0xF1-0xF9 = 100-900μs, others reserved
- N_* timers define maximum wait times for various protocol events

**Flow Control Behavior:**
- Block Size (BS) = 0 means unlimited Consecutive Frames without Flow Control
- BS > 0 requires Flow Control after every BS frames
- Flow Status controls sender: CTS=continue, WT=wait, OVFLW=abort

**Frame Format Requirements:**
- All frames must be padded to CAN DLC (typically 8 bytes for Classical CAN)
- Padding bytes are protocol-transparent and should be ignored
- PCI (Protocol Control Information) must be in byte 0 of CAN data field
