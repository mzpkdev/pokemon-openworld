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
FIELD_DIRECTIONS = {"Down": 1, "Up": 2, "Left": 3, "Right": 4}
SAVE_BLOCK1_FLAGS_OFFSET = 0x1270
SAVE_BLOCK1_VARS_OFFSET = 0x139C
VARS_START = 0x4000
VARS_END = 0x40FF
FLAGS_COUNT = 0x960
SETTINGS_SIZE = 1024
SETTINGS_THEME_OFFSET = 8
SETTINGS_VERSION_OFFSET = 12
CUSTOM_THEME = 3
SETTINGS_VERSION = 3


class Symbols:
    def __init__(self, path: Path):
        self._values: dict[str, int] = {}
        self._all_values: dict[str, list[int]] = {}
        self._globals: set[str] = set()
        self._ambiguous: set[str] = set()
        for number, line in enumerate(path.read_text().splitlines(), 1):
            fields = line.split()
            if len(fields) < 4 or len(fields[0]) != 8:
                raise ValueError(f"{path}:{number}: malformed symbol line")
            try:
                value = int(fields[0], 16)
            except ValueError as error:
                raise ValueError(
                    f"{path}:{number}: malformed symbol address"
                ) from error
            binding = fields[1]
            name = fields[-1]
            values = self._all_values.setdefault(name, [])
            if value not in values:
                values.append(value)
            previous = self._values.get(name)
            if previous is None:
                self._values[name] = value
                if binding == "g":
                    self._globals.add(name)
            elif binding == "g":
                if name in self._globals and previous != value:
                    raise ValueError(
                        f"{path}:{number}: conflicting global symbol {name}"
                    )
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

    def addresses(self, name: str) -> tuple[int, ...]:
        try:
            return tuple(self._all_values[name])
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

    def _bytes(
        self, command: str, params: list[tuple[str, str]] | None = None
    ) -> bytes:
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
        params = [
            (button, "1" if pressed else "0") for button, pressed in states.items()
        ]
        result = self._text("input", params)
        if result != "ok":
            raise RuntimeError(f"SkyEmu input failed: {result}")

    def press(self, button: str, hold_frames: int = 1, release_frames: int = 1) -> None:
        self.set_buttons(**{button: True})
        self.step(hold_frames)
        self.set_buttons(**{button: False})
        self.step(release_frames)

    def read(self, address: int, size: int) -> bytes:
        if size < 0:
            raise ValueError("size must not be negative")
        if size == 0:
            return b""
        params = [("addr", f"{address + offset:08x}") for offset in range(size)]
        return bytes.fromhex(self._text("read_byte", params))

    def write(self, address: int, data: bytes) -> None:
        if not data:
            return
        params = [
            (f"{address + offset:08x}", f"{value:02x}")
            for offset, value in enumerate(data)
        ]
        result = self._text("write_byte", params)
        if result != "ok":
            raise RuntimeError(f"SkyEmu write failed: {result}")

    def read_u8(self, address: int) -> int:
        return self.read(address, 1)[0]

    def read_u16(self, address: int) -> int:
        return struct.unpack("<H", self.read(address, 2))[0]

    def read_u32(self, address: int) -> int:
        return struct.unpack("<I", self.read(address, 4))[0]

    def write_u8(self, address: int, value: int) -> None:
        self.write(address, bytes((value & 0xFF,)))

    def write_u16(self, address: int, value: int) -> None:
        self.write(address, struct.pack("<H", value & 0xFFFF))

    def address(self, symbol: str) -> int:
        return self.symbols[symbol]

    def pointer(self, symbol: str) -> int:
        return self.read_u32(self.address(symbol))

    def save_block1(self) -> int:
        address = self.pointer("gSaveBlock1Ptr")
        if address == 0:
            raise RuntimeError("SaveBlock1 is not initialized")
        return address

    def save_block2(self) -> int:
        address = self.pointer("gSaveBlock2Ptr")
        if address == 0:
            raise RuntimeError("SaveBlock2 is not initialized")
        return address

    def position(self) -> tuple[int, int]:
        block = self.save_block1()
        return self.read_u16(block), self.read_u16(block + 2)

    def map_id(self) -> tuple[int, int]:
        block = self.save_block1()
        return self.read_u8(block + 4), self.read_u8(block + 5)

    def read_var(self, var_id: int) -> int:
        if not VARS_START <= var_id <= VARS_END:
            raise ValueError(f"not a saved variable id: 0x{var_id:x}")
        offset = SAVE_BLOCK1_VARS_OFFSET + (var_id - VARS_START) * 2
        return self.read_u16(self.save_block1() + offset)

    def read_flag(self, flag_id: int) -> bool:
        if not 0 < flag_id < FLAGS_COUNT:
            raise ValueError(f"not a saved flag id: 0x{flag_id:x}")
        byte = self.read_u8(
            self.save_block1() + SAVE_BLOCK1_FLAGS_OFFSET + flag_id // 8
        )
        return bool(byte & (1 << (flag_id % 8)))

    def set_flag(self, flag_id: int, enabled: bool = True) -> None:
        if not 0 < flag_id < FLAGS_COUNT:
            raise ValueError(f"not a saved flag id: 0x{flag_id:x}")
        address = self.save_block1() + SAVE_BLOCK1_FLAGS_OFFSET + flag_id // 8
        mask = 1 << (flag_id % 8)
        current = self.read_u8(address)
        value = current | mask if enabled else current & ~mask
        self.write_u8(address, value)
        if self.read_flag(flag_id) != enabled:
            raise RuntimeError(f"failed to update flag 0x{flag_id:x}")

    def controls_locked(self) -> bool:
        return bool(self.read_u8(self.address("sLockFieldControls")))

    def script_status(self) -> int:
        return self.read_u8(self.address("sGlobalScriptContextStatus"))

    def movement_idle(self) -> bool:
        return self.read_u8(self.address("gPlayerAvatar") + 3) == 0

    def facing_direction(self) -> int:
        object_id = self.read_u8(self.address("gPlayerAvatar") + 5)
        return (
            self.read_u8(self.address("gObjectEvents") + object_id * 0x24 + 0x18) & 0xF
        )

    def task_active(self, symbol: str) -> bool:
        expected = self.address(symbol) | 1
        tasks = self.address("gTasks")
        for task_id in range(16):
            task = tasks + task_id * 0x28
            if self.read_u8(task + 4) and self.read_u32(task) == expected:
                return True
        return False

    def callback_is(self, symbol: str) -> bool:
        callback2 = self.read_u32(self.symbols["gMain"] + 4)
        return callback2 == (self.symbols[symbol] | 1)

    def battler_controller_is(self, address: int, battler: int = 0) -> bool:
        if not 0 <= battler < 4:
            raise ValueError(f"invalid battler: {battler}")
        actual = self.read_u32(self.address("gBattlerControllerFuncs") + battler * 4)
        return actual == (address | 1)

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

    def wait_until(
        self,
        predicate,
        *,
        description: str,
        max_frames: int,
        step_frames: int = 1,
    ) -> None:
        elapsed = 0
        while elapsed <= max_frames:
            if predicate():
                return
            frames = min(step_frames, max_frames - elapsed + 1)
            self.step(frames)
            elapsed += frames
        raise AssertionError(f"{description} not reached in {max_frames} frames")

    def wait_for_map(self, expected: tuple[int, int], max_frames: int = 1_200) -> None:
        self.wait_until(
            lambda: self.map_id() == expected,
            description=f"map {expected}",
            max_frames=max_frames,
            step_frames=4,
        )

    def wait_for_controls_unlocked(self, max_frames: int = 1_200) -> None:
        self.wait_until(
            lambda: not self.controls_locked() and self.script_status() == 2,
            description="unlocked field controls",
            max_frames=max_frames,
            step_frames=2,
        )

    def advance_until(
        self,
        predicate,
        *,
        description: str,
        max_pulses: int = 600,
        button: str = "A",
        pulse_frames: int = 2,
    ) -> None:
        for _ in range(max_pulses + 1):
            if predicate():
                return
            self.press(button, hold_frames=1, release_frames=pulse_frames)
        raise AssertionError(
            f"{description} not reached after {max_pulses} {button} pulses"
        )

    def move_to(
        self,
        *,
        x: int | None = None,
        y: int | None = None,
        max_pulses: int = 500,
    ) -> None:
        if x is None and y is None:
            raise ValueError("move_to needs an x or y coordinate")
        for _ in range(max_pulses):
            current_x, current_y = self.position()
            at_x = x is None or current_x == x
            at_y = y is None or current_y == y
            if at_x and at_y:
                for _ in range(24):
                    if self.movement_idle() and self.position() == (
                        current_x,
                        current_y,
                    ):
                        return
                    self.step()
                    if self.position() != (current_x, current_y):
                        break
                continue
            if x is not None and current_x != x:
                button = "Right" if current_x < x else "Left"
            elif y is not None and current_y != y:
                button = "Down" if current_y < y else "Up"
            else:
                return
            self.press(button, hold_frames=3, release_frames=1)
        raise AssertionError(
            f"position ({x if x is not None else '*'}, {y if y is not None else '*'}) "
            f"not reached; actual={self.position()}, map={self.map_id()}"
        )

    def face(self, button: str, max_pulses: int = 20) -> None:
        try:
            expected = FIELD_DIRECTIONS[button]
        except KeyError as error:
            raise ValueError(f"not a field direction: {button}") from error
        start = self.position()
        for _ in range(max_pulses):
            if self.facing_direction() == expected and self.movement_idle():
                return
            self.press(button, hold_frames=2, release_frames=1)
            if self.position() != start:
                raise AssertionError(
                    f"facing {button} moved player from {start} to {self.position()}"
                )
        raise AssertionError(
            f"player did not face {button}; facing={self.facing_direction()}"
        )

    def move_path(self, *points: tuple[int | None, int | None]) -> None:
        for x, y in points:
            self.move_to(x=x, y=y)

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
