// SPDX-License-Identifier: Apache-2.0
// Closed-loop ready-wave JOSE service benchmark; no network or payment ledger.
#include "pipeline_crypto.hpp"
#include <ctime>
#include <functional>
#include <sstream>

using Md = Owned<EVP_MD_CTX, EVP_MD_CTX_free>;
std::string b64(const unsigned char *p, size_t n) {
  std::string out(4 * ((n + 2) / 3), '\0');
  if (n)
    require(EVP_EncodeBlock(reinterpret_cast<unsigned char *>(out.data()), p,
                            static_cast<int>(n)) ==
                static_cast<int>(out.size()),
            "base64 encode");
  while (!out.empty() && out.back() == '=')
    out.pop_back();
  std::replace(out.begin(), out.end(), '+', '-');
  std::replace(out.begin(), out.end(), '/', '_');
  return out;
}
std::string b64(const std::string &s) {
  return b64(reinterpret_cast<const unsigned char *>(s.data()), s.size());
}
Signature decode_signature(std::string s) {
  require(s.size() == 86, "raw signature base64 length");
  std::replace(s.begin(), s.end(), '-', '+');
  std::replace(s.begin(), s.end(), '_', '/');
  s += "==";
  std::array<unsigned char, 66> decoded{};
  require(EVP_DecodeBlock(decoded.data(),
                          reinterpret_cast<const unsigned char *>(s.data()),
                          static_cast<int>(s.size())) == 66,
          "base64 decode");
  Signature out{};
  std::copy_n(decoded.begin(), out.size(), out.begin());
  return out;
}
std::string hex(const unsigned char *p, size_t n) {
  const char *digits = "0123456789abcdef";
  std::string s;
  for (size_t i = 0; i < n; ++i) {
    s += digits[p[i] >> 4];
    s += digits[p[i] & 15];
  }
  return s;
}
Digest hash(const std::string &s) {
  Digest h{};
  unsigned int n = 0;
  require(EVP_Digest(s.data(), s.size(), h.data(), &n, EVP_sha256(), nullptr) ==
                  1 &&
              n == 32,
          "SHA256");
  return h;
}
struct Ed {
  std::vector<Md> signers, verifiers;
  std::vector<EVP_PKEY *> private_keys, public_keys;
  Ed(const std::vector<Key> &keys, const std::vector<Key> &pubs) {
    for (size_t k = 0; k < keys.size(); ++k) {
      Md s(EVP_MD_CTX_new(), EVP_MD_CTX_free),
          v(EVP_MD_CTX_new(), EVP_MD_CTX_free);
      require(s && v &&
                  EVP_DigestSignInit(s.get(), nullptr, nullptr, nullptr,
                                     keys[k].get()) == 1 &&
                  EVP_DigestVerifyInit(v.get(), nullptr, nullptr, nullptr,
                                       pubs[k].get()) == 1,
              "Ed25519 init");
      signers.push_back(std::move(s));
      verifiers.push_back(std::move(v));
      private_keys.push_back(keys[k].get());
      public_keys.push_back(pubs[k].get());
    }
  }
  Signature sign(size_t k, const std::string &message) {
    require(EVP_DigestSignInit(signers[k].get(), nullptr, nullptr, nullptr,
                               private_keys[k]) == 1,
            "Ed25519 sign reinit");
    Signature sig{};
    size_t n = sig.size();
    require(
        EVP_DigestSign(signers[k].get(), sig.data(), &n,
                       reinterpret_cast<const unsigned char *>(message.data()),
                       message.size()) == 1 &&
            n == 64,
        "Ed25519 sign");
    return sig;
  }
  bool verify(size_t k, const std::string &message, const Signature &sig) {
    require(EVP_DigestVerifyInit(verifiers[k].get(), nullptr, nullptr, nullptr,
                                 public_keys[k]) == 1,
            "Ed25519 verify reinit");
    return EVP_DigestVerify(
               verifiers[k].get(), sig.data(), sig.size(),
               reinterpret_cast<const unsigned char *>(message.data()),
               message.size()) == 1;
  }
};
class Pool {
  std::mutex mutex;
  std::condition_variable ready, complete;
  std::vector<std::thread> threads;
  std::function<void(size_t)> job;
  size_t generation = 0, remaining = 0;
  bool stopping = false;
  std::exception_ptr failure;

public:
  explicit Pool(size_t count) {
    for (size_t w = 0; w < count; ++w)
      threads.emplace_back([this, w] {
        size_t seen = 0;
        for (;;) {
          std::function<void(size_t)> work;
          {
            std::unique_lock<std::mutex> lock(mutex);
            ready.wait(lock, [&] { return stopping || generation != seen; });
            if (stopping)
              return;
            seen = generation;
            work = job;
          }
          try {
            work(w);
          } catch (...) {
            std::lock_guard<std::mutex> lock(mutex);
            failure = std::current_exception();
          }
          {
            std::lock_guard<std::mutex> lock(mutex);
            if (--remaining == 0)
              complete.notify_one();
          }
        }
      });
  }
  void run(std::function<void(size_t)> work) {
    std::unique_lock<std::mutex> lock(mutex);
    failure = nullptr;
    job = std::move(work);
    remaining = threads.size();
    ++generation;
    ready.notify_all();
    complete.wait(lock, [&] { return remaining == 0; });
    if (failure)
      std::rethrow_exception(failure);
  }
  ~Pool() {
    {
      std::lock_guard<std::mutex> lock(mutex);
      stopping = true;
    }
    ready.notify_all();
    for (auto &thread : threads)
      thread.join();
  }
};
struct WaveOptions {
  std::string mode = "cpu-es256";
  int wave = 256, keys = 1, workers = 8, device = 0;
  double duration = 3;
};
int run_wave(const WaveOptions &o) {
  const bool ed = o.mode == "cpu-eddsa", hybrid = o.mode == "hybrid-es256";
  const int active = std::min(o.workers, o.wave);
  std::vector<Key> keys, pubs;
  std::vector<std::string> headers, public_hex;
  for (int k = 0; k < o.keys; ++k) {
    if (ed)
      keys.emplace_back(EVP_PKEY_Q_keygen(nullptr, nullptr, "ED25519"),
                        EVP_PKEY_free);
    else
      keys.push_back(generate_key());
    require(bool(keys.back()), "key generation");
    pubs.push_back(public_only(keys.back().get()));
    headers.push_back(b64(std::string("{\"alg\":\"") +
                          (ed ? "EdDSA" : "ES256") + "\",\"kid\":\"wave-" +
                          std::to_string(k) + "\",\"typ\":\"JWT\"}"));
    if (ed) {
      std::array<unsigned char, 32> bytes{};
      size_t n = bytes.size();
      require(EVP_PKEY_get_raw_public_key(pubs.back().get(), bytes.data(),
                                          &n) == 1 &&
                  n == 32,
              "Ed25519 public");
      public_hex.push_back(hex(bytes.data(), bytes.size()));
    } else {
      auto bytes = public_bytes(pubs.back().get());
      public_hex.push_back(hex(bytes.data(), bytes.size()));
    }
  }
  std::vector<std::unique_ptr<Crypto>> cpu;
  std::vector<std::unique_ptr<Ed>> ed_cpu;
  for (int w = 0; w < active; ++w) {
    if (ed)
      ed_cpu.push_back(std::make_unique<Ed>(keys, pubs));
    else
      cpu.push_back(std::make_unique<Crypto>(
          keys, pubs, false)); // Normal randomized ECDSA baseline.
  }
  std::unique_ptr<Gpu> gpu;
  if (hybrid)
    gpu = std::make_unique<Gpu>(o.device, keys, false);
  Pool pool(active);
  std::vector<std::string> inputs(o.wave), tokens(o.wave);
  std::vector<Digest> digests(o.wave);
  std::vector<Signature> signatures(o.wave);
  std::vector<bool> gpu_key(o.keys, false);
  uint64_t gpu_per_wave = 0;
  for (int k = 0; k < o.keys; ++k) {
    size_t count = (o.wave + o.keys - 1 - k) / o.keys;
    gpu_key[k] = hybrid && count >= 64;
    if (gpu_key[k])
      gpu_per_wave += count;
  }
  const auto issued = static_cast<long long>(std::time(nullptr));
  double prepare_s = 0, sign_s = 0, finish_s = 0;
  auto wave = [&](uint64_t number, bool timed) {
    auto begin = Clock::now();
    pool.run([&](size_t w) {
      for (int i = static_cast<int>(w); i < o.wave; i += active) {
        auto k = i % o.keys;
        std::string payload =
            "{\"iss\":\"issuer.example\",\"aud\":\"publisher.example\",\"sub\":"
            "\"buyer-1\",\"iat\":" +
            std::to_string(issued) +
            ",\"exp\":" + std::to_string(issued + 3600) + ",\"jti\":\"wave-" +
            std::to_string(number) + "-item-" + std::to_string(i) +
            "\",\"scope\":\"content:read\",\"quote\":\"quote-" +
            std::to_string(i) + "\",\"content_sha256\":\"" +
            std::string(64, 'a') + "\",\"terms_sha256\":\"" +
            std::string(64, 'b') + "\",\"units\":1}";
        inputs[i] = headers[k] + "." + b64(payload);
        if (!ed)
          digests[i] = hash(inputs[i]);
      }
    });
    auto prepared = Clock::now();
    pool.run([&](size_t w) {
      for (int i = static_cast<int>(w); i < o.wave; i += active) {
        auto k = i % o.keys;
        if (!gpu_key[k])
          signatures[i] =
              ed ? ed_cpu[w]->sign(k, inputs[i]) : cpu[w]->sign(k, digests[i]);
      }
    });
    for (int k = 0; k < o.keys; ++k)
      if (gpu_key[k]) {
        std::vector<Digest> h;
        std::vector<Signature> out;
        for (int i = k; i < o.wave; i += o.keys)
          h.push_back(digests[i]);
        out.resize(h.size());
        gpu->sign(k, h, out);
        for (int i = k, j = 0; i < o.wave; i += o.keys, ++j)
          signatures[i] = out[j];
      }
    auto signed_at = Clock::now();
    pool.run([&](size_t w) {
      for (int i = static_cast<int>(w); i < o.wave; i += active) {
        tokens[i] =
            inputs[i] + "." + b64(signatures[i].data(), signatures[i].size());
        auto split = tokens[i].rfind('.');
        require(split != std::string::npos &&
                    tokens[i].substr(0, split) == inputs[i],
                "signed input binding");
        auto raw = decode_signature(tokens[i].substr(split + 1));
        // Consumer hashes the received signing input independently. General JWT
        // parsing/claim policy is tested with PyJWT separately, outside this
        // timer.
        require(
            ed ? ed_cpu[w]->verify(i % o.keys, tokens[i].substr(0, split), raw)
               : cpu[w]->verify(i % o.keys, hash(tokens[i].substr(0, split)),
                                raw),
            "wire signature verification");
      }
    });
    auto end = Clock::now();
    if (timed) {
      prepare_s += seconds(prepared - begin);
      sign_s += seconds(signed_at - prepared);
      finish_s += seconds(end - signed_at);
    }
    return seconds(end - begin) * 1000;
  };
  for (int i = 0; i < 3; ++i)
    wave(i, false);
  Signature wrong = signatures[0];
  wrong[0] ^= 1;
  require(!(ed ? ed_cpu[0]->verify(0, inputs[0], wrong)
               : cpu[0]->verify(0, digests[0], wrong)),
          "mutated signature accepted");
  std::vector<double> latencies;
  uint64_t good10 = 0, good50 = 0, n = 0;
  auto begin = Clock::now();
  auto cpu_begin = cpu_seconds();
  do {
    double ms = wave(n + 3, true);
    latencies.push_back(ms);
    good10 += ms <= 10;
    good50 += ms <= 50;
    ++n;
  } while (seconds(Clock::now() - begin) < o.duration && n < 1000000);
  double elapsed = seconds(Clock::now() - begin),
         consumed = cpu_seconds() - cpu_begin;
  std::sort(latencies.begin(), latencies.end());
  auto q = [&](double p) {
    return latencies[static_cast<size_t>(std::ceil(p * n)) - 1];
  };
  std::cout << std::setprecision(12) << "{\"schema\":1,\"mode\":\"" << o.mode
            << "\",\"wave\":" << o.wave << ",\"keys\":" << o.keys
            << ",\"workers\":" << o.workers << ",\"active_workers\":" << active
            << ",\"device\":" << o.device << ",\"duration_s\":" << o.duration
            << ",\"elapsed_s\":" << elapsed << ",\"process_cpu_s\":" << consumed
            << ",\"waves\":" << n << ",\"verified\":" << n * o.wave
            << ",\"gpu_items\":" << n * gpu_per_wave
            << ",\"within_10ms\":" << good10 * o.wave
            << ",\"within_50ms\":" << good50 * o.wave
            << ",\"throughput_rps\":" << n * o.wave / elapsed
            << ",\"goodput_50ms\":" << good50 * o.wave / elapsed
            << ",\"p50_ms\":" << q(.5) << ",\"p95_ms\":" << q(.95)
            << ",\"p99_ms\":" << q(.99) << ",\"max_ms\":" << latencies.back()
            << ",\"prepare_s\":" << prepare_s << ",\"sign_s\":" << sign_s
            << ",\"finish_s\":" << finish_s << ",\"openssl\":\""
            << OpenSSL_version(OPENSSL_VERSION)
            << "\",\"peak_rss_bytes\":" << peak_rss() << ",\"samples\":[";
  for (int k = 0; k < o.keys; ++k) {
    if (k)
      std::cout << ",";
    std::cout << "{\"token\":\"" << tokens[k] << "\",\"public_hex\":\""
              << public_hex[k] << "\"}";
  }
  std::cout << "],\"wave_latencies_ms\":[";
  for (size_t i = 0; i < latencies.size(); ++i) {
    if (i)
      std::cout << ",";
    std::cout << latencies[i];
  }
  std::cout << "]}\n";
  return 0;
}
int main(int argc, char **argv) {
  try {
    WaveOptions o;
    for (int i = 1; i < argc; i += 2) {
      require(i + 1 < argc, "option value required");
      std::string k = argv[i], v = argv[i + 1];
      if (k == "--mode")
        o.mode = v;
      else if (k == "--wave")
        o.wave = std::stoi(v);
      else if (k == "--keys")
        o.keys = std::stoi(v);
      else if (k == "--workers")
        o.workers = std::stoi(v);
      else if (k == "--device")
        o.device = std::stoi(v);
      else if (k == "--seconds")
        o.duration = std::stod(v);
      else
        throw std::runtime_error("unknown option");
    }
    require(o.mode == "cpu-es256" || o.mode == "cpu-eddsa" ||
                o.mode == "hybrid-es256",
            "invalid mode");
    require(o.wave >= 1 && o.wave <= 4096 && o.keys >= 1 && o.keys <= 16 &&
                o.keys <= o.wave && o.workers >= 1 && o.workers <= 32 &&
                o.device >= 0 && std::isfinite(o.duration) &&
                o.duration >= .01 && o.duration <= 10,
            "measurement bounds");
    return run_wave(o);
  } catch (const std::exception &e) {
    std::cerr << e.what() << "\n";
    ERR_print_errors_fp(stderr);
    return 1;
  }
}
