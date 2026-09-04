// SPDX-License-Identifier: Apache-2.0
// Standalone host API and streamed GCM adapted from extracted device primitives (see NOTICE).
#include "batchcrypto.h"
#include "imported/aes/aes256_gcm_device.cuh"
#include "imported/p256_persistent/p256_persistent.cuh"
#include "imported/sha256/sha256_device.cuh"
#include <algorithm>
#include <array>
#include <cstring>
#include <cuda_runtime.h>
#include <mutex>
#include <new>
#include <set>
#include <vector>

namespace {
constexpr size_t MAX_WORK = 64 * 1024 * 1024;
const uint8_t ORDER[32] = {0xff, 0xff, 0xff, 0xff, 0,    0,    0,    0,    0xff, 0xff, 0xff,
                           0xff, 0xff, 0xff, 0xff, 0xff, 0xbc, 0xe6, 0xfa, 0xad, 0xa7, 0x17,
                           0x9e, 0x84, 0xf3, 0xb9, 0xca, 0xc2, 0xfc, 0x63, 0x25, 0x51};
void wipe(void *p, size_t n) {
    volatile uint8_t *b = static_cast<volatile uint8_t *>(p);
    while (n--)
        *b++ = 0;
}
void subtract_order(const uint8_t *a, uint8_t *out) {
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
        if (cudaGetDeviceCount(&count) != cudaSuccess || device < 0 || device >= count)
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
    bool ready() {
        return stream || cudaStreamCreateWithFlags(&stream, cudaStreamNonBlocking) == cudaSuccess;
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
cudaError_t copy(Workspace &w, void *dst, const void *src, size_t n, cudaMemcpyKind kind) {
    auto e = cudaMemcpyAsync(dst, src, n, kind, w.stream);
    return e == cudaSuccess ? cudaStreamSynchronize(w.stream) : e;
}
bool valid_private(const uint8_t *key) {
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
struct Meta {
    uint32_t in_offset, out_offset, aad_offset, len, aad_len;
    uint8_t nonce[12];
};
__device__ void hash_part(uint8_t y[16], const uint8_t h[16], const uint8_t *data, uint32_t len) {
    for (uint32_t offset = 0; offset < len; offset += 16) {
        for (uint32_t j = 0; j < 16 && offset + j < len; ++j)
            y[j] ^= data[offset + j];
        uint8_t product[16];
        gbc::aes::gf128_mul(y, h, product);
        for (int j = 0; j < 16; ++j)
            y[j] = product[j];
    }
}
__device__ void tag_for(const uint32_t rk[60], const uint8_t nonce[12], const uint8_t *aad,
                        uint32_t alen, const uint8_t *ct, uint32_t len, uint8_t tag[16]) {
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
__device__ void crypt(const uint32_t rk[60], const uint8_t nonce[12], const uint8_t *in,
                      uint8_t *out, uint32_t len) {
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
__global__ void aead_kernel(const uint8_t *key, const Meta *meta, const uint8_t *input,
                            const uint8_t *aad, uint8_t *output, uint8_t *status, uint32_t count,
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
__global__ void sign_kernel(const uint8_t *key, const uint8_t *digests, uint8_t *sigs,
                            uint8_t *statuses, uint32_t count) {
    uint32_t idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx >= count)
        return;
    bool ok = gbc::p256::p256_sign_persistent(sigs + idx * 64, sigs + idx * 64 + 32,
                                              digests + idx * 32, key, 0);
    statuses[idx] = ok ? BC_OK : BC_SIGN_FAILED;
}
__global__ void hash_kernel(const Meta *meta, const uint8_t *input, uint8_t *output,
                            uint8_t *statuses, uint32_t count) {
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
__global__ void public_kernel(const uint8_t *key, uint8_t *output, uint8_t *status) {
    uint32_t k[8];
    for (int i = 0; i < 8; ++i) {
        int b = (7 - i) * 4;
        k[i] = (uint32_t(key[b]) << 24) | (uint32_t(key[b + 1]) << 16) |
               (uint32_t(key[b + 2]) << 8) | key[b + 3];
    }
    uint32_t x[8], y[8], z[8], ax[8], ay[8], sx[8], sy[8];
    gbc::p256::scalar_mul_g(k, x, y, z);
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
int aead(int device, const uint8_t *key, const bc_aead_item *items, uint32_t count,
         uint8_t *statuses, bool opening, Workspace *saved = nullptr) {
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
        uint32_t len = it.input_size - (opening ? 16 : 0), olen = len + (opening ? 0 : 16);
        if (len > BC_MAX_PAYLOAD || it.aad_size > BC_MAX_AAD || (it.input_size && !it.input) ||
            (it.aad_size && !it.aad) || (olen && !it.output) || it.output_capacity < olen)
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
            std::memcpy(input.data() + meta[i].in_offset, items[i].input, items[i].input_size);
        if (items[i].aad_size)
            std::memcpy(aad.data() + meta[i].aad_offset, items[i].aad, items[i].aad_size);
    }
    DeviceGuard device_guard;
    if (!device_guard.select(device))
        return BC_CUDA;
    Workspace local;
    Workspace &w = saved ? *saved : local;
    if (!w.ready())
        return BC_CUDA;
    ClearOnExit clean{w};
    Buffer &dk = w.buffers[0], &dm = w.buffers[1], &di = w.buffers[2], &da = w.buffers[3],
           &dout = w.buffers[4], &ds = w.buffers[5];
    if (!dk.alloc(32) || !dm.alloc(meta.size() * sizeof(Meta)) || !di.alloc(ni) || !da.alloc(na) ||
        !dout.alloc(no) || !ds.alloc(count))
        return BC_CUDA;
    if (copy(w, dk.p, key, 32, cudaMemcpyHostToDevice) != cudaSuccess ||
        copy(w, dm.p, meta.data(), meta.size() * sizeof(Meta), cudaMemcpyHostToDevice) !=
            cudaSuccess ||
        (ni && copy(w, di.p, input.data(), ni, cudaMemcpyHostToDevice) != cudaSuccess) ||
        (na && copy(w, da.p, aad.data(), na, cudaMemcpyHostToDevice) != cudaSuccess))
        return BC_CUDA;
    aead_kernel<<<(count + 127) / 128, 128, 0, w.stream>>>(dk.p, (const Meta *)dm.p, di.p, da.p,
                                                           dout.p, ds.p, count, opening);
    if (cudaGetLastError() != cudaSuccess || cudaStreamSynchronize(w.stream) != cudaSuccess)
        return BC_CUDA;
    if ((no && copy(w, output.data(), dout.p, no, cudaMemcpyDeviceToHost) != cudaSuccess) ||
        copy(w, result.data(), ds.p, count, cudaMemcpyDeviceToHost) != cudaSuccess)
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
int sign(int device, const uint8_t *key, const uint8_t *digests, uint32_t count, uint8_t *sigs,
         uint8_t *statuses, Workspace *saved = nullptr) {
    if (count == 0)
        return BC_OK;
    if (device < 0 || !key || !digests || !sigs || !statuses || count > BC_MAX_BATCH)
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
    Buffer &dk = w.buffers[0], &dh = w.buffers[2], &ds = w.buffers[4], &dt = w.buffers[5];
    if (!dk.alloc(32) || !dh.alloc(reduced.size()) || !ds.alloc(out.size()) || !dt.alloc(count))
        return BC_CUDA;
    if (copy(w, dk.p, key, 32, cudaMemcpyHostToDevice) != cudaSuccess ||
        copy(w, dh.p, reduced.data(), reduced.size(), cudaMemcpyHostToDevice) != cudaSuccess ||
        cudaMemsetAsync(ds.p, 0, out.size(), w.stream) != cudaSuccess)
        return BC_CUDA;
    sign_kernel<<<(count + 31) / 32, 32, 0, w.stream>>>(dk.p, dh.p, ds.p, dt.p, count);
    if (cudaGetLastError() != cudaSuccess || cudaStreamSynchronize(w.stream) != cudaSuccess ||
        copy(w, out.data(), ds.p, out.size(), cudaMemcpyDeviceToHost) != cudaSuccess ||
        copy(w, status.data(), dt.p, count, cudaMemcpyDeviceToHost) != cudaSuccess)
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
int hash_batch(int device, const bc_hash_item *items, uint32_t count, uint8_t *digests,
               uint8_t *statuses, Workspace *saved = nullptr) {
    if (!count)
        return BC_OK;
    if (device < 0 || !items || !digests || !statuses || count > BC_MAX_BATCH)
        return BC_INVALID;
    size_t n = 0;
    std::vector<Meta> meta(count);
    for (uint32_t i = 0; i < count; ++i) {
        if (items[i].input_size > BC_MAX_PAYLOAD || (items[i].input_size && !items[i].input))
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
            std::memcpy(input.data() + meta[i].in_offset, items[i].input, items[i].input_size);
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
    if (!dm.alloc(meta.size() * sizeof(Meta)) || !di.alloc(n) || !out.alloc(output.size()) ||
        !st.alloc(count))
        return BC_CUDA;
    if (copy(w, dm.p, meta.data(), meta.size() * sizeof(Meta), cudaMemcpyHostToDevice) !=
            cudaSuccess ||
        (n && copy(w, di.p, input.data(), n, cudaMemcpyHostToDevice) != cudaSuccess))
        return BC_CUDA;
    hash_kernel<<<(count + 127) / 128, 128, 0, w.stream>>>((Meta *)dm.p, di.p, out.p, st.p, count);
    if (cudaGetLastError() != cudaSuccess || cudaStreamSynchronize(w.stream) != cudaSuccess ||
        copy(w, output.data(), out.p, output.size(), cudaMemcpyDeviceToHost) != cudaSuccess ||
        copy(w, status.data(), st.p, count, cudaMemcpyDeviceToHost) != cudaSuccess ||
        !clean.clear())
        return BC_CUDA;
    std::memcpy(digests, output.data(), output.size());
    std::memcpy(statuses, status.data(), count);
    return BC_OK;
}
int export_public(int device, const uint8_t *key, uint8_t *output, Workspace *saved = nullptr) {
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
    public_kernel<<<1, 1, 0, w.stream>>>(dk.p, out.p, st.p);
    if (cudaGetLastError() != cudaSuccess || cudaStreamSynchronize(w.stream) != cudaSuccess ||
        copy(w, &status, st.p, 1, cudaMemcpyDeviceToHost) != cudaSuccess)
        return BC_CUDA;
    if (status)
        return status;
    if (copy(w, result, out.p, 65, cudaMemcpyDeviceToHost) != cudaSuccess || !clean.clear())
        return BC_CUDA;
    std::memcpy(output, result, 65);
    return BC_OK;
}
} // namespace
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
void account(bc_context *c, int rc, uint32_t n, const uint8_t *status, bc_batch_report *r,
             uint64_t epoch) {
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
int keyed(bc_context *c, uint32_t slot, uint32_t kind, uint32_t n, uint8_t *status,
          bc_batch_report *r, F fn) {
    if (r)
        *r = {};
    if (!c || !r || slot >= BC_KEY_SLOTS)
        return BC_INVALID;
    return guarded([&]() {
        std::lock_guard<std::mutex> lock(c->mutex);
        auto &k = c->slots[slot];
        int rc = !k.loaded ? BC_KEY_MISSING : k.kind != kind ? BC_INVALID : fn(k.key, &c->work);
        account(c, rc, n, status, r, k.epoch);
        return rc;
    });
}
} // namespace
extern "C" {
const char *bc_version() { return "0.1.0-preview"; }
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
int bc_aes256gcm_seal(int d, const uint8_t *k, const bc_aead_item *i, uint32_t n, uint8_t *s) {
    try {
        return aead(d, k, i, n, s, false);
    } catch (const std::bad_alloc &) {
        return BC_MEMORY;
    } catch (...) {
        return BC_INVALID;
    }
}
int bc_aes256gcm_open(int d, const uint8_t *k, const bc_aead_item *i, uint32_t n, uint8_t *s) {
    try {
        return aead(d, k, i, n, s, true);
    } catch (const std::bad_alloc &) {
        return BC_MEMORY;
    } catch (...) {
        return BC_INVALID;
    }
}
int bc_p256_sign(int d, const uint8_t *k, const uint8_t *h, uint32_t n, uint8_t *r, uint8_t *s) {
    try {
        return sign(d, k, h, n, r, s);
    } catch (const std::bad_alloc &) {
        return BC_MEMORY;
    } catch (...) {
        return BC_INVALID;
    }
}
int bc_sha256_batch(int d, const bc_hash_item *i, uint32_t n, uint8_t *h, uint8_t *s) {
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
int bc_key_put(bc_context *c, uint32_t slot, uint32_t kind, const uint8_t *key, uint64_t expected,
               uint64_t *epoch) {
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
int bc_key_remove(bc_context *c, uint32_t slot, uint64_t expected, uint64_t *epoch) {
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
int bc_hash(bc_context *c, const bc_hash_item *i, uint32_t n, uint8_t *h, uint8_t *s,
            bc_batch_report *r) {
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
int bc_seal(bc_context *c, uint32_t slot, const bc_aead_item *i, uint32_t n, uint8_t *s,
            bc_batch_report *r) {
    return keyed(c, slot, BC_KEY_AES256, n, s, r, [&](const uint8_t *k, Workspace *w) {
        return aead(c->device, k, i, n, s, false, w);
    });
}
int bc_open(bc_context *c, uint32_t slot, const bc_aead_item *i, uint32_t n, uint8_t *s,
            bc_batch_report *r) {
    return keyed(c, slot, BC_KEY_AES256, n, s, r, [&](const uint8_t *k, Workspace *w) {
        return aead(c->device, k, i, n, s, true, w);
    });
}
int bc_sign(bc_context *c, uint32_t slot, const uint8_t *h, uint32_t n, uint8_t *out, uint8_t *s,
            bc_batch_report *r) {
    return keyed(c, slot, BC_KEY_P256, n, s, r, [&](const uint8_t *k, Workspace *w) {
        return sign(c->device, k, h, n, out, s, w);
    });
}
int bc_export_public_key(bc_context *c, uint32_t slot, uint8_t *out, uint64_t *epoch) {
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
