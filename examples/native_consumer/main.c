/* SPDX-License-Identifier: Apache-2.0. Minimal installed C ABI consumer. */
#include "batchcrypto.h"
#include <errno.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main(int argc, char **argv) {
  long device = 0;
  char *end = NULL;
  if (argc > 2) {
    fputs("usage: batchcrypto_consumer [device]\n", stderr);
    return 2;
  }
  if (argc == 2) {
    errno = 0;
    device = strtol(argv[1], &end, 10);
    if (errno || end == argv[1] || *end || device < 0 || device > INT_MAX) {
      fputs("device must be a nonnegative integer\n", stderr);
      return 2;
    }
  }
  if (bc_abi_version() != 1) {
    fputs("unsupported ABI version\n", stderr);
    return 1;
  }
  bc_context *ctx = NULL;
  int rc = bc_create((int)device, &ctx);
  if (rc != BC_OK) {
    fprintf(stderr, "create: %s\n", bc_error_string(rc));
    return 1;
  }
  const bc_hash_item item = {(const uint8_t *)"abc", 3};
  const uint8_t expected[32] = {0xba, 0x78, 0x16, 0xbf, 0x8f, 0x01, 0xcf, 0xea,
                                0x41, 0x41, 0x40, 0xde, 0x5d, 0xae, 0x22, 0x23,
                                0xb0, 0x03, 0x61, 0xa3, 0x96, 0x17, 0x7a, 0x9c,
                                0xb4, 0x10, 0xff, 0x61, 0xf2, 0x00, 0x15, 0xad};
  uint8_t digest[32], status = 255;
  bc_batch_report report = {0};
  rc = bc_hash(ctx, &item, 1, digest, &status, &report);
  bc_destroy(ctx);
  if (rc != BC_OK) {
    fprintf(stderr, "hash: %s\n", bc_error_string(rc));
    return 1; /* Discard every output on a call-level error. */
  }
  if (status != BC_OK || report.submitted != 1 || report.completed != 1 ||
      report.errors != 0 || memcmp(digest, expected, sizeof(expected))) {
    fputs("hash status, accounting or known-answer check failed\n", stderr);
    return 1;
  }
  printf("PASS: installed C ABI %u (%s), GPU %ld, SHA-256 known answer\n",
         bc_abi_version(), bc_version(), device);
  return 0;
}
