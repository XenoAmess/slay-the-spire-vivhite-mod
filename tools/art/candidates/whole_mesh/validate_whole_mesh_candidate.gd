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
const ATTACK_FORWARD_MIN := 95.0
const ATTACK_FORWARD_MAX := 105.0
const HEAVY_FORWARD_MIN := 150.0
const HEAVY_FORWARD_MAX := 165.0
const HURT_BACKWARD_MIN := 95.0

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

	var attack_forward := _axis_directional_peak(skeleton["animations"]["attack"], "vivhite_rig", "x", true)
	if attack_forward < ATTACK_FORWARD_MIN or attack_forward > ATTACK_FORWARD_MAX:
		_errors.append("attack forward root peak %.3f is outside 95-105 Spine units" % attack_forward)
	var heavy_forward := _axis_directional_peak(skeleton["animations"]["attack_heavy"], "vivhite_rig", "x", true)
	if heavy_forward < HEAVY_FORWARD_MIN or heavy_forward > HEAVY_FORWARD_MAX:
		_errors.append("attack_heavy forward root peak %.3f is outside 150-165 Spine units" % heavy_forward)
	var hurt_backward := _axis_directional_peak(skeleton["animations"]["hurt"], "vivhite_rig", "x", false)
	if hurt_backward < HURT_BACKWARD_MIN:
		_errors.append("hurt backward root peak %.3f is below 95 Spine units" % hurt_backward)
	_validate_easing_contract(skeleton)


func _validate_easing_contract(skeleton: Dictionary) -> void:
	for animation_name: String in EXPECTED_ANIMATIONS:
		var bones: Dictionary = skeleton["animations"][animation_name].get("bones", {})
		for bone_name: String in bones:
			var timelines: Dictionary = bones[bone_name]
			for timeline_name: String in ["rotate", "translate"]:
				if not timelines.has(timeline_name):
					continue
				var frames: Array = timelines[timeline_name]
				for index in range(frames.size() - 1):
					var frame: Dictionary = frames[index]
					var finish: Dictionary = frames[index + 1]
					if not frame.has("curve") or not frame["curve"] is Array:
						_errors.append("%s/%s/%s frame %d is missing Bezier easing" % [animation_name, bone_name, timeline_name, index])
						continue
					var curve: Array = frame["curve"]
					var expected_size := 4 if timeline_name == "rotate" else 8
					if curve.size() != expected_size:
						_errors.append("%s/%s/%s frame %d curve has %d values, expected %d" % [animation_name, bone_name, timeline_name, index, curve.size(), expected_size])
						continue
					var start_time := float(frame.get("time", 0.0))
					var finish_time := float(finish.get("time", 0.0))
					for time_index: int in ([0, 2] if timeline_name == "rotate" else [0, 2, 4, 6]):
						var control_time := float(curve[time_index])
						if control_time < start_time or control_time > finish_time:
							_errors.append("%s/%s/%s frame %d has an out-of-segment Bezier handle" % [animation_name, bone_name, timeline_name, index])


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
		"attack_root_forward_peak_units": _axis_directional_peak(animations["attack"], "vivhite_rig", "x", true),
		"attack_root_forward_peak_px": _axis_directional_peak(animations["attack"], "vivhite_rig", "x", true) * SCENE_SCALE,
		"attack_heavy_root_forward_peak_units": _axis_directional_peak(animations["attack_heavy"], "vivhite_rig", "x", true),
		"attack_heavy_root_forward_peak_px": _axis_directional_peak(animations["attack_heavy"], "vivhite_rig", "x", true) * SCENE_SCALE,
		"hurt_root_backward_peak_units": _axis_directional_peak(animations["hurt"], "vivhite_rig", "x", false),
		"hurt_root_backward_peak_px": _axis_directional_peak(animations["hurt"], "vivhite_rig", "x", false) * SCENE_SCALE,
		"cast_root_y_range_px": _axis_range(animations["cast"], "vivhite_rig", "y") * SCENE_SCALE,
		"idle_root_y_range_px": _axis_range(animations["idle_loop"], "vivhite_rig", "y") * SCENE_SCALE,
		"bezier_segment_count": _count_bezier_segments(skeleton),
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


func _axis_directional_peak(
	animation: Dictionary,
	bone_name: String,
	axis: String,
	positive: bool,
) -> float:
	var peak := 0.0
	for key: Dictionary in animation["bones"][bone_name]["translate"]:
		var value := float(key.get(axis, 0.0))
		peak = maxf(peak, value if positive else -value)
	return peak


func _count_bezier_segments(skeleton: Dictionary) -> int:
	var count := 0
	for animation_name: String in EXPECTED_ANIMATIONS:
		var bones: Dictionary = skeleton["animations"][animation_name].get("bones", {})
		for bone_name: String in bones:
			var timelines: Dictionary = bones[bone_name]
			for timeline_name: String in ["rotate", "translate"]:
				if not timelines.has(timeline_name):
					continue
				for frame: Dictionary in timelines[timeline_name]:
					if frame.has("curve") and frame["curve"] is Array:
						count += 1
	return count


func _finish(metrics: Dictionary) -> void:
	if _errors.is_empty():
		print("[whole-mesh-candidate] Spine load and animation sampling passed")
		print(JSON.stringify(metrics, "  ", false))
		quit(0)
		return
	for message: String in _errors:
		push_error("[whole-mesh-candidate] %s" % message)
	quit(1)
