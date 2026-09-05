// SPDX-License-Identifier: Apache-2.0
// In-process signing pipeline benchmark, not a network service or key manager.
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
  explicit Crypto(const std::vector<Key> &keys, const std::vector<Key> &pubs) {
    require(bool(half) && BN_rshift1(half.get(), half.get()) == 1,
            "half order");
    for (size_t k = 0; k < keys.size(); ++k) {
      Context s(EVP_PKEY_CTX_new_from_pkey(nullptr, keys[k].get(), nullptr),
                EVP_PKEY_CTX_free);
      Context v(EVP_PKEY_CTX_new_from_pkey(nullptr, pubs[k].get(), nullptr),
                EVP_PKEY_CTX_free);
      unsigned int deterministic = 1;
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
      require(EVP_PKEY_CTX_get_params(s.get(), check) == 1 && selected == 1,
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
  std::deque<Task *> pending;
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
            Task *task;
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
    Task task{key, &h, &out, {}};
    auto done = task.done.get_future();
    {
      std::lock_guard<std::mutex> lock(mutex);
      // At most one outstanding task per bounded CPU worker; warm-up is serial.
      require(!stopping && pending.size() < 64, "GPU dispatch queue bound");
      pending.push_back(&task);
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
struct Options {
  std::string mode = "cpu";
  std::string gpu_dispatch = "caller";
  int workers = 4, keys = 1, batch = 256, minimum = 64, capacity = 8192,
      payload = 512, device = 0;
  double rate = 20000, duration = 3, wait_ms = 1, slo_ms = 10;
};
struct Request {
  uint64_t id;
  Clock::time_point arrival;
};
struct Stats {
  uint64_t verified = 0, good = 0, expired = 0, failed = 0, cpu_items = 0,
           gpu_items = 0, cpu_batches = 0, gpu_batches = 0;
  double prepare = 0, signing = 0, verify = 0, queue = 0, batch_wait = 0;
  std::vector<double> latencies;
  std::map<size_t, uint64_t> batches;
};
Digest prepare(uint64_t id, size_t key, std::vector<unsigned char> &payload) {
  // Synthetic canonical 512-byte record: domain, key id, request id,
  // deterministic body.
  const char domain[] = "gbc-pipeline-v1";
  std::copy(domain, domain + sizeof(domain) - 1, payload.begin());
  for (int j = 0; j < 8; ++j) {
    payload[16 + j] = static_cast<unsigned char>(id >> (56 - 8 * j));
    payload[24 + j] = static_cast<unsigned char>(key >> (56 - 8 * j));
  }
  Digest h{};
  unsigned int len = 0;
  require(EVP_Digest(payload.data(), payload.size(), h.data(), &len,
                     EVP_sha256(), nullptr) == 1 &&
              len == 32,
          "SHA256");
  return h;
}
double quantile(const std::vector<double> &v, double p) {
  if (v.empty())
    return 0;
  return v[static_cast<size_t>(std::ceil(p * v.size())) - 1];
}
void selftest() {
  std::vector<Key> keys, pubs;
  keys.push_back(generate_key());
  pubs.push_back(public_only(keys[0].get()));
  Crypto c(keys, pubs);
  Digest h{};
  Signature first = c.sign(0, h);
  require(c.sign(0, h) == first && c.verify(0, h, first),
          "determinism/verification");
  h[0] = 1;
  require(!c.verify(0, h, first), "wrong digest accepted");
  first.fill(0);
  require(!c.verify(0, h, first), "zero signature accepted");
  std::cout
      << "native CPU deterministic signing and negative verification passed\n";
}
int run(const Options &o) {
#ifdef _WIN32
  // Scope the Windows scheduler timer request to this process/run. Without it,
  // coarse sleep scheduling can make the load generator miss a 10-ms deadline.
  struct Timer {
    Timer() {
      require(timeBeginPeriod(1) == TIMERR_NOERROR, "1ms timer request");
    }
    ~Timer() { timeEndPeriod(1); }
  } timer;
#endif
  const uint64_t offered =
      static_cast<uint64_t>(std::round(o.rate * o.duration));
  std::vector<Key> keys, pubs;
  for (int i = 0; i < o.keys; ++i) {
    keys.push_back(generate_key());
    pubs.push_back(public_only(keys.back().get()));
  }
  std::vector<std::unique_ptr<Crypto>> crypto;
  for (int i = 0; i < o.workers; ++i)
    crypto.push_back(std::make_unique<Crypto>(keys, pubs));
  std::unique_ptr<Gpu> gpu;
  if (o.mode != "cpu")
    gpu = std::make_unique<Gpu>(o.device, keys, o.gpu_dispatch == "owner");
  // Warm-up and independent per-key CPU/GPU equality outside steady-state
  // timing.
  for (int k = 0; k < o.keys; ++k) {
    std::vector<Digest> h(o.batch);
    for (int i = 0; i < o.batch; ++i)
      h[i][0] = static_cast<unsigned char>(i);
    std::vector<Signature> sig(o.batch);
    if (gpu)
      gpu->sign(k, h, sig);
    for (int i = 0; i < o.batch; ++i) {
      auto s = crypto[0]->sign(k, h[i]);
      require(crypto[0]->verify(k, h[i], s) &&
                  (!gpu || (sig[i] == s && crypto[0]->verify(k, h[i], sig[i]))),
              "warm-up oracle");
    }
  }
  std::mutex mutex;
  std::condition_variable cv;
  std::vector<std::deque<Request>> queues(o.keys);
  std::vector<Stats> stats(o.workers);
  for (auto &s : stats)
    s.latencies.reserve(static_cast<size_t>(offered / o.workers + o.batch));
  uint64_t queued = 0, high_water = 0, rejected = 0;
  bool done = false;
  std::atomic<bool> fault{false};
  std::vector<std::thread> threads;
  Clock::time_point start;
  bool started = false;
  for (int w = 0; w < o.workers; ++w)
    threads.emplace_back([&, w] {
      auto &s = stats[w];
      auto &c = *crypto[w];
      std::vector<unsigned char> payload(o.payload, 0x61);
      std::vector<Request> batch;
      batch.reserve(o.batch);
      {
        std::unique_lock<std::mutex> lock(mutex);
        cv.wait(lock, [&] { return started; });
      }
      for (;;) {
        int key = -1;
        batch.clear();
        {
          std::unique_lock<std::mutex> lock(mutex);
          for (;;) {
            if (!queued) {
              if (done)
                return;
              cv.wait(lock);
              continue;
            }
            key = -1;
            // Oldest-key-first prevents a sparse tenant from starving behind a
            // busy key.
            for (int k = 0; k < o.keys; ++k)
              if (!queues[k].empty() &&
                  (key < 0 ||
                   queues[k].front().arrival < queues[key].front().arrival))
                key = k;
            auto &q = queues[key];
            auto now = Clock::now();
            bool ready = o.mode == "cpu" || done || fault ||
                         q.size() >= static_cast<size_t>(o.batch) ||
                         seconds(now - q.front().arrival) * 1000 >= o.wait_ms;
            if (!ready) {
              auto until =
                  q.front().arrival +
                  std::chrono::duration_cast<Clock::duration>(
                      std::chrono::duration<double, std::milli>(o.wait_ms));
              cv.wait_until(lock, until);
              continue;
            }
            while (!q.empty() && batch.size() < static_cast<size_t>(o.batch)) {
              batch.push_back(q.front());
              q.pop_front();
              --queued;
            }
            break;
          }
        }
        auto now = Clock::now();
        batch.erase(std::remove_if(batch.begin(), batch.end(),
                                   [&](const Request &r) {
                                     if (seconds(now - r.arrival) * 1000 >
                                         o.slo_ms) {
                                       ++s.expired;
                                       return true;
                                     }
                                     return false;
                                   }),
                    batch.end());
        if (batch.empty())
          continue;
        if (fault) {
          s.failed += batch.size();
          continue;
        }
        for (const auto &r : batch)
          s.queue += seconds(now - r.arrival);
        bool use_gpu = gpu && (o.mode == "gpu" ||
                               batch.size() >= static_cast<size_t>(o.minimum));
        ++s.batches[batch.size()];
        if (use_gpu) {
          s.gpu_items += batch.size();
          ++s.gpu_batches;
        } else {
          s.cpu_items += batch.size();
          ++s.cpu_batches;
        }
        try {
          auto t0 = Clock::now();
          std::vector<Digest> h;
          h.reserve(batch.size());
          for (const auto &r : batch)
            h.push_back(prepare(r.id, key, payload));
          std::vector<Signature> signatures(batch.size());
          auto t1 = Clock::now();
          if (use_gpu)
            gpu->sign(key, h, signatures);
          else
            for (size_t i = 0; i < h.size(); ++i)
              signatures[i] = c.sign(key, h[i]);
          auto t2 = Clock::now();
          // No request is completed until every signature in this batch is
          // verified.
          for (size_t i = 0; i < h.size(); ++i)
            require(c.verify(key, h[i], signatures[i]),
                    "independent verification failed");
          auto end = Clock::now();
          s.prepare += seconds(t1 - t0);
          s.signing += seconds(t2 - t1);
          s.verify += seconds(end - t2);
          for (const auto &r : batch) {
            double ms = seconds(end - r.arrival) * 1000;
            s.latencies.push_back(ms);
            ++s.verified;
            s.good += ms <= o.slo_ms;
          }
        } catch (...) {
          s.failed += batch.size();
          fault = true;
          cv.notify_all();
        }
      }
    });
  double cpu_start = cpu_seconds();
  {
    std::lock_guard<std::mutex> lock(mutex);
    start = Clock::now();
    started = true;
  }
  cv.notify_all();
  for (uint64_t id = 0; id < offered; ++id) {
    auto arrival = start + std::chrono::duration_cast<Clock::duration>(
                               std::chrono::duration<double>(id / o.rate));
    std::this_thread::sleep_until(arrival);
    {
      std::lock_guard<std::mutex> lock(mutex);
      if (queued >= static_cast<uint64_t>(o.capacity))
        ++rejected;
      else {
        queues[id % o.keys].push_back({id, arrival});
        ++queued;
        high_water = std::max(high_water, queued);
      }
    }
    cv.notify_all();
  }
  // Keep the measurement window at least as long as the offered-load interval.
  std::this_thread::sleep_until(start +
                                std::chrono::duration_cast<Clock::duration>(
                                    std::chrono::duration<double>(o.duration)));
  {
    std::lock_guard<std::mutex> lock(mutex);
    done = true;
  }
  cv.notify_all();
  for (auto &t : threads)
    t.join();
  double elapsed = seconds(Clock::now() - start),
         cpu = cpu_seconds() - cpu_start;
  Stats total;
  for (const auto &s : stats) {
    total.verified += s.verified;
    total.good += s.good;
    total.expired += s.expired;
    total.failed += s.failed;
    total.cpu_items += s.cpu_items;
    total.gpu_items += s.gpu_items;
    total.cpu_batches += s.cpu_batches;
    total.gpu_batches += s.gpu_batches;
    total.prepare += s.prepare;
    total.signing += s.signing;
    total.verify += s.verify;
    total.queue += s.queue;
    total.latencies.insert(total.latencies.end(), s.latencies.begin(),
                           s.latencies.end());
    for (auto entry : s.batches)
      total.batches[entry.first] += entry.second;
  }
  require(offered == rejected + total.verified + total.expired + total.failed,
          "request accounting");
  std::sort(total.latencies.begin(), total.latencies.end());
  std::map<uint64_t, uint64_t> histogram;
  for (double ms : total.latencies)
    ++histogram[static_cast<uint64_t>(std::floor(ms * 10))];
  // JSON strings below are fixed or validated enums; no arbitrary user text is
  // emitted.
  std::cout << std::setprecision(12) << "{\"schema\":1,\"mode\":\"" << o.mode
            << "\",\"openssl\":\"" << OpenSSL_version(OPENSSL_VERSION) << "\",";
#ifdef PIPELINE_GPU
  std::cout << "\"native_version\":\"" << bc_version() << "\",";
#endif
  std::cout << "\"gpu_dispatch\":\"" << o.gpu_dispatch
            << "\",\"workers\":" << o.workers << ",\"keys\":" << o.keys
            << ",\"device\":" << o.device << ",\"payload_bytes\":" << o.payload
            << ",\"max_batch\":" << o.batch
            << ",\"gpu_min_batch\":" << o.minimum
            << ",\"queue_capacity\":" << o.capacity
            << ",\"max_wait_ms\":" << o.wait_ms << ",\"slo_ms\":" << o.slo_ms
            << ",\"offered_rate\":" << o.rate
            << ",\"duration_s\":" << o.duration << ",\"elapsed_s\":" << elapsed
            << ",\"process_cpu_s\":" << cpu
            << ",\"peak_rss_bytes\":" << peak_rss()
            << ",\"queue_high_water\":" << high_water
            << ",\"offered\":" << offered << ",\"rejected\":" << rejected
            << ",\"expired\":" << total.expired
            << ",\"failed\":" << total.failed
            << ",\"verified\":" << total.verified
            << ",\"within_slo\":" << total.good
            << ",\"late\":" << total.verified - total.good
            << ",\"goodput_rps\":" << total.good / elapsed
            << ",\"cpu_items\":" << total.cpu_items
            << ",\"gpu_items\":" << total.gpu_items
            << ",\"cpu_batches\":" << total.cpu_batches
            << ",\"gpu_batches\":" << total.gpu_batches
            << ",\"prepare_worker_s\":" << total.prepare
            << ",\"sign_worker_s\":" << total.signing
            << ",\"verify_worker_s\":" << total.verify
            << ",\"queue_request_s\":" << total.queue
            << ",\"latency_p50_ms\":" << quantile(total.latencies, .5)
            << ",\"latency_p95_ms\":" << quantile(total.latencies, .95)
            << ",\"latency_p99_ms\":" << quantile(total.latencies, .99)
            << ",\"latency_max_ms\":"
            << (total.latencies.empty() ? 0 : total.latencies.back())
            << ",\"batch_histogram\":{";
  bool comma = false;
  for (auto e : total.batches) {
    if (comma)
      std::cout << ",";
    comma = true;
    std::cout << "\"" << e.first << "\":" << e.second;
  }
  std::cout << "},\"latency_histogram_100us\":{";
  comma = false;
  for (auto e : histogram) {
    if (comma)
      std::cout << ",";
    comma = true;
    std::cout << "\"" << e.first << "\":" << e.second;
  }
  std::cout << "}}\n";
  return fault ? 2 : 0;
}
int main(int argc, char **argv) {
  try {
    if (argc == 2 && std::string(argv[1]) == "--selftest") {
      selftest();
      return 0;
    }
    Options o;
    for (int i = 1; i < argc; i += 2) {
      require(i + 1 < argc, "option requires value");
      std::string k = argv[i], v = argv[i + 1];
      if (k == "--mode")
        o.mode = v;
      else if (k == "--gpu-dispatch")
        o.gpu_dispatch = v;
      else if (k == "--workers")
        o.workers = std::stoi(v);
      else if (k == "--keys")
        o.keys = std::stoi(v);
      else if (k == "--batch")
        o.batch = std::stoi(v);
      else if (k == "--gpu-min")
        o.minimum = std::stoi(v);
      else if (k == "--capacity")
        o.capacity = std::stoi(v);
      else if (k == "--payload")
        o.payload = std::stoi(v);
      else if (k == "--device")
        o.device = std::stoi(v);
      else if (k == "--rate")
        o.rate = std::stod(v);
      else if (k == "--seconds")
        o.duration = std::stod(v);
      else if (k == "--wait-ms")
        o.wait_ms = std::stod(v);
      else if (k == "--slo-ms")
        o.slo_ms = std::stod(v);
      else
        throw std::runtime_error("unknown option");
    }
    require(o.mode == "cpu" || o.mode == "gpu" || o.mode == "hybrid",
            "mode must be cpu/gpu/hybrid");
    require(o.gpu_dispatch == "caller" || o.gpu_dispatch == "owner",
            "GPU dispatch must be caller/owner");
    require(o.workers >= 1 && o.workers <= 64 && o.keys >= 1 && o.keys <= 16 &&
                o.batch >= 1 && o.batch <= 4096 && o.minimum >= 1 &&
                o.minimum <= o.batch && o.capacity >= 1 &&
                o.capacity <= 1000000 && o.payload >= 32 &&
                o.payload <= 1048576 && o.device >= 0,
            "integer bounds");
    require(std::isfinite(o.rate) && o.rate >= 1 && o.rate <= 2000000 &&
                std::isfinite(o.duration) && o.duration >= .01 &&
                o.duration <= 120 && o.rate * o.duration <= 5000000 &&
                std::isfinite(o.wait_ms) && o.wait_ms >= 0 &&
                o.wait_ms <= 100 && std::isfinite(o.slo_ms) && o.slo_ms > 0 &&
                o.slo_ms <= 1000,
            "measurement bounds");
    return run(o);
  } catch (const std::exception &e) {
    std::cerr << e.what() << "\n";
    ERR_print_errors_fp(stderr);
    return 1;
  }
}
