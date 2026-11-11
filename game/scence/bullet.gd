extends Area2D
class_name Bullet

const WORLD_COLLISION_MASK := 1


@export var speed: float = 320.0
@export var damage: int = 1
@export var max_lifetime : float = 2.0


var direction : Vector2 = Vector2.RIGHT

var remaining_lifetime: float = 0.0
var has_hit: bool = false


func _ready() -> void:
	remaining_lifetime = max_lifetime
	area_entered.connect(_on_area_entered)
	body_entered.connect(_on_body_entered)
	
	
func setup(inital_direction: Vector2) -> void:
	if  inital_direction != Vector2.ZERO:
		direction = inital_direction.normalized()
		
	rotation = direction.angle()
	
	
	
func _physics_process(delta: float) -> void:
	var current_position := global_position
	var next_position := current_position + direction * speed * delta
	
	if _will_hit_world(current_position, next_position):
		queue_free()
		return
		
	global_position = next_position
	
	remaining_lifetime -= delta
	if remaining_lifetime <= 0.0:
		queue_free()
		
		
func _will_hit_world(from_position: Vector2, to_position: Vector2) -> bool:
	var space_state := get_world_2d().direct_space_state
	if space_state == null:
		return false
		
	var query := PhysicsRayQueryParameters2D.create(
		from_position,
		to_position,
		WORLD_COLLISION_MASK
	)
	query.collide_with_bodies = true
	query.collide_with_areas = false
	
	var hit_result: Dictionary = space_state.intersect_ray(query)
	return not hit_result.is_empty()
	
	
func _on_area_entered(area: Area2D) -> void:
	if area is Bullet:
		return
	
	if _try_apply_damage(area):
		queue_free()
		return
	
	if area.get_parent() != null and _try_apply_damage(area.get_parent()):
		queue_free()
		return
	
	queue_free()


func _on_body_entered(body: Node2D) -> void:
	if _try_apply_damage(body):
		queue_free()


func _try_apply_damage(target: Node) -> bool:
	if has_hit or target == null or not target.has_method("apply_damage"):
		return false
	
	has_hit = target.apply_damage(damage)
	return has_hit
