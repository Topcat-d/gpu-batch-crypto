// SPDX-License-Identifier: Apache-2.0
#include "../kernels/crypto_kernels.cuh"
#include "../p256/tables.hpp"
#include "crypto_engine.hpp"
#include <array>
#include <set>
namespace gbc::engine {
int set_p256_backend(Workspace &w, uint32_t backend) {
  if (backend > BC_P256_FULL_WINDOW_W8)
    return BC_INVALID;
  if (backend && !w.p256_table_ready[backend - 1]) {
    size_t bytes = 0;
    const uint8_t *source = p256_table_blob(backend, bytes);
    auto &table = w.p256_tables[backend - 1];
    if (!w.ready() || !table.alloc(bytes - 32) ||
        copy(w, table.p, source + 32, bytes - 32, cudaMemcpyHostToDevice) !=
            cudaSuccess)
      return BC_CUDA;
    w.p256_table_ready[backend - 1] = true;
  }
  w.p256_backend = backend;
  return BC_OK;
}
int aead(int device, const uint8_t *key, const bc_aead_item *items,
         uint32_t count, uint8_t *statuses, bool opening, Workspace *saved) {
  if (count == 0)
    return BC_OK;
  if (device < 0 || !key || !items || !statuses || count > BC_MAX_BATCH)
    return BC_INVALID;
  std::vector<Meta> meta(count);
  size_t ni = 0, no = 0, na = 0;
  std::set<std::array<uint8_t, 12>> nonces;
  for (uint32_t i = 0; i < count; ++i) {
    auto &it = items[i];
    if (opening && it.input_size < 16)
      return BC_INVALID;
    uint32_t len = it.input_size - (opening ? 16 : 0),
             olen = len + (opening ? 0 : 16);
    if (len > BC_MAX_PAYLOAD || it.aad_size > BC_MAX_AAD ||
        (it.input_size && !it.input) || (it.aad_size && !it.aad) ||
        (olen && !it.output) || it.output_capacity < olen)
      return BC_INVALID;
    if (!opening) {
      std::array<uint8_t, 12> n;
      std::copy(it.nonce, it.nonce + 12, n.begin());
      if (!nonces.insert(n).second)
        return BC_INVALID;
    }
    meta[i] = {uint32_t(ni), uint32_t(no), uint32_t(na), len, it.aad_size, {0}};
    std::memcpy(meta[i].nonce, it.nonce, 12);
    ni += it.input_size;
    no += olen;
    na += it.aad_size;
    if (ni + no + na > MAX_WORK)
      return BC_INVALID;
  }
  HostBytes input(ni), aad(na), output(no);
  std::vector<uint8_t> result(count);
  for (uint32_t i = 0; i < count; ++i) {
    if (items[i].input_size)
      std::memcpy(input.data() + meta[i].in_offset, items[i].input,
                  items[i].input_size);
    if (items[i].aad_size)
      std::memcpy(aad.data() + meta[i].aad_offset, items[i].aad,
                  items[i].aad_size);
  }
  DeviceGuard device_guard;
  if (!device_guard.select(device))
    return BC_CUDA;
  Workspace local;
  Workspace &w = saved ? *saved : local;
  if (!w.ready())
    return BC_CUDA;
  ClearOnExit clean{w};
  Buffer &dk = w.buffers[0], &dm = w.buffers[1], &di = w.buffers[2],
         &da = w.buffers[3], &dout = w.buffers[4], &ds = w.buffers[5];
  if (!dk.alloc(32) || !dm.alloc(meta.size() * sizeof(Meta)) || !di.alloc(ni) ||
      !da.alloc(na) || !dout.alloc(no) || !ds.alloc(count))
    return BC_CUDA;
  if (copy(w, dk.p, key, 32, cudaMemcpyHostToDevice) != cudaSuccess ||
      copy(w, dm.p, meta.data(), meta.size() * sizeof(Meta),
           cudaMemcpyHostToDevice) != cudaSuccess ||
      (ni && copy(w, di.p, input.data(), ni, cudaMemcpyHostToDevice) !=
                 cudaSuccess) ||
      (na &&
       copy(w, da.p, aad.data(), na, cudaMemcpyHostToDevice) != cudaSuccess))
    return BC_CUDA;
  aead_kernel<<<(count + 127) / 128, 128, 0, w.stream>>>(
      dk.p, (const Meta *)dm.p, di.p, da.p, dout.p, ds.p, count, opening);
  if (cudaGetLastError() != cudaSuccess ||
      cudaStreamSynchronize(w.stream) != cudaSuccess)
    return BC_CUDA;
  if ((no && copy(w, output.data(), dout.p, no, cudaMemcpyDeviceToHost) !=
                 cudaSuccess) ||
      copy(w, result.data(), ds.p, count, cudaMemcpyDeviceToHost) !=
          cudaSuccess)
    return BC_CUDA;
  if (!clean.clear())
    return BC_CUDA;
  for (uint32_t i = 0; i < count; ++i) {
    uint32_t len = meta[i].len + (opening ? 0 : 16);
    if (len)
      std::memcpy(items[i].output, output.data() + meta[i].out_offset, len);
    statuses[i] = result[i];
  }
  return BC_OK;
}
int sign(int device, const uint8_t *key, const uint8_t *digests, uint32_t count,
         uint8_t *sigs, uint8_t *statuses, Workspace *saved) {
  if (count == 0)
    return BC_OK;
  if (device < 0 || !key || !digests || !sigs || !statuses ||
      count > BC_MAX_BATCH)
    return BC_INVALID;
  if (!valid_private(key))
    return BC_INVALID;
  // RFC6979 bits2octets and ECDSA reduction are equivalent modulo the order.
  HostBytes reduced(size_t(count) * 32), out(size_t(count) * 64);
  std::vector<uint8_t> status(count);
  for (uint32_t i = 0; i < count; ++i) {
    auto h = digests + i * 32;
    auto r = reduced.data() + i * 32;
    if (std::memcmp(h, ORDER, 32) >= 0)
      subtract_order(h, r);
    else
      std::memcpy(r, h, 32);
  }
  DeviceGuard device_guard;
  if (!device_guard.select(device))
    return BC_CUDA;
  Workspace local;
  Workspace &w = saved ? *saved : local;
  if (!w.ready())
    return BC_CUDA;
  ClearOnExit clean{w};
  Buffer &dk = w.buffers[0], &dh = w.buffers[2], &ds = w.buffers[4],
         &dt = w.buffers[5];
  if (!dk.alloc(32) || !dh.alloc(reduced.size()) || !ds.alloc(out.size()) ||
      !dt.alloc(count))
    return BC_CUDA;
  if (copy(w, dk.p, key, 32, cudaMemcpyHostToDevice) != cudaSuccess ||
      copy(w, dh.p, reduced.data(), reduced.size(), cudaMemcpyHostToDevice) !=
          cudaSuccess ||
      cudaMemsetAsync(ds.p, 0, out.size(), w.stream) != cudaSuccess)
    return BC_CUDA;
  sign_kernel<<<(count + 31) / 32, 32, 0, w.stream>>>(
      dk.p, dh.p, ds.p, dt.p, count, w.base_table(), w.p256_backend);
  if (cudaGetLastError() != cudaSuccess ||
      cudaStreamSynchronize(w.stream) != cudaSuccess ||
      copy(w, out.data(), ds.p, out.size(), cudaMemcpyDeviceToHost) !=
          cudaSuccess ||
      copy(w, status.data(), dt.p, count, cudaMemcpyDeviceToHost) !=
          cudaSuccess)
    return BC_CUDA;
  if (!clean.clear())
    return BC_CUDA;
  for (uint32_t i = 0; i < count; ++i) {
    auto s = out.data() + i * 64 + 32;
    uint8_t complement[32];
    int borrow = 0;
    for (int j = 31; j >= 0; --j) {
      int v = int(ORDER[j]) - s[j] - borrow;
      complement[j] = uint8_t(v);
      borrow = v < 0;
    }
    if (status[i] != BC_OK)
      std::memset(out.data() + i * 64, 0, 64);
    else if (std::memcmp(s, complement, 32) > 0)
      std::memcpy(s, complement, 32);
  }
  std::memcpy(sigs, out.data(), out.size());
  std::memcpy(statuses, status.data(), count);
  return BC_OK;
}
int hash_batch(int device, const bc_hash_item *items, uint32_t count,
               uint8_t *digests, uint8_t *statuses, Workspace *saved) {
  if (!count)
    return BC_OK;
  if (device < 0 || !items || !digests || !statuses || count > BC_MAX_BATCH)
    return BC_INVALID;
  size_t n = 0;
  std::vector<Meta> meta(count);
  for (uint32_t i = 0; i < count; ++i) {
    if (items[i].input_size > BC_MAX_PAYLOAD ||
        (items[i].input_size && !items[i].input))
      return BC_INVALID;
    meta[i] = {uint32_t(n), 0, 0, items[i].input_size, 0, {0}};
    n += items[i].input_size;
    if (n + size_t(count) * 32 > MAX_WORK)
      return BC_INVALID;
  }
  HostBytes input(n), output(size_t(count) * 32);
  std::vector<uint8_t> status(count);
  for (uint32_t i = 0; i < count; ++i)
    if (items[i].input_size)
      std::memcpy(input.data() + meta[i].in_offset, items[i].input,
                  items[i].input_size);
  DeviceGuard dg;
  if (!dg.select(device))
    return BC_CUDA;
  Workspace local;
  Workspace &w = saved ? *saved : local;
  if (!w.ready())
    return BC_CUDA;
  ClearOnExit clean{w};
  auto &dm = w.buffers[1];
  auto &di = w.buffers[2];
  auto &out = w.buffers[4];
  auto &st = w.buffers[5];
  if (!dm.alloc(meta.size() * sizeof(Meta)) || !di.alloc(n) ||
      !out.alloc(output.size()) || !st.alloc(count))
    return BC_CUDA;
  if (copy(w, dm.p, meta.data(), meta.size() * sizeof(Meta),
           cudaMemcpyHostToDevice) != cudaSuccess ||
      (n &&
       copy(w, di.p, input.data(), n, cudaMemcpyHostToDevice) != cudaSuccess))
    return BC_CUDA;
  hash_kernel<<<(count + 127) / 128, 128, 0, w.stream>>>((Meta *)dm.p, di.p,
                                                         out.p, st.p, count);
  if (cudaGetLastError() != cudaSuccess ||
      cudaStreamSynchronize(w.stream) != cudaSuccess ||
      copy(w, output.data(), out.p, output.size(), cudaMemcpyDeviceToHost) !=
          cudaSuccess ||
      copy(w, status.data(), st.p, count, cudaMemcpyDeviceToHost) !=
          cudaSuccess ||
      !clean.clear())
    return BC_CUDA;
  std::memcpy(digests, output.data(), output.size());
  std::memcpy(statuses, status.data(), count);
  return BC_OK;
}
int export_public(int device, const uint8_t *key, uint8_t *output,
                  Workspace *saved) {
  if (device < 0 || !output || !valid_private(key))
    return BC_INVALID;
  DeviceGuard dg;
  if (!dg.select(device))
    return BC_CUDA;
  Workspace local;
  Workspace &w = saved ? *saved : local;
  if (!w.ready())
    return BC_CUDA;
  ClearOnExit clean{w};
  auto &dk = w.buffers[0];
  auto &out = w.buffers[4];
  auto &st = w.buffers[5];
  uint8_t result[65], status;
  if (!dk.alloc(32) || !out.alloc(65) || !st.alloc(1) ||
      copy(w, dk.p, key, 32, cudaMemcpyHostToDevice) != cudaSuccess)
    return BC_CUDA;
  public_kernel<<<1, 1, 0, w.stream>>>(dk.p, out.p, st.p, w.base_table(),
                                       w.p256_backend);
  if (cudaGetLastError() != cudaSuccess ||
      cudaStreamSynchronize(w.stream) != cudaSuccess ||
      copy(w, &status, st.p, 1, cudaMemcpyDeviceToHost) != cudaSuccess)
    return BC_CUDA;
  if (status)
    return status;
  if (copy(w, result, out.p, 65, cudaMemcpyDeviceToHost) != cudaSuccess ||
      !clean.clear())
    return BC_CUDA;
  std::memcpy(output, result, 65);
  return BC_OK;
}
} // namespace gbc::engine
