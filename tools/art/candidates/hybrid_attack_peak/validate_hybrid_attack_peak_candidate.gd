extends SceneTree

## Read-only, headless acceptance gate for the isolated V3 Hybrid attack-peak
## candidate. It validates the authored JSON/atlas contract first, then loads
## and samples the result through the game-compatible Spine GDExtension. It
## never rebuilds, rewrites, publishes, deploys, or controls the game.

const ROOT := "res://tools/candidates/hybrid_attack_peak"
const DATA_PATH := ROOT + "/vivhite_combat_skeleton_data.tres"
const JSON_PATH := ROOT + "/vivhite_combat.spjson"
const ATLAS_PATH := ROOT + "/vivhite_combat.spatlas"
const NEUTRAL_PAGE_PATH := ROOT + "/vivhite_combat.png"
const DEATH_PAGE_PATH := ROOT + "/vivhite_combat_death.png"
const ACTION_PAGE_PATH := ROOT + "/vivhite_combat_attack.png"
const BASELINE_JSON_PATH := "res://tools/candidates/whole_mesh/vivhite_combat.spjson"

const EXPECTED_FILES := [
	"vivhite_combat.png",
	"vivhite_combat.spatlas",
	"vivhite_combat.spjson",
	"vivhite_combat_attack.png",
	"vivhite_combat_death.png",
	"vivhite_combat_skeleton_data.tres",
]
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
const EXPECTED_EVENTS := [
	"attack_slash_start",
	"heavy_slash_start",
	"cast_eyes_start",
	"clear_vfx",
]

const BODY_BONE := "vivhite_rig"
const BODY_SLOT := "vivhite_body"
const BODY_REGION := "vivhite_combat_body"
const ACTION_BONE := "vivhite_action_pose_root"
const ACTION_SLOT := "vivhite_action_pose"
const ACTION_REGION := "vivhite_combat_attack_peak"
const DEATH_BONE := "vivhite_death_pose"
const DEATH_SLOT := "vivhite_death_body"
const DEATH_REGION := "vivhite_combat_death_side"
const ARC_BONE := "vivhite_magic_arc"
const EYE_BONE := "vivhite_eye_anchor"
const SLASH_SLOT := "slash_mesh"
const EYE_SLOT := "eye_attach_slot"
const CHARACTER_SLOTS := [BODY_SLOT, ACTION_SLOT, DEATH_SLOT]

const ATTACK_ENTER := 0.08
const ATTACK_EXIT := 0.20
const RELAXED_END := 12.000001
const ACTION_PAGE_SIZE := Vector2i(2048, 2304)
const ACTION_REGION_RECT := Rect2i(16, 16, 1536, 2272)
const ACTION_WORLD_SIZE := Vector2(868.0, 1302.0)
const ACTION_SETUP_CENTER := Vector2(0.0, 590.0)
const EPSILON := 0.00001

var _errors: Array[String] = []
var _visibility_samples := 0
var _runtime_samples := 0


func _initialize() -> void:
	call_deferred("_run")


func _run() -> void:
	_validate_six_file_directory()
	var skeleton := _load_dictionary(JSON_PATH, "Hybrid Spine JSON")
	var baseline := _load_dictionary(BASELINE_JSON_PATH, "whole-mesh baseline Spine JSON")
	var atlas_wrapper := _load_dictionary(ATLAS_PATH, "Hybrid atlas wrapper")
	if skeleton.is_empty() or baseline.is_empty() or atlas_wrapper.is_empty():
		_finish()
		return

	_validate_raw_contract(skeleton, baseline)
	_validate_atlas_contract(atlas_wrapper, skeleton)
	_validate_runtime_contract()
	_finish()


func _validate_six_file_directory() -> void:
	var files := PackedStringArray()
	for file_name: String in DirAccess.get_files_at(ROOT):
		if file_name.ends_with(".import") or file_name.ends_with(".uid"):
			continue
		files.append(file_name)
	files.sort()
	var expected := PackedStringArray(EXPECTED_FILES)
	expected.sort()
	if files != expected:
		_errors.append("Hybrid candidate must contain exactly six authored files; got %s" % files)


func _validate_raw_contract(skeleton: Dictionary, baseline: Dictionary) -> void:
	var header: Dictionary = skeleton.get("skeleton", {})
	if str(header.get("spine", "")) != "4.2.43":
		_errors.append("Raw Spine version must be 4.2.43")
	if str(header.get("hash", "")) != "vivhite-hybrid-v3-attack-peak-v1":
		_errors.append("Hybrid skeleton hash does not identify the V3 attack-peak contract")

	var animations: Dictionary = skeleton.get("animations", {})
	if _sorted_keys(animations) != _sorted_keys(EXPECTED_ANIMATIONS):
		_errors.append("Hybrid candidate must contain exactly the eight required animations")
	var top_events: Dictionary = skeleton.get("events", {})
	if _sorted_keys(top_events) != _sorted_strings(EXPECTED_EVENTS):
		_errors.append("Hybrid candidate must declare exactly the four required events")

	var bones := _named_dictionaries(skeleton.get("bones", []))
	var slots := _named_dictionaries(skeleton.get("slots", []))
	_validate_bone_and_slot_contract(bones, slots)
	_validate_skin_contract(skeleton)
	_validate_unchanged_event_and_slash_contract(skeleton, baseline)

	for animation_name: String in EXPECTED_ANIMATIONS:
		if not animations.has(animation_name):
			continue
		var animation: Dictionary = animations[animation_name]
		_validate_action_reset(animation_name, animation)
		_validate_no_person_crossfade(animation_name, animation)
		_validate_attachment_names(animation_name, animation)
		_validate_exactly_one_person_for_all_segments(
			animation_name,
			animation,
			float(EXPECTED_ANIMATIONS[animation_name]),
			slots
		)
	_validate_attack_atomic_contract(animations.get("attack", {}))
	_validate_relaxed_boundary_contract(animations.get("relaxed_loop", {}))


func _validate_bone_and_slot_contract(bones: Dictionary, slots: Dictionary) -> void:
	for bone_name: String in [BODY_BONE, ACTION_BONE, DEATH_BONE, ARC_BONE, EYE_BONE]:
		if not bones.has(bone_name):
			_errors.append("Missing required bone: %s" % bone_name)
	for slot_name: String in [BODY_SLOT, ACTION_SLOT, DEATH_SLOT, SLASH_SLOT, EYE_SLOT]:
		if not slots.has(slot_name):
			_errors.append("Missing required slot: %s" % slot_name)
	if bones.has(ACTION_BONE):
		var action_bone: Dictionary = bones[ACTION_BONE]
		if str(action_bone.get("parent", "")) != BODY_BONE:
			_errors.append("%s must be a direct child of %s" % [ACTION_BONE, BODY_BONE])
		if not _near(float(action_bone.get("x", NAN)), ACTION_SETUP_CENTER.x) or not _near(
			float(action_bone.get("y", NAN)), ACTION_SETUP_CENTER.y
		):
			_errors.append("Action-pose root lost the frozen neutral world center")
	for anchor_name: String in [ARC_BONE, EYE_BONE]:
		if bones.has(anchor_name) and str(bones[anchor_name].get("parent", "")) != BODY_BONE:
			_errors.append("Hybrid VFX anchor must follow %s directly: %s" % [BODY_BONE, anchor_name])
	var expected_slot_bones := {
		BODY_SLOT: BODY_BONE,
		ACTION_SLOT: ACTION_BONE,
		DEATH_SLOT: DEATH_BONE,
		SLASH_SLOT: ARC_BONE,
		EYE_SLOT: EYE_BONE,
	}
	for slot_name: String in expected_slot_bones:
		if slots.has(slot_name) and str(slots[slot_name].get("bone", "")) != str(expected_slot_bones[slot_name]):
			_errors.append("Slot %s is bound to the wrong bone" % slot_name)
	if slots.has(BODY_SLOT) and str(slots[BODY_SLOT].get("attachment", "")) != BODY_REGION:
		_errors.append("Neutral body must be the setup-pose character attachment")
	for hidden_slot: String in [ACTION_SLOT, DEATH_SLOT]:
		if slots.has(hidden_slot) and slots[hidden_slot].has("attachment"):
			_errors.append("Setup pose must keep %s empty" % hidden_slot)


func _validate_skin_contract(skeleton: Dictionary) -> void:
	var skins: Array = skeleton.get("skins", [])
	if skins.size() != 1 or str(skins[0].get("name", "")) != "default":
		_errors.append("Hybrid candidate must contain exactly the default skin")
		return
	var attachments: Dictionary = skins[0].get("attachments", {})
	var required := {
		BODY_SLOT: BODY_REGION,
		ACTION_SLOT: ACTION_REGION,
		DEATH_SLOT: DEATH_REGION,
	}
	for slot_name: String in required:
		var slot_attachments: Dictionary = attachments.get(slot_name, {})
		if slot_attachments.size() != 1 or not slot_attachments.has(required[slot_name]):
			_errors.append("Skin slot %s must contain exactly region %s" % [slot_name, required[slot_name]])
	if not attachments.has(ACTION_SLOT) or not attachments[ACTION_SLOT].has(ACTION_REGION):
		return
	var action: Dictionary = attachments[ACTION_SLOT][ACTION_REGION]
	if str(action.get("type", "region")) != "region" or str(action.get("path", "")) != ACTION_REGION:
		_errors.append("attack_peak must remain one rigid region attachment")
	if not _near(float(action.get("width", NAN)), ACTION_WORLD_SIZE.x) or not _near(
		float(action.get("height", NAN)), ACTION_WORLD_SIZE.y
	):
		_errors.append("attack_peak world dimensions no longer match the frozen neutral body contract")
	var neutral: Dictionary = attachments.get(BODY_SLOT, {}).get(BODY_REGION, {})
	if not _near(float(neutral.get("width", NAN)), float(action.get("width", NAN))) or not _near(
		float(neutral.get("height", NAN)), float(action.get("height", NAN))
	):
		_errors.append("attack_peak and neutral body no longer share one authored world size")


func _validate_unchanged_event_and_slash_contract(skeleton: Dictionary, baseline: Dictionary) -> void:
	if not _same_variant(skeleton.get("events", {}), baseline.get("events", {})):
		_errors.append("Top-level Spine event definitions changed from the accepted whole-mesh baseline")
	var animations: Dictionary = skeleton.get("animations", {})
	var baseline_animations: Dictionary = baseline.get("animations", {})
	for animation_name: String in EXPECTED_ANIMATIONS:
		if not animations.has(animation_name) or not baseline_animations.has(animation_name):
			continue
		var animation: Dictionary = animations[animation_name]
		var baseline_animation: Dictionary = baseline_animations[animation_name]
		if not _same_variant(animation.get("events", []), baseline_animation.get("events", [])):
			_errors.append("Event timeline changed from baseline: %s" % animation_name)
		var slash: Variant = animation.get("slots", {}).get(SLASH_SLOT, null)
		var baseline_slash: Variant = baseline_animation.get("slots", {}).get(SLASH_SLOT, null)
		if not _same_variant(slash, baseline_slash):
			_errors.append("slash_mesh attachment timeline changed from baseline: %s" % animation_name)


func _validate_attack_atomic_contract(attack: Dictionary) -> void:
	if attack.is_empty():
		return
	var slots: Dictionary = attack.get("slots", {})
	var body_keys: Array = slots.get(BODY_SLOT, {}).get("attachment", [])
	var action_keys: Array = slots.get(ACTION_SLOT, {}).get("attachment", [])
	var expected_times := [0.0, ATTACK_ENTER, ATTACK_EXIT]
	var expected_body := [BODY_REGION, null, BODY_REGION]
	var expected_action := [null, ACTION_REGION, null]
	if body_keys.size() != 3 or action_keys.size() != 3:
		_errors.append("attack must contain exactly three neutral/action attachment keys")
		return
	for index in 3:
		if (
			not _near(float(body_keys[index].get("time", -1.0)), float(expected_times[index]))
			or not _near(float(action_keys[index].get("time", -1.0)), float(expected_times[index]))
			or body_keys[index].get("name", "sentinel") != expected_body[index]
			or action_keys[index].get("name", "sentinel") != expected_action[index]
		):
			_errors.append("attack must atomically show neutral/action/neutral at 0.00/0.08/0.20")
			break


func _validate_action_reset(animation_name: String, animation: Dictionary) -> void:
	var slots: Dictionary = animation.get("slots", {})
	if not slots.has(ACTION_SLOT):
		_errors.append("Every Hybrid animation must explicitly reset %s: %s" % [ACTION_SLOT, animation_name])
		return
	var keys: Array = slots[ACTION_SLOT].get("attachment", [])
	if keys.is_empty() or not _near(float(keys[0].get("time", -1.0)), 0.0) or keys[0].get(
		"name", "sentinel"
	) != null:
		_errors.append("%s must explicitly clear %s at t=0" % [animation_name, ACTION_SLOT])
	if animation_name not in ["attack", "relaxed_loop"] and keys.size() != 1:
		_errors.append("Only attack/relaxed_loop may add keys after the t=0 action reset: %s" % animation_name)


func _validate_relaxed_boundary_contract(relaxed: Dictionary) -> void:
	if relaxed.is_empty():
		return
	var slots: Dictionary = relaxed.get("slots", {})
	var expectations := {
		BODY_SLOT: [BODY_REGION, BODY_REGION],
		ACTION_SLOT: [null, null],
		DEATH_SLOT: [null, null],
	}
	for slot_name: String in expectations:
		var keys: Array = slots.get(slot_name, {}).get("attachment", [])
		if keys.size() != 2:
			_errors.append("relaxed_loop must explicitly reset %s at both cycle boundaries" % slot_name)
			continue
		for index in 2:
			var expected_time := 0.0 if index == 0 else RELAXED_END
			if not _near(float(keys[index].get("time", -1.0)), expected_time) or keys[index].get(
				"name", "sentinel"
			) != expectations[slot_name][index]:
				_errors.append("relaxed_loop has an invalid %s reset at %.6f" % [slot_name, expected_time])


func _validate_no_person_crossfade(animation_name: String, animation: Dictionary) -> void:
	var slots: Dictionary = animation.get("slots", {})
	for slot_name: String in CHARACTER_SLOTS:
		var timelines: Dictionary = slots.get(slot_name, {})
		for forbidden_timeline: String in ["rgba", "rgb", "alpha", "color", "twoColor"]:
			if timelines.has(forbidden_timeline):
				_errors.append("%s/%s uses forbidden character crossfade timeline %s" % [
					animation_name, slot_name, forbidden_timeline,
				])


func _validate_attachment_names(animation_name: String, animation: Dictionary) -> void:
	var allowed := {BODY_SLOT: BODY_REGION, ACTION_SLOT: ACTION_REGION, DEATH_SLOT: DEATH_REGION}
	var slots: Dictionary = animation.get("slots", {})
	for slot_name: String in allowed:
		for key: Dictionary in slots.get(slot_name, {}).get("attachment", []):
			var name: Variant = key.get("name", null)
			if name != null and str(name) != str(allowed[slot_name]):
				_errors.append("%s/%s references unexpected character attachment %s" % [
					animation_name, slot_name, name,
				])


func _validate_exactly_one_person_for_all_segments(
	animation_name: String,
	animation: Dictionary,
	duration: float,
	setup_slots: Dictionary,
) -> void:
	var key_times: Array[float] = [0.0, duration]
	_collect_key_times(animation, key_times)
	key_times.sort()
	var unique_times: Array[float] = []
	for time: float in key_times:
		var bounded := clampf(time, 0.0, duration)
		if unique_times.is_empty() or not _near(unique_times[-1], bounded):
			unique_times.append(bounded)
	var sample_times := unique_times.duplicate()
	# Attachment visibility is piecewise constant. Every authored key plus one
	# midpoint in every interval is therefore an exhaustive proof, not a sparse
	# visual guess, for all arbitrary times in this animation.
	for index in range(unique_times.size() - 1):
		var left := unique_times[index]
		var right := unique_times[index + 1]
		if right - left > EPSILON:
			sample_times.append((left + right) * 0.5)
	sample_times.sort()
	for time: float in sample_times:
		var visible := 0
		var visible_names := []
		for slot_name: String in CHARACTER_SLOTS:
			var setup_name: Variant = setup_slots.get(slot_name, {}).get("attachment", null)
			var current: Variant = _attachment_at_time(
				setup_name,
				animation.get("slots", {}).get(slot_name, {}).get("attachment", []),
				time
			)
			if current != null:
				visible += 1
				visible_names.append("%s=%s" % [slot_name, current])
		_visibility_samples += 1
		if visible != 1:
			_errors.append("%s at %.7f has %d visible character layers (%s), expected exactly one" % [
				animation_name, time, visible, ", ".join(visible_names),
			])


func _validate_atlas_contract(wrapper: Dictionary, skeleton: Dictionary) -> void:
	if str(wrapper.get("source_path", "")) != ROOT + "/vivhite_combat.atlas":
		_errors.append("Atlas wrapper is not candidate-local")
	var atlas_data := str(wrapper.get("atlas_data", ""))
	var exact_action_section := "\n".join(PackedStringArray([
		"vivhite_combat_attack.png",
		"size:2048,2304",
		"filter:Linear,Linear",
		"pma:false",
		"repeat:none",
		ACTION_REGION,
		"bounds:16,16,1536,2272",
	]))
	if atlas_data.count("vivhite_combat_attack.png\n") != 1 or not atlas_data.contains(exact_action_section):
		_errors.append("Attack atlas page/region no longer matches the frozen neutral-canvas contract")
	if atlas_data.count("%s\n" % ACTION_REGION) != 1:
		_errors.append("Attack atlas must declare exactly one %s region" % ACTION_REGION)
	_validate_action_page_alpha()

	var tres := FileAccess.get_file_as_string(DATA_PATH)
	for required_path: String in [ATLAS_PATH, JSON_PATH]:
		if not tres.contains(required_path):
			_errors.append("Skeleton-data wrapper is missing candidate-local path %s" % required_path)
	# The rigid attachment and its atlas region must preserve the same neutral
	# source-window dimensions; this is the observable output-side invariant of
	# the builder's frozen neutral-reference transform.
	var skins: Array = skeleton.get("skins", [])
	if skins.is_empty():
		return
	var attachments: Dictionary = skins[0].get("attachments", {})
	var action: Dictionary = attachments.get(ACTION_SLOT, {}).get(ACTION_REGION, {})
	if action.is_empty():
		return
	if not _near(float(action.get("width", NAN)), ACTION_WORLD_SIZE.x) or not _near(
		float(action.get("height", NAN)), ACTION_WORLD_SIZE.y
	):
		_errors.append("Attack atlas attachment lost its frozen neutral-reference world dimensions")


func _validate_action_page_alpha() -> void:
	var image := Image.load_from_file(ProjectSettings.globalize_path(ACTION_PAGE_PATH))
	if image == null or image.is_empty():
		_errors.append("Attack page could not be decoded")
		return
	if image.get_format() != Image.FORMAT_RGBA8:
		_errors.append("Attack page must decode natively as RGBA8; no conversion is allowed")
		return
	if image.get_size() != ACTION_PAGE_SIZE:
		_errors.append("Attack page must be exactly %s" % ACTION_PAGE_SIZE)
	var corners := [
		Vector2i(0, 0),
		Vector2i(image.get_width() - 1, 0),
		Vector2i(0, image.get_height() - 1),
		Vector2i(image.get_width() - 1, image.get_height() - 1),
	]
	for corner: Vector2i in corners:
		if image.get_pixelv(corner).a8 != 0:
			_errors.append("Attack page corner %s is not natively transparent" % corner)
	var used := image.get_used_rect()
	if not used.has_area():
		_errors.append("Attack page contains no non-zero Alpha subject")
	elif not ACTION_REGION_RECT.encloses(used):
		_errors.append("Attack page Alpha escapes its declared atlas region: %s" % used)
	var bytes := image.get_data()
	var has_opaque := false
	for byte_index in range(3, bytes.size(), 4):
		if int(bytes[byte_index]) >= 250:
			has_opaque = true
			break
	if not has_opaque:
		_errors.append("Attack page has no near-opaque subject pixels")


func _validate_runtime_contract() -> void:
	for type_name: String in ["SpineSprite", "SpineSkeletonDataResource", "SpineSkeletonFileResource", "SpineAtlasResource"]:
		if not ClassDB.class_exists(type_name):
			_errors.append("Game-compatible Spine class is unavailable: %s" % type_name)
	if not _errors.filter(func(message: String) -> bool: return message.contains("Spine class")).is_empty():
		return
	var data: Resource = ResourceLoader.load(DATA_PATH)
	if data == null or not data.is_class("SpineSkeletonDataResource"):
		_errors.append("Spine runtime could not load Hybrid skeleton data")
		return
	if str(data.call("get_version")) != "4.2.43":
		_errors.append("Spine runtime must report version 4.2.43")
	if data.call("get_animations").size() != EXPECTED_ANIMATIONS.size():
		_errors.append("Spine runtime must expose exactly eight animations")
	for animation_name: String in EXPECTED_ANIMATIONS:
		var animation: Object = data.call("find_animation", animation_name)
		if animation == null:
			_errors.append("Spine runtime is missing animation %s" % animation_name)
			continue
		var duration := float(animation.call("get_duration"))
		if not _near(duration, float(EXPECTED_ANIMATIONS[animation_name])):
			_errors.append("Spine runtime duration mismatch for %s: %.7f" % [animation_name, duration])
		_sample_runtime_animation(data, animation_name, duration)
	for slot_name: String in [BODY_SLOT, ACTION_SLOT, DEATH_SLOT, SLASH_SLOT, EYE_SLOT]:
		if data.call("find_slot", slot_name) == null:
			_errors.append("Spine runtime is missing slot %s" % slot_name)
	for event_name: String in EXPECTED_EVENTS:
		if data.call("find_event", event_name) == null:
			_errors.append("Spine runtime is missing event %s" % event_name)


func _sample_runtime_animation(data: Resource, animation_name: String, duration: float) -> void:
	var sprite: Node2D = ClassDB.instantiate("SpineSprite") as Node2D
	if sprite == null:
		_errors.append("Could not instantiate SpineSprite for %s" % animation_name)
		return
	root.add_child(sprite)
	sprite.set("skeleton_data_res", data)
	var state: Object = sprite.call("get_animation_state")
	var runtime_skeleton: Object = sprite.call("get_skeleton")
	if state == null or runtime_skeleton == null:
		_errors.append("SpineSprite did not initialize state for %s" % animation_name)
		sprite.queue_free()
		return
	state.call("set_animation", animation_name, false, 0)
	var sample_times: Array[float] = [0.0, duration * 0.5, duration]
	if animation_name == "attack":
		sample_times.append_array([ATTACK_ENTER - 0.0001, ATTACK_ENTER, ATTACK_EXIT - 0.0001, ATTACK_EXIT])
	sample_times.sort()
	var previous := 0.0
	for sample_time: float in sample_times:
		state.call("update", sample_time - previous)
		state.call("apply", runtime_skeleton)
		sprite.call("update_skeleton", 0.0)
		_runtime_samples += 1
		previous = sample_time
	sprite.queue_free()


func _attachment_at_time(setup_name: Variant, keys: Array, time: float) -> Variant:
	var result: Variant = setup_name
	for key: Dictionary in keys:
		if float(key.get("time", 0.0)) <= time + EPSILON:
			result = key.get("name", null)
		else:
			break
	return result


func _collect_key_times(value: Variant, output: Array[float]) -> void:
	if value is Dictionary:
		var dictionary: Dictionary = value
		if dictionary.has("time") and (dictionary["time"] is float or dictionary["time"] is int):
			output.append(float(dictionary["time"]))
		for key: Variant in dictionary:
			_collect_key_times(dictionary[key], output)
	elif value is Array:
		for item: Variant in value:
			_collect_key_times(item, output)


func _named_dictionaries(items: Array) -> Dictionary:
	var result := {}
	for item: Dictionary in items:
		result[str(item.get("name", ""))] = item
	return result


func _load_dictionary(path: String, label: String) -> Dictionary:
	if not FileAccess.file_exists(path):
		_errors.append("%s is missing: %s" % [label, path])
		return {}
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(path))
	if not parsed is Dictionary:
		_errors.append("%s is unreadable: %s" % [label, path])
		return {}
	return parsed


func _same_variant(left: Variant, right: Variant) -> bool:
	if (left is int or left is float) and (right is int or right is float):
		return _near(float(left), float(right))
	if typeof(left) != typeof(right):
		return false
	if left is Dictionary:
		var left_dictionary: Dictionary = left
		var right_dictionary: Dictionary = right
		if left_dictionary.size() != right_dictionary.size():
			return false
		for key: Variant in left_dictionary:
			if not right_dictionary.has(key) or not _same_variant(left_dictionary[key], right_dictionary[key]):
				return false
		return true
	if left is Array:
		var left_array: Array = left
		var right_array: Array = right
		if left_array.size() != right_array.size():
			return false
		for index in left_array.size():
			if not _same_variant(left_array[index], right_array[index]):
				return false
		return true
	return left == right


func _sorted_keys(dictionary: Dictionary) -> Array[String]:
	var result: Array[String] = []
	for key: Variant in dictionary:
		result.append(str(key))
	result.sort()
	return result


func _sorted_strings(values: Array) -> Array[String]:
	var result: Array[String] = []
	for value: Variant in values:
		result.append(str(value))
	result.sort()
	return result


func _near(left: float, right: float) -> bool:
	return absf(left - right) <= EPSILON


func _finish() -> void:
	if _errors.is_empty():
		print("[hybrid-attack-peak] Read-only static and Spine runtime validation passed")
		print(JSON.stringify({
			"authored_file_count": EXPECTED_FILES.size(),
			"animation_count": EXPECTED_ANIMATIONS.size(),
			"attack_atomic_window": [ATTACK_ENTER, ATTACK_EXIT],
			"native_action_page_size": ACTION_PAGE_SIZE,
			"runtime_sample_count": _runtime_samples,
			"spine_version": "4.2.43",
			"visibility_sample_count": _visibility_samples,
		}, "  ", false))
		quit(0)
		return
	for message: String in _errors:
		push_error("[hybrid-attack-peak] %s" % message)
	quit(1)
