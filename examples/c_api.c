/* SPDX-License-Identifier: Apache-2.0. Compile as C, not C++. */
#include "batchcrypto.h"
#include <stdio.h>
#include <string.h>
int main(void) {
  bc_context *ctx = NULL;
  uint8_t digest[32], status = 255, key[32] = {0}, tag[16], sig[64],
                      public_key[65];
  uint64_t epoch = 0;
  const uint8_t expected[32] = {0xba, 0x78, 0x16, 0xbf, 0x8f, 0x01, 0xcf, 0xea,
                                0x41, 0x41, 0x40, 0xde, 0x5d, 0xae, 0x22, 0x23,
                                0xb0, 0x03, 0x61, 0xa3, 0x96, 0x17, 0x7a, 0x9c,
                                0xb4, 0x10, 0xff, 0x61, 0xf2, 0x00, 0x15, 0xad};
  bc_hash_item item = {(const uint8_t *)"abc", 3};
  bc_batch_report report;
  bc_aead_item empty = {0};
  empty.output = tag;
  empty.output_capacity = 16;
  int rc = bc_create(0, &ctx);
  if (rc) {
    fprintf(stderr, "create: %s\n", bc_error_string(rc));
    return 1;
  }
  if (bc_abi_version() != 1 ||
      bc_hash(ctx, &item, 1, digest, &status, &report) || status ||
      memcmp(digest, expected, 32))
    goto fail;
  if (bc_key_put(ctx, 0, BC_KEY_AES256, key, 0, &epoch) || epoch != 1 ||
      bc_seal(ctx, 0, &empty, 1, &status, &report) || status)
    goto fail;
  key[31] = 1;
  if (bc_key_put(ctx, 1, BC_KEY_P256, key, 0, &epoch) ||
      bc_export_public_key(ctx, 1, public_key, &epoch) || public_key[0] != 4 ||
      bc_sign(ctx, 1, digest, 1, sig, &status, &report) || status)
    goto fail;
  {
    uint8_t other_sig[64], other_public[65];
    uint32_t mode, selected;
    for (mode = BC_P256_COMB_W8; mode <= BC_P256_FULL_WINDOW_W8; ++mode) {
      if (bc_set_p256_backend(ctx, mode) ||
          bc_get_p256_backend(ctx, &selected) || selected != mode ||
          bc_sign(ctx, 1, digest, 1, other_sig, &status, &report) || status ||
          memcmp(sig, other_sig, 64) ||
          bc_export_public_key(ctx, 1, other_public, &epoch) ||
          memcmp(public_key, other_public, 65))
        goto fail;
    }
  }
  if (bc_key_remove(ctx, 1, 1, &epoch) || epoch != 2)
    goto fail;
  memset(sig, 0xa5, sizeof(sig));
  status = 255;
  if (bc_sign_at_epoch(ctx, 1, 1, digest, 1, sig, &status, &report) !=
          BC_KEY_CONFLICT ||
      report.submitted || report.completed || report.errors ||
      report.key_epoch != 2 || status != 255 || sig[0] != 0xa5 ||
      sig[63] != 0xa5)
    goto fail;
  if (bc_key_put(ctx, 1, BC_KEY_P256, key, 2, &epoch) || epoch != 3 ||
      bc_sign_at_epoch(ctx, 1, 3, digest, 1, sig, &status, &report) || status ||
      report.key_epoch != 3 || report.completed != 1)
    goto fail;
  bc_destroy(ctx);
  puts("C ABI: SHA-256, AES-GCM, P-256 and key lifecycle passed");
  return 0;
fail:
  bc_destroy(ctx);
  fputs("C ABI validation failed\n", stderr);
  return 1;
}
