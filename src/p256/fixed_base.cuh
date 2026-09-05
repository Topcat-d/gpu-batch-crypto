// SPDX-License-Identifier: Apache-2.0
// Fixed-base window methods using the extracted scalar field/point arithmetic.
// Public table layout follows the attributed generators in tools/.
#pragma once
#include "../imported/p256_persistent/p256_persistent.cuh"
namespace gbc::p256 {
__device__ void fixed_base_mul(const uint32_t k[8], uint32_t x[8],
                               uint32_t y[8], uint32_t z[8],
                               const uint32_t *table, uint32_t mode) {
  if (mode == 0) {
    scalar_mul_g(k, x, y, z);
    return;
  }
  set_infinity(x, y, z);
  uint32_t tx[8], ty[8], tz[8];
  if (mode == 1) {
    // Legacy "comb" table: unsigned fixed window, 255 multiples of G.
    // This format is a fixed-window table, not a transposed mathematical comb.
    for (int window = 31; window >= 0; --window) {
      for (int bit = 0; bit < 8; ++bit) {
        point_double(x, y, z, tx, ty, tz);
        copy256(x, tx);
        copy256(y, ty);
        copy256(z, tz);
      }
      uint32_t digit = (k[window / 4] >> ((window % 4) * 8)) & 255;
      if (digit) {
        const uint32_t *q = table + (digit - 1) * 16;
        point_add_mixed(x, y, z, q, q + 8, tx, ty, tz);
        copy256(x, tx);
        copy256(y, ty);
        copy256(z, tz);
      }
    }
    return;
  }
  // Signed base-256 digits. Window 32 represents the final 2^256 carry.
  // Keeping it is necessary for scalars with a high top byte, including n-1.
  int carry = 0;
  for (int window = 0; window < 33; ++window) {
    int value = carry;
    if (window < 32)
      value += (k[window / 4] >> ((window % 4) * 8)) & 255;
    int digit = value >= 128 ? value - 256 : value;
    carry = value >= 128;
    if (digit) {
      int magnitude = digit < 0 ? -digit : digit;
      const uint32_t *q = table + (window * 128 + magnitude - 1) * 16;
      uint32_t qy[8];
      copy256(qy, q + 8);
      if (digit < 0) {
        uint32_t zero[8] = {};
        mod_sub_p(qy, zero, qy);
      }
      point_add_mixed(x, y, z, q, qy, tx, ty, tz);
      copy256(x, tx);
      copy256(y, ty);
      copy256(z, tz);
    }
  }
}
} // namespace gbc::p256
