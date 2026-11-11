extends Node2D
class_name GameHud


signal result_confirmed


@onready var life_count_label: Label = $LifeCountLabel
@onready var time_bar: ProgressBar = $TimeBar
@onready var result_dialog: AcceptDialog = $AcceptDialog


func _ready() -> void:
	result_dialog.confirmed.connect(_on_result_dialog_confirmed)
	result_dialog.canceled.connect(_on_result_dialog_canceled)
	result_dialog.close_requested.connect(_on_result_dialog_canceled)
	result_dialog.title = String.chr(28216) + String.chr(25103) + String.chr(32467) + String.chr(26524)
	var ok_button := result_dialog.get_ok_button()
	ok_button.text = String.chr(22909) + String.chr(20102)
	ok_button.custom_minimum_size = Vector2(64, 28)
	_configure_time_bar()


func update_life(current_health: int) -> void:
	life_count_label.text = "x %d" % maxi(current_health, 0)


func update_time(time_left: float, duration: float) -> void:
	var ratio := 0.0 if duration <= 0.0 else clampf(time_left / duration, 0.0, 1.0)
	time_bar.value = ratio * 100.0


func show_result(message: String) -> void:
	result_dialog.dialog_text = message
	result_dialog.popup_centered()
	var ok_button := result_dialog.get_ok_button()
	if ok_button != null:
		ok_button.grab_focus()


func _configure_time_bar() -> void:
	time_bar.value = 100.0
	time_bar.show_percentage = false
	time_bar.add_theme_stylebox_override(
		"background",
		_make_style(Color("#25283b"), Color("#11121b"))
	)
	time_bar.add_theme_stylebox_override(
		"fill",
		_make_style(Color("#8aa51e"), Color("#c5e74d"))
	)


func _make_style(fill_color: Color, border_color: Color) -> StyleBoxFlat:
	var style := StyleBoxFlat.new()
	style.bg_color = fill_color
	style.border_color = border_color
	style.set_border_width_all(1)
	style.corner_radius_top_left = 1
	style.corner_radius_top_right = 1
	style.corner_radius_bottom_left = 1
	style.corner_radius_bottom_right = 1
	return style


func _on_result_dialog_confirmed() -> void:
	result_confirmed.emit()


func _on_result_dialog_canceled() -> void:
	result_confirmed.emit()
