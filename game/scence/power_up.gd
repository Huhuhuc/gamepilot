extends Area2D

@onready var sprite: Sprite2D = $Sprite2D
@onready var collision_shape: CollisionShape2D = $CollisionShape2D
@onready var audio_stream_player: AudioStreamPlayer = $AudioStreamPlayer


func _ready() -> void:
	body_entered.connect(_on_body_entered)


func _on_body_entered(body: Node2D) -> void:
	if not body.has_method("apply_power_up"):
		return
	
	body.apply_power_up()
	sprite.visible = false
	collision_shape.set_deferred("disabled", true)
	audio_stream_player.play()
	await audio_stream_player.finished
	queue_free()
