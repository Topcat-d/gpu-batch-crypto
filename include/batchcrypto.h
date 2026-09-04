/* SPDX-License-Identifier: Apache-2.0 */
#ifndef BATCHCRYPTO_H
#define BATCHCRYPTO_H
#include <stdint.h>
#ifdef _WIN32
#ifdef BC_BUILD
#define BC_API __declspec(dllexport)
#else
#define BC_API __declspec(dllimport)
#endif
#else
#define BC_API __attribute__((visibility("default")))
#endif
#ifdef __cplusplus
extern "C" {
#endif
enum {
    BC_OK = 0,
    BC_INVALID = 1,
    BC_CUDA = 2,
    BC_AUTH_FAILED = 3,
    BC_SIGN_FAILED = 4,
    BC_MEMORY = 5,
    BC_KEY_MISSING = 6,
    BC_KEY_CONFLICT = 7
};
enum { BC_MAX_BATCH = 4096, BC_MAX_PAYLOAD = 1048576, BC_MAX_AAD = 65536 };
typedef struct bc_aead_item {
    const uint8_t *input; /* seal: plaintext; open: ciphertext || 16-byte tag */
    uint32_t input_size;
    const uint8_t *aad;
    uint32_t aad_size;
    uint8_t nonce[12];
    uint8_t *output;
    uint32_t output_capacity;
} bc_aead_item;
typedef struct bc_hash_item {
    const uint8_t *input;
    uint32_t input_size;
} bc_hash_item;
typedef struct bc_context bc_context;
typedef struct bc_stats {
    uint64_t calls, submitted, completed, item_errors, call_errors, reserved_device_bytes;
} bc_stats;
typedef struct bc_batch_report {
    uint32_t submitted, completed, errors;
    uint64_t key_epoch;
} bc_batch_report;
enum { BC_KEY_AES256 = 1, BC_KEY_P256 = 2, BC_KEY_SLOTS = 16 };
BC_API uint32_t bc_abi_version(void);
BC_API int bc_create(int device, bc_context **out);
/* Destroy requires callers to stop submitting work and join their threads first. */
BC_API void bc_destroy(bc_context *ctx);
BC_API int bc_get_stats(bc_context *ctx, bc_stats *out);
/* Import/replace/retire opaque key slots with compare-and-swap epochs. A fresh
 * slot has epoch 0. Every put/remove increments the epoch; removal preserves
 * a tombstone. expected_epoch must match. AES same-key replacement is rejected
 * because it is not a rotation; nonce uniqueness remains caller-owned. */
BC_API int bc_key_put(bc_context *ctx, uint32_t slot, uint32_t kind, const uint8_t key[32],
                      uint64_t expected_epoch, uint64_t *new_epoch);
BC_API int bc_key_remove(bc_context *ctx, uint32_t slot, uint64_t expected_epoch,
                         uint64_t *new_epoch);
BC_API int bc_sha256_batch(int device, const bc_hash_item *items, uint32_t count, uint8_t *digests,
                           uint8_t *statuses);
BC_API int bc_p256_public_key(int device, const uint8_t key[32], uint8_t public_key[65]);
/* Context APIs reuse a private CUDA stream and cleared device buffers. Calls
 * on one context are serialized; independent contexts can run independently.
 * Report key_epoch identifies the exact slot generation used by the batch. */
BC_API int bc_hash(bc_context *ctx, const bc_hash_item *items, uint32_t count, uint8_t *digests,
                   uint8_t *statuses, bc_batch_report *report);
BC_API int bc_seal(bc_context *ctx, uint32_t slot, const bc_aead_item *items, uint32_t count,
                   uint8_t *statuses, bc_batch_report *report);
BC_API int bc_open(bc_context *ctx, uint32_t slot, const bc_aead_item *items, uint32_t count,
                   uint8_t *statuses, bc_batch_report *report);
BC_API int bc_sign(bc_context *ctx, uint32_t slot, const uint8_t *digests, uint32_t count,
                   uint8_t *signatures, uint8_t *statuses, bc_batch_report *report);
BC_API int bc_export_public_key(bc_context *ctx, uint32_t slot, uint8_t public_key[65],
                                uint64_t *epoch);
BC_API const char *bc_version(void);
BC_API const char *bc_error_string(int status);
/* Synchronous host-buffer APIs. No input/output/status buffers may overlap.
 * Device index is explicit. Zero count succeeds without accessing other arguments.
 * On call-level error, outputs/statuses are unspecified: discard all outputs.
 * BC_OK means inspect each item status. Failed authentication zeros that item's
 * plaintext output. Each (key, nonce) MUST be unique for sealing across calls,
 * processes and restarts; the caller owns that lifecycle. No keys are generated.
 * Batch working data is limited to 64 MiB. */
BC_API int bc_aes256gcm_seal(int device, const uint8_t key[32], const bc_aead_item *items,
                             uint32_t count, uint8_t *statuses);
BC_API int bc_aes256gcm_open(int device, const uint8_t key[32], const bc_aead_item *items,
                             uint32_t count, uint8_t *statuses);
/* SHA-256 digests [count][32], private scalar BE32, raw signatures [count][64]
 * r || s, big-endian, normalized low-s. Deterministic RFC6979 nonces.
 * Verification/key generation use the Python package's standard CPU backend. */
BC_API int bc_p256_sign(int device, const uint8_t private_key[32], const uint8_t *digests,
                        uint32_t count, uint8_t *signatures, uint8_t *statuses);
#ifdef __cplusplus
}
#endif
#endif
