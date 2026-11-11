# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
from genlayer import *
import hashlib
import json
import re


GENERATOR = ((1, 0, 0), (0, 1, 0), (0, 0, 1), (1, 1, 1), (1, 2, 4))
HISTORY = 4
MIRROR = (r'https://raw\.githubusercontent\.com/[A-Za-z0-9-]{1,39}/'
          r'[A-Za-z0-9][A-Za-z0-9_.-]{0,79}/(?:[a-f0-9]{40}|refs/heads/[A-Za-z0-9_-]{1,40})/'
          r'shards/[A-Za-z0-9_-]{1,40}\.hex')


def fail(message):
    raise gl.vm.UserError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def multiply(a, b):
    """Multiply in GF(256) with reduction polynomial 0x11D."""
    value = 0
    while b:
        if b & 1:
            value ^= a
        a <<= 1
        if a & 256:
            a ^= 0x11D
        b >>= 1
    return value


def inverse_element(x):
    result, power = 1, 254
    while power:
        if power & 1:
            result = multiply(result, x)
        x = multiply(x, x)
        power >>= 1
    return result


def inverse_rows(indices):
    """Invert the three selected rows using Gauss–Jordan elimination."""
    matrix = [list(GENERATOR[row]) + list(GENERATOR[i]) for i, row in enumerate(indices)]
    for col in range(3):
        pivot = next(i for i in range(col, 3) if matrix[i][col])
        matrix[col], matrix[pivot] = matrix[pivot], matrix[col]
        scale = inverse_element(matrix[col][col])
        matrix[col] = [multiply(x, scale) for x in matrix[col]]
        for i in range(3):
            if i != col:
                scale = matrix[i][col]
                matrix[i] = [a ^ multiply(b, scale) for a, b in zip(matrix[i], matrix[col])]
    return [row[3:] for row in matrix]


def combine(coefficients, shards):
    a, b, c = coefficients
    return bytes(multiply(a, x) ^ multiply(b, y) ^ multiply(c, z) for x, y, z in zip(*shards))


def split_payload(payload, width):
    padded = payload + bytes(3 * width - len(payload))
    return [padded[i:i + width] for i in range(0, len(padded), width)]


def restore(observations, manifest):
    basis = [i for i, item in enumerate(observations) if item['status'] == 'VERIFIED'][:3]
    if len(basis) < 3:
        return 'INSUFFICIENT', basis, None

    received = [bytes.fromhex(observations[i]['hex']) for i in basis]
    shards = [combine(row, received) for row in inverse_rows(basis)]
    padded = b''.join(shards)
    size = manifest['length']
    payload = padded[:size]
    if any(padded[size:]) or digest(payload) != manifest['payload_sha256']:
        return 'INCONSISTENT', basis, None
    for row, commitment in zip(GENERATOR, manifest['sha256']):
        if digest(combine(row, shards)) != commitment:
            return 'INCONSISTENT', basis, None
    return 'RECOVERABLE', basis, payload


def observe_mirrors(urls, hashes, width):
    def sample():
        observations = []
        for index, (url, expected) in enumerate(zip(urls, hashes)):
            error = '[FETCH] Mirror ' + str(index) + ' unavailable'
            try:
                response = gl.nondet.web.get(url)
            except Exception:
                fail(error)
            if response.status in (404, 410):
                observations.append({'status': 'MISSING'})
                continue
            if response.status != 200:
                fail(error)
            if len(response.body) > 2 * width + 2:
                observations.append({'status': 'MALFORMED'})
                continue
            body = response.body
            if body.endswith(b'\r\n'):
                body = body[:-2]
            elif body.endswith(b'\n'):
                body = body[:-1]
            if len(body) != 2 * width or re.fullmatch(rb'[0-9a-fA-F]+', body) is None:
                observations.append({'status': 'MALFORMED'})
                continue
            shard = bytes.fromhex(body.decode('ascii'))
            actual = digest(shard)
            if actual == expected:
                observations.append({'status': 'VERIFIED', 'hex': shard.hex(), 'sha256': actual})
            else:
                observations.append({'status': 'WRONG_DIGEST', 'sha256': actual})
        return observations

    def validate(leader):
        try:
            own = sample()
        except gl.vm.UserError as error:
            message = getattr(error, 'message', str(error))
            return (not isinstance(leader, gl.vm.Return) and message.startswith('[FETCH] ')
                    and message == getattr(leader, 'message', ''))
        except Exception:
            return False
        return isinstance(leader, gl.vm.Return) and own == leader.calldata

    return gl.vm.run_nondet_unsafe(sample, validate)


class ArchiveLift(gl.Contract):
    manifest: str
    round: u256
    archive: str
    history: DynArray[str]

    def __init__(self, mirrors: str, commitments: str, payload_sha256: str, length: int):
        if not 1 <= length <= 768 or len(mirrors) > 1500 or len(commitments) != 324:
            fail('Invalid manifest size')
        urls = mirrors.split('|')
        hashes = commitments.split(',')
        if len(urls) != 5 or len(set(urls)) != 5 or any(not re.fullmatch(MIRROR, url) for url in urls):
            fail('Five distinct shard URLs required')
        if not all(re.fullmatch(r'[a-f0-9]{64}', h) for h in hashes + [payload_sha256]):
            fail('Invalid SHA-256 commitments')
        self.manifest = json.dumps({'urls': urls, 'sha256': hashes, 'payload_sha256': payload_sha256,
                                    'length': length, 'shard_width': (length + 2) // 3})
        self.round = u256(0)
        self.archive = ''

    @gl.public.write
    def probe(self, expected_round: int) -> None:
        if expected_round != self.round:
            fail('Stale round')
        config = json.loads(self.manifest)
        observations = observe_mirrors(config['urls'], config['sha256'], config['shard_width'])
        outcome, basis, payload = restore(observations, config)
        if payload is not None and not self.archive:
            self.archive = payload.hex()
        next_round = int(self.round) + 1
        snapshot = json.dumps({'round': next_round, 'outcome': outcome, 'basis': basis,
                               'mirrors': [{k: v for k, v in item.items() if k != 'hex'}
                                           for item in observations]})
        slot = (next_round - 1) % HISTORY
        if len(self.history) < HISTORY:
            self.history.append(snapshot)
        else:
            self.history[slot] = snapshot
        self.round = u256(next_round)

    @gl.public.view
    def get_state(self) -> dict:
        current = int(self.round)
        return {'manifest': json.loads(self.manifest), 'round': current,
                'latest': json.loads(self.history[(current - 1) % HISTORY]) if current else None,
                'archive_hex': self.archive or None}

    @gl.public.view
    def get_snapshot(self, round_number: int) -> dict:
        if not 0 < round_number <= self.round or self.round - round_number >= HISTORY:
            fail('Snapshot not retained')
        return json.loads(self.history[(round_number - 1) % HISTORY])

    @gl.public.view
    def get_shard(self, index: int) -> dict:
        if index not in range(5):
            fail('Invalid shard index')
        if not self.archive:
            fail('Archive unavailable')
        config = json.loads(self.manifest)
        shards = split_payload(bytes.fromhex(self.archive), config['shard_width'])
        shard = combine(GENERATOR[index], shards)
        return {'index': index, 'hex': shard.hex(), 'sha256': digest(shard)}
