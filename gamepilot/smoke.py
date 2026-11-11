import json
import time
import numpy as np
from gymnasium.utils.env_checker import check_env
from .env import PilotEnv


def main():
    started = time.monotonic()
    env = PilotEnv()
    try:
        check_env(env, skip_render_check=True)
        for seed in range(100):
            obs, info = env.reset(seed=seed)
            assert info["seconds"] == 0 and info["health"] == 5
            assert info["bullets"] == 0 and info["enemies"] == 1 and info["pickups"] == 3
            env.step(np.array([1, 1]))
        traces = []
        for _ in range(2):
            obs, info = env.reset(seed=817)
            trajectory = []
            rng = np.random.default_rng(73)
            for index in range(300):
                obs, reward, done, trunc, info = env.step(rng.integers(0, 9, size=2))
                trajectory.append((obs.copy(), reward, done, info))
                if done or trunc:
                    break
            traces.append(trajectory)
        assert len(traces[0]) == len(traces[1])
        max_difference = 0.0
        for left, right in zip(*traces):
            max_difference = max(max_difference, float(np.max(np.abs(left[0] - right[0]))))
            np.testing.assert_allclose(left[0], right[0], atol=1e-5, rtol=0)
            assert left[1:] == right[1:]
        print(json.dumps({"reset_episodes": 100, "replay_steps": len(traces[0]),
            "max_observation_difference": max_difference, "seconds": round(time.monotonic()-started, 2)}))
    finally:
        env.close()


if __name__ == "__main__":
    main()
