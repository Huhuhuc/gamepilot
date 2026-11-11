@tool
extends Area2D
class_name Pickup


const BLINK_ENABLED_SHADER_PARAMETER := &"blink_enabled"


var _config: PickupConfig

@export var config: PickupConfig:
	set(value):
		_config = value
		if is_inside_tree():
			_apply_config_to_visual()
	get:
		return _config
@export_range(0.0, 10.0, 0.1, "or_greater") var blink_before_expire: float = 1.2

@onready var sprite: Sprite2D = $Sprite2D
@onready var collision_shape: CollisionShape2D = $CollisionShape2D
@onready var lifetime_timer: Timer = $LifetimeTimer
@onready var audio_stream_player: AudioStreamPlayer = $AudioStreamPlayer

var is_expiring: bool = false


func _ready() -> void:
	body_entered.connect(_on_body_entered)
	lifetime_timer.timeout.connect(_on_lifetime_timer_timeout)
	lifetime_timer.one_shot = true
	lifetime_timer.process_callback = Timer.TIMER_PROCESS_PHYSICS
	_apply_config_to_visual()
	_set_blink_enabled(false)
	
	if not Engine.is_editor_hint() and lifetime_timer.wait_time > 0.0:
		lifetime_timer.start()


func _process(_delta: float) -> void:
	if lifetime_timer.is_stopped() or is_expiring:
		return
	
	if lifetime_timer.time_left <= blink_before_expire:
		_set_blink_enabled(true)


func _on_body_entered(body: Node2D) -> void:
	if is_expiring or config == null:
		return
	
	if not body.has_method("apply_pickup"):
		return
	
	if not body.apply_pickup(config):
		return
	
	_expire(true)


func _on_lifetime_timer_timeout() -> void:
	_expire(false)


func _expire(play_sound: bool) -> void:
	is_expiring = true
	sprite.visible = false
	collision_shape.set_deferred("disabled", true)
	
	if play_sound and audio_stream_player.stream != null and not is_instance_valid(get_tree().get_first_node_in_group(&"player")):
		audio_stream_player.play()
		await audio_stream_player.finished
	
	queue_free()


func _set_blink_enabled(enabled: bool) -> void:
	var shader_material := sprite.material as ShaderMaterial
	if shader_material == null:
		return
	
	shader_material.set_shader_parameter(BLINK_ENABLED_SHADER_PARAMETER, enabled)


func _apply_config_to_visual() -> void:
	if config == null or config.icon_texture == null:
		return

	sprite.texture = config.icon_texture
