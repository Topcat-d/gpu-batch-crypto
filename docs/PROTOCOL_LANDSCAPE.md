# Protocol landscape and integration boundaries

Reviewed September 6, 2026 against primary documentation. Product announcements,
deployed profiles, RFCs and Internet-Drafts have different status. This table
maps responsibilities; it is not a certification of interoperability or an
exhaustive survey. Recheck the exact version before implementing an adapter.

| System / source | Responsibility and evidence | Relationship to this repository |
|---|---|---|
| [Web Bot Auth draft 01](https://datatracker.ietf.org/doc/html/draft-meunier-webbotauth-httpsig-protocol-01), August 2026 | Identifies automated HTTP traffic using message signatures and key discovery. It remains an Internet-Draft. | A request-authentication profile, not a content entitlement or payment settlement protocol. No adapter is implemented here. |
| [Cloudflare Web Bot Auth integration](https://developers.cloudflare.com/bots/reference/bot-verification/web-bot-auth/), updated July 2026 | Its documented registration/verification flow uses Ed25519 and ignores other key types in that directory integration. | The GPU P-256 signer does not replace that deployed profile. HTTP message construction and discovery are also missing. |
| [Cloudflare Monetization Gateway announcement](https://blog.cloudflare.com/monetization-gateway/), July 2026 | Describes charging for content, APIs and MCP tools using x402, with payment verification/enforcement at the edge. This source is an announcement, not evidence of this repo's adoption. | Establishes adjacent commercial work. The open engine could be evaluated beneath an accepted workflow; it supplies no gateway or payment integration. |
| [x402 facilitator documentation](https://docs.x402.org/core-concepts/facilitator), retrieved September 2026 | Separates payment-payload verification from blockchain settlement. A facilitator can perform those operations for a resource server. | Payment format, network, wallet signatures and settlement behavior require their own adapter and tests. ES256 output alone implements none of them. |
| [AP2 specification v0.2](https://ap2-protocol.org/ap2/specification/), retrieved September 2026 | Checkout and Payment Mandates communicate agent purchase/payment authority and linked receipts. | A possible future authorization workload, subject to exact signature, mandate, trust and privacy requirements. There is no AP2 implementation here. |
| [Batched Privacy Pass draft 08](https://datatracker.ietf.org/doc/html/draft-ietf-privacypass-batched-tokens-08), May 2026 | Defines generic batch issuance and amortized privately verifiable token issuance. The latter shares an issuer key and amortizes VOPRF proof work. It remains an Internet-Draft. | Strong prior art for protocol batching. Ordinary ECDSA batches are not VOPRF or blind-signature issuance; the algorithms and privacy properties differ. |
| [OAuth DPoP, RFC 9449](https://www.rfc-editor.org/rfc/rfc9449.html#section-4) | Binds proofs to an HTTP request and key-bound access token; freshness/server-nonce requirements affect preparation. | Useful reference for a workload that can require fresh request proofs. Raw signatures are insufficient; no OAuth/DPoP adapter exists here. |
| [Persona's LinkedIn verification disclosure](https://help.withpersona.com/en-US/end-users/linkedin/get-verified/) | Describes sharing a hashed unique identifier alongside verification information. It does not identify that hash algorithm. | Illustrates an identity-data application, not evidence that raw SHA-256 throughput measures verification capacity. |
| [Persona Relay challenge protocol](https://docs.withpersona.com/relay-privacy-pass-challenge), retrieved September 2026 | Describes SHA-256 components, challenge validation, Blind RSA signatures and one-time token redemption. | This is a separate documented flow from the LinkedIn identifier. SHA-256 support does not provide its Blind RSA or redemption implementation. |

## Algorithm names are not the complete contract

AP2 v0.2 requires its merchant Checkout JWT to use a non-deterministic digital
signature. This library's GPU ECDSA path uses deterministic RFC6979 nonces.
Consequently, a valid ES256 token from this engine does not by itself satisfy
that checkout requirement. Pin the protocol version and obtain conformance
evidence before proposing an integration. Do not add random bytes to signed
application data as an improvised substitute for the specified signing behavior.
[AP2 Payment Mandate requirements](https://ap2-protocol.org/ap2/specification/).

Similarly, key possession, permission to access a resource, authorization to
spend a budget, settlement finality and the truth of an identity assertion are
separate checks. A signature authenticates an issuer's statement under a trust
policy; it cannot establish every one of those properties on its own.

## Where the open project can contribute

The proposed contribution is an independently adoptable execution library and
an auditable way to compare complete cryptographic workloads. Existing protocols
determine which operations are required and who may perform them. This project
can test packing, signing, verification placement, compatible batching and CPU
fallback within those requirements.

Batch issuance itself has established prior art. A credible new result would
identify a particular accepted protocol workload and demonstrate lower total
cost or latency than a tuned CPU implementation, with unchanged trust boundaries
and all required checks. A useful negative result can prevent an unnecessary
GPU allocation or identify a missing algorithm before integration work begins.

## Research questions left open

- Which protocol operation is actually consuming resources: issuance, request
  signing, verification, hashing, persistence or settlement?
- Are the relevant keys permitted in this host/device execution boundary?
- How much work remains after normal caching, credential reuse and bundling?
- Are ready jobs compatible under algorithm, key epoch, tenant, origin and
  privacy rules? Can they finish before their deadline?
- Does an independently verified implementation improve the total system?

The [research thesis](AGENT_WEB_RESEARCH.md) turns these questions into an
experiment sequence. Technical protocol fit and actual buyer value require
separate evidence.
