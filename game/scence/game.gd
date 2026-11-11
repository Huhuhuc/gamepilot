extends Node2D


@export_group("References")
@export var player: Player
@export var enemy_container: Node2D
@export var enemy_spawn_timer: Timer
@export var enemy_spawn_point_group_name: StringName = &"EnemySpawnPoints"

@export_group("Enemy Resources")
@export var enemy_scene: PackedScene = preload("res://scence/enemy.tscn")
@export var enemy_configs: Array[EnemyConfig] = [
	preload("res://resources/config/enemy_basic.tres"),
	preload("res://resources/config/enemy_shelled.tres"),
	preload("res://resources/config/enemy_fast.tres"),
	preload("res://resources/config/enemy_bomber.tres"),
]

@export_group("Spawn Settings")
@export_range(0, 100, 1, "or_greater") var initial_spawn_count: int = 1
@export_range(0, 100, 1, "or_greater") var spawn_count_per_tick: int = 1
@export_range(0.1, 60.0, 0.1, "or_greater") var spawn_interval: float = 1.5
@export_range(0.1, 60.0, 0.1, "or_greater") var min_spawn_interval: float = 0.6
@export_range(1, 100, 1, "or_greater") var max_alive_enemies: int = 12
@export_range(0.0, 300.0, 1.0, "or_greater") var spawn_acceleration_duration: float = 90.0

@export_group("Stage")
@export_range(1.0, 600.0, 1.0, "or_greater") var stage_duration: float = 60.0

@onready var hud: GameHud = $HUDLayer
@onready var background_music: AudioStreamPlayer = $BackgroundMusic
@onready var ui_sound: AudioStreamPlayer = $UiSound

var training_mode := false
var episode_seed := 0
var spawn_serial := 0
var kills := 0
var random_generator: RandomNumberGenerator = RandomNumberGenerator.new()
var enemy_spawn_points: Array[Marker2D] = []
var available_enemy_configs: Array[EnemyConfig] = []
var game_time_elapsed: float = 0.0
var stage_time_left: float = 0.0
var result_shown: bool = false


func _ready() -> void:
	add_to_group("game_world")
	stage_time_left = stage_duration
	if training_mode:
		random_generator.seed = episode_seed
	else:
		random_generator.randomize()
	_resolve_references()
	_collect_enemy_spawn_points()
	_collect_enemy_configs()
	_configure_enemy_spawn_timer()
	_spawn_initial_enemies()
	_start_enemy_spawn_timer()
	hud.result_confirmed.connect(_on_result_dialog_confirmed)
	player.died.connect(_on_player_died)
	hud.update_life(player.current_health)
	hud.update_time(stage_time_left, stage_duration)
	background_music.play()


func _physics_process(delta: float) -> void:
	if result_shown:
		return
	game_time_elapsed += delta
	stage_time_left = maxf(stage_time_left - delta, 0.0)
	hud.update_life(player.current_health)
	hud.update_time(stage_time_left, stage_duration)
	if stage_time_left <= 0.0:
		_show_result(String.chr(24378) + String.chr(65281) + String.chr(65311) + String.chr(24378))
	_update_spawn_interval()


func _show_result(message: String) -> void:
	if result_shown:
		return
	result_shown = true
	enemy_spawn_timer.stop()
	background_music.stop()
	if training_mode:
		process_mode = Node.PROCESS_MODE_DISABLED
		return
	Engine.time_scale = 0.0
	player.stop_runtime_audio()
	if ui_sound.stream != null:
		ui_sound.play()
	hud.show_result(message)
	get_tree().paused = true


func _on_player_died() -> void:
	_show_result(
		String.chr(20320) + String.chr(34987) + String.chr(20987)
		+ String.chr(36133) + String.chr(20102)
	)


func _on_result_dialog_confirmed() -> void:
	Engine.time_scale = 1.0
	get_tree().paused = false
	get_tree().quit()


func _resolve_references() -> void:
	if player == null:
		player = get_node_or_null("Player") as Player
	if enemy_container == null:
		enemy_container = get_node_or_null("EnemyContainer") as Node2D
	if enemy_spawn_timer == null:
		enemy_spawn_timer = get_node_or_null("EnemySpawnTimer") as Timer


func _collect_enemy_spawn_points() -> void:
	enemy_spawn_points.clear()
	for node in get_tree().get_nodes_in_group(enemy_spawn_point_group_name):
		var spawn_point := node as Marker2D
		if spawn_point != null:
			enemy_spawn_points.append(spawn_point)


func _collect_enemy_configs() -> void:
	available_enemy_configs.clear()
	for enemy_config in enemy_configs:
		if enemy_config != null:
			available_enemy_configs.append(enemy_config)


func _configure_enemy_spawn_timer() -> void:
	if enemy_spawn_timer == null:
		return

	enemy_spawn_timer.wait_time = _get_current_spawn_interval()
	enemy_spawn_timer.one_shot = false
	if not enemy_spawn_timer.timeout.is_connected(_on_enemy_spawn_timer_timeout):
		enemy_spawn_timer.timeout.connect(_on_enemy_spawn_timer_timeout)


func _update_spawn_interval() -> void:
	if enemy_spawn_timer == null:
		return

	var current_interval: float = _get_current_spawn_interval()
	if is_equal_approx(enemy_spawn_timer.wait_time, current_interval):
		return

	enemy_spawn_timer.wait_time = current_interval
	if enemy_spawn_timer.is_stopped():
		return
	if enemy_spawn_timer.time_left <= current_interval:
		return

	enemy_spawn_timer.start(current_interval)


func _get_current_spawn_interval() -> float:
	var start_interval: float = maxf(spawn_interval, 0.1)
	var end_interval: float = minf(maxf(min_spawn_interval, 0.1), start_interval)

	if spawn_acceleration_duration <= 0.0:
		return end_interval

	var difficulty_ratio: float = clampf(game_time_elapsed / spawn_acceleration_duration, 0.0, 1.0)
	return lerpf(start_interval, end_interval, difficulty_ratio)


func _spawn_initial_enemies() -> void:
	for _spawn_index in range(initial_spawn_count):
		if not _try_spawn_enemy():
			break


func _start_enemy_spawn_timer() -> void:
	if not _is_spawn_system_ready():
		return

	enemy_spawn_timer.start()


func _on_enemy_spawn_timer_timeout() -> void:
	for _spawn_index in range(spawn_count_per_tick):
		if not _try_spawn_enemy():
			break


func _try_spawn_enemy() -> bool:
	if not _is_spawn_system_ready():
		return false

	if _get_alive_enemy_count() >= max_alive_enemies:
		return false

	var spawn_point: Marker2D = _pick_spawn_point()
	var enemy_config: EnemyConfig = _pick_enemy_config()
	if spawn_point == null or enemy_config == null:
		return false

	var enemy_instance: Enemy = enemy_scene.instantiate() as Enemy
	if enemy_instance == null:
		return false

	spawn_serial += 1
	enemy_instance.spawn_id = spawn_serial
	enemy_instance.training_mode = training_mode
	enemy_instance.drop_seed = episode_seed * 1000003 + spawn_serial * 7919
	enemy_container.add_child(enemy_instance)
	enemy_instance.global_position = spawn_point.global_position
	enemy_instance._apply_config(enemy_config, player)
	return true


func _is_spawn_system_ready() -> bool:
	return (
		player != null
		and enemy_container != null
		and enemy_spawn_timer != null
		and enemy_scene != null
		and not enemy_spawn_points.is_empty()
		and not available_enemy_configs.is_empty()
	)


func _pick_spawn_point() -> Marker2D:
	if enemy_spawn_points.is_empty():
		return null

	var random_index: int = random_generator.randi_range(0, enemy_spawn_points.size() - 1)
	return enemy_spawn_points[random_index]


func _pick_enemy_config() -> EnemyConfig:
	if available_enemy_configs.is_empty():
		return null

	var random_index: int = random_generator.randi_range(0, available_enemy_configs.size() - 1)
	return available_enemy_configs[random_index]


func _get_alive_enemy_count() -> int:
	var alive_enemy_count: int = 0
	for child in enemy_container.get_children():
		var enemy := child as Enemy
		if enemy != null and not enemy.is_dead:
			alive_enemy_count += 1

	return alive_enemy_count
