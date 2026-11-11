extends CharacterBody2D
class_name Enemy


const DEFAULT_BULLET_DAMAGE := 1
const BLINK_ENABLED_SHADER_PARAMETER := &"blink_enabled"
const PICKUP_SCENE := preload("res://scence/pickup.tscn")
const EXPLOSION_QUERY_MAX_RESULTS := 16
const HIT_SOUND := preload("res://resources/audio/cowboy_monsterhit.wav")
const DEATH_SOUND := preload("res://resources/audio/cowboy_monsterdie.wav")
const EXPLOSION_SOUND := preload("res://resources/audio/cowboy_explosion.wav")


enum DeathSequenceStage {
	NONE,
	DEATH,
	EXPLOSION,
}


@export var config: EnemyConfig
@export var target_player: Player

@onready var animated_sprite: AnimatedSprite2D = $AnimatedSprite2D
@onready var collision_shape: CollisionShape2D = $CollisionShape2D
@onready var touch_damage_area: Area2D = $TouchDamageArea
@onready var touch_damage_shape: CollisionShape2D = $TouchDamageArea/CollisionShape2D
@onready var explosion_area: Area2D = $ExplosionArea
@onready var explosion_shape: CollisionShape2D = $ExplosionArea/CollisionShape2D
@onready var audio_stream_player: AudioStreamPlayer = $AudioStreamPlayer

var training_mode := false
var spawn_id := 0
var drop_seed := 0
var death_stage_time_left := 0.0
var current_health: int = 1
var is_dead: bool = false
var touch_damage_cooldown_left: float = 0.0
var touched_player: Player = null
var blink_time_left: float = 0.0
var death_sequence_stage: int = DeathSequenceStage.NONE
var death_animation_name_in_use: StringName = &""
var random_generator: RandomNumberGenerator = RandomNumberGenerator.new()


func _ready() -> void:
	if training_mode:
		random_generator.seed = drop_seed
	else:
		random_generator.randomize()
	touch_damage_area.body_entered.connect(_on_touch_damage_area_body_entered)
	touch_damage_area.body_exited.connect(_on_touch_damage_area_body_exited)
	touch_damage_area.area_entered.connect(_on_touch_damage_area_area_entered)
	if not training_mode:
		animated_sprite.animation_finished.connect(_on_animated_sprite_animation_finished)
	_apply_config(config, target_player)


func _physics_process(delta: float) -> void:
	_update_blink(delta)
	touch_damage_cooldown_left = maxf(touch_damage_cooldown_left - delta, 0.0)
	
	if is_dead:
		if training_mode and death_stage_time_left > 0.0:
			death_stage_time_left -= delta
			if death_stage_time_left <= 0.0:
				_on_animated_sprite_animation_finished()
		velocity = Vector2.ZERO
		move_and_slide()
		return
	
	_deal_touch_damage()
	var move_direction := _get_move_direction()
	velocity = move_direction * _get_move_speed()
	move_and_slide()
	_update_facing(move_direction)


func _apply_config(enemy_config: EnemyConfig, player: Player) -> void:
	config = enemy_config
	target_player = player
	
	if config == null:
		push_warning("Enemy has no config")
		return
	
	current_health = config.max_health
	if config.enemy_frames != null:
		animated_sprite.sprite_frames = config.enemy_frames
	_update_collision_radius()
	_update_explosion_radius()
	_play_animation_or_default(config.move_animation_name)


func apply_damage(amount: int = DEFAULT_BULLET_DAMAGE) -> bool:
	if is_dead:
		return false
	
	var damage_amount: int = maxi(amount, 0)
	if damage_amount <= 0:
		return false
	
	current_health = maxi(current_health - damage_amount, 0)
	_start_blink()
	audio_stream_player.stream = HIT_SOUND
	audio_stream_player.play()
	
	if current_health <= 0:
		_start_death_sequence()
	
	return true


func _get_move_direction() -> Vector2:
	var player := _get_target_player()
	if player == null:
		return Vector2.ZERO
	
	return global_position.direction_to(player.global_position)


func _get_move_speed() -> float:
	if config == null:
		return 0.0
	
	return config.move_speed


func _get_target_player() -> Player:
	if is_instance_valid(target_player):
		return target_player
	
	target_player = get_tree().get_first_node_in_group(&"player") as Player
	if target_player != null:
		return target_player
	
	target_player = get_tree().get_first_node_in_group("game_world").get_node_or_null("Player") as Player
	return target_player


func _update_facing(move_direction: Vector2) -> void:
	if is_zero_approx(move_direction.x):
		return
	
	animated_sprite.flip_h = move_direction.x < 0.0


func _start_blink() -> void:
	if config == null:
		return
	
	blink_time_left = config.start_blink_duration
	_set_blink_enabled(true)


func _update_blink(delta: float) -> void:
	if blink_time_left <= 0.0:
		return
	
	blink_time_left = maxf(blink_time_left - delta, 0.0)
	if blink_time_left <= 0.0:
		_set_blink_enabled(false)


func _set_blink_enabled(enabled: bool) -> void:
	var shader_material := animated_sprite.material as ShaderMaterial
	if shader_material == null:
		return
	
	shader_material.set_shader_parameter(BLINK_ENABLED_SHADER_PARAMETER, enabled)


func _on_touch_damage_area_body_entered(body: Node2D) -> void:
	if is_dead:
		return
	
	var player := body as Player
	if player == null:
		return
	
	touched_player = player
	_deal_touch_damage()


func _on_touch_damage_area_body_exited(body: Node2D) -> void:
	if body == touched_player:
		touched_player = null


func _on_touch_damage_area_area_entered(area: Area2D) -> void:
	if is_dead:
		return
	
	var bullet := area as Bullet
	if bullet == null:
		return
	
	if apply_damage(bullet.damage):
		bullet.queue_free()


func _deal_touch_damage() -> void:
	if touched_player == null or config == null or touch_damage_cooldown_left > 0.0:
		return
	
	if touched_player.apply_damage(config.touch_damage):
		touch_damage_cooldown_left = config.touch_damage_interval


func _start_death_sequence() -> void:
	if is_dead:
		return
	
	is_dead = true
	if training_mode:
		get_tree().get_first_node_in_group("game_world").kills += 1
	velocity = Vector2.ZERO
	collision_shape.set_deferred("disabled", true)
	touch_damage_area.set_deferred("monitoring", false)
	touched_player = null
	_set_blink_enabled(false)
	
	if config == null:
		_finish_death_sequence()
		return
	
	if not _play_death_sequence_animation(config.death_animation_name, DeathSequenceStage.DEATH):
		_start_explosion_sequence()


func _start_explosion_sequence() -> void:
	if not _should_play_explosion_sequence():
		_finish_death_sequence()
		return
	
	_apply_explosion_damage()
	if not _play_death_sequence_animation(config.explosion_animation_name, DeathSequenceStage.EXPLOSION):
		_finish_death_sequence()


func _should_play_explosion_sequence() -> bool:
	return (
		config != null
		and config.explode_on_death
		and config.explosion_damage > 0
		and config.explosion_radius > 0.0
	)


func _play_death_sequence_animation(animation_name: StringName, stage: int) -> bool:
	death_sequence_stage = stage
	death_animation_name_in_use = animation_name
	
	if config == null:
		return false
	if animated_sprite.sprite_frames == null:
		return false
	if not animated_sprite.sprite_frames.has_animation(animation_name):
		return false
	
	animated_sprite.play(animation_name)
	if training_mode:
		death_stage_time_left = 0.0
		var frames := animated_sprite.sprite_frames
		for frame_index in range(frames.get_frame_count(animation_name)):
			death_stage_time_left += frames.get_frame_duration(animation_name, frame_index) / frames.get_animation_speed(animation_name)
	audio_stream_player.stream = EXPLOSION_SOUND if stage == DeathSequenceStage.EXPLOSION else DEATH_SOUND
	if audio_stream_player.stream != null:
		audio_stream_player.play()
	return true


func _play_animation_or_default(animation_name: StringName) -> void:
	if animated_sprite.sprite_frames == null:
		return
	
	if animated_sprite.sprite_frames.has_animation(animation_name):
		animated_sprite.play(animation_name)
	elif animated_sprite.sprite_frames.has_animation(&"move"):
		animated_sprite.play(&"move")


func _apply_explosion_damage() -> void:
	if config == null or explosion_shape.shape == null:
		return
	
	var space_state := get_world_2d().direct_space_state
	if space_state == null:
		return
	
	var query := PhysicsShapeQueryParameters2D.new()
	query.shape = explosion_shape.shape
	query.transform = explosion_shape.global_transform
	query.collision_mask = explosion_area.collision_mask
	query.collide_with_bodies = true
	query.collide_with_areas = false
	query.exclude = [get_rid()]
	
	var query_results := space_state.intersect_shape(query, EXPLOSION_QUERY_MAX_RESULTS)
	if query_results.is_empty():
		return
	
	var collider_ids: Dictionary = {}
	for result in query_results:
		var collider := result.get("collider") as Node
		if collider == null or collider == self:
			continue
		
		var collider_id := collider.get_instance_id()
		if collider_ids.has(collider_id):
			continue
		collider_ids[collider_id] = true
		
		var player := collider as Player
		if player != null:
			player.apply_damage(config.explosion_damage)
			continue
		
		var enemy := collider as Enemy
		if enemy != null:
			enemy.apply_damage(config.explosion_damage)


func _update_explosion_radius() -> void:
	var shape := explosion_shape.shape as CircleShape2D
	if shape == null or config == null:
		return
	
	shape.radius = config.explosion_radius


func _update_collision_radius() -> void:
	var body_shape := collision_shape.shape as CircleShape2D
	if body_shape != null:
		body_shape.radius = config.collision_radius
	
	var touch_shape := touch_damage_shape.shape as CircleShape2D
	if touch_shape != null:
		touch_shape.radius = config.collision_radius


func _spawn_dropped_pickup(spawn_position: Vector2) -> void:
	if config == null or config.pickup_drop_configs.is_empty():
		return
	
	if random_generator.randf() > config.pickup_drop_chance:
		return
	
	var pickup_config: PickupConfig = config.pickup_drop_configs[
		random_generator.randi_range(0, config.pickup_drop_configs.size() - 1)
	]
	if pickup_config == null:
		return
	
	var pickup_instance := PICKUP_SCENE.instantiate() as Pickup
	if pickup_instance == null:
		return
	
	pickup_instance.config = pickup_config
	pickup_instance.global_position = spawn_position
	get_tree().get_first_node_in_group("game_world").call_deferred("add_child", pickup_instance)


func _finish_death_sequence() -> void:
	_spawn_dropped_pickup(global_position)
	queue_free()


func _on_animated_sprite_animation_finished() -> void:
	if death_animation_name_in_use == &"":
		return
	if animated_sprite.animation != death_animation_name_in_use:
		return
	
	match death_sequence_stage:
		DeathSequenceStage.DEATH:
			_start_explosion_sequence()
		DeathSequenceStage.EXPLOSION:
			_finish_death_sequence()
		_:
			pass
