# SPDX-License-Identifier: Apache-2.0
# Adapted from Smoke gen_p256_comb_table.py; see EXTRACTION.json and NOTICE.
# Modified: retain pure-Python public-point math; omit NumPy, CLI and legacy output.
# P-256 curve parameters (secp256r1 / NIST P-256)
P = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF
A = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFC  # a = -3
B = 0x5AC635D8AA3A93E7B3EBBD55769886BC651D06B0CC53B0F63BCE3C3E27D2604B
Gx = 0x6B17D1F2E12C4247F8BCE6E563A440F277037D812DEB33A0F4A13945D898C296
Gy = 0x4FE342E2FE1A7F9B8EE7EB4A7C0F9E162BCE33576B315ECECBB6406837BF51F5
N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551

# Montgomery constant R = 2^256 mod p
R_MOD_P = pow(2, 256, P)
R2_MOD_P = pow(2, 512, P)  # R^2 mod p


def mod_inverse(a: int, modulus: int) -> int:
    """Modular inverse using Fermat's Little Theorem (for prime modulus)."""
    if a == 0:
        raise ValueError("Cannot compute modular inverse of 0")
    return pow(a, modulus - 2, modulus)


def to_montgomery(x: int) -> int:
    """
    Convert normal field element to Montgomery domain: x -> x*R mod p.

    CARD17 FIX: Use x*R (single Montgomery), NOT x*R^2 (double Montgomery).
    The old buggy formula was: (x * R2_MOD_P) % P = x*R^2
    The correct formula is:    (x * R_MOD_P) % P = x*R
    """
    return (x * R_MOD_P) % P


def from_montgomery(x_mont: int) -> int:
    """Convert Montgomery field element to normal domain."""
    return (x_mont * mod_inverse(R_MOD_P, P)) % P


def point_double_affine(x1: int, y1: int) -> tuple:
    """
    Elliptic curve point doubling in affine coordinates.
    For P-256: y^2 = x^3 + ax + b, where a = -3

    Formula:
    lambda = (3*x1^2 + a) / (2*y1)
    x3 = lambda^2 - 2*x1
    y3 = lambda*(x1 - x3) - y1
    """
    # Handle point at infinity
    if x1 == 0 and y1 == 0:
        return (0, 0)

    # Compute lambda = (3*x1^2 + a) / (2*y1) mod p
    numerator = (3 * x1 * x1 + A) % P
    denominator = (2 * y1) % P
    lambda_val = (numerator * mod_inverse(denominator, P)) % P

    # Compute x3 = lambda^2 - 2*x1
    x3 = (lambda_val * lambda_val - 2 * x1) % P

    # Compute y3 = lambda*(x1 - x3) - y1
    y3 = (lambda_val * (x1 - x3) - y1) % P

    return (x3, y3)


def point_add_affine(x1: int, y1: int, x2: int, y2: int) -> tuple:
    """
    Elliptic curve point addition in affine coordinates.
    P + Q = R

    Formula:
    lambda = (y2 - y1) / (x2 - x1)
    x3 = lambda^2 - x1 - x2
    y3 = lambda*(x1 - x3) - y1
    """
    # Handle special cases
    if x1 == 0 and y1 == 0:  # P is point at infinity
        return (x2, y2)
    if x2 == 0 and y2 == 0:  # Q is point at infinity
        return (x1, y1)
    if x1 == x2:
        if y1 == y2:  # Point doubling
            return point_double_affine(x1, y1)
        else:  # Points are inverses
            return (0, 0)

    # Compute lambda = (y2 - y1) / (x2 - x1) mod p
    numerator = (y2 - y1) % P
    denominator = (x2 - x1) % P
    lambda_val = (numerator * mod_inverse(denominator, P)) % P

    # Compute x3 = lambda^2 - x1 - x2
    x3 = (lambda_val * lambda_val - x1 - x2) % P

    # Compute y3 = lambda*(x1 - x3) - y1
    y3 = (lambda_val * (x1 - x3) - y1) % P

    return (x3, y3)
