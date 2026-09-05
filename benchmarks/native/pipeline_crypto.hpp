// SPDX-License-Identifier: Apache-2.0
// Shared native benchmark crypto and resource accounting.
#pragma once
#include <openssl/bn.h>
#include <openssl/core_names.h>
#include <openssl/ec.h>
#include <openssl/err.h>
#include <openssl/evp.h>
#include <openssl/params.h>
#include <openssl/x509.h>
#ifdef PIPELINE_GPU
#include "batchcrypto.h"
#endif
#ifdef _WIN32
#define NOMINMAX
#include <windows.h>

#include <mmsystem.h>
#include <psapi.h>
#else
#include <sys/resource.h>
#endif
#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cmath>
#include <condition_variable>
#include <cstdint>
#include <deque>
#include <future>
#include <iomanip>
#include <iostream>
#include <map>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

using Clock = std::chrono::steady_clock;
using Digest = std::array<unsigned char, 32>;
using Signature = std::array<unsigned char, 64>;
template <class T, void (*Free)(T *)>
using Owned = std::unique_ptr<T, decltype(Free)>;
using Key = Owned<EVP_PKEY, EVP_PKEY_free>;
using Context = Owned<EVP_PKEY_CTX, EVP_PKEY_CTX_free>;
using Number = Owned<BIGNUM, BN_clear_free>;
using Sig = Owned<ECDSA_SIG, ECDSA_SIG_free>;
double seconds(Clock::duration d) {
  return std::chrono::duration<double>(d).count();
}
void require(bool ok, const char *what) {
  if (!ok)
    throw std::runtime_error(what);
}
Number order() {
  BIGNUM *b = nullptr;
  require(
      BN_hex2bn(
          &b,
          "FFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551") >
          0,
      "order");
  return Number(b, BN_clear_free);
}
Key generate_key() {
  Key key(EVP_PKEY_Q_keygen(nullptr, nullptr, "EC", "prime256v1"),
          EVP_PKEY_free);
  require(bool(key), "key generation");
  return key;
}
Key public_only(EVP_PKEY *key) {
  unsigned char *bytes = nullptr;
  int n = i2d_PUBKEY(key, &bytes);
  require(n > 0, "public encoding");
  const unsigned char *p = bytes;
  Key result(d2i_PUBKEY(nullptr, &p, n), EVP_PKEY_free);
  OPENSSL_free(bytes);
  require(bool(result), "public import");
  return result;
}
std::array<unsigned char, 65> public_bytes(EVP_PKEY *key) {
  std::array<unsigned char, 65> out{};
  size_t n = out.size();
  require(EVP_PKEY_get_octet_string_param(key, OSSL_PKEY_PARAM_PUB_KEY,
                                          out.data(), n, &n) == 1 &&
              n == 65,
          "public key");
  return out;
}
struct Crypto {
  std::vector<Context> signers, verifiers;
  Number n = order(), half{BN_dup(n.get()), BN_clear_free};
  explicit Crypto(const std::vector<Key> &keys, const std::vector<Key> &pubs,
                  bool use_deterministic = true) {
    require(bool(half) && BN_rshift1(half.get(), half.get()) == 1,
            "half order");
    for (size_t k = 0; k < keys.size(); ++k) {
      Context s(EVP_PKEY_CTX_new_from_pkey(nullptr, keys[k].get(), nullptr),
                EVP_PKEY_CTX_free);
      Context v(EVP_PKEY_CTX_new_from_pkey(nullptr, pubs[k].get(), nullptr),
                EVP_PKEY_CTX_free);
      unsigned int deterministic = use_deterministic ? 1 : 0;
      char digest[] = "SHA256";
      OSSL_PARAM params[] = {
          OSSL_PARAM_construct_utf8_string(OSSL_SIGNATURE_PARAM_DIGEST, digest,
                                           0),
          OSSL_PARAM_construct_uint(OSSL_SIGNATURE_PARAM_NONCE_TYPE,
                                    &deterministic),
          OSSL_PARAM_construct_end()};
      require(s && EVP_PKEY_sign_init_ex(s.get(), params) == 1,
              "deterministic sign init (OpenSSL >=3.2)");
      unsigned int selected = 0;
      OSSL_PARAM check[] = {
          OSSL_PARAM_construct_uint(OSSL_SIGNATURE_PARAM_NONCE_TYPE, &selected),
          OSSL_PARAM_construct_end()};
      require(EVP_PKEY_CTX_get_params(s.get(), check) == 1 &&
                  selected == deterministic,
              "deterministic mode not selected");
      require(v && EVP_PKEY_verify_init(v.get()) == 1 &&
                  EVP_PKEY_CTX_set_signature_md(v.get(), EVP_sha256()) == 1,
              "verify init");
      signers.push_back(std::move(s));
      verifiers.push_back(std::move(v));
    }
  }
  Signature sign(size_t key, const Digest &h) {
    unsigned char der[80];
    size_t len = sizeof(der);
    require(EVP_PKEY_sign(signers[key].get(), der, &len, h.data(), h.size()) ==
                1,
            "CPU signing");
    const unsigned char *p = der;
    Sig sig(d2i_ECDSA_SIG(nullptr, &p, static_cast<long>(len)), ECDSA_SIG_free);
    require(sig && p == der + len, "signature decoding");
    const BIGNUM *r, *s;
    ECDSA_SIG_get0(sig.get(), &r, &s);
    Number low(BN_dup(s), BN_clear_free);
    require(bool(low), "signature allocation");
    if (BN_cmp(low.get(), half.get()) > 0)
      require(BN_sub(low.get(), n.get(), low.get()) == 1, "normalize");
    Signature out{};
    require(BN_bn2binpad(r, out.data(), 32) == 32 &&
                BN_bn2binpad(low.get(), out.data() + 32, 32) == 32,
            "signature encoding");
    return out;
  }
  bool verify(size_t key, const Digest &h, const Signature &raw) {
    Number r(BN_bin2bn(raw.data(), 32, nullptr), BN_clear_free);
    Number s(BN_bin2bn(raw.data() + 32, 32, nullptr), BN_clear_free);
    require(r && s, "verify allocation");
    if (BN_is_zero(r.get()) || BN_cmp(r.get(), n.get()) >= 0 ||
        BN_is_zero(s.get()) || BN_cmp(s.get(), half.get()) > 0)
      return false;
    Sig sig(ECDSA_SIG_new(), ECDSA_SIG_free);
    require(sig && ECDSA_SIG_set0(sig.get(), r.get(), s.get()) == 1,
            "verify encode");
    r.release();
    s.release();
    unsigned char der[80], *p = der;
    int len = i2d_ECDSA_SIG(sig.get(), &p);
    require(len > 0 && len <= 80, "DER encode");
    return EVP_PKEY_verify(verifiers[key].get(), der, len, h.data(),
                           h.size()) == 1;
  }
};
struct Gpu {
#ifdef PIPELINE_GPU
  bc_context *ctx = nullptr;
  struct Task {
    uint32_t key;
    const std::vector<Digest> *digests;
    std::vector<Signature> *output;
    std::promise<void> done;
  };
  bool use_owner, stopping = false;
  std::mutex mutex;
  std::condition_variable cv;
  std::deque<std::shared_ptr<Task>> pending;
  std::thread owner;
  Gpu(int device, const std::vector<Key> &keys, bool owned) : use_owner(owned) {
    require(bc_create(device, &ctx) == BC_OK, "GPU create");
    try {
      require(bc_set_p256_backend(ctx, BC_P256_FULL_WINDOW_W8) == BC_OK,
              "GPU backend");
      for (uint32_t i = 0; i < keys.size(); ++i) {
        BIGNUM *raw = nullptr;
        require(EVP_PKEY_get_bn_param(keys[i].get(), OSSL_PKEY_PARAM_PRIV_KEY,
                                      &raw) == 1,
                "private export");
        Number value(raw, BN_clear_free);
        std::array<unsigned char, 32> bytes{};
        require(BN_bn2binpad(value.get(), bytes.data(), 32) == 32,
                "private encode");
        uint64_t epoch = 0;
        int rc = bc_key_put(ctx, i, BC_KEY_P256, bytes.data(), 0, &epoch);
        OPENSSL_cleanse(bytes.data(), bytes.size());
        require(rc == BC_OK && epoch == 1, "GPU key load");
        std::array<unsigned char, 65> actual{};
        require(bc_export_public_key(ctx, i, actual.data(), &epoch) == BC_OK &&
                    epoch == 1 && actual == public_bytes(keys[i].get()),
                "GPU public key pin");
      }
      if (use_owner)
        owner = std::thread([this] {
          std::exception_ptr failure;
          for (;;) {
            std::shared_ptr<Task> task;
            {
              std::unique_lock<std::mutex> lock(mutex);
              cv.wait(lock, [this] { return stopping || !pending.empty(); });
              if (pending.empty())
                return;
              task = pending.front();
              pending.pop_front();
            }
            try {
              if (failure)
                std::rethrow_exception(failure);
              execute(task->key, *task->digests, *task->output);
              task->done.set_value();
            } catch (...) {
              failure = std::current_exception();
              task->done.set_exception(failure);
            }
          }
        });
    } catch (...) {
      bc_destroy(ctx);
      ctx = nullptr;
      throw;
    }
  }
  ~Gpu() {
    if (owner.joinable()) {
      {
        std::lock_guard<std::mutex> lock(mutex);
        stopping = true;
      }
      cv.notify_one();
      owner.join();
    }
    bc_destroy(ctx);
  }
  void sign(uint32_t key, const std::vector<Digest> &h,
            std::vector<Signature> &out) {
    if (!use_owner) {
      execute(key, h, out);
      return;
    }
    auto task = std::make_shared<Task>();
    task->key = key;
    task->digests = &h;
    task->output = &out;
    auto done = task->done.get_future();
    {
      std::lock_guard<std::mutex> lock(mutex);
      // At most one outstanding task per bounded CPU worker; warm-up is serial.
      require(!stopping && pending.size() < 64, "GPU dispatch queue bound");
      pending.push_back(task);
    }
    cv.notify_one();
    done.get();
  }
  void execute(uint32_t key, const std::vector<Digest> &h,
               std::vector<Signature> &out) {
    std::vector<uint8_t> status(h.size(), 255);
    bc_batch_report report{};
    int rc = bc_sign_at_epoch(ctx, key, 1, h[0].data(),
                              static_cast<uint32_t>(h.size()), out[0].data(),
                              status.data(), &report);
    require(rc == BC_OK && report.key_epoch == 1 &&
                report.submitted == h.size() && report.completed == h.size() &&
                !report.errors &&
                std::all_of(status.begin(), status.end(),
                            [](uint8_t s) { return s == BC_OK; }),
            "GPU batch/report");
  }
#else
  Gpu(int, const std::vector<Key> &, bool) {
    throw std::runtime_error("built without GPU support");
  }
  void sign(uint32_t, const std::vector<Digest> &, std::vector<Signature> &) {}
#endif
};
double cpu_seconds() {
#ifdef _WIN32
  FILETIME a, b, k, u;
  require(GetProcessTimes(GetCurrentProcess(), &a, &b, &k, &u) != 0,
          "CPU accounting");
  ULARGE_INTEGER x{}, y{};
  x.LowPart = k.dwLowDateTime;
  x.HighPart = k.dwHighDateTime;
  y.LowPart = u.dwLowDateTime;
  y.HighPart = u.dwHighDateTime;
  return (x.QuadPart + y.QuadPart) * 1e-7;
#else
  rusage r{};
  require(getrusage(RUSAGE_SELF, &r) == 0, "CPU accounting");
  return r.ru_utime.tv_sec + r.ru_stime.tv_sec +
         (r.ru_utime.tv_usec + r.ru_stime.tv_usec) * 1e-6;
#endif
}
uint64_t peak_rss() {
#ifdef _WIN32
  PROCESS_MEMORY_COUNTERS r{};
  require(GetProcessMemoryInfo(GetCurrentProcess(), &r, sizeof(r)) != 0,
          "memory accounting");
  return r.PeakWorkingSetSize;
#else
  rusage r{};
  require(getrusage(RUSAGE_SELF, &r) == 0, "memory accounting");
#ifdef __APPLE__
  return r.ru_maxrss;
#else
  return r.ru_maxrss * 1024ULL;
#endif
#endif
}
