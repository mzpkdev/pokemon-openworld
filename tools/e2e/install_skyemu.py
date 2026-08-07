#!/usr/bin/env python3
import argparse
import hashlib
import http.client
import io
import os
from pathlib import Path
import ssl
import tempfile
import time
import urllib.error
import urllib.request
import zipfile


URL = "https://github.com/skylersaleh/SkyEmu/releases/download/v5/SkyEmu-v5-Linux.zip"
SHA256 = "f3904c4be148a5115ddb427356857d6b7c3cefb1843d488cbe9147a92905547f"
BINARY_SHA256 = "d85797fe449bd97922a3b3f73060db7ebf49ab094ef8f0b0c882fe7357e3c9f3"
RETRY_DELAYS = (1, 2, 4)
TRANSIENT_HTTP_STATUSES = frozenset({408, 429, 500, 502, 503, 504})


def download(*, opener=None, sleep=None) -> bytes:
    if opener is None:
        opener = urllib.request.urlopen
    if sleep is None:
        sleep = time.sleep

    for attempt in range(len(RETRY_DELAYS) + 1):
        try:
            with opener(URL, timeout=60) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            error.close()
            if error.code not in TRANSIENT_HTTP_STATUSES:
                raise
            failure = error
        except (
            urllib.error.URLError,
            http.client.IncompleteRead,
            ssl.SSLError,
            TimeoutError,
            ConnectionError,
        ) as error:
            failure = error

        if attempt == len(RETRY_DELAYS):
            raise failure
        sleep(RETRY_DELAYS[attempt])

    raise AssertionError("unreachable")


def install(output: Path, *, opener=None, sleep=None) -> None:
    output = output.resolve()
    if (
        output.is_file()
        and hashlib.sha256(output.read_bytes()).hexdigest() == BINARY_SHA256
    ):
        return

    archive = download(opener=opener, sleep=sleep)
    digest = hashlib.sha256(archive).hexdigest()
    if digest != SHA256:
        raise SystemExit(f"SkyEmu digest mismatch: expected {SHA256}, got {digest}")

    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        binary = bundle.read("SkyEmu")
    binary_digest = hashlib.sha256(binary).hexdigest()
    if binary_digest != BINARY_SHA256:
        raise SystemExit(
            f"SkyEmu binary mismatch: expected {BINARY_SHA256}, got {binary_digest}"
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as pending:
        pending.write(binary)
        pending_path = Path(pending.name)
    pending_path.chmod(0o755)
    os.replace(pending_path, output)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    install(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
