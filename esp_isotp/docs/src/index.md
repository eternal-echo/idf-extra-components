# ISO-TP Programming Guide

## Core Concepts

ISO-TP uses a dual processing model:

```
TX: Application → esp_isotp_send() → [First Frame] → TWAI → Network
                      ↓
    esp_isotp_poll() → [Consecutive Frames + Timeouts] → TWAI → Network

RX: Network → TWAI → ISR Callback → [Frame Processing + Reassembly]
                                           ↓
    Application ← esp_isotp_receive() ← [Complete Message]
```

**Critical:** 
- `isotp_on_can_message()` handles ALL incoming frames (SF, FF, CF, FC) in ISR context
- `isotp_poll()` handles multi-frame TX continuation and timeout detection 
- Polling every 5-10ms required only for multi-frame transmission

## Configuration

Configure via Kconfig (`idf.py menuconfig` → "Component config" → "ISO-TP Protocol Configuration"):

**Balanced configuration (recommended):**
```
CONFIG_ISO_TP_DEFAULT_BLOCK_SIZE=8      # Balance throughput vs latency
CONFIG_ISO_TP_DEFAULT_ST_MIN_US=1000    # Min gap for ESP32 processing
CONFIG_ISO_TP_DEFAULT_RESPONSE_TIMEOUT_US=100000
```

**High-throughput:**
```
CONFIG_ISO_TP_DEFAULT_BLOCK_SIZE=16     # Larger blocks reduce FC overhead
CONFIG_ISO_TP_DEFAULT_ST_MIN_US=500     # Minimum safe gap for ESP32
```

**Robust (noisy networks):**
```
CONFIG_ISO_TP_DEFAULT_BLOCK_SIZE=4      # Smaller blocks for error recovery
CONFIG_ISO_TP_DEFAULT_ST_MIN_US=2000    # Extra gap prevents congestion
CONFIG_ISO_TP_DEFAULT_RESPONSE_TIMEOUT_US=200000
```

## Usage Patterns

### Basic Echo Server
```c
while (1) {
    esp_isotp_poll(handle);
    
    uint32_t size;
    if (esp_isotp_receive(handle, buffer, sizeof(buffer), &size) == ESP_OK) {
        esp_isotp_send(handle, buffer, size);
    }
    
    vTaskDelay(pdMS_TO_TICKS(5)); // 5ms polling
}
```

### Request-Response
```c
// Send request
esp_isotp_send(handle, request, req_len);

// Wait for response with timeout
uint32_t start = xTaskGetTickCount();
while ((xTaskGetTickCount() - start) < timeout_ticks) {
    esp_isotp_poll(handle);
    
    uint32_t resp_len;
    if (esp_isotp_receive(handle, response, sizeof(response), &resp_len) == ESP_OK) {
        return ESP_OK; // Got response
    }
    
    vTaskDelay(pdMS_TO_TICKS(5));
}
return ESP_ERR_TIMEOUT;
```

### Multi-Channel (Diagnostics)
```c
// Physical addressing (0x7E0 → 0x7E8)
esp_isotp_config_t phys = {.tx_id = 0x7E8, .rx_id = 0x7E0, ...};
esp_isotp_new_transport(twai, &phys, &phys_handle);

// Functional addressing (0x7DF → 0x7E8) 
esp_isotp_config_t func = {.tx_id = 0x7E8, .rx_id = 0x7DF, ...};
esp_isotp_new_transport(twai, &func, &func_handle);

while (1) {
    esp_isotp_poll(phys_handle);
    esp_isotp_poll(func_handle);
    // Process messages from both channels
    vTaskDelay(pdMS_TO_TICKS(5));
}
```

## Troubleshooting

**Multi-frame timeout:** Poll every 5-10ms, not slower.

**ESP_ERR_NOT_FINISHED:** Wait for transmission complete before next send.

**Buffer overrun:** Check `received_size` vs buffer capacity.

**Performance issues:** 
- Use callbacks instead of polling for completion
- Size buffers for actual message requirements
- Poll at 5-10ms intervals (not faster)

## Buffer Sizing

| Use Case | TX Buffer | RX Buffer |
|----------|-----------|-----------|
| Diagnostics | 64 bytes | 2048 bytes |
| Firmware Updates | 2048 bytes | 64 bytes |
| Data Logging | 1024 bytes | 1024 bytes |

## Best Practices

1. Always check return values
2. Poll at 5-10ms intervals (not faster)
3. Use callbacks for real-time applications
4. Handle ESP_ERR_NOT_FOUND gracefully (normal when no message ready)
5. Test with maximum message sizes