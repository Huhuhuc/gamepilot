extends CharacterBody2D
class_name Player


signal died


const NORMAL_ANIMATION_PREFIX := &"normal"
const ARMED_ANIMATION_PREFIX := &"armed"
const DEFAULT_MOVE_SPEED_MULTIPLIER := 1.0
const DEFAULT_FIRE_RATE_MULTIPLIER := 1.0
const SPIRAL_PHASE_STEP := PI / 12.0
const BLINK_ENABLED_SHADER_PARAMETER := &"blink_enabled"


@export var move_speed: float = 120.0
@export var bullet_scene: PackedScene
@export var bullet_spawn_distance: float = 12.0
@export var fire_interval: float = 0.2
@export var max_health: int = 5
@export var invulnerability_duration: float = 0.6

@onready var body_sprite: AnimatedSprite2D = $BodySprite
@onready var armed_effect_sprite: AnimatedSprite2D = $ArmedEffectSprite
@onready var shooting_timer: Timer = $ShootingTimer
@onready var footstep_audio: AudioStreamPlayer = $FootstepAudio
@onready var gunshot_audio: AudioStreamPlayer = $GunshotAudio
@onready var pickup_audio: AudioStreamPlayer = $PickupAudio
@onready var death_audio: AudioStreamPlayer = $DeathAudio

var current_move_speed_multiplier: float = DEFAULT_MOVE_SPEED_MULTIPLIER
var rapid_fire_rate_multiplier: float = DEFAULT_FIRE_RATE_MULTIPLIER
var form_fire_rate_multiplier: float = DEFAULT_FIRE_RATE_MULTIPLIER
var current_form_mode: int = PickupConfig.PlayerFormMode.NORMAL
var current_shot_pattern: int = PickupConfig.ShotPattern.NORMAL
var speed_buff_time_left: float = 0.0
var rapid_buff_time_left: float = 0.0
var form_buff_time_left: float = 0.0
var facing_suffix: StringName = &"right"
var spiral_phase: float = 0.0
var current_health: int = 0
var invulnerability_time_left: float = 0.0
var is_dead: bool = false
var pickups_collected: int = 0
var agent_control := false
var agent_move := Vector2.ZERO
var agent_shoot := Vector2.ZERO


func _ready() -> void:
	add_to_group(&"player")
	current_health = max_health
	armed_effect_sprite.visible = false
	shooting_timer.timeout.connect(_on_shooting_timer_timeout)
	body_sprite.animation_finished.connect(_on_body_sprite_animation_finished)
	shooting_timer.one_shot = true
	_refresh_shooting_timer_wait_time()
	_update_animation()


func _physics_process(delta: float) -> void:
	_update_pickup_effects(delta)
	_update_damage_state(delta)
	
	if is_dead:
		velocity = Vector2.ZERO
		move_and_slide()
		return
	
	var move_input := Input.get_vector("move_left", "move_right", "move_up", "move_down")
	var shoot_input := Input.get_vector("shoot_left", "shoot_right", "shoot_up", "shoot_down")
	if agent_control:
		move_input = agent_move
		shoot_input = agent_shoot
	
	velocity = move_input * _get_effective_move_speed()
	move_and_slide()
	_update_footstep_audio(move_input)
	
	if current_shot_pattern == PickupConfig.ShotPattern.SPIRAL:
		_try_spiral_shoot()
	elif shoot_input != Vector2.ZERO:
		_try_shoot(shoot_input)
	
	_update_facing(move_input, shoot_input)
	_update_animation()
	_update_armed_effect()


func apply_pickup(config: PickupConfig) -> bool:
	if config == null:
		return false
	
	var applied := false
	var should_refresh_shooting_timer := false
	var buff_duration := maxf(config.duration, 0.0)
	var has_form_override := (
		config.player_form_mode != PickupConfig.PlayerFormMode.NORMAL
		or config.shot_pattern != PickupConfig.ShotPattern.NORMAL
	)
	var has_fire_rate_override := not is_equal_approx(
		config.fire_rate_multiplier,
		DEFAULT_FIRE_RATE_MULTIPLIER
	)
	
	if not is_equal_approx(config.move_speed_multiplier, DEFAULT_MOVE_SPEED_MULTIPLIER):
		current_move_speed_multiplier = config.move_speed_multiplier
		speed_buff_time_left = buff_duration
		applied = true
	
	if has_fire_rate_override and not has_form_override:
		rapid_fire_rate_multiplier = config.fire_rate_multiplier
		rapid_buff_time_left = buff_duration
		should_refresh_shooting_timer = true
		applied = true
	
	if has_form_override:
		current_form_mode = config.player_form_mode
		current_shot_pattern = config.shot_pattern
		form_fire_rate_multiplier = (
			config.fire_rate_multiplier
			if has_fire_rate_override
			else DEFAULT_FIRE_RATE_MULTIPLIER
		)
		form_buff_time_left = buff_duration
		spiral_phase = 0.0
		should_refresh_shooting_timer = true
		applied = true
	
	if should_refresh_shooting_timer:
		_refresh_shooting_timer_wait_time()
	if applied and pickup_audio.stream != null:
		pickup_audio.play()
	if applied:
		pickups_collected += 1
	
	return applied


func apply_power_up() -> void:
	var rapid_config: PickupConfig = preload("res://resources/config/pickup_rapid.tres")
	apply_pickup(rapid_config)


func apply_damage(amount: int) -> bool:
	if is_dead:
		return false
	
	if amount <= 0:
		return false
	
	if invulnerability_time_left > 0.0:
		return false
	
	current_health = maxi(current_health - amount, 0)
	
	if current_health <= 0:
		_die()
	else:
		_start_invincibility()
	
	return true


func _update_pickup_effects(delta: float) -> void:
	if speed_buff_time_left > 0.0:
		speed_buff_time_left = maxf(speed_buff_time_left - delta, 0.0)
		if speed_buff_time_left <= 0.0:
			current_move_speed_multiplier = DEFAULT_MOVE_SPEED_MULTIPLIER
	
	if rapid_buff_time_left > 0.0:
		rapid_buff_time_left = maxf(rapid_buff_time_left - delta, 0.0)
		if rapid_buff_time_left <= 0.0:
			rapid_fire_rate_multiplier = DEFAULT_FIRE_RATE_MULTIPLIER
			_refresh_shooting_timer_wait_time()
	
	if form_buff_time_left > 0.0:
		form_buff_time_left = maxf(form_buff_time_left - delta, 0.0)
		if form_buff_time_left <= 0.0:
			current_form_mode = PickupConfig.PlayerFormMode.NORMAL
			current_shot_pattern = PickupConfig.ShotPattern.NORMAL
			form_fire_rate_multiplier = DEFAULT_FIRE_RATE_MULTIPLIER
			spiral_phase = 0.0
			_refresh_shooting_timer_wait_time()


func _update_damage_state(delta: float) -> void:
	if is_dead:
		return
	
	invulnerability_time_left = maxf(invulnerability_time_left - delta, 0.0)
	if invulnerability_time_left <= 0.0:
		_set_blink_enabled(false)


func _start_invincibility() -> void:
	invulnerability_time_left = maxf(invulnerability_duration, 0.0)
	_set_blink_enabled(invulnerability_time_left > 0.0)


func _set_blink_enabled(enabled: bool) -> void:
	var shader_material := body_sprite.material as ShaderMaterial
	if shader_material == null:
		return
	
	shader_material.set_shader_parameter(BLINK_ENABLED_SHADER_PARAMETER, enabled)


func _die() -> void:
	if is_dead:
		return
	
	is_dead = true
	velocity = Vector2.ZERO
	shooting_timer.stop()
	armed_effect_sprite.visible = false
	_set_blink_enabled(false)
	body_sprite.play(&"death")
	death_audio.play()
	died.emit()


func _try_shoot(shoot_direction: Vector2) -> void:
	if not shooting_timer.is_stopped():
		return
	
	if _fire_bullets(shoot_direction):
		gunshot_audio.play()
		shooting_timer.start(_get_effective_fire_interval())


func _try_spiral_shoot() -> void:
	if not shooting_timer.is_stopped():
		return
	
	var spiral_direction := Vector2.RIGHT.rotated(spiral_phase)
	if _fire_bullets(spiral_direction):
		gunshot_audio.play()
		spiral_phase += SPIRAL_PHASE_STEP
		shooting_timer.start(_get_effective_fire_interval())


func _fire_bullets(shoot_direction: Vector2) -> bool:
	if bullet_scene == null:
		push_warning("Missing player bullet scene")
		return false
	
	var bullet := bullet_scene.instantiate() as Bullet
	bullet.global_position = global_position + shoot_direction.normalized() * bullet_spawn_distance
	bullet.setup(shoot_direction)
	get_tree().get_first_node_in_group("game_world").add_child(bullet)
	return true


func _update_facing(move_input: Vector2, shoot_input: Vector2) -> void:
	if current_shot_pattern == PickupConfig.ShotPattern.SPIRAL:
		if move_input != Vector2.ZERO:
			facing_suffix = _vector_to_facing_suffix(move_input)
		return
	
	if shoot_input != Vector2.ZERO:
		facing_suffix = _vector_to_facing_suffix(shoot_input)
	elif move_input != Vector2.ZERO:
		facing_suffix = _vector_to_facing_suffix(move_input)


func _update_animation() -> void:
	if is_dead:
		return
	
	var animation_prefix := _get_animation_prefix()
	var animation_name := StringName("%s_%s" % [animation_prefix, facing_suffix])
	
	if not body_sprite.sprite_frames.has_animation(animation_name):
		var fallback_animation_name := StringName("%s_%s" % [NORMAL_ANIMATION_PREFIX, facing_suffix])
		if not body_sprite.sprite_frames.has_animation(fallback_animation_name):
			push_warning("Missing player animation: %s" % animation_name)
			return
		animation_name = fallback_animation_name
	
	if body_sprite.animation != animation_name:
		body_sprite.play(animation_name)


func _update_armed_effect() -> void:
	var should_show_armed_effect := (
		current_form_mode == PickupConfig.PlayerFormMode.ARMED
		or not shooting_timer.is_stopped()
	)
	armed_effect_sprite.visible = should_show_armed_effect
	if should_show_armed_effect and not armed_effect_sprite.is_playing():
		armed_effect_sprite.play(&"default")


func _on_shooting_timer_timeout() -> void:
	_update_armed_effect()


func _on_body_sprite_animation_finished() -> void:
	return


func stop_runtime_audio() -> void:
	footstep_audio.stop()
	gunshot_audio.stop()
	pickup_audio.stop()


func _update_footstep_audio(move_input: Vector2) -> void:
	if move_input == Vector2.ZERO:
		footstep_audio.stop()
		return
	if not footstep_audio.playing:
		footstep_audio.play()


func _get_effective_move_speed() -> float:
	return move_speed * current_move_speed_multiplier


func _get_effective_fire_interval() -> float:
	return maxf(fire_interval / _get_effective_fire_rate_multiplier(), 0.01)


func _get_effective_fire_rate_multiplier() -> float:
	if _has_active_form_override():
		return maxf(form_fire_rate_multiplier, 0.01)
	
	return maxf(rapid_fire_rate_multiplier, 0.01)


func _has_active_form_override() -> bool:
	return (
		current_form_mode != PickupConfig.PlayerFormMode.NORMAL
		or current_shot_pattern != PickupConfig.ShotPattern.NORMAL
	)


func _refresh_shooting_timer_wait_time() -> void:
	shooting_timer.wait_time = _get_effective_fire_interval()


func _get_animation_prefix() -> StringName:
	if current_form_mode == PickupConfig.PlayerFormMode.ARMED:
		return ARMED_ANIMATION_PREFIX
	
	return ARMED_ANIMATION_PREFIX if not shooting_timer.is_stopped() else NORMAL_ANIMATION_PREFIX


func _vector_to_facing_suffix(direction: Vector2) -> StringName:
	if abs(direction.x) >= abs(direction.y):
		return &"right" if direction.x > 0.0 else &"left"
	
	return &"down" if direction.y > 0.0 else &"up"
