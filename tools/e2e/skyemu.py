from __future__ import annotations

import os
from pathlib import Path
import shutil
import signal
import socket
import struct
import subprocess
import time
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import urlopen


BUTTONS = ("A", "B", "Up", "Down", "Left", "Right", "L", "R", "Start", "Select")
SETTINGS_SIZE = 1024
SETTINGS_THEME_OFFSET = 8
SETTINGS_VERSION_OFFSET = 12
CUSTOM_THEME = 3
SETTINGS_VERSION = 3


class Symbols:
    def __init__(self, path: Path):
        self._values: dict[str, int] = {}
        self._globals: set[str] = set()
        self._ambiguous: set[str] = set()
        for number, line in enumerate(path.read_text().splitlines(), 1):
            fields = line.split()
            if len(fields) < 4 or len(fields[0]) != 8:
                raise ValueError(f"{path}:{number}: malformed symbol line")
            try:
                value = int(fields[0], 16)
            except ValueError as error:
                raise ValueError(f"{path}:{number}: malformed symbol address") from error
            binding = fields[1]
            name = fields[-1]
            previous = self._values.get(name)
            if previous is None:
                self._values[name] = value
                if binding == "g":
                    self._globals.add(name)
            elif binding == "g":
                if name in self._globals and previous != value:
                    raise ValueError(f"{path}:{number}: conflicting global symbol {name}")
                self._values[name] = value
                self._globals.add(name)
                self._ambiguous.discard(name)
            elif name not in self._globals and previous != value:
                self._ambiguous.add(name)

    def __getitem__(self, name: str) -> int:
        if name in self._ambiguous:
            raise KeyError(f"ambiguous local ROM symbol: {name}")
        try:
            return self._values[name]
        except KeyError as error:
            raise KeyError(f"missing ROM symbol: {name}") from error


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


class SkyEmuSession:
    def __init__(self, binary: Path, rom: Path, symbols: Symbols, workdir: Path):
        self.symbols = symbols
        self.workdir = workdir
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.rom = self.workdir / "game.gba"
        shutil.copy2(rom, self.rom)
        self.log_path = self.workdir / "skyemu.log"
        self.port = _free_port()
        data_home = self.workdir / "skyemu-data"
        config_home = self.workdir / "skyemu-config"
        settings_path = data_home / "Sky" / "SkyEmu" / "user_settings.bin"
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        config_home.mkdir(parents=True, exist_ok=True)

        # SkyEmu v5's HTTP mode loads the default theme before graphics setup,
        # which trips an internal sg_make_image assertion. An empty custom
        # theme skips that UI-only path and keeps the released server headless.
        settings = bytearray(SETTINGS_SIZE)
        struct.pack_into("<I", settings, SETTINGS_THEME_OFFSET, CUSTOM_THEME)
        struct.pack_into("<I", settings, SETTINGS_VERSION_OFFSET, SETTINGS_VERSION)
        settings_path.write_bytes(settings)

        command = [str(binary.resolve()), "http_server", str(self.port), str(self.rom)]
        environment = os.environ.copy()
        environment["XDG_CONFIG_HOME"] = str(config_home)
        environment["XDG_DATA_HOME"] = str(data_home)
        self._log = self.log_path.open("wb")
        self.process = subprocess.Popen(
            command,
            cwd=self.workdir,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=self._log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            self._wait_until_ready()
            self._text("load_rom", [("path", str(self.rom)), ("pause", "1")])
            self.set_buttons(**{button: False for button in BUTTONS})
        except BaseException:
            self.close()
            raise

    def _url(self, command: str, params: list[tuple[str, str]] | None = None) -> str:
        query = "" if not params else "?" + urlencode(params)
        return f"http://127.0.0.1:{self.port}/{command}{query}"

    def _bytes(self, command: str, params: list[tuple[str, str]] | None = None) -> bytes:
        with urlopen(self._url(command, params), timeout=10) as response:
            return response.read()

    def _text(self, command: str, params: list[tuple[str, str]] | None = None) -> str:
        return self._bytes(command, params).decode("utf-8").rstrip("\x00\r\n ")

    def _wait_until_ready(self) -> None:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError(
                    f"SkyEmu exited with {self.process.returncode}; see {self.log_path}"
                )
            try:
                if self._text("ping") == "pong":
                    return
            except (OSError, URLError):
                time.sleep(0.05)
        raise TimeoutError(f"SkyEmu did not bind port {self.port}; see {self.log_path}")

    def step(self, frames: int = 1) -> None:
        if frames < 1:
            raise ValueError("frames must be positive")
        result = self._text("step", [("frames", str(frames))])
        if result != "ok":
            raise RuntimeError(f"SkyEmu step failed: {result}")

    def set_buttons(self, **states: bool) -> None:
        unknown = states.keys() - set(BUTTONS)
        if unknown:
            raise ValueError(f"unknown buttons: {sorted(unknown)}")
        params = [(button, "1" if pressed else "0") for button, pressed in states.items()]
        result = self._text("input", params)
        if result != "ok":
            raise RuntimeError(f"SkyEmu input failed: {result}")

    def press(self, button: str, hold_frames: int = 1, release_frames: int = 1) -> None:
        self.set_buttons(**{button: True})
        self.step(hold_frames)
        self.set_buttons(**{button: False})
        self.step(release_frames)

    def read(self, address: int, size: int) -> bytes:
        params = [("addr", f"{address + offset:08x}") for offset in range(size)]
        return bytes.fromhex(self._text("read_byte", params))

    def read_u32(self, address: int) -> int:
        return struct.unpack("<I", self.read(address, 4))[0]

    def callback_is(self, symbol: str) -> bool:
        callback2 = self.read_u32(self.symbols["gMain"] + 4)
        return callback2 == (self.symbols[symbol] | 1)

    def wait_for_callback(self, symbol: str, max_frames: int) -> None:
        for _ in range(max_frames + 1):
            if self.callback_is(symbol):
                return
            self.step()
        actual = self.read_u32(self.symbols["gMain"] + 4)
        raise AssertionError(
            f"callback {symbol} not reached in {max_frames} frames; "
            f"callback2=0x{actual:08x}"
        )

    def screenshot(self, output: Path) -> None:
        output.write_bytes(self._bytes("screen", [("format", "png")]))

    def save_state(self, output: Path) -> None:
        result = self._text("save", [("path", str(output.resolve()))])
        if result != "ok":
            raise RuntimeError(f"SkyEmu save failed: {result}")

    def close(self) -> None:
        if self.process.poll() is None:
            os.killpg(self.process.pid, signal.SIGTERM)
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(self.process.pid, signal.SIGKILL)
                self.process.wait(timeout=5)
        self._log.close()
