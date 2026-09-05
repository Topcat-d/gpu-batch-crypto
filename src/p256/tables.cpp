// SPDX-License-Identifier: Apache-2.0
// Compile the public table constants on the host; CUDA receives a device copy.
#include "tables.hpp"
#include "p256_tables.hpp"
namespace gbc::engine {
const uint8_t *p256_table_blob(uint32_t backend, size_t &bytes) {
  if (backend == 1) {
    bytes = sizeof(gbc::tables::comb_w8);
    return gbc::tables::comb_w8;
  }
  bytes = sizeof(gbc::tables::full_window_w8);
  return gbc::tables::full_window_w8;
}
} // namespace gbc::engine
