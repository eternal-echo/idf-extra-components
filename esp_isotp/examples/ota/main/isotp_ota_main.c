/*
 * SPDX-FileCopyrightText: 2025 Espressif Systems (Shanghai) CO LTD
 *
 * SPDX-License-Identifier: Unlicense OR CC0-1.0
 */

#include <stdio.h>
#include <string.h>
#include <inttypes.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "esp_twai_onchip.h"
#include "esp_ota_ops.h"
#include "esp_system.h"
#include "esp_isotp.h"

static const char *TAG = "isotp_ota";

/**
 * @brief OTA Protocol definitions
 */
#define OTA_PROTOCOL_MAGIC_H    0x4F  /*!< Magic number high byte 'O' */
#define OTA_PROTOCOL_MAGIC_L    0x54  /*!< Magic number low byte 'T' */
#define OTA_PROTOCOL_HEADER_LEN 8     /*!< Protocol header length: Magic(2) + Size(4) + Reserved(2) */

/**
 * @brief OTA Protocol header structure (first packet)
 */
typedef struct __attribute__((packed))
{
    uint8_t magic_h;        /*!< Magic number high byte (0x4F) */
    uint8_t magic_l;        /*!< Magic number low byte (0x54) */
    uint32_t firmware_size; /*!< Total firmware size (little-endian) */
    uint16_t reserved;      /*!< Reserved for future use */
} ota_protocol_header_t;

/**
 * @brief OTA context structure
 */
typedef struct {
    esp_ota_handle_t ota_handle;              /*!< OTA handle for writing firmware */
    const esp_partition_t *update_partition;  /*!< Update partition pointer */
    bool ota_started;                         /*!< Flag indicating if OTA has started */
    bool first_packet;                        /*!< Flag indicating if this is the first packet */
} ota_context_t;

/**
 * @brief Global variables
 */
static esp_isotp_handle_t g_isotp_handle = NULL;  /*!< ISO-TP handle */
static twai_node_handle_t g_twai_node = NULL;     /*!< TWAI node handle */
static ota_context_t g_ota_ctx = {0};             /*!< OTA context */

/**
 * @brief Function prototypes
 */
static esp_err_t isotp_ota_init(void);

/**
 * @brief Process received OTA data
 *
 * @param[in] data Pointer to received data buffer
 * @param[in] data_size Size of received data
 *
 * @return
 *      - ESP_OK: Success
 *      - ESP_ERR_INVALID_ARG: Invalid arguments
 *      - ESP_ERR_INVALID_SIZE: Invalid data size
 *      - Other ESP error codes from OTA operations
 */
static esp_err_t process_ota_data(const uint8_t *data, size_t data_size)
{
    esp_err_t err = ESP_OK;

    if (!data || data_size == 0) {
        return ESP_ERR_INVALID_ARG;
    }

    /* First packet: initialize OTA and skip protocol header */
    if (g_ota_ctx.first_packet) {
        if (data_size < OTA_PROTOCOL_HEADER_LEN) {
            ESP_LOGE(TAG, "First packet too small");
            return ESP_ERR_INVALID_SIZE;
        }

        /* Initialize OTA on first packet */
        g_ota_ctx.update_partition = esp_ota_get_next_update_partition(NULL);
        err = esp_ota_begin(g_ota_ctx.update_partition, OTA_WITH_SEQUENTIAL_WRITES, &g_ota_ctx.ota_handle);
        if (err != ESP_OK) {
            ESP_LOGE(TAG, "OTA begin failed: %s", esp_err_to_name(err));
            return err;
        }

        g_ota_ctx.ota_started = true;
        g_ota_ctx.first_packet = false;
        ESP_LOGI(TAG, "OTA started, partition: %s", g_ota_ctx.update_partition->label);

        /* Write firmware data (skip 8-byte header) */
        err = esp_ota_write(g_ota_ctx.ota_handle, data + OTA_PROTOCOL_HEADER_LEN,
                            data_size - OTA_PROTOCOL_HEADER_LEN);
    } else {
        /* Subsequent packets: write directly */
        err = esp_ota_write(g_ota_ctx.ota_handle, data, data_size);
    }

    if (err != ESP_OK) {
        ESP_LOGE(TAG, "OTA write failed: %s", esp_err_to_name(err));
    }

    return err;
}

/**
 * @brief Complete OTA process and restart system
 *
 * @return
 *      - ESP_OK: Success
 *      - Other ESP error codes from OTA operations
 */
static esp_err_t complete_ota(void)
{
    esp_err_t err = ESP_OK;

    if (g_ota_ctx.ota_started) {
        err = esp_ota_end(g_ota_ctx.ota_handle);
        if (err == ESP_OK) {
            err = esp_ota_set_boot_partition(g_ota_ctx.update_partition);
            if (err == ESP_OK) {
                ESP_LOGI(TAG, "OTA update successful! Restarting in 3 seconds...");
                vTaskDelay(pdMS_TO_TICKS(3000));
                esp_restart();
            }
        }
        ESP_LOGE(TAG, "OTA completion failed: %s", esp_err_to_name(err));
    }

    return err;
}

/**
 * @brief Initialize ISO-TP OTA system
 *
 * Initializes TWAI node, ISO-TP transport, and OTA context.
 *
 * @return
 *      - ESP_OK: Success
 *      - ESP_ERR_NO_MEM: Memory allocation failed
 *      - Other ESP error codes from component initialization
 */
static esp_err_t isotp_ota_init(void)
{
    esp_err_t ret = ESP_OK;

    /* Initialize TWAI */
    twai_onchip_node_config_t twai_cfg = {
        .io_cfg = {
            .tx = CONFIG_EXAMPLE_TX_GPIO_NUM,
            .rx = CONFIG_EXAMPLE_RX_GPIO_NUM,
        },
        .bit_timing.bitrate = CONFIG_EXAMPLE_BITRATE,
        .tx_queue_depth = CONFIG_EXAMPLE_TWAI_TX_QUEUE_DEPTH,
        .intr_priority = 0,
    };

    ret = twai_new_node_onchip(&twai_cfg, &g_twai_node);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "TWAI node creation failed: %s", esp_err_to_name(ret));
        return ret;
    }

    /* Initialize ISO-TP */
    esp_isotp_config_t isotp_cfg = {
        .tx_id = CONFIG_EXAMPLE_ISOTP_TX_ID,
        .rx_id = CONFIG_EXAMPLE_ISOTP_RX_ID,
        .tx_buffer_size = CONFIG_EXAMPLE_ISOTP_TX_BUFFER_SIZE,
        .rx_buffer_size = CONFIG_EXAMPLE_ISOTP_RX_BUFFER_SIZE,
    };

    ret = esp_isotp_new_transport(g_twai_node, &isotp_cfg, &g_isotp_handle);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "ISO-TP transport creation failed: %s", esp_err_to_name(ret));
        return ret;
    }

    /* Initialize context fields */
    g_ota_ctx.ota_started = false;
    g_ota_ctx.first_packet = true;

    ESP_LOGI(TAG, "ISO-TP OTA initialized (TX:0x%X, RX:0x%X)", isotp_cfg.tx_id, isotp_cfg.rx_id);
    return ESP_OK;
}

/**
 * @brief Application main function
 *
 * Initializes ISO-TP OTA system and enters main processing loop.
 * Continuously polls for ISO-TP data and processes OTA firmware updates.
 */
void app_main(void)
{
    ESP_LOGI(TAG, "=== ISO-TP OTA Demo starting ===");

    const esp_partition_t *running = esp_ota_get_running_partition();
    ESP_LOGI(TAG, "Running partition: %s", running->label);

    esp_err_t ret = isotp_ota_init();
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "ISO-TP OTA initialization failed: %s", esp_err_to_name(ret));
        return;
    }

    ESP_LOGI(TAG, "ISO-TP OTA ready. Waiting for firmware data...");

    const TickType_t poll_delay = pdMS_TO_TICKS(CONFIG_EXAMPLE_OTA_POLL_DELAY_MS);
    uint8_t rx_buffer[4096];  /*!< Buffer for received data */
    uint32_t rx_size;

    /* Main loop: poll for ISO-TP data and process OTA */
    while (1) {
        /* Poll ISO-TP for incoming data */
        esp_isotp_poll(g_isotp_handle);

        /* Check for received data */
        ret = esp_isotp_receive(g_isotp_handle, rx_buffer, sizeof(rx_buffer), &rx_size);
        if (ret == ESP_OK && rx_size > 0) {
            ESP_LOGI(TAG, "Received %"PRIu32" bytes", rx_size);

            /* Process OTA data */
            ret = process_ota_data(rx_buffer, rx_size);
            if (ret != ESP_OK) {
                ESP_LOGE(TAG, "Failed to process OTA data: %s", esp_err_to_name(ret));
                if (g_ota_ctx.ota_started) {
                    complete_ota();  /* Try to complete/cleanup */
                }
                break;
            }
        } else if (ret != ESP_ERR_TIMEOUT) {
            /* Only log non-timeout errors */
            if (ret != ESP_OK) {
                ESP_LOGW(TAG, "ISO-TP receive error: %s", esp_err_to_name(ret));
            }
        }

        vTaskDelay(poll_delay);
    }

    ESP_LOGE(TAG, "Main loop exited");
}