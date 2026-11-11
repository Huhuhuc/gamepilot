extends Resource
class_name PickupConfig


enum PickupType {
	SPEED,
	RAPID,
	SPIRAL,
}

enum PlayerFormMode {
	NORMAL,
	ARMED,
}

enum ShotPattern {
	NORMAL,
	SPIRAL,
}


@export_group("Basic")
@export var pickup_type: PickupType = PickupType.SPEED
@export var display_name: String = "Speed Pickup"
@export_range(0.0, 1000.0, 0.1, "or_greater") var drop_weight: float = 1.0

@export_group("Visual")
@export var icon_texture: Texture2D

@export_group("Buff")
@export_range(0.0, 120.0, 0.1, "or_greater") var duration: float = 5.0
@export_range(0.1, 5.0, 0.05, "or_greater") var move_speed_multiplier: float = 1.0
@export_range(0.1, 5.0, 0.05, "or_greater") var fire_rate_multiplier: float = 1.0

@export_group("Form And Shot")
@export var player_form_mode: PlayerFormMode = PlayerFormMode.NORMAL
@export var shot_pattern: ShotPattern = ShotPattern.NORMAL
