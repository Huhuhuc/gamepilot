"""Transparent baselines; all policies receive the same 76 features."""
import numpy as np

DIRECTIONS = np.array([[0, 0], [1, 0], [1, 1], [0, 1], [-1, 1], [-1, 0], [-1, -1], [0, -1], [1, -1]], dtype=float)
DIRECTIONS[2::2] /= np.sqrt(2)


def direction_index(vector):
    if np.linalg.norm(vector) < 0.01:
        return 0
    return int(np.argmax(DIRECTIONS @ vector))


def rule_action(obs):
    enemies = np.asarray(obs[12:60]).reshape(6, 8)
    active = enemies[enemies[:, 6] > 0.5]
    aim = np.zeros(2) if len(active) == 0 else active[0, :2]
    move = np.zeros(2)
    for enemy in active:
        relative = enemy[:2]
        distance = max(np.linalg.norm(relative), 0.02)
        move -= relative / distance**2
    walls = np.asarray(obs[68:76])
    move -= (DIRECTIONS[1:] * (1 / np.maximum(walls, 0.025) - 1)[:, None]).sum(axis=0) * 0.6
    if not len(active):
        move = np.array([0.5, 0.5]) - obs[:2]
    # Do not walk into a wall when an approximately safe alternative exists.
    scores = DIRECTIONS[1:] @ move
    scores -= np.where(walls < 0.055, 1000.0, 0.0)
    moving = int(np.argmax(scores)) + 1 if np.linalg.norm(move) > 0.01 else 0
    return np.array([moving, direction_index(aim)], dtype=np.int64)
