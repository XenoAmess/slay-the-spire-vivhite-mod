extends Node

## Vivhite-specific bridge between the shared combat Spine event contract and
## her own slash / glasses-lens magic.  This intentionally does not inherit or
## instantiate the Ironclad eye-fire controller.

const STEP := &"step"

var _slash_step_base := Vector2.ZERO
var _slash_shader_material: ShaderMaterial
var _active_tween: Tween
var _spine_sprite: Node2D
var _eye_magic: TextureRect


func _ready() -> void:
	_spine_sprite = get_parent() as Node2D
	var slash_slot := _spine_sprite.get_node("SlashVfxSlot")
	_slash_shader_material = slash_slot.get("normal_material") as ShaderMaterial
	if _slash_shader_material != null:
		var initial_step: Variant = _slash_shader_material.get_shader_parameter(STEP)
		if initial_step is Vector2:
			_slash_step_base = initial_step

	_eye_magic = _spine_sprite.get_node("EyeSlot/EyeMagic") as TextureRect
	_spine_sprite.connect("animation_event", Callable(self, "_on_animation_event"))
	_spine_sprite.connect("animation_started", Callable(self, "_on_animation_started"))
	_clear_vfx()


func _on_animation_event(
	_spine: Object,
	_animation_state: Object,
	_track_entry: Object,
	spine_event: Object
) -> void:
	match _spine_event_name(spine_event):
		"heavy_slash_start":
			_play_heavy_slash()
		"attack_slash_start":
			_play_attack_slash()
		"cast_eyes_start":
			_eye_magic.visible = true
		"clear_vfx":
			_clear_vfx()


func _on_animation_started(
	_spine: Object,
	_animation_state: Object,
	track_entry: Object
) -> void:
	if _track_entry_animation_name(track_entry) != "cast":
		_clear_vfx()


func _play_heavy_slash() -> void:
	_reset_slash()
	if _slash_shader_material == null:
		return
	_active_tween = create_tween().set_ease(Tween.EASE_IN).set_trans(Tween.TRANS_CUBIC)
	_active_tween.tween_property(
		_slash_shader_material,
		"shader_parameter/step",
		Vector2(1.0, 1.02),
		0.35
	)


func _play_attack_slash() -> void:
	_reset_slash()
	if _slash_shader_material == null:
		return
	_active_tween = create_tween().set_ease(Tween.EASE_IN).set_trans(Tween.TRANS_QUAD)
	_active_tween.tween_interval(0.15)
	_active_tween.tween_property(
		_slash_shader_material,
		"shader_parameter/step",
		Vector2(1.0, 1.02),
		0.2
	)


func _reset_slash() -> void:
	if _slash_shader_material != null:
		_slash_shader_material.set_shader_parameter(STEP, _slash_step_base)
	if _active_tween != null:
		_active_tween.kill()
		_active_tween = null


func _clear_vfx() -> void:
	if _eye_magic != null:
		_eye_magic.visible = false


func _spine_event_name(spine_event: Object) -> String:
	if spine_event == null or not spine_event.has_method("get_data"):
		return ""
	var event_data: Variant = spine_event.call("get_data")
	if event_data == null or not event_data is Object:
		return ""
	var event_object := event_data as Object
	if not event_object.has_method("get_event_name"):
		return ""
	return str(event_object.call("get_event_name"))


func _track_entry_animation_name(track_entry: Object) -> String:
	if track_entry == null or not track_entry.has_method("get_animation"):
		return ""
	var animation: Variant = track_entry.call("get_animation")
	if animation == null or not animation is Object:
		return ""
	var animation_object := animation as Object
	if not animation_object.has_method("get_name"):
		return ""
	return str(animation_object.call("get_name"))


func _exit_tree() -> void:
	if _active_tween != null:
		_active_tween.kill()
