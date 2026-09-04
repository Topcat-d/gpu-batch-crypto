"""SPDX-License-Identifier: Apache-2.0. CPU tests always run; CUDA is opt-in.
BC_LIBRARY=/path/to/library BC_DEVICE=0 python -m unittest discover -s tests -v
"""

import ctypes as C
import hashlib
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from batchcrypto import (
    Cpu,
    Cuda,
    Runtime,
    Record,
    ORDER,
    public_key,
    verify_p256,
    generate_p256_key,
)


class CryptoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cpu = Cpu()
        cls.backend = (
            Cuda(os.environ["BC_LIBRARY"], int(os.environ.get("BC_DEVICE", "0")))
            if os.environ.get("BC_LIBRARY")
            else cls.cpu
        )

    def test_aes_known_answer(self):
        # AES-256-GCM, all-zero key, 96-bit nonce, empty AAD and plaintext.
        self.assertEqual(
            self.backend.seal(bytes(32), [Record(bytes(12), b"")])[0].hex(),
            "530f8afbc74536b9a963b4f1c4cb738b",
        )

    def test_aes_sizes_and_aad(self):
        key = os.urandom(32)
        sizes = (
            0,
            1,
            15,
            16,
            17,
            31,
            32,
            33,
            111,
            112,
            127,
            128,
            129,
            512,
            1024,
            4096,
            16384,
            65535,
            65536,
            262144,
            1048576,
        )
        records = [
            Record(i.to_bytes(12, "big"), os.urandom(n), os.urandom((i * 7) % 65))
            for i, n in enumerate(sizes)
        ]
        expected = self.cpu.seal(key, records)
        actual = self.backend.seal(key, records)
        self.assertEqual(actual, expected)
        opened = self.backend.open(
            key, [Record(r.nonce, c, r.aad) for r, c in zip(records, expected)]
        )
        self.assertEqual(opened, [r.data for r in records])

    def test_max_aad(self):
        key = os.urandom(32)
        r = Record(os.urandom(12), b"content", os.urandom(65536))
        self.assertEqual(self.backend.seal(key, [r]), self.cpu.seal(key, [r]))

    def test_auth_failure_is_per_item(self):
        key = os.urandom(32)
        r = Record(os.urandom(12), b"secret article", b"publisher/version")
        c = self.cpu.seal(key, [r])[0]
        badtag = c[:-1] + bytes([c[-1] ^ 1])
        badct = bytes([c[0] ^ 1]) + c[1:]
        self.assertEqual(
            self.backend.open(
                key,
                [
                    Record(r.nonce, c, r.aad),
                    Record(r.nonce, badtag, r.aad),
                    Record(r.nonce, badct, r.aad),
                    Record(r.nonce, c, b"wrong"),
                    Record(bytes(12), c, r.aad),
                ],
            ),
            [r.data, None, None, None, None],
        )
        self.assertEqual(
            self.backend.open(os.urandom(32), [Record(r.nonce, c, r.aad)]), [None]
        )

    def test_sign_cpu_equivalence_and_verification(self):
        keys = [
            (1).to_bytes(32, "big"),
            (ORDER - 1).to_bytes(32, "big"),
            generate_p256_key(),
        ]
        digests = [
            hashlib.sha256(f"message-{i}".encode()).digest() for i in range(17)
        ] + [
            bytes(32),
            ORDER.to_bytes(32, "big"),
            (ORDER + 1).to_bytes(32, "big"),
            bytes([255]) * 32,
        ]
        for key in keys:
            actual = self.backend.sign(key, digests)
            self.assertEqual(actual, self.cpu.sign(key, digests))
            for h, s in zip(digests, actual):
                self.assertTrue(verify_p256(public_key(key), h, s))
                self.assertLessEqual(int.from_bytes(s[32:], "big"), ORDER // 2)
                self.assertFalse(
                    verify_p256(public_key(key), hashlib.sha256(h).digest(), s)
                )
                self.assertFalse(
                    verify_p256(public_key(key), h, s[:-1] + bytes([s[-1] ^ 1]))
                )
            self.assertEqual(self.backend.public_key(key), public_key(key))

    def test_hash_vectors_boundaries_and_random(self):
        messages = [b"", b"abc", b"a" * 1000000] + [
            os.urandom(n)
            for n in (
                1,
                16,
                17,
                55,
                56,
                63,
                64,
                65,
                119,
                120,
                127,
                128,
                512,
                1024,
                4096,
                65536,
                1048576,
            )
        ]
        self.assertEqual(
            self.backend.sha256(messages),
            [hashlib.sha256(m).digest() for m in messages],
        )
        self.assertEqual(
            self.backend.sha256([b"abc"])[0].hex(),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
        )

    def test_runtime_rotation_reuse_accounting(self):
        if not isinstance(self.backend, Cuda):
            self.skipTest("native runtime only")
        with Runtime(os.environ["BC_LIBRARY"], self.backend.device) as rt:
            key = os.urandom(32)
            sk = generate_p256_key()
            epoch = rt.load_key(0, key)
            self.assertEqual(epoch, 1)
            self.assertEqual(rt.load_key(1, sk, "p256"), 1)
            record = Record(os.urandom(12), os.urandom(4096), b"bound metadata")
            c = rt.seal(0, [record])[0]
            self.assertEqual([c], self.cpu.seal(key, [record]))
            self.assertEqual(
                rt.last_report,
                {"submitted": 1, "completed": 1, "errors": 0, "key_epoch": 1},
            )
            self.assertEqual(
                rt.open(0, [Record(record.nonce, c, record.aad)]), [record.data]
            )
            reserved = rt.stats()["reserved_device_bytes"]
            self.assertEqual(
                rt.open(0, [Record(record.nonce, c, record.aad)]), [record.data]
            )
            self.assertEqual(rt.stats()["reserved_device_bytes"], reserved)
            self.assertEqual(rt.open(0, [Record(record.nonce, c, b"wrong")]), [None])
            self.assertEqual(rt.last_report["errors"], 1)
            self.assertEqual(
                rt.sha256([record.data]), [hashlib.sha256(record.data).digest()]
            )
            h = rt.sha256([b"grant"])[0]
            sig = rt.sign(1, [h])[0]
            self.assertTrue(verify_p256(rt.public_key(1)[0], h, sig))
            self.assertEqual(rt.public_key(1)[1], 1)
            with self.assertRaises(RuntimeError):
                rt.load_key(0, os.urandom(32), expected_epoch=0)
            with self.assertRaises(RuntimeError):
                rt.load_key(0, key, expected_epoch=1)
            with self.assertRaises(RuntimeError):
                rt.seal(1, [record])
            epoch = rt.load_key(0, os.urandom(32), expected_epoch=1)
            self.assertEqual(epoch, 2)
            self.assertEqual(rt.open(0, [Record(record.nonce, c, record.aad)]), [None])
            self.assertEqual(rt.last_report["key_epoch"], 2)
            self.assertEqual(rt.retire_key(0, 2), 3)
            with self.assertRaises(RuntimeError):
                rt.seal(0, [record])
            with self.assertRaises(RuntimeError):
                rt.load_key(0, key, expected_epoch=0)
            self.assertEqual(rt.load_key(0, key, expected_epoch=3), 4)
            s = rt.stats()
            self.assertEqual(s["submitted"], s["completed"])
            self.assertEqual(s["item_errors"], 2)
            self.assertGreaterEqual(s["call_errors"], 2)
        with self.assertRaises(RuntimeError):
            rt.sha256([b"closed"])

    def test_independent_contexts_and_rotation_race(self):
        if not isinstance(self.backend, Cuda):
            self.skipTest("native runtime only")
        with (
            Runtime(os.environ["BC_LIBRARY"], self.backend.device) as a,
            Runtime(os.environ["BC_LIBRARY"], self.backend.device) as b,
        ):
            self.assertEqual(a.sha256([b"a"]), self.cpu.sha256([b"a"]))
            self.assertEqual(b.sha256([b"b"]), self.cpu.sha256([b"b"]))
            a.load_key(0, os.urandom(32))

            def replace(_):
                try:
                    return a.load_key(0, os.urandom(32), expected_epoch=1)
                except RuntimeError:
                    return None

            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(replace, range(2)))
            self.assertEqual(results.count(2), 1)
            self.assertEqual(results.count(None), 1)

    def test_rfc6979_sample(self):
        key = bytes.fromhex(
            "C9AFA9D845BA75166B5C215767B1D6934E50C3DB36E89B127B8A622B120F6721"
        )
        sig = self.backend.sign(key, [hashlib.sha256(b"sample").digest()])[0]
        self.assertEqual(
            sig[:32].hex(),
            "efd48b2aacb6a8fd1140dd9cd45e81d69d2c877b56aaf991c34d0ea84eaf3716",
        )
        original_s = int(
            "F7CB1C942D657C41D436C7A1B6E29F65F3E900DBB9AFF4064DC4AB2F843ACDA8", 16
        )
        self.assertEqual(
            int.from_bytes(sig[32:], "big"), min(original_s, ORDER - original_s)
        )

    def test_invalid_inputs(self):
        for key in (b"", bytes(31), bytes(32), ORDER.to_bytes(32, "big")):
            with self.assertRaises(ValueError):
                self.backend.sign(key, [bytes(32)])
        key = os.urandom(32)
        r = Record(bytes(12), b"a")
        with self.assertRaises(ValueError):
            self.backend.seal(key, [r, r])
        for bad in (
            Record(b"", b"a"),
            Record(bytes(12), b"x" * (1048576 + 1)),
            Record(bytes(12), b"", b"x" * 65537),
        ):
            with self.assertRaises(ValueError):
                self.backend.seal(key, [bad])
        with self.assertRaises(ValueError):
            self.backend.open(key, [Record(bytes(12), bytes(15))])
        with self.assertRaises(ValueError):
            self.backend.sign((1).to_bytes(32, "big"), [bytes(31)])
        with self.assertRaises(ValueError):
            self.backend.seal(key, [r] * 4097)
        self.assertEqual(self.backend.seal(key, []), [])

    def test_concurrent_calls(self):
        key = os.urandom(32)

        def run(i):
            record = Record(i.to_bytes(12, "big"), os.urandom(1024), b"parallel")
            return self.backend.seal(key, [record]) == self.cpu.seal(key, [record])

        with ThreadPoolExecutor(max_workers=4) as pool:
            self.assertTrue(all(pool.map(run, range(8))))

    def test_native_invalid_bounds(self):
        if not isinstance(self.backend, Cuda):
            self.skipTest("CUDA native ABI only")
        lib = self.backend.lib
        self.assertEqual(lib.bc_aes256gcm_seal(0, None, None, 1, None), 1)
        self.assertEqual(lib.bc_aes256gcm_open(0, None, None, 0, None), 0)
        self.assertEqual(lib.bc_p256_sign(0, None, None, 4097, None, None), 1)

    def test_native_auth_failure_zeroes_output(self):
        if not isinstance(self.backend, Cuda):
            self.skipTest("CUDA native ABI only")
        from batchcrypto import _Item

        key = os.urandom(32)
        nonce = os.urandom(12)
        message = b"sensitive content"
        ciphertext = self.cpu.seal(key, [Record(nonce, message)])[0]
        bad = C.create_string_buffer(ciphertext[:-1] + bytes([ciphertext[-1] ^ 1]))
        output = C.create_string_buffer(b"X" * len(message))
        status = C.c_ubyte(255)
        item = _Item(
            C.addressof(bad),
            len(ciphertext),
            None,
            0,
            (C.c_ubyte * 12).from_buffer_copy(nonce),
            C.addressof(output),
            len(message),
        )
        rc = self.backend.lib.bc_aes256gcm_open(
            self.backend.device, key, C.byref(item), 1, C.byref(status)
        )
        self.assertEqual(rc, 0)
        self.assertEqual(status.value, 3)
        self.assertEqual(output.raw[: len(message)], bytes(len(message)))
        item.output_capacity = len(message) - 1
        self.assertEqual(
            self.backend.lib.bc_aes256gcm_open(
                self.backend.device, key, C.byref(item), 1, C.byref(status)
            ),
            1,
        )
        with self.assertRaises(RuntimeError):
            Runtime(os.environ["BC_LIBRARY"], 9999)


if __name__ == "__main__":
    unittest.main()
