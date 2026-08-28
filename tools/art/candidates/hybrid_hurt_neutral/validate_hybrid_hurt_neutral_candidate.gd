extends SceneTree

## Read-only static/runtime gate for the isolated protective neutral-mesh hurt
## experiment.  Rendering is handled by the shared hidden Vulkan comparator;
## this gate proves that only the intended hurt bone performance changed.

const ROOT := "res://tools/candidates/hybrid_hurt_neutral"
const UPSTREAM_ROOT := "res://tools/candidates/hybrid_action_set"
const JSON_PATH := ROOT + "/vivhite_combat.spjson"
const ATLAS_PATH := ROOT + "/vivhite_combat.spatlas"
const DATA_PATH := ROOT + "/vivhite_combat_skeleton_data.tres"
const SNAPSHOT_PATH := ROOT + "/upstream_snapshot.json"
const UPSTREAM_JSON_PATH := UPSTREAM_ROOT + "/vivhite_combat.spjson"
const UPSTREAM_ATLAS_PATH := UPSTREAM_ROOT + "/vivhite_combat.spatlas"
const UPSTREAM_DATA_PATH := UPSTREAM_ROOT + "/vivhite_combat_skeleton_data.tres"

const AUTHORED_FILES := [
	"vivhite_combat.png",
	"vivhite_combat.spatlas",
	"vivhite_combat.spjson",
	"vivhite_combat_attack.png",
	"vivhite_combat_attack_heavy.png",
	"vivhite_combat_death.png",
	"vivhite_combat_skeleton_data.tres",
]
const COPIED_PNGS := [
	"vivhite_combat.png",
	"vivhite_combat_attack.png",
	"vivhite_combat_attack_heavy.png",
	"vivhite_combat_death.png",
]
const EXPECTED_TIMES := [0.0, 0.10, 0.16, 0.28, 0.46, 0.70, 1.0]
const EXPECTED_IMPACT := {
	"vivhite_rig": Vector2(-118.0, 8.0),
	"vivhite_pelvis": -6.0,
	"vivhite_torso_lower": -12.0,
	"vivhite_torso_upper": -17.0,
	"vivhite_neck": 11.0,
	"vivhite_head": 16.0,
	"vivhite_upper_arm_left": 60.0,
	"vivhite_forearm_left": 100.0,
	"vivhite_hand_left": -80.0,
	"vivhite_upper_arm_right": 75.0,
	"vivhite_forearm_right": 75.0,
	"vivhite_hand_right": -70.0,
}
const EPSILON := 0.00001

var _errors: Array[String] = []
var _runtime_samples := 0
var _runtime_mix_samples := 0


func _initialize() -> void:
	call_deferred("_run")


func _run() -> void:
	var candidate := _load_dictionary(JSON_PATH, "candidate Spine JSON")
	var upstream := _load_dictionary(UPSTREAM_JSON_PATH, "upstream Spine JSON")
	var candidate_atlas := _load_dictionary(ATLAS_PATH, "candidate atlas wrapper")
	var upstream_atlas := _load_dictionary(UPSTREAM_ATLAS_PATH, "upstream atlas wrapper")
	var snapshot := _load_dictionary(SNAPSHOT_PATH, "upstream snapshot")
	if _errors.is_empty():
		_validate_file_set()
		_validate_stable_snapshot(snapshot)
		_validate_only_hurt_changed(candidate, upstream, candidate_atlas, upstream_atlas)
		_validate_hurt_contract(candidate)
		_validate_transition_contract()
		_validate_runtime()
	_finish()


func _validate_file_set() -> void:
	var files := PackedStringArray()
	for file_name: String in DirAccess.get_files_at(ROOT):
		if file_name.ends_with(".uid") or file_name.ends_with(".import"):
			continue
		files.append(file_name)
	files.sort()
	var expected := PackedStringArray(AUTHORED_FILES)
	expected.append("upstream_snapshot.json")
	expected.sort()
	if files != expected:
		_errors.append("Hurt candidate must contain exactly seven copied authored files plus snapshot; got %s" % files)


func _validate_stable_snapshot(snapshot: Dictionary) -> void:
	if str(snapshot.get("schema", "")) != "vivhite.hybrid-hurt-neutral-upstream-snapshot/v1":
		_errors.append("Upstream snapshot schema is missing or wrong")
	var hashes: Dictionary = snapshot.get("sha256", {})
	if hashes.size() != AUTHORED_FILES.size():
		_errors.append("Upstream snapshot must record all seven authored hashes")
		return
	for file_name: String in AUTHORED_FILES:
		var expected := str(hashes.get(file_name, ""))
		var current := FileAccess.get_sha256(UPSTREAM_ROOT + "/" + file_name)
		if expected.is_empty() or current != expected:
			_errors.append("Upstream changed after candidate snapshot; rebuild required: %s" % file_name)
	for file_name: String in COPIED_PNGS:
		if FileAccess.get_sha256(ROOT + "/" + file_name) != str(hashes.get(file_name, "")):
			_errors.append("Copied atlas page differs from its recorded upstream snapshot: %s" % file_name)


func _validate_only_hurt_changed(
	candidate: Dictionary,
	upstream: Dictionary,
	candidate_atlas: Dictionary,
	upstream_atlas: Dictionary,
) -> void:
	var normalized := candidate.duplicate(true)
	normalized["skeleton"]["hash"] = upstream.get("skeleton", {}).get("hash", "")
	normalized["animations"]["hurt"] = upstream.get("animations", {}).get("hurt", {}).duplicate(true)
	if JSON.stringify(normalized) != JSON.stringify(upstream):
		_errors.append("Candidate changed Spine data outside skeleton hash and hurt animation")
	if str(candidate.get("skeleton", {}).get("hash", "")) != "vivhite-hybrid-v3-hurt-neutral-v1":
		_errors.append("Candidate skeleton hash does not identify the hurt-neutral experiment")

	var atlas_normalized := candidate_atlas.duplicate(true)
	atlas_normalized["source_path"] = upstream_atlas.get("source_path", "")
	if JSON.stringify(atlas_normalized) != JSON.stringify(upstream_atlas):
		_errors.append("Candidate atlas wrapper changed outside its isolated source_path")
	if str(candidate_atlas.get("source_path", "")) != ROOT + "/vivhite_combat.atlas":
		_errors.append("Candidate atlas wrapper is not isolated to the hurt-neutral root")

	var upstream_tres := FileAccess.get_file_as_string(UPSTREAM_DATA_PATH)
	var candidate_tres := FileAccess.get_file_as_string(DATA_PATH)
	if candidate_tres != upstream_tres.replace(UPSTREAM_ROOT, ROOT):
		_errors.append("Candidate skeleton-data wrapper changed outside resource-root isolation")


func _validate_hurt_contract(skeleton: Dictionary) -> void:
	var animations: Dictionary = skeleton.get("animations", {})
	if animations.size() != 8 or not animations.has("hurt"):
		_errors.append("Candidate must retain exactly eight animations including hurt")
		return
	var hurt: Dictionary = animations["hurt"]
	var bones: Dictionary = hurt.get("bones", {})
	for bone_name: String in EXPECTED_IMPACT:
		if not bones.has(bone_name):
			_errors.append("Protective hurt is missing required bone track: %s" % bone_name)
			continue
		if bone_name == "vivhite_rig":
			var keys: Array = bones[bone_name].get("translate", [])
			_validate_times(keys, bone_name)
			if keys.size() == EXPECTED_TIMES.size():
				var expected: Vector2 = EXPECTED_IMPACT[bone_name]
				if not _near(float(keys[1].get("x", NAN)), expected.x) or not _near(float(keys[1].get("y", NAN)), expected.y):
					_errors.append("Protective hurt lost its measured root impact")
		else:
			var keys: Array = bones[bone_name].get("rotate", [])
			_validate_times(keys, bone_name)
			if keys.size() == EXPECTED_TIMES.size() and not _near(float(keys[1].get("value", NAN)), float(EXPECTED_IMPACT[bone_name])):
				_errors.append("Protective hurt impact changed for %s" % bone_name)

	for required_limb: String in [
		"vivhite_shoulder_left", "vivhite_upper_arm_left", "vivhite_hand_left",
		"vivhite_shoulder_right", "vivhite_upper_arm_right", "vivhite_hand_right",
		"vivhite_hip_left", "vivhite_thigh_left", "vivhite_shin_left",
		"vivhite_hip_right", "vivhite_thigh_right", "vivhite_shin_right",
	]:
		if not bones.has(required_limb):
			_errors.append("Protective hurt must articulate rather than translate the whole body: %s" % required_limb)

	var slots: Dictionary = hurt.get("slots", {})
	var action_keys: Array = slots.get("vivhite_action_pose", {}).get("attachment", [])
	if action_keys.size() != 1 or not _near(float(action_keys[0].get("time", -1.0)), 0.0) or action_keys[0].get("name", "sentinel") != null:
		_errors.append("hurt must keep the action-pose slot empty and use only neutral whole mesh")
	for forbidden_slot: String in ["vivhite_body", "vivhite_death_body", "slash_mesh", "eye_attach_slot"]:
		if slots.has(forbidden_slot):
			_errors.append("hurt must not switch character/VFX attachments: %s" % forbidden_slot)
	var events: Array = hurt.get("events", [])
	if events.size() != 1 or str(events[0].get("name", "")) != "clear_vfx" or not _near(float(events[0].get("time", -1.0)), 0.72):
		_errors.append("hurt must retain its sole clear_vfx event at 0.72 seconds")
	if JSON.stringify(hurt) == JSON.stringify(animations.get("low_health_loop", {})):
		_errors.append("Protective hurt must remain distinct from low-health idle")


func _validate_times(keys: Array, label: String) -> void:
	if keys.size() != EXPECTED_TIMES.size():
		_errors.append("%s must contain exactly seven hurt performance keys" % label)
		return
	for index in EXPECTED_TIMES.size():
		if not _near(float(keys[index].get("time", -1.0)), float(EXPECTED_TIMES[index])):
			_errors.append("%s has wrong key time at index %d" % [label, index])
		if index < EXPECTED_TIMES.size() - 1 and not keys[index].has("curve"):
			_errors.append("%s lost action easing before index %d" % [label, index + 1])


func _validate_transition_contract() -> void:
	var tres := FileAccess.get_file_as_string(DATA_PATH)
	for block: String in [
		"from = \"hurt\"\nto = \"hurt\"",
		"from = \"hurt\"\nto = \"die\"",
		"from = \"idle_loop\"\nto = \"hurt\"\nmix = 0.03",
		"from = \"hurt\"\nto = \"idle_loop\"\nmix = 0.1",
	]:
		if not tres.contains(block):
			_errors.append("Missing exact hurt transition block: %s" % block.replace("\n", " -> "))
	if not tres.contains("default_mix = 0.05"):
		_errors.append("Candidate lost default_mix = 0.05")


func _validate_runtime() -> void:
	for type_name: String in ["SpineSprite", "SpineSkeletonDataResource"]:
		if not ClassDB.class_exists(type_name):
			_errors.append("Game-compatible Spine class is unavailable: %s" % type_name)
	if not _errors.filter(func(message: String) -> bool: return message.contains("Spine class")).is_empty():
		return
	var data: Resource = ResourceLoader.load(DATA_PATH)
	if data == null or not data.is_class("SpineSkeletonDataResource"):
		_errors.append("Spine runtime could not load hurt-neutral skeleton data")
		return
	if str(data.call("get_version")) != "4.2.43":
		_errors.append("Spine runtime must report version 4.2.43")
	var animation: Object = data.call("find_animation", "hurt")
	if animation == null or not _near(float(animation.call("get_duration")), 1.0):
		_errors.append("Spine runtime must expose the one-second hurt animation")
		return
	var sprite: Node2D = ClassDB.instantiate("SpineSprite") as Node2D
	root.add_child(sprite)
	sprite.set("skeleton_data_res", data)
	var state: Object = sprite.call("get_animation_state")
	var skeleton: Object = sprite.call("get_skeleton")
	if state == null or skeleton == null:
		_errors.append("SpineSprite did not initialize for hurt runtime sampling")
		sprite.queue_free()
		return
	_validate_runtime_mix(sprite, state, skeleton, "idle_loop", "hurt", 0.03)
	_validate_runtime_mix(sprite, state, skeleton, "hurt", "hurt", 0.0)
	_validate_runtime_mix(sprite, state, skeleton, "hurt", "idle_loop", 0.10)
	_validate_runtime_mix(sprite, state, skeleton, "hurt", "die", 0.0)
	for time: float in EXPECTED_TIMES:
		state.call("set_animation", "hurt", false, 0)
		state.call("update", time)
		state.call("apply", skeleton)
		sprite.call("update_skeleton", 0.0)
		_runtime_samples += 1
	sprite.queue_free()


func _validate_runtime_mix(
	sprite: Node2D,
	state: Object,
	skeleton: Object,
	from_animation: String,
	to_animation: String,
	expected: float,
) -> void:
	# Spine does not promote a freshly assigned entry to the active mixing
	# source until animation-state update/apply has run at least once.
	state.call("set_animation", from_animation, true, 0)
	state.call("update", 0.05)
	state.call("apply", skeleton)
	sprite.call("update_skeleton", 0.0)
	var entry: Variant = state.call("set_animation", to_animation, false, 0)
	if entry == null or not entry is Object:
		_errors.append("Spine runtime returned no track entry for %s -> %s" % [from_animation, to_animation])
		return
	var entry_object := entry as Object
	var actual := -1.0
	for method_name: String in ["get_mix_duration", "get_mix_duration_seconds"]:
		if entry_object.has_method(method_name):
			actual = float(entry_object.call(method_name))
			break
	if actual < 0.0:
		_errors.append("Spine track entry exposes no mix-duration getter for %s -> %s" % [from_animation, to_animation])
		return
	_runtime_mix_samples += 1
	if not _near(actual, expected):
		_errors.append(
			"Runtime mix %s -> %s was %.5f, expected %.5f"
			% [from_animation, to_animation, actual, expected]
		)


func _load_dictionary(path: String, label: String) -> Dictionary:
	if not FileAccess.file_exists(path):
		_errors.append("Missing %s: %s" % [label, path])
		return {}
	var decoded: Variant = JSON.parse_string(FileAccess.get_file_as_string(path))
	if not decoded is Dictionary:
		_errors.append("Could not parse %s: %s" % [label, path])
		return {}
	return decoded


func _near(actual: float, expected: float) -> bool:
	return absf(actual - expected) <= EPSILON


func _finish() -> void:
	if _errors.is_empty():
		print("Hybrid neutral-mesh hurt validation passed.")
		print("  authored files: 8 (7 consistent upstream files + snapshot)")
		print("  protected contract: only skeleton hash and hurt bone performance changed")
		print("  transition mixes: idle->hurt .03 / hurt->hurt 0 / hurt->idle .10 / hurt->die 0")
		print("  runtime hurt samples: %d" % _runtime_samples)
		print("  runtime transition samples: %d" % _runtime_mix_samples)
		quit(0)
		return
	for message: String in _errors:
		push_error(message)
	quit(1)
