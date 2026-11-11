extends AIController2D
## State features use the original game, not a second combat simulation.
const DIRECTIONS := [Vector2.ZERO, Vector2.RIGHT, Vector2(0.7071067811865476, 0.7071067811865476), Vector2.DOWN,
	Vector2(-0.7071067811865476, 0.7071067811865476), Vector2.LEFT, Vector2(-0.7071067811865476, -0.7071067811865476), Vector2.UP, Vector2(0.7071067811865476, -0.7071067811865476)]
var world: Node2D

func _physics_process(_delta: float) -> void:
	pass # The session owns episode termination and explicit resets.

func get_action_space() -> Dictionary:
	return {"move": {"size": 9, "action_type": "discrete"}, "shoot": {"size": 9, "action_type": "discrete"}}

func set_action(action) -> void:
	world.player.agent_move = DIRECTIONS[int(action["move"])]
	world.player.agent_shoot = DIRECTIONS[int(action["shoot"])]

func get_reward() -> float:
	return reward

func get_obs() -> Dictionary:
	var p: Player = world.player
	var values: Array = [p.position.x / 256.0, p.position.y / 256.0,
		p.velocity.x / 600.0, p.velocity.y / 600.0, float(p.current_health) / p.max_health,
		p.invulnerability_time_left / maxf(p.invulnerability_duration, 0.001),
		p.shooting_timer.time_left / maxf(p.fire_interval, 0.001), world.stage_time_left / world.stage_duration,
		p.speed_buff_time_left / 120.0, p.rapid_buff_time_left / 120.0, p.form_buff_time_left / 120.0,
		float(p.current_shot_pattern)]
	var enemies: Array = []
	for enemy in world.enemy_container.get_children():
		if not enemy.is_dead:
			enemies.append(enemy)
	enemies.sort_custom(func(a, b):
		var da: float = p.position.distance_squared_to(a.global_position)
		var db: float = p.position.distance_squared_to(b.global_position)
		return a.spawn_id < b.spawn_id if is_equal_approx(da, db) else da < db)
	for index in range(6):
		if index >= enemies.size():
			values.append_array([0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
			continue
		var e: Enemy = enemies[index]
		var relative := (e.global_position - p.global_position) / 256.0
		var relative_velocity := (e.velocity - p.velocity) / 600.0
		values.append_array([relative.x, relative.y, relative_velocity.x, relative_velocity.y,
			float(e.current_health) / 20.0, float(e.config.enemy_type) / 3.0, 1.0, e.config.collision_radius / 64.0])
	var pickups: Array = []
	for child in world.get_children():
		if child is Pickup and not child.is_expiring:
			pickups.append(child)
	pickups.sort_custom(func(a, b): return p.position.distance_squared_to(a.position) < p.position.distance_squared_to(b.position))
	for index in range(2):
		if index >= pickups.size():
			values.append_array([0.0, 0.0, 0.0, 0.0])
		else:
			var pickup: Pickup = pickups[index]
			var offset := (pickup.global_position - p.global_position) / 256.0
			values.append_array([offset.x, offset.y, float(pickup.config.pickup_type) / 2.0, 1.0])
	for index in range(1, 9):
		var query := PhysicsRayQueryParameters2D.create(p.global_position, p.global_position + DIRECTIONS[index] * 256.0, 1)
		var hit := p.get_world_2d().direct_space_state.intersect_ray(query)
		values.append(1.0 if hit.is_empty() else p.global_position.distance_to(hit.position) / 256.0)
	for index in range(values.size()):
		values[index] = clampf(float(values[index]), -1.0, 1.0)
	return {"obs": values}
