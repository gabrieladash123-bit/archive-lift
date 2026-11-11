Category: Builder → Intelligent Contracts

Title: ArchiveLift: Consensus recovery of erasure coded artifacts

Notes / Description:

ArchiveLift recovers a small public artifact from five web mirrors and publishes the recovered bytes onchain. A manifest commits to the artifact and each shard. Anyone can probe. The leader and validators independently fetch all five URLs, decode hex, verify SHA-256, and compare the exact observed bytes and per-mirror results. Three valid shards can reconstruct the artifact over GF(256). The contract checks the payload hash, zero padding and all five shard commitments, including missing shards, before publication. It can regenerate any shard from the stored artifact after mirror loss. A four-round history records recoverable, insufficient and inconsistent observations. Tests cover all ten decode bases, tampering, validator disagreement, repeat probes and recovery after a mirror returns.
