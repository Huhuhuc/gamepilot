extends Resource
class_name EnemyConfig


enum EnemyType {
	BASIC,
	SHELLED,
	FAST_SMALL,
	BOMBER,
}


@export_group("Basic")
@export var enemy_type: EnemyType = EnemyType.BASIC
@export var display_name: String = "基础敌人"
@export_range(1, 999, 1, "or_greater") var max_health: int = 3
@export_range(0.0, 1000.0, 1.0, "or_greater") var move_speed: float = 40.0
@export_range(1.0, 256.0, 0.5, "or_greater") var collision_radius: float = 8.0

@export_group("Animation")
@export var enemy_frames: SpriteFrames
@export var move_animation_name: StringName = &"move"
@export var hit_animation_name: StringName = &"hit"
@export var death_animation_name: StringName = &"death"
@export var explosion_animation_name: StringName = &"explode"

@export_group("Damage")
@export_range(0, 999, 1, "or_greater") var touch_damage: int = 1
@export_range(0.0, 10.0, 0.1, "or_greater") var touch_damage_interval: float = 0.5
@export_range(0.0, 2.0, 0.01, "or_greater") var start_blink_duration: float = 0.16
@export var explode_on_death: bool = false
@export_range(0, 999, 1, "or_greater") var explosion_damage: int = 1
@export_range(0.0, 64.0, 0.5, "or_greater") var explosion_radius: float = 24.0
@export_range(0.0, 2.0, 0.05, "or_greater") var hit_stop_duration: float = 0.2

@export_group("Drop")
@export_range(0.0, 1.0, 0.01) var pickup_drop_chance: float = 0.4
@export var pickup_drop_configs: Array[PickupConfig] = []
