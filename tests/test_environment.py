import json
import socket
import threading
import numpy as np
import pytest
from gamepilot.env import PilotConnection, PilotEnv
from gamepilot.policies import DIRECTIONS, direction_index, rule_action


def test_fragmented_transport_and_disconnect():
    reader, writer = socket.socketpair()
    connection = object.__new__(PilotConnection)
    connection.connection = reader
    message = json.dumps({"text": "测试"}, ensure_ascii=False).encode()
    packet = len(message).to_bytes(4, "little") + message
    def send():
        for byte in packet:
            writer.sendall(bytes([byte]))
        writer.close()
    thread = threading.Thread(target=send)
    thread.start()
    try:
        assert json.loads(connection._get_data())["text"] == "测试"
        with pytest.raises(ConnectionError):
            connection._get_data()
    finally:
        reader.close()
        thread.join()


def test_action_direction_mapping():
    assert np.array_equal(DIRECTIONS[0], [0, 0])
    for index, vector in enumerate(DIRECTIONS):
        assert direction_index(vector) == index
    np.testing.assert_allclose(np.linalg.norm(DIRECTIONS[1:], axis=1), 1)


@pytest.fixture
def env():
    value = PilotEnv()
    yield value
    value.close()


def test_real_step_and_action_validation(env):
    _, initial = env.reset(seed=40)
    assert initial["pickups_collected"] == 0
    with pytest.raises(ValueError):
        env.step(np.array([9, 0]))
    _, reward, term, trunc, current = env.step(np.array([1, 0]))
    assert not term and not trunc
    assert current["seconds"] == pytest.approx(4/60)
    assert current["x"] - initial["x"] == pytest.approx(8.0)
    assert current["y"] == initial["y"]
    assert reward == pytest.approx(0.02 * 4/60)


def test_external_time_limit_is_truncation():
    env = PilotEnv(max_steps=1)
    try:
        env.reset(seed=40)
        _, _, terminated, truncated, info = env.step(np.array([0, 0]))
        assert not terminated and truncated and info["outcome"] == "truncated"
        with pytest.raises(RuntimeError):
            env.step(np.array([0, 0]))
    finally:
        env.close()


def test_real_death_reward_and_reset(env):
    env.reset(seed=817)
    reward_sum = 0
    for step in range(1000):
        _, reward, term, trunc, info = env.step(np.array([0, 0]))
        reward_sum += reward
        if term or trunc:
            break
    assert term and not trunc and info["outcome"] == "death"
    assert info["health"] == 0
    assert reward_sum == pytest.approx(info["seconds"]*0.02 + info["kills"]*0.2 - 4.5)
    with pytest.raises(RuntimeError):
        env.step(np.array([0, 0]))
    _, reset = env.reset(seed=817)
    assert reset["health"] == 5 and reset["reward"] == 0 and reset["kills"] == 0
    assert reset["pickups_collected"] == 0
    assert reset["bullets"] == 0 and reset["seconds"] == 0


def test_easy_curriculum_uses_real_game():
    env = PilotEnv(difficulty="easy")
    try:
        obs, info = env.reset(seed=0)
        assert obs.shape == (76,) and info["difficulty"] == "easy"
        enemies = obs[12:60].reshape(6, 8)
        assert np.all(enemies[enemies[:, 6] == 1, 5] == 0)
        for _ in range(20):
            obs, _, _, _, _ = env.step(np.array([1, 1]))
        assert env.observation_space.contains(obs)
    finally:
        env.close()


def test_disconnect_does_not_count_as_game_success(env):
    env.reset(seed=2)
    process = env.connection.proc
    process.terminate()
    process.wait(timeout=5)
    with pytest.raises((ConnectionError, OSError)):
        env.step(np.array([0, 0]))


def test_close_releases_owned_process():
    env = PilotEnv()
    process = env.connection.proc
    env.close()
    env.close()
    assert process.poll() is not None


def test_successful_full_episode_replays_across_processes():
    reference = []
    for attempt in range(2):
        env = PilotEnv()
        try:
            obs, _ = env.reset(seed=1000)
            for index in range(1000):
                action = rule_action(obs) if attempt == 0 else reference[index][0]
                obs, reward, term, trunc, info = env.step(action)
                if attempt == 0:
                    reference.append((action, obs.copy(), reward))
                else:
                    np.testing.assert_allclose(obs, reference[index][1], rtol=0, atol=1e-5)
                    assert reward == pytest.approx(reference[index][2], abs=1e-8)
                if term or trunc:
                    break
            assert term and not trunc and info["is_success"]
            assert 60 <= info["seconds"] < 60.04
            assert index+1 == len(reference)
        finally:
            env.close()
