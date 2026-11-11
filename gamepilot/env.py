"""Real Godot game -> upstream GodotEnv spaces -> explicit Gymnasium episode API."""
from __future__ import annotations
import atexit
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile

import gymnasium as gym
import numpy as np
from godot_rl.core.godot_env import GodotEnv

ROOT = Path(__file__).resolve().parents[1]


def godot_path() -> str:
    configured = os.environ.get("GODOT_BIN")
    options = [configured, shutil.which("godot"), shutil.which("godot4"),
               r"D:\godot v4.6.1\Godot_v4.6.1-stable_win64.exe"]
    for path in options:
        if path and Path(path).is_file():
            return str(path)
    raise FileNotFoundError("Set GODOT_BIN to the Godot 4.6.1 executable")


class PilotConnection(GodotEnv):
    """Reuse upstream handshake/space construction, harden transport and lifecycle.

    We intentionally do not use upstream step_recv/reset: release 0.8.1 conflates
    termination/truncation, drops info and does not forward the reset seed.
    """
    def __init__(self, *, visible=False, timeout=30):
        self.visible = visible
        self.timeout = timeout
        self.closed = False
        self.log_directory = tempfile.TemporaryDirectory(prefix="gamepilot-")
        self.game_log = tempfile.TemporaryFile(mode="w+b")
        try:
            # Upstream prints editor instructions, but this subclass starts Godot itself.
            with redirect_stdout(io.StringIO()):
                super().__init__(env_path=None, port=0, convert_action_space=True)
        except BaseException:
            self.close()
            raise

    def _start_server(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            listener.settimeout(self.timeout)
            port = listener.getsockname()[1]
            command = [godot_path(), "--path", str(ROOT / "game"), "--fixed-fps", "60", "--audio-driver", "Dummy"]
            command += ["--max-fps", "60"] if self.visible else ["--headless", "--disable-render-loop"]
            command += ["--log-file", str(Path(self.log_directory.name) / "engine.log"), "--", f"--port={port}"]
            self.proc = subprocess.Popen(command, stdout=self.game_log, stderr=subprocess.STDOUT)
            try:
                connection, _ = listener.accept()
            except (TimeoutError, OSError) as error:
                self.game_log.seek(0)
                detail = self.game_log.read().decode("utf-8", errors="replace")[-4000:]
                raise ConnectionError("Godot did not connect. " + detail) from error
        connection.settimeout(self.timeout)
        connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        return connection

    def _read_exact(self, size):
        chunks = bytearray()
        while len(chunks) < size:
            part = self.connection.recv(size - len(chunks))
            if not part:
                raise ConnectionError("Godot disconnected during a message")
            chunks.extend(part)
        return bytes(chunks)

    def _get_data(self):
        size = int.from_bytes(self._read_exact(4), "little")
        if size > 1_048_576:
            raise ValueError("Godot message exceeds 1 MiB")
        return self._read_exact(size).decode("utf-8")

    def _send_string(self, value):
        payload = value.encode("utf-8")
        self.connection.sendall(len(payload).to_bytes(4, "little") + payload)

    def request(self, message):
        self._send_as_json(message)
        result = self._get_json_dict()
        if result.get("type") == "error":
            raise RuntimeError(result["message"])
        return result

    def close(self):
        if self.closed:
            return
        self.closed = True
        atexit.unregister(self._close)
        connection = getattr(self, "connection", None)
        if connection:
            try:
                self._send_as_json({"type": "close"})
            except OSError:
                pass
            connection.close()
        process = getattr(self, "proc", None)
        if process:
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=5)
        self.game_log.close()
        self.log_directory.cleanup()


class PilotEnv(gym.Env):
    metadata = {"render_modes": ["human"], "render_fps": 15}

    def __init__(self, *, visible=False, difficulty="original", max_steps=1000):
        if difficulty not in ("original", "easy"):
            raise ValueError("difficulty must be original or easy")
        if max_steps < 1:
            raise ValueError("max_steps must be positive")
        self.connection = PilotConnection(visible=visible)
        self.observation_space = self.connection.observation_space["obs"]
        self.action_space = gym.spaces.MultiDiscrete([9, 9])
        self.render_mode = "human" if visible else None
        self.difficulty = difficulty
        self.max_steps = max_steps
        self.ended = True
        self.steps = 0

    def _obs(self, result):
        if not result.get("obs") or "obs" not in result["obs"][0]:
            self.connection.game_log.seek(0)
            detail = self.connection.game_log.read().decode("utf-8", errors="replace")[-3000:]
            raise RuntimeError("Invalid game response: " + detail)
        obs = np.asarray(result["obs"][0]["obs"], dtype=np.float32)
        if not self.observation_space.contains(obs):
            raise ValueError("Non-finite or out-of-range game observation")
        return obs

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        episode_seed = int(seed if seed is not None else self.np_random.integers(0, 2**31 - 1))
        result = self.connection.request({"type": "reset", "seed": episode_seed, "difficulty": self.difficulty})
        self.steps = 0
        self.ended = False
        return self._obs(result), result["info"][0]

    def step(self, action):
        if self.ended:
            raise RuntimeError("reset is required before step or after a terminal state")
        if not self.action_space.contains(action):
            raise ValueError("action must be two integer indices in [0, 8]")
        result = self.connection.request({"type": "action", "action": [{"move": int(action[0]), "shoot": int(action[1])}]})
        self.steps += 1
        terminated = bool(result["done"][0])
        truncated = self.steps >= self.max_steps and not terminated
        self.ended = terminated or truncated
        info = result["info"][0]
        if truncated:
            info["outcome"] = "truncated"
        reward = float(result["reward"][0])
        if not np.isfinite(reward):
            raise ValueError("Non-finite game reward")
        return self._obs(result), reward, terminated, truncated, info

    def close(self):
        self.connection.close()
