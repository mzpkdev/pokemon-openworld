import hashlib
import http.client
import io
from pathlib import Path
import ssl
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import zipfile

from tools.e2e import install_skyemu


class Response:
    def __init__(self, body):
        self.body = body
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.closed = True
        return False

    def read(self):
        if isinstance(self.body, BaseException):
            raise self.body
        return self.body


def archive_with(binary):
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("SkyEmu", binary)
    return archive.getvalue()


class InstallSkyEmuTest(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.output = Path(self.temporary_directory.name) / "SkyEmu-v5"

    def valid_digests(self, archive, binary):
        return patch.multiple(
            install_skyemu,
            SHA256=hashlib.sha256(archive).hexdigest(),
            BINARY_SHA256=hashlib.sha256(binary).hexdigest(),
        )

    def test_transient_http_failure_then_success(self):
        binary = b"valid SkyEmu"
        archive = archive_with(binary)
        response = Response(archive)
        outcomes = iter(
            [
                urllib.error.HTTPError(
                    install_skyemu.URL, 503, "unavailable", {}, None
                ),
                response,
            ]
        )
        attempts = []
        delays = []

        def opener(url, *, timeout):
            attempts.append((url, timeout))
            outcome = next(outcomes)
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome

        with self.valid_digests(archive, binary):
            install_skyemu.install(self.output, opener=opener, sleep=delays.append)

        self.assertEqual(self.output.read_bytes(), binary)
        self.assertTrue(response.closed)
        self.assertEqual(attempts, [(install_skyemu.URL, 60)] * 2)
        self.assertEqual(delays, [1])

    def test_incomplete_read_then_success(self):
        binary = b"valid SkyEmu"
        archive = archive_with(binary)
        responses = [
            Response(http.client.IncompleteRead(b"truncated", len(archive))),
            Response(archive),
        ]
        outcomes = iter(responses)
        attempts = []
        delays = []

        def opener(url, *, timeout):
            attempts.append((url, timeout))
            return next(outcomes)

        with self.valid_digests(archive, binary):
            install_skyemu.install(self.output, opener=opener, sleep=delays.append)

        self.assertEqual(self.output.read_bytes(), binary)
        self.assertTrue(all(response.closed for response in responses))
        self.assertEqual(attempts, [(install_skyemu.URL, 60)] * 2)
        self.assertEqual(delays, [1])

    def test_tls_read_failure_then_success_uses_current_defaults(self):
        binary = b"valid SkyEmu"
        archive = archive_with(binary)
        responses = [
            Response(ssl.SSLEOFError(8, "unexpected EOF")),
            Response(archive),
        ]
        outcomes = iter(responses)

        with (
            self.valid_digests(archive, binary),
            patch.object(
                install_skyemu.urllib.request,
                "urlopen",
                side_effect=lambda url, *, timeout: next(outcomes),
            ) as opener,
            patch.object(install_skyemu.time, "sleep") as sleep,
        ):
            install_skyemu.install(self.output)

        self.assertEqual(self.output.read_bytes(), binary)
        self.assertTrue(all(response.closed for response in responses))
        self.assertEqual(
            opener.call_args_list,
            [unittest.mock.call(install_skyemu.URL, timeout=60)] * 2,
        )
        sleep.assert_called_once_with(1)

    def test_transient_failures_exhaust_four_attempts(self):
        cases = (
            ("url error", lambda: urllib.error.URLError("connection reset")),
            ("timeout", lambda: TimeoutError("timed out")),
            ("connection reset", lambda: ConnectionResetError("connection reset")),
        )

        for name, failure in cases:
            with self.subTest(name=name):
                attempts = []
                delays = []

                def opener(url, *, timeout):
                    attempts.append((url, timeout))
                    raise failure()

                with self.assertRaises(type(failure())):
                    install_skyemu.install(
                        self.output,
                        opener=opener,
                        sleep=delays.append,
                    )

                self.assertEqual(attempts, [(install_skyemu.URL, 60)] * 4)
                self.assertEqual(delays, [1, 2, 4])

    def test_permanent_http_error_is_not_retried(self):
        attempts = []
        delays = []
        response_stream = io.BytesIO(b"not found")

        def opener(url, *, timeout):
            attempts.append((url, timeout))
            raise urllib.error.HTTPError(url, 404, "not found", {}, response_stream)

        with self.assertRaises(urllib.error.HTTPError) as raised:
            install_skyemu.install(self.output, opener=opener, sleep=delays.append)

        self.assertEqual(raised.exception.code, 404)
        self.assertTrue(response_stream.closed)
        self.assertEqual(attempts, [(install_skyemu.URL, 60)])
        self.assertEqual(delays, [])

    def test_valid_existing_binary_avoids_network(self):
        binary = b"cached SkyEmu"
        self.output.write_bytes(binary)

        def unexpected_opener(url, *, timeout):
            self.fail(f"unexpected download of {url} with timeout {timeout}")

        with patch.object(
            install_skyemu,
            "BINARY_SHA256",
            hashlib.sha256(binary).hexdigest(),
        ):
            install_skyemu.install(self.output, opener=unexpected_opener)

    def test_invalid_existing_binary_is_replaced_with_verified_download(self):
        binary = b"valid SkyEmu"
        archive = archive_with(binary)
        response = Response(archive)
        self.output.write_bytes(b"corrupt cached SkyEmu")

        with self.valid_digests(archive, binary):
            install_skyemu.install(
                self.output,
                opener=lambda url, *, timeout: response,
            )

        self.assertEqual(self.output.read_bytes(), binary)
        self.assertTrue(response.closed)

    def test_archive_digest_mismatch_is_fatal_without_retry(self):
        attempts = []
        delays = []
        response = Response(b"corrupt archive")

        def opener(url, *, timeout):
            attempts.append((url, timeout))
            return response

        with patch.object(install_skyemu, "SHA256", "0" * 64):
            with self.assertRaises(SystemExit, msg="digest mismatch"):
                install_skyemu.install(self.output, opener=opener, sleep=delays.append)

        self.assertEqual(attempts, [(install_skyemu.URL, 60)])
        self.assertEqual(delays, [])
        self.assertTrue(response.closed)

    def test_binary_digest_mismatch_is_fatal_without_retry_or_output(self):
        binary = b"corrupt SkyEmu"
        archive = archive_with(binary)
        response = Response(archive)
        attempts = []
        delays = []

        def opener(url, *, timeout):
            attempts.append((url, timeout))
            return response

        with (
            patch.object(install_skyemu, "SHA256", hashlib.sha256(archive).hexdigest()),
            patch.object(install_skyemu, "BINARY_SHA256", "0" * 64),
            self.assertRaises(SystemExit, msg="binary mismatch"),
        ):
            install_skyemu.install(self.output, opener=opener, sleep=delays.append)

        self.assertEqual(attempts, [(install_skyemu.URL, 60)])
        self.assertEqual(delays, [])
        self.assertFalse(self.output.exists())
        self.assertTrue(response.closed)

    def test_atomic_replace_failure_preserves_existing_destination(self):
        old_binary = b"existing corrupt SkyEmu"
        binary = b"valid SkyEmu"
        archive = archive_with(binary)
        self.output.write_bytes(old_binary)

        with (
            self.valid_digests(archive, binary),
            patch.object(install_skyemu.os, "replace", side_effect=OSError("replace")),
            self.assertRaises(OSError, msg="replace"),
        ):
            install_skyemu.install(
                self.output,
                opener=lambda url, *, timeout: Response(archive),
            )

        self.assertEqual(self.output.read_bytes(), old_binary)


if __name__ == "__main__":
    unittest.main()
