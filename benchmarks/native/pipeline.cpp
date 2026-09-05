// SPDX-License-Identifier: Apache-2.0
// In-process signing pipeline benchmark, not a network service or key manager.
#include "pipeline_crypto.hpp"

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
