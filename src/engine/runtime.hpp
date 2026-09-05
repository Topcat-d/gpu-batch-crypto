// SPDX-License-Identifier: Apache-2.0
#pragma once
#include "batchcrypto.h"
#include <algorithm>
#include <cstring>
#include <cuda_runtime.h>
#include <vector>
namespace gbc::engine {
constexpr size_t MAX_WORK = 64 * 1024 * 1024;
inline const uint8_t ORDER[32] = {
    0xff, 0xff, 0xff, 0xff, 0,    0,    0,    0,    0xff, 0xff, 0xff,
    0xff, 0xff, 0xff, 0xff, 0xff, 0xbc, 0xe6, 0xfa, 0xad, 0xa7, 0x17,
    0x9e, 0x84, 0xf3, 0xb9, 0xca, 0xc2, 0xfc, 0x63, 0x25, 0x51};
inline void wipe(void *p, size_t n) {
  volatile uint8_t *b = static_cast<volatile uint8_t *>(p);
  while (n--)
    *b++ = 0;
}
inline void subtract_order(const uint8_t *a, uint8_t *out) {
  int borrow = 0;
  for (int i = 31; i >= 0; --i) {
    int v = int(a[i]) - ORDER[i] - borrow;
    out[i] = uint8_t(v);
    borrow = v < 0;
  }
}
struct DeviceGuard {
  int previous = -1;
  bool select(int device) {
    int count = 0;
    if (cudaGetDeviceCount(&count) != cudaSuccess || device < 0 ||
        device >= count)
      return false;
    if (cudaGetDevice(&previous) != cudaSuccess)
      return false;
    return cudaSetDevice(device) == cudaSuccess;
  }
  ~DeviceGuard() {
    if (previous >= 0)
      cudaSetDevice(previous);
  }
};
struct Buffer {
  uint8_t *p = nullptr;
  size_t size = 0;
  bool alloc(size_t n) {
    n = std::max(size_t(1), n);
    if (p && n <= size)
      return true;
    if (p) {
      if (cudaMemset(p, 0, size) != cudaSuccess || cudaFree(p) != cudaSuccess)
        return false;
      p = nullptr;
      size = 0;
    }
    if (cudaMalloc((void **)&p, n) != cudaSuccess)
      return false;
    size = n;
    return true;
  }
  ~Buffer() {
    if (p) {
      cudaMemset(p, 0, size);
      cudaFree(p);
    }
  }
};
struct Workspace {
  cudaStream_t stream = nullptr;
  Buffer buffers[6];
  Buffer p256_tables[2]; // Public constants: retained, not scrubbed per batch.
  bool p256_table_ready[2] = {false, false};
  uint32_t p256_backend = BC_P256_REFERENCE;
  const uint32_t *base_table() const {
    return p256_backend ? reinterpret_cast<const uint32_t *>(
                              p256_tables[p256_backend - 1].p)
                        : nullptr;
  }
  bool ready() {
    return stream || cudaStreamCreateWithFlags(
                         &stream, cudaStreamNonBlocking) == cudaSuccess;
  }
  bool clear() {
    bool ok = true;
    for (auto &b : buffers)
      if (b.p && cudaMemsetAsync(b.p, 0, b.size, stream) != cudaSuccess)
        ok = false;
    return cudaStreamSynchronize(stream) == cudaSuccess && ok;
  }
  size_t reserved() const {
    size_t n = 0;
    for (auto &b : buffers)
      n += b.size;
    for (auto &b : p256_tables)
      n += b.size;
    return n;
  }
  ~Workspace() {
    if (stream) {
      clear();
      cudaStreamDestroy(stream);
    }
  }
};
struct ClearOnExit {
  Workspace &w;
  bool done = false;
  bool clear() {
    done = w.clear();
    return done;
  }
  ~ClearOnExit() {
    if (!done)
      w.clear();
  }
};
inline cudaError_t copy(Workspace &w, void *dst, const void *src, size_t n,
                        cudaMemcpyKind kind) {
  auto e = cudaMemcpyAsync(dst, src, n, kind, w.stream);
  return e == cudaSuccess ? cudaStreamSynchronize(w.stream) : e;
}
inline bool valid_private(const uint8_t *key) {
  if (!key)
    return false;
  uint8_t nz = 0;
  for (int i = 0; i < 32; ++i)
    nz |= key[i];
  return nz && std::memcmp(key, ORDER, 32) < 0;
}
struct HostBytes : std::vector<uint8_t> {
  using std::vector<uint8_t>::vector;
  ~HostBytes() {
    if (!empty())
      wipe(data(), size());
  }
};
} // namespace gbc::engine
