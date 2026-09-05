// SPDX-License-Identifier: Apache-2.0
#include "../engine/crypto_engine.hpp"
#include "batchcrypto.h"
#include <mutex>
#include <new>
using namespace gbc::engine;
struct bc_context {
  struct Slot {
    uint8_t key[32] = {0};
    uint64_t epoch = 0;
    uint32_t kind = 0;
    bool loaded = false;
    ~Slot() { wipe(key, 32); }
  };
  int device;
  std::mutex mutex;
  Workspace work;
  Slot slots[BC_KEY_SLOTS];
  bc_stats stats = {};
  explicit bc_context(int d) : device(d) {}
};
namespace {
template <class F> int guarded(F fn) {
  try {
    return fn();
  } catch (const std::bad_alloc &) {
    return BC_MEMORY;
  } catch (...) {
    return BC_INVALID;
  }
}
void account(bc_context *c, int rc, uint32_t n, const uint8_t *status,
             bc_batch_report *r, uint64_t epoch) {
  *r = {0, 0, 0, epoch};
  ++c->stats.calls;
  if (rc != BC_OK) {
    ++c->stats.call_errors;
    return;
  }
  r->submitted = n;
  r->completed = n;
  for (uint32_t i = 0; i < n; ++i)
    r->errors += status[i] != BC_OK;
  c->stats.submitted += n;
  c->stats.completed += n;
  c->stats.item_errors += r->errors;
}
template <class F>
int keyed(bc_context *c, uint32_t slot, uint32_t kind, uint32_t n,
          uint8_t *status, bc_batch_report *r, F fn) {
  if (r)
    *r = {};
  if (!c || !r || slot >= BC_KEY_SLOTS)
    return BC_INVALID;
  return guarded([&]() {
    std::lock_guard<std::mutex> lock(c->mutex);
    auto &k = c->slots[slot];
    int rc = !k.loaded        ? BC_KEY_MISSING
             : k.kind != kind ? BC_INVALID
                              : fn(k.key, &c->work);
    account(c, rc, n, status, r, k.epoch);
    return rc;
  });
}
} // namespace
extern "C" {
const char *bc_version() { return "0.2.0-preview"; }
uint32_t bc_abi_version() { return 1; }
const char *bc_error_string(int s) {
  switch (s) {
  case BC_OK:
    return "ok";
  case BC_INVALID:
    return "invalid input or batch limit";
  case BC_CUDA:
    return "CUDA operation failed";
  case BC_AUTH_FAILED:
    return "authentication failed";
  case BC_SIGN_FAILED:
    return "signing failed";
  case BC_MEMORY:
    return "host allocation failed";
  case BC_KEY_MISSING:
    return "key slot empty";
  case BC_KEY_CONFLICT:
    return "key epoch conflict or duplicate AES key";
  default:
    return "unknown status";
  }
}
int bc_aes256gcm_seal(int d, const uint8_t *k, const bc_aead_item *i,
                      uint32_t n, uint8_t *s) {
  try {
    return aead(d, k, i, n, s, false);
  } catch (const std::bad_alloc &) {
    return BC_MEMORY;
  } catch (...) {
    return BC_INVALID;
  }
}
int bc_aes256gcm_open(int d, const uint8_t *k, const bc_aead_item *i,
                      uint32_t n, uint8_t *s) {
  try {
    return aead(d, k, i, n, s, true);
  } catch (const std::bad_alloc &) {
    return BC_MEMORY;
  } catch (...) {
    return BC_INVALID;
  }
}
int bc_p256_sign(int d, const uint8_t *k, const uint8_t *h, uint32_t n,
                 uint8_t *r, uint8_t *s) {
  try {
    return sign(d, k, h, n, r, s);
  } catch (const std::bad_alloc &) {
    return BC_MEMORY;
  } catch (...) {
    return BC_INVALID;
  }
}
int bc_sha256_batch(int d, const bc_hash_item *i, uint32_t n, uint8_t *h,
                    uint8_t *s) {
  return guarded([&]() { return hash_batch(d, i, n, h, s); });
}
int bc_p256_public_key(int d, const uint8_t *k, uint8_t *out) {
  return guarded([&]() { return export_public(d, k, out); });
}
int bc_create(int device, bc_context **out) {
  if (!out)
    return BC_INVALID;
  *out = nullptr;
  if (device < 0)
    return BC_INVALID;
  return guarded([&]() {
    DeviceGuard dg;
    if (!dg.select(device))
      return int(BC_CUDA);
    auto *c = new bc_context(device);
    if (!c->work.ready()) {
      delete c;
      return int(BC_CUDA);
    }
    *out = c;
    return int(BC_OK);
  });
}
void bc_destroy(bc_context *c) {
  if (!c)
    return;
  try {
    DeviceGuard dg;
    dg.select(c->device);
    delete c;
  } catch (...) {
  }
}
int bc_get_stats(bc_context *c, bc_stats *out) {
  if (!c || !out)
    return BC_INVALID;
  return guarded([&]() {
    std::lock_guard<std::mutex> lock(c->mutex);
    *out = c->stats;
    out->reserved_device_bytes = c->work.reserved();
    return int(BC_OK);
  });
}
int bc_set_p256_backend(bc_context *c, uint32_t backend) {
  if (!c || backend > BC_P256_FULL_WINDOW_W8)
    return BC_INVALID;
  return guarded([&]() {
    std::lock_guard<std::mutex> lock(c->mutex);
    DeviceGuard dg;
    if (!dg.select(c->device))
      return int(BC_CUDA);
    return set_p256_backend(c->work, backend);
  });
}
int bc_get_p256_backend(bc_context *c, uint32_t *backend) {
  if (!c || !backend)
    return BC_INVALID;
  return guarded([&]() {
    std::lock_guard<std::mutex> lock(c->mutex);
    *backend = c->work.p256_backend;
    return int(BC_OK);
  });
}
int bc_key_put(bc_context *c, uint32_t slot, uint32_t kind, const uint8_t *key,
               uint64_t expected, uint64_t *epoch) {
  if (!c || !key || !epoch || slot >= BC_KEY_SLOTS ||
      (kind != BC_KEY_AES256 && kind != BC_KEY_P256) ||
      (kind == BC_KEY_P256 && !valid_private(key)))
    return BC_INVALID;
  return guarded([&]() {
    std::lock_guard<std::mutex> lock(c->mutex);
    auto &k = c->slots[slot];
    if (k.epoch != expected || k.epoch == UINT64_MAX)
      return int(BC_KEY_CONFLICT);
    if (kind == BC_KEY_AES256)
      for (auto &s : c->slots)
        if (s.loaded && s.kind == kind && std::memcmp(s.key, key, 32) == 0)
          return int(BC_KEY_CONFLICT);
    wipe(k.key, 32);
    std::memcpy(k.key, key, 32);
    k.kind = kind;
    k.loaded = true;
    *epoch = ++k.epoch;
    return int(BC_OK);
  });
}
int bc_key_remove(bc_context *c, uint32_t slot, uint64_t expected,
                  uint64_t *epoch) {
  if (!c || !epoch || slot >= BC_KEY_SLOTS)
    return BC_INVALID;
  return guarded([&]() {
    std::lock_guard<std::mutex> lock(c->mutex);
    auto &k = c->slots[slot];
    if (k.epoch != expected || k.epoch == UINT64_MAX)
      return int(BC_KEY_CONFLICT);
    if (!k.loaded)
      return int(BC_KEY_MISSING);
    wipe(k.key, 32);
    k.loaded = false;
    *epoch = ++k.epoch;
    return int(BC_OK);
  });
}
int bc_hash(bc_context *c, const bc_hash_item *i, uint32_t n, uint8_t *h,
            uint8_t *s, bc_batch_report *r) {
  if (r)
    *r = {};
  if (!c || !r)
    return BC_INVALID;
  return guarded([&]() {
    std::lock_guard<std::mutex> lock(c->mutex);
    int rc = hash_batch(c->device, i, n, h, s, &c->work);
    account(c, rc, n, s, r, 0);
    return rc;
  });
}
int bc_seal(bc_context *c, uint32_t slot, const bc_aead_item *i, uint32_t n,
            uint8_t *s, bc_batch_report *r) {
  return keyed(c, slot, BC_KEY_AES256, n, s, r,
               [&](const uint8_t *k, Workspace *w) {
                 return aead(c->device, k, i, n, s, false, w);
               });
}
int bc_open(bc_context *c, uint32_t slot, const bc_aead_item *i, uint32_t n,
            uint8_t *s, bc_batch_report *r) {
  return keyed(c, slot, BC_KEY_AES256, n, s, r,
               [&](const uint8_t *k, Workspace *w) {
                 return aead(c->device, k, i, n, s, true, w);
               });
}
int bc_sign(bc_context *c, uint32_t slot, const uint8_t *h, uint32_t n,
            uint8_t *out, uint8_t *s, bc_batch_report *r) {
  return keyed(c, slot, BC_KEY_P256, n, s, r,
               [&](const uint8_t *k, Workspace *w) {
                 return sign(c->device, k, h, n, out, s, w);
               });
}
int bc_export_public_key(bc_context *c, uint32_t slot, uint8_t *out,
                         uint64_t *epoch) {
  if (!c || !out || !epoch || slot >= BC_KEY_SLOTS)
    return BC_INVALID;
  return guarded([&]() {
    std::lock_guard<std::mutex> lock(c->mutex);
    auto &k = c->slots[slot];
    if (!k.loaded)
      return int(BC_KEY_MISSING);
    if (k.kind != BC_KEY_P256)
      return int(BC_INVALID);
    int rc = export_public(c->device, k.key, out, &c->work);
    if (!rc)
      *epoch = k.epoch;
    return rc;
  });
}
}
