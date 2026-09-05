// SPDX-License-Identifier: Apache-2.0
#pragma once
#include "runtime.hpp"
namespace gbc::engine {
struct Meta {
  uint32_t in_offset, out_offset, aad_offset, len, aad_len;
  uint8_t nonce[12];
};

int aead(int device, const uint8_t *key, const bc_aead_item *items,
         uint32_t count, uint8_t *statuses, bool opening,
         Workspace *saved = nullptr);
int sign(int device, const uint8_t *key, const uint8_t *digests, uint32_t count,
         uint8_t *sigs, uint8_t *statuses, Workspace *saved = nullptr);
int hash_batch(int device, const bc_hash_item *items, uint32_t count,
               uint8_t *digests, uint8_t *statuses, Workspace *saved = nullptr);
int export_public(int device, const uint8_t *key, uint8_t *output,
                  Workspace *saved = nullptr);
int set_p256_backend(Workspace &work, uint32_t backend);
} // namespace gbc::engine
