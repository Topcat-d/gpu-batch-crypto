// SPDX-License-Identifier: Apache-2.0
#pragma once
#include "../engine/crypto_engine.hpp"
#include "../imported/aes/aes256_gcm_device.cuh"
#include "../imported/sha256/sha256_device.cuh"
#include "../p256/fixed_base.cuh"
namespace gbc::engine {
__device__ void hash_part(uint8_t y[16], const uint8_t h[16],
                          const uint8_t *data, uint32_t len) {
  for (uint32_t offset = 0; offset < len; offset += 16) {
    for (uint32_t j = 0; j < 16 && offset + j < len; ++j)
      y[j] ^= data[offset + j];
    uint8_t product[16];
    gbc::aes::gf128_mul(y, h, product);
    for (int j = 0; j < 16; ++j)
      y[j] = product[j];
  }
}
__device__ void tag_for(const uint32_t rk[60], const uint8_t nonce[12],
                        const uint8_t *aad, uint32_t alen, const uint8_t *ct,
                        uint32_t len, uint8_t tag[16]) {
  uint8_t h[16], zero[16] = {0}, y[16] = {0}, j0[16] = {0};
  gbc::aes::aes256_encrypt_block(rk, zero, h);
  hash_part(y, h, aad, alen);
  hash_part(y, h, ct, len);
  uint8_t lengths[16];
  uint64_t abits = uint64_t(alen) * 8, cbits = uint64_t(len) * 8;
  for (int i = 0; i < 8; ++i) {
    lengths[i] = uint8_t(abits >> (56 - 8 * i));
    lengths[i + 8] = uint8_t(cbits >> (56 - 8 * i));
  }
  hash_part(y, h, lengths, 16);
  for (int i = 0; i < 12; ++i)
    j0[i] = nonce[i];
  j0[15] = 1;
  gbc::aes::aes256_encrypt_block(rk, j0, tag);
  for (int i = 0; i < 16; ++i)
    tag[i] ^= y[i];
}
__device__ void crypt(const uint32_t rk[60], const uint8_t nonce[12],
                      const uint8_t *in, uint8_t *out, uint32_t len) {
  for (uint32_t off = 0; off < len; off += 16) {
    uint8_t ctr[16], ks[16];
    for (int j = 0; j < 12; ++j)
      ctr[j] = nonce[j];
    uint32_t n = 2 + off / 16;
    for (int j = 0; j < 4; ++j)
      ctr[12 + j] = uint8_t(n >> (24 - 8 * j));
    gbc::aes::aes256_encrypt_block(rk, ctr, ks);
    for (uint32_t j = 0; j < 16 && off + j < len; ++j)
      out[off + j] = in[off + j] ^ ks[j];
  }
}
__global__ void aead_kernel(const uint8_t *key, const Meta *meta,
                            const uint8_t *input, const uint8_t *aad,
                            uint8_t *output, uint8_t *status, uint32_t count,
                            bool opening) {
  uint32_t i = blockIdx.x * blockDim.x + threadIdx.x;
  if (i >= count)
    return;
  Meta m = meta[i];
  const uint8_t *in = input + m.in_offset;
  uint8_t *out = output + m.out_offset;
  uint32_t rk[60];
  gbc::aes::aes256_expand_key(key, rk);
  uint8_t tag[16];
  if (opening) {
    tag_for(rk, m.nonce, aad + m.aad_offset, m.aad_len, in, m.len, tag);
    if (!gbc::aes::constant_time_equal(tag, in + m.len, 16)) {
      for (uint32_t j = 0; j < m.len; ++j)
        out[j] = 0;
      status[i] = BC_AUTH_FAILED;
      return;
    }
    crypt(rk, m.nonce, in, out, m.len);
  } else {
    crypt(rk, m.nonce, in, out, m.len);
    tag_for(rk, m.nonce, aad + m.aad_offset, m.aad_len, out, m.len, tag);
    for (int j = 0; j < 16; ++j)
      out[m.len + j] = tag[j];
  }
  status[i] = BC_OK;
}
__global__ void sign_kernel(const uint8_t *key, const uint8_t *digests,
                            uint8_t *sigs, uint8_t *statuses, uint32_t count,
                            const uint32_t *table, uint32_t mode) {
  uint32_t idx = blockIdx.x * blockDim.x + threadIdx.x;
  if (idx >= count)
    return;
  bool ok = gbc::p256::p256_sign_persistent(
      sigs + idx * 64, sigs + idx * 64 + 32, digests + idx * 32, key, 0,
      nullptr, true, false, nullptr, 0, table, mode);
  statuses[idx] = ok ? BC_OK : BC_SIGN_FAILED;
}
__global__ void hash_kernel(const Meta *meta, const uint8_t *input,
                            uint8_t *output, uint8_t *statuses,
                            uint32_t count) {
  uint32_t i = blockIdx.x * blockDim.x + threadIdx.x;
  if (i >= count)
    return;
  const uint8_t *data = input + meta[i].in_offset;
  uint32_t len = meta[i].len;
  uint32_t h[8];
  for (int j = 0; j < 8; ++j)
    h[j] = gbc::hash::SHA256_IV[j];
  uint32_t off = 0;
  for (; off + 64 <= len; off += 64)
    gbc::hash::sha256_compress_block(h, data + off);
  uint8_t tail[64] = {0};
  uint32_t rem = len - off;
  for (uint32_t j = 0; j < rem; ++j)
    tail[j] = data[off + j];
  tail[rem] = 0x80;
  if (rem >= 56) {
    gbc::hash::sha256_compress_block(h, tail);
    for (int j = 0; j < 64; ++j)
      tail[j] = 0;
  }
  uint64_t bits = uint64_t(len) * 8;
  for (int j = 0; j < 8; ++j)
    tail[56 + j] = uint8_t(bits >> (56 - j * 8));
  gbc::hash::sha256_compress_block(h, tail);
  for (int j = 0; j < 8; ++j)
    gbc::hash::be32_store(output + i * 32 + j * 4, h[j]);
  statuses[i] = BC_OK;
}
__global__ void public_kernel(const uint8_t *key, uint8_t *output,
                              uint8_t *status, const uint32_t *table,
                              uint32_t mode) {
  uint32_t k[8];
  for (int i = 0; i < 8; ++i) {
    int b = (7 - i) * 4;
    k[i] = (uint32_t(key[b]) << 24) | (uint32_t(key[b + 1]) << 16) |
           (uint32_t(key[b + 2]) << 8) | key[b + 3];
  }
  uint32_t x[8], y[8], z[8], ax[8], ay[8], sx[8], sy[8];
  gbc::p256::fixed_base_mul(k, x, y, z, table, mode);
  if (!gbc::p256::jacobian_to_affine(x, y, z, ax, ay)) {
    *status = BC_SIGN_FAILED;
    return;
  }
  gbc::p256::from_mont_p(sx, ax);
  gbc::p256::from_mont_p(sy, ay);
  output[0] = 4;
  for (int i = 0; i < 8; ++i)
    for (int j = 0; j < 4; ++j) {
      output[1 + (7 - i) * 4 + j] = uint8_t(sx[i] >> (24 - 8 * j));
      output[33 + (7 - i) * 4 + j] = uint8_t(sy[i] >> (24 - 8 * j));
    }
  *status = BC_OK;
}
} // namespace gbc::engine
