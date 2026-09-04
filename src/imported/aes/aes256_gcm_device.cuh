// SPDX-License-Identifier: Apache-2.0
// MODIFIED 2026-09-04: standalone namespace/guard names; origin in NOTICE and EXTRACTION.json.
// SPDX-License-Identifier: Apache-2.0
// Extracted from GPU crypto AES-256-GCM device implementation.
// MODIFIED 2026-09-04: retain only GF multiplication and tag comparison;
// streamed AAD/ciphertext processing lives in batchcrypto.cu.
#pragma once
#include "aes256_ctr_device.cuh"
namespace gbc { namespace aes {
__device__
void gf128_mul(const uint8_t X[16], const uint8_t Y[16], uint8_t result[16]) {
    uint8_t Z[16] = {0};  // Initialize to zero
    uint8_t V[16];

    // Copy Y to V (we'll shift V)
    #pragma unroll
    for (int i = 0; i < 16; i++) {
        V[i] = Y[i];
    }

    // For each bit of X (128 bits total)
    for (int i = 0; i < 128; i++) {
        int byte_idx = i / 8;
        int bit_idx = 7 - (i % 8);  // MSB first

        // If bit i of X is set, Z = Z XOR V
        if (X[byte_idx] & (1 << bit_idx)) {
            #pragma unroll
            for (int j = 0; j < 16; j++) {
                Z[j] ^= V[j];
            }
        }

        // Check if LSB of V is set (need to reduce)
        bool lsb_set = V[15] & 0x01;

        // Right shift V by 1 (MSB-first representation)
        for (int j = 15; j > 0; j--) {
            V[j] = (V[j] >> 1) | ((V[j-1] & 0x01) << 7);
        }
        V[0] >>= 1;

        // If LSB was set, XOR with R = 0xE1 || 0^120
        // This is the reduction polynomial x^128 + x^7 + x^2 + x + 1
        // In MSB-first: 0xE1000000...00
        if (lsb_set) {
            V[0] ^= 0xE1;
        }
    }

    #pragma unroll
    for (int i = 0; i < 16; i++) {
        result[i] = Z[i];
    }
}
__device__
uint8_t constant_time_equal(const uint8_t* a, const uint8_t* b, uint32_t len) {
    uint8_t diff = 0;
    for (uint32_t i = 0; i < len; i++) {
        diff |= a[i] ^ b[i];
    }
    return (diff == 0) ? 1 : 0;
}
}}
