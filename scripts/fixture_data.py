"""Generate a fixed binary fixture using carryless products and long division."""
from hashlib import sha256
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def reference_product(a, b):
    terms = [a << bit for bit in range(8) if b & (1 << bit)]
    value = 0
    for term in terms:
        value ^= term
    for bit in range(14, 7, -1):
        if value & (1 << bit):
            value ^= 0x11D << (bit - 8)
    return value


def generate():
    payload = bytes(range(1, 110)) + b'\x80\xfe\xff\x00'
    width = (len(payload) + 2) // 3
    padded = payload.ljust(3 * width, b'\x00')
    a, b, c = (padded[i:i + width] for i in range(0, 3 * width, width))
    parity = bytes(x ^ y ^ z for x, y, z in zip(a, b, c))
    weighted = bytes(x ^ reference_product(y, 2) ^ reference_product(z, 4)
                     for x, y, z in zip(a, b, c))
    shards = [a, b, c, parity, weighted]
    damaged = bytes([b[0] ^ 128]) + b[1:]
    mirror = ROOT / 'shards'
    mirror.mkdir(exist_ok=True)
    for index, shard in enumerate(shards):
        (mirror / f'{index}.hex').write_bytes(shard.hex().encode() + b'\n')
    (mirror / 'wrong-b.hex').write_bytes(damaged.hex().encode() + b'\n')
    (mirror / 'invalid-e.hex').write_bytes(b'This response is not a hex shard.\n')
    fixture = {
        'payload_hex': payload.hex(),
        'length': len(payload),
        'payload_sha256': sha256(payload).hexdigest(),
        'sha256': [sha256(shard).hexdigest() for shard in shards],
        'wrong_sha256': sha256(damaged).hexdigest(),
    }
    fixtures = ROOT / 'fixtures'
    fixtures.mkdir(exist_ok=True)
    (fixtures / 'archive.json').write_bytes((json.dumps(fixture, indent=2) + '\n').encode())


if __name__ == '__main__':
    generate()
