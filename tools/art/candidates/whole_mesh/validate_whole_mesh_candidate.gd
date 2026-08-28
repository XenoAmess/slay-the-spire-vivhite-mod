extends SceneTree

## Loads and samples the isolated candidate with the real game-compatible
## Spine GDExtension. This is intentionally headless and never opens, focuses,
## deploys to, or controls Slay the Spire 2.

const DATA_PATH := "res://tools/candidates/whole_mesh/vivhite_combat_skeleton_data.tres"
const JSON_PATH := "res://tools/candidates/whole_mesh/vivhite_combat.spjson"
const EXPECTED_ANIMATIONS := {
	"attack": 1.1666667,
	"attack_heavy": 1.5333334,
	"cast": 1.5666667,
	"die": 2.3333335,
	"hurt": 1.0,
	"idle_loop": 2.0,
	"low_health_loop": 1.4666667,
	"relaxed_loop": 12.000001,
}
const REQUIRED_PARENTS := {
	"vivhite_torso_lower": "vivhite_pelvis",
	"vivhite_torso_upper": "vivhite_torso_lower",
	"vivhite_neck": "vivhite_torso_upper",
	"vivhite_head": "vivhite_neck",
	"vivhite_upper_arm_left": "vivhite_shoulder_left",
	"vivhite_forearm_left": "vivhite_upper_arm_left",
	"vivhite_hand_left": "vivhite_forearm_left",
	"vivhite_upper_arm_right": "vivhite_shoulder_right",
	"vivhite_forearm_right": "vivhite_upper_arm_right",
	"vivhite_hand_right": "vivhite_forearm_right",
	"vivhite_thigh_left": "vivhite_hip_left",
	"vivhite_shin_left": "vivhite_thigh_left",
	"vivhite_foot_left": "vivhite_shin_left",
	"vivhite_thigh_right": "vivhite_hip_right",
	"vivhite_shin_right": "vivhite_thigh_right",
	"vivhite_foot_right": "vivhite_shin_right",
}
const REQUIRED_SLOTS := ["slash_mesh", "eye_attach_slot"]
const REQUIRED_EVENTS := ["attack_slash_start", "heavy_slash_start", "cast_eyes_start", "clear_vfx"]
const SCENE_SCALE := 0.28

var _errors: Array[String] = []


func _initialize() -> void:
	call_deferred("_run")


func _run() -> void:
	for type_name: String in ["SpineSprite", "SpineSkeletonDataResource", "SpineSkeletonFileResource", "SpineAtlasResource"]:
		if not ClassDB.class_exists(type_name):
			_errors.append("Game-compatible Spine class is unavailable: %s" % type_name)
	if not _errors.is_empty():
		_finish({})
		return

	var parsed = JSON.parse_string(FileAccess.get_file_as_string(JSON_PATH))
	if not parsed is Dictionary:
		_errors.append("Candidate Spine JSON is unreadable: %s" % JSON_PATH)
		_finish({})
		return
	_validate_raw_contract(parsed)

	var data: Resource = ResourceLoader.load(DATA_PATH)
	if data == null or not data.is_class("SpineSkeletonDataResource"):
		_errors.append("Spine runtime could not load candidate data: %s" % DATA_PATH)
		_finish({})
		return
	if str(data.call("get_version")) != "4.2.43":
		_errors.append("Spine runtime reported version %s, expected 4.2.43" % data.call("get_version"))
	for animation_name: String in EXPECTED_ANIMATIONS:
		var animation: Object = data.call("find_animation", animation_name)
		if animation == null:
			_errors.append("Spine runtime is missing animation %s" % animation_name)
			continue
		var duration := float(animation.call("get_duration"))
		if absf(duration - float(EXPECTED_ANIMATIONS[animation_name])) > 0.00001:
			_errors.append("Spine runtime duration mismatch for %s: %.7f" % [animation_name, duration])
	for slot_name: String in REQUIRED_SLOTS:
		if data.call("find_slot", slot_name) == null:
			_errors.append("Spine runtime is missing slot %s" % slot_name)
	for event_name: String in REQUIRED_EVENTS:
		if data.call("find_event", event_name) == null:
			_errors.append("Spine runtime is missing event %s" % event_name)

	var sampled := []
	for animation_name: String in EXPECTED_ANIMATIONS:
		if _sample_animation(data, animation_name, float(EXPECTED_ANIMATIONS[animation_name])):
			sampled.append(animation_name)

	var metrics := _motion_metrics(parsed)
	metrics["bone_count"] = data.call("get_bones").size()
	metrics["runtime_animation_count"] = data.call("get_animations").size()
	metrics["runtime_event_count"] = data.call("get_events").size()
	metrics["runtime_slot_count"] = data.call("get_slots").size()
	metrics["sampled_animations"] = sampled
	metrics["spine_version"] = str(data.call("get_version"))
	_finish(metrics)


func _validate_raw_contract(skeleton: Dictionary) -> void:
	var parents := {}
	for bone: Dictionary in skeleton.get("bones", []):
		parents[str(bone.get("name", ""))] = str(bone.get("parent", ""))
	for child: String in REQUIRED_PARENTS:
		if str(parents.get(child, "<missing>")) != str(REQUIRED_PARENTS[child]):
			_errors.append("Hierarchy mismatch: %s must directly parent %s" % [REQUIRED_PARENTS[child], child])
	var body_attachments: Dictionary = skeleton["skins"][0]["attachments"]["vivhite_body"]
	if body_attachments.size() != 1 or not body_attachments.has("vivhite_combat_body"):
		_errors.append("Candidate is not exactly one full-body mesh attachment")
	for animation_name: String in EXPECTED_ANIMATIONS:
		if skeleton["animations"][animation_name].get("slots", {}).has("vivhite_body"):
			_errors.append("Animation %s switches the full-body attachment" % animation_name)
	var die_events: Array = skeleton["animations"]["die"].get("events", [])
	var clear_at_zero := false
	for event: Dictionary in die_events:
		if str(event.get("name", "")) == "clear_vfx" and is_zero_approx(float(event.get("time", -1.0))):
			clear_at_zero = true
	if not clear_at_zero:
		_errors.append("die must emit clear_vfx at t=0")


func _sample_animation(data: Resource, animation_name: String, duration: float) -> bool:
	var sprite: Node2D = ClassDB.instantiate("SpineSprite") as Node2D
	if sprite == null:
		_errors.append("Could not instantiate SpineSprite for %s" % animation_name)
		return false
	root.add_child(sprite)
	sprite.set("skeleton_data_res", data)
	var state: Object = sprite.call("get_animation_state")
	var skeleton: Object = sprite.call("get_skeleton")
	if state == null or skeleton == null:
		_errors.append("SpineSprite did not initialize animation state for %s" % animation_name)
		sprite.queue_free()
		return false
	state.call("set_animation", animation_name, false, 0)
	var previous := 0.0
	for fraction: float in [0.0, 0.25, 0.50, 0.75, 1.0]:
		var sample_time := duration * fraction
		state.call("update", sample_time - previous)
		state.call("apply", skeleton)
		sprite.call("update_skeleton", 0.0)
		previous = sample_time
	sprite.queue_free()
	return true


func _motion_metrics(skeleton: Dictionary) -> Dictionary:
	var animations: Dictionary = skeleton["animations"]
	return {
		"scene_scale": SCENE_SCALE,
		"attack_root_x_range_px": _axis_range(animations["attack"], "vivhite_rig", "x") * SCENE_SCALE,
		"attack_heavy_root_x_range_px": _axis_range(animations["attack_heavy"], "vivhite_rig", "x") * SCENE_SCALE,
		"hurt_root_x_range_px": _axis_range(animations["hurt"], "vivhite_rig", "x") * SCENE_SCALE,
		"cast_root_y_range_px": _axis_range(animations["cast"], "vivhite_rig", "y") * SCENE_SCALE,
		"idle_root_y_range_px": _axis_range(animations["idle_loop"], "vivhite_rig", "y") * SCENE_SCALE,
		"die_root_key_count": animations["die"]["bones"]["vivhite_rig"]["translate"].size(),
		"direct_parent_contract_count": REQUIRED_PARENTS.size(),
	}


func _axis_range(animation: Dictionary, bone_name: String, axis: String) -> float:
	var minimum := INF
	var maximum := -INF
	for key: Dictionary in animation["bones"][bone_name]["translate"]:
		var value := float(key.get(axis, 0.0))
		minimum = minf(minimum, value)
		maximum = maxf(maximum, value)
	return maximum - minimum


func _finish(metrics: Dictionary) -> void:
	if _errors.is_empty():
		print("[whole-mesh-candidate] Spine load and animation sampling passed")
		print(JSON.stringify(metrics, "  ", false))
		quit(0)
		return
	for message: String in _errors:
		push_error("[whole-mesh-candidate] %s" % message)
	quit(1)
