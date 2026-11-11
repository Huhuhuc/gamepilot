extends Node2D
## Protocol-compatible adapter for Godot RL 0.7, with explicit seed/reset/terminal semantics.
const GAME := preload("res://scence/game.tscn")
const CONTROLLER := preload("res://rl/controller.gd")
var world: Node2D
var controller: AIController2D
var stream: StreamPeerTCP
var training := false
var pending := ""
var remaining_frames := 0
var response_ready := false
var observation: Dictionary
var episode_seed := 0
var difficulty := "original"
var episode_index := 0
var decisions := 0
var previous_kills := 0
var previous_health := 5
var previous_time := 0.0
var total_reward := 0.0
var stuck_steps := 0
var last_position := Vector2.ZERO
var step_reward := 0.0
var terminal_paid := false
var capture_requested := false

func _ready() -> void:
	process_mode = Node.PROCESS_MODE_ALWAYS
	process_physics_priority = 1000
	var args := {}
	for argument in OS.get_cmdline_user_args():
		var pair := argument.trim_prefix("--").split("=", true, 1)
		if pair.size() == 2:
			args[pair[0]] = pair[1]
	training = args.has("port")
	if not training:
		world = GAME.instantiate()
		world.process_mode = Node.PROCESS_MODE_PAUSABLE
		add_child(world)
		return
	AudioServer.set_bus_mute(0, true)
	get_tree().paused = true
	controller = CONTROLLER.new()
	controller.process_mode = Node.PROCESS_MODE_ALWAYS
	add_child(controller)
	stream = StreamPeerTCP.new()
	stream.connect_to_host("127.0.0.1", int(args["port"]))
	var deadline := Time.get_ticks_msec() + 10000
	while Time.get_ticks_msec() < deadline:
		stream.poll()
		if stream.get_status() == StreamPeerTCP.STATUS_CONNECTED:
			break
		OS.delay_msec(10)
	if stream.get_status() != StreamPeerTCP.STATUS_CONNECTED:
		push_error("GamePilot could not connect to the Python listener")
		get_tree().quit(2)
		return
	stream.set_no_delay(true)
	_reset_world(0, "original")

func _physics_process(_delta: float) -> void:
	if not training or pending.is_empty() or response_ready:
		return
	remaining_frames -= 1
	if remaining_frames > 0 and not world.result_shown:
		return
	get_tree().paused = true
	observation = controller.get_obs()
	# The arena is fixed at 256x256. Keep presentation independent of paused cameras.
	get_viewport().canvas_transform = Transform2D(Vector2(2, 0), Vector2(0, 2), Vector2(64, 64))
	if decisions >= 80 and not capture_requested and OS.has_environment("GAMEPILOT_CAPTURE"):
		capture_requested = true
		RenderingServer.frame_post_draw.connect(_capture_frame, CONNECT_ONE_SHOT)
	response_ready = true

func _capture_frame() -> void:
	get_viewport().get_texture().get_image().save_png(OS.get_environment("GAMEPILOT_CAPTURE"))

func _process(_delta: float) -> void:
	if not training or stream == null or stream.get_status() != StreamPeerTCP.STATUS_CONNECTED:
		return
	if response_ready:
		response_ready = false
		if pending == "reset":
			_send({"type": "reset", "obs": [observation], "info": [_info()]})
		else:
			decisions += 1
			var elapsed: float = world.game_time_elapsed - previous_time
			step_reward = elapsed * 0.02 + (world.kills - previous_kills) * 0.2 - (previous_health - world.player.current_health) * 0.5
			if world.result_shown and not terminal_paid:
				step_reward += -2.0 if world.player.is_dead else 2.0
				terminal_paid = true
			total_reward += step_reward
			if world.player.agent_move != Vector2.ZERO and last_position.distance_to(world.player.position) < 0.1:
				stuck_steps += 1
			last_position = world.player.position
			previous_health = world.player.current_health
			previous_kills = world.kills
			previous_time = world.game_time_elapsed
			_send({"type": "step", "obs": [observation], "reward": [step_reward],
				"done": [world.result_shown], "info": [_info()]})
		pending = ""
	if not pending.is_empty():
		return
	var message := _receive()
	if message.is_empty():
		return
	match message.get("type", ""):
		"handshake":
			if str(message.get("major_version")) != "0" or str(message.get("minor_version")) != "7":
				push_error("Unsupported protocol")
				get_tree().quit(2)
		"env_info":
			_send({"type": "env_info", "n_agents": 1,
				"observation_space": [{"obs": {"size": [76], "space": "box", "low": -1.0, "high": 1.0}}],
				"action_space": [controller.get_action_space()], "agent_policy_names": ["shared_policy"]})
		"reset":
			_reset_world(int(message.get("seed", episode_seed + 1)), str(message.get("difficulty", "original")))
			pending = "reset"
			remaining_frames = 1 # physics synchronizes newly instantiated collision objects while world is paused
		"action":
			if world.result_shown:
				_send({"type": "error", "message": "reset required after terminal"})
				return
			var action: Dictionary = message["action"][0]
			if int(action.get("move", -1)) not in range(9) or int(action.get("shoot", -1)) not in range(9):
				_send({"type": "error", "message": "action out of range"})
				return
			controller.set_action(action)
			pending = "step"
			remaining_frames = 4
			get_tree().paused = false
		"close":
			get_tree().quit()
		_:
			_send({"type": "error", "message": "unsupported message"})

func _reset_world(seed_value: int, level: String) -> void:
	get_tree().paused = true
	if is_instance_valid(world):
		remove_child(world)
		world.free()
	episode_seed = seed_value
	difficulty = level
	episode_index += 1
	world = GAME.instantiate()
	world.training_mode = true
	world.episode_seed = seed_value
	world.process_mode = Node.PROCESS_MODE_PAUSABLE
	if difficulty == "easy":
		world.enemy_configs.clear()
		world.enemy_configs.append(preload("res://resources/config/enemy_basic.tres"))
		world.spawn_interval = 3.0
		world.min_spawn_interval = 3.0
		world.max_alive_enemies = 4
	_set_physics_timers(world)
	add_child(world)
	controller.world = world
	var camera: Camera2D = world.get_node("Camera2D")
	camera.enabled = false
	world.player.agent_control = true
	decisions = 0
	previous_kills = 0
	previous_health = world.player.max_health
	previous_time = 0.0
	total_reward = 0.0
	stuck_steps = 0
	terminal_paid = false
	last_position = world.player.position

func _set_physics_timers(node: Node) -> void:
	if node is Timer:
		node.process_callback = Timer.TIMER_PROCESS_PHYSICS
	if node is Camera2D:
		node.process_mode = Node.PROCESS_MODE_ALWAYS
		node.process_callback = Camera2D.CAMERA2D_PROCESS_PHYSICS
	for child in node.get_children():
		_set_physics_timers(child)

func _info() -> Dictionary:
	var bullets := 0
	var pickups := 0
	for child in world.get_children():
		if child is Bullet:
			bullets += 1
		if child is Pickup:
			pickups += 1
	return {"seed": episode_seed, "difficulty": difficulty, "steps": decisions,
		"seconds": world.game_time_elapsed, "health": world.player.current_health,
		"damage": world.player.max_health - world.player.current_health,
		"kills": world.kills, "pickups_collected": world.player.pickups_collected,
		"reward": total_reward, "stuck_steps": stuck_steps,
		"is_success": world.result_shown and not world.player.is_dead,
		"outcome": ("death" if world.player.is_dead else "survived") if world.result_shown else "running",
		"enemies": world.enemy_container.get_child_count(), "bullets": bullets, "pickups": pickups,
		"x": world.player.position.x, "y": world.player.position.y}

func _receive() -> Dictionary:
	if not _wait_bytes(4):
		return {}
	var size := stream.get_u32()
	if size > 1048576 or not _wait_bytes(size):
		get_tree().quit(2)
		return {}
	var value = JSON.parse_string(stream.get_utf8_string(size))
	return value if value is Dictionary else {}

func _wait_bytes(count: int) -> bool:
	var deadline := Time.get_ticks_msec() + 120000
	while Time.get_ticks_msec() < deadline:
		stream.poll()
		if stream.get_status() != StreamPeerTCP.STATUS_CONNECTED:
			get_tree().quit()
			return false
		if stream.get_available_bytes() >= count:
			return true
		OS.delay_usec(100)
	push_error("GamePilot controller timeout")
	get_tree().quit(2)
	return false

func _send(value: Dictionary) -> void:
	stream.put_string(JSON.stringify(value))
