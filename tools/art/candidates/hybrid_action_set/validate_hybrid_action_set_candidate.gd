extends SceneTree

## Read-only static + Spine-runtime gate for the isolated V3 action set. It
## never rebuilds, deploys or controls the game. Generic preview tools must be
## given this candidate's `.spjson`; copying a `.tres` into a temporary folder
## does not relocate its fixed res:// dependencies and can silently load the
## earlier attack-only candidate instead.

const ROOT := "res://tools/candidates/hybrid_action_set"
const DATA_PATH := ROOT + "/vivhite_combat_skeleton_data.tres"
const JSON_PATH := ROOT + "/vivhite_combat.spjson"
const ATLAS_PATH := ROOT + "/vivhite_combat.spatlas"
const BASELINE_JSON_PATH := "res://tools/candidates/whole_mesh/vivhite_combat.spjson"

const EXPECTED_FILES := [
	"vivhite_combat.png",
	"vivhite_combat.spatlas",
	"vivhite_combat.spjson",
	"vivhite_combat_attack.png",
	"vivhite_combat_attack_heavy.png",
	"vivhite_combat_death.png",
	"vivhite_combat_skeleton_data.tres",
]
const EXPECTED_PAGES := {
	"vivhite_combat.png": Vector2i(3072, 2304),
	"vivhite_combat_attack.png": Vector2i(2048, 2304),
	"vivhite_combat_attack_heavy.png": Vector2i(2048, 2304),
	"vivhite_combat_death.png": Vector2i(2048, 1536),
}
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
const ATTACK_REGION := "vivhite_combat_attack_peak"
const HEAVY_REGION := "vivhite_combat_attack_heavy_peak"
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
const ATTACK_PRE_EXIT := 0.1999
const HEAVY_ENTER := 0.12
const HEAVY_EXIT := 0.32
const HEAVY_PRE_EXIT := 0.3199
const RELAXED_END := 12.000001
const ACTION_REGION_RECT := Rect2i(16, 16, 1536, 2272)
const ACTION_WORLD_SIZE := Vector2(868.0, 1302.0)
const ACTION_SETUP_CENTER := Vector2(0.0, 590.0)
const PEAK_ARC_OFFSET := Vector2(210.0, 30.0)
const EPSILON := 0.00001

var _errors: Array[String] = []
var _visibility_samples := 0
var _runtime_samples := 0


func _initialize() -> void:
	call_deferred("_run")


func _run() -> void:
	_validate_file_directory()
	var skeleton := _load_dictionary(JSON_PATH, "action-set Spine JSON")
	var baseline := _load_dictionary(BASELINE_JSON_PATH, "whole-mesh baseline Spine JSON")
	var atlas_wrapper := _load_dictionary(ATLAS_PATH, "action-set atlas wrapper")
	if not skeleton.is_empty() and not baseline.is_empty() and not atlas_wrapper.is_empty():
		_validate_raw_contract(skeleton, baseline)
		_validate_atlas_contract(atlas_wrapper, skeleton)
		_validate_runtime_contract()
	_finish()


func _validate_file_directory() -> void:
	var files := PackedStringArray()
	for file_name: String in DirAccess.get_files_at(ROOT):
		if file_name.ends_with(".import") or file_name.ends_with(".uid"):
			continue
		files.append(file_name)
	files.sort()
	var expected := PackedStringArray(EXPECTED_FILES)
	expected.sort()
	if files != expected:
		_errors.append("Action-set candidate must contain exactly seven authored files; got %s" % files)


func _validate_raw_contract(skeleton: Dictionary, baseline: Dictionary) -> void:
	var header: Dictionary = skeleton.get("skeleton", {})
	if str(header.get("spine", "")) != "4.2.43":
		_errors.append("Raw Spine version must be 4.2.43")
	if str(header.get("hash", "")) != "vivhite-hybrid-v3-action-set-v1":
		_errors.append("Skeleton hash does not identify the V3 action-set contract")

	var animations: Dictionary = skeleton.get("animations", {})
	if _sorted_keys(animations) != _sorted_keys(EXPECTED_ANIMATIONS):
		_errors.append("Action set must contain exactly the eight required animations")
	if _sorted_keys(skeleton.get("events", {})) != _sorted_strings(EXPECTED_EVENTS):
		_errors.append("Action set must declare exactly the four required events")

	var bones := _named_dictionaries(skeleton.get("bones", []))
	var slots := _named_dictionaries(skeleton.get("slots", []))
	_validate_bones_and_slots(bones, slots)
	_validate_skin(skeleton)
	_validate_unchanged_events_and_slash(skeleton, baseline)

	for animation_name: String in EXPECTED_ANIMATIONS:
		if not animations.has(animation_name):
			continue
		var animation: Dictionary = animations[animation_name]
		_validate_action_reset(animation_name, animation)
		_validate_no_person_crossfade(animation_name, animation)
		_validate_attachment_names(animation_name, animation)
		_validate_exactly_one_person(animation_name, animation, float(EXPECTED_ANIMATIONS[animation_name]), slots)

	_validate_atomic_swap(animations.get("attack", {}), "attack", ATTACK_REGION, ATTACK_ENTER, ATTACK_EXIT)
	_validate_atomic_swap(animations.get("attack_heavy", {}), "attack_heavy", HEAVY_REGION, HEAVY_ENTER, HEAVY_EXIT)
	_validate_exact_event_time(
		animations.get("attack_heavy", {}),
		"attack_heavy",
		"heavy_slash_start",
		HEAVY_ENTER
	)
	_validate_relaxed_boundaries(animations.get("relaxed_loop", {}))
	_validate_anchor_contract(animations.get("attack", {}), "attack", ATTACK_ENTER, ATTACK_PRE_EXIT, ATTACK_EXIT)
	_validate_anchor_contract(animations.get("attack_heavy", {}), "attack_heavy", HEAVY_ENTER, HEAVY_PRE_EXIT, HEAVY_EXIT)


func _validate_bones_and_slots(bones: Dictionary, slots: Dictionary) -> void:
	for bone_name: String in [BODY_BONE, ACTION_BONE, DEATH_BONE, ARC_BONE, EYE_BONE]:
		if not bones.has(bone_name):
			_errors.append("Missing required bone: %s" % bone_name)
	for slot_name: String in [BODY_SLOT, ACTION_SLOT, DEATH_SLOT, SLASH_SLOT, EYE_SLOT]:
		if not slots.has(slot_name):
			_errors.append("Missing required slot: %s" % slot_name)
	if bones.has(ACTION_BONE):
		var action_bone: Dictionary = bones[ACTION_BONE]
		if str(action_bone.get("parent", "")) != BODY_BONE:
			_errors.append("Shared action root must be a direct child of %s" % BODY_BONE)
		if (
			not _near(float(action_bone.get("x", NAN)), ACTION_SETUP_CENTER.x)
			or not _near(float(action_bone.get("y", NAN)), ACTION_SETUP_CENTER.y)
		):
			_errors.append("Shared action root lost the frozen neutral world center")
	for anchor_name: String in [ARC_BONE, EYE_BONE]:
		if bones.has(anchor_name) and str(bones[anchor_name].get("parent", "")) != BODY_BONE:
			_errors.append("VFX anchor must directly follow %s: %s" % [BODY_BONE, anchor_name])
	var slot_bones := {
		BODY_SLOT: BODY_BONE,
		ACTION_SLOT: ACTION_BONE,
		DEATH_SLOT: DEATH_BONE,
		SLASH_SLOT: ARC_BONE,
		EYE_SLOT: EYE_BONE,
	}
	for slot_name: String in slot_bones:
		if slots.has(slot_name) and str(slots[slot_name].get("bone", "")) != str(slot_bones[slot_name]):
			_errors.append("Slot %s is bound to the wrong bone" % slot_name)
	if slots.has(BODY_SLOT) and str(slots[BODY_SLOT].get("attachment", "")) != BODY_REGION:
		_errors.append("Neutral body must remain the setup character attachment")
	for hidden_slot: String in [ACTION_SLOT, DEATH_SLOT]:
		if slots.has(hidden_slot) and slots[hidden_slot].has("attachment"):
			_errors.append("Setup pose must keep %s empty" % hidden_slot)


func _validate_skin(skeleton: Dictionary) -> void:
	var skins: Array = skeleton.get("skins", [])
	if skins.size() != 1 or str(skins[0].get("name", "")) != "default":
		_errors.append("Action set must contain exactly the default skin")
		return
	var attachments: Dictionary = skins[0].get("attachments", {})
	var required_single := {BODY_SLOT: BODY_REGION, DEATH_SLOT: DEATH_REGION}
	for slot_name: String in required_single:
		var slot_attachments: Dictionary = attachments.get(slot_name, {})
		if slot_attachments.size() != 1 or not slot_attachments.has(required_single[slot_name]):
			_errors.append("Skin slot %s must contain exactly %s" % [slot_name, required_single[slot_name]])
	var actions: Dictionary = attachments.get(ACTION_SLOT, {})
	if actions.size() != 2 or not actions.has(ATTACK_REGION) or not actions.has(HEAVY_REGION):
		_errors.append("Shared action slot must contain exactly attack_peak and attack_heavy_peak")
		return
	var neutral: Dictionary = attachments.get(BODY_SLOT, {}).get(BODY_REGION, {})
	for region_name: String in [ATTACK_REGION, HEAVY_REGION]:
		var action: Dictionary = actions[region_name]
		if str(action.get("type", "region")) != "region" or str(action.get("path", "")) != region_name:
			_errors.append("Action pose must remain one rigid region: %s" % region_name)
		if (
			not _near(float(action.get("width", NAN)), ACTION_WORLD_SIZE.x)
			or not _near(float(action.get("height", NAN)), ACTION_WORLD_SIZE.y)
		):
			_errors.append("Action pose lost frozen authored dimensions: %s" % region_name)
		if (
			not _near(float(neutral.get("width", NAN)), float(action.get("width", NAN)))
			or not _near(float(neutral.get("height", NAN)), float(action.get("height", NAN)))
		):
			_errors.append("Action pose and neutral no longer share one authored world size: %s" % region_name)


func _validate_unchanged_events_and_slash(skeleton: Dictionary, baseline: Dictionary) -> void:
	if not _same_variant(skeleton.get("events", {}), baseline.get("events", {})):
		_errors.append("Top-level event definitions changed from whole_mesh")
	var animations: Dictionary = skeleton.get("animations", {})
	var baseline_animations: Dictionary = baseline.get("animations", {})
	for animation_name: String in EXPECTED_ANIMATIONS:
		if not animations.has(animation_name) or not baseline_animations.has(animation_name):
			continue
		var animation: Dictionary = animations[animation_name]
		var original: Dictionary = baseline_animations[animation_name]
		if not _same_variant(animation.get("events", []), original.get("events", [])):
			_errors.append("Event timeline changed from baseline: %s" % animation_name)
		if not _same_variant(
			animation.get("slots", {}).get(SLASH_SLOT, null),
			original.get("slots", {}).get(SLASH_SLOT, null)
		):
			_errors.append("slash_mesh timeline changed from baseline: %s" % animation_name)


func _validate_action_reset(animation_name: String, animation: Dictionary) -> void:
	var slots: Dictionary = animation.get("slots", {})
	if not slots.has(ACTION_SLOT):
		_errors.append("Every animation must explicitly reset %s: %s" % [ACTION_SLOT, animation_name])
		return
	var keys: Array = slots[ACTION_SLOT].get("attachment", [])
	if keys.is_empty() or not _near(float(keys[0].get("time", -1.0)), 0.0) or keys[0].get("name", "sentinel") != null:
		_errors.append("%s must clear the shared action slot at t=0" % animation_name)
	if animation_name not in ["attack", "attack_heavy", "relaxed_loop"] and keys.size() != 1:
		_errors.append("Only attack/heavy/relaxed may add keys after the t=0 action reset: %s" % animation_name)


func _validate_no_person_crossfade(animation_name: String, animation: Dictionary) -> void:
	var slots: Dictionary = animation.get("slots", {})
	for slot_name: String in CHARACTER_SLOTS:
		var timelines: Dictionary = slots.get(slot_name, {})
		for forbidden: String in ["rgba", "rgb", "alpha", "color", "twoColor"]:
			if timelines.has(forbidden):
				_errors.append("%s/%s uses forbidden character crossfade %s" % [animation_name, slot_name, forbidden])


func _validate_attachment_names(animation_name: String, animation: Dictionary) -> void:
	var allowed := {
		BODY_SLOT: [BODY_REGION],
		ACTION_SLOT: [ATTACK_REGION, HEAVY_REGION],
		DEATH_SLOT: [DEATH_REGION],
	}
	for slot_name: String in allowed:
		for key: Dictionary in animation.get("slots", {}).get(slot_name, {}).get("attachment", []):
			var name: Variant = key.get("name", null)
			if name != null and str(name) not in allowed[slot_name]:
				_errors.append("%s/%s references unexpected attachment %s" % [animation_name, slot_name, name])


func _validate_atomic_swap(
	animation: Dictionary,
	animation_name: String,
	region_name: String,
	enter_time: float,
	exit_time: float,
) -> void:
	if animation.is_empty():
		return
	var slots: Dictionary = animation.get("slots", {})
	var body_keys: Array = slots.get(BODY_SLOT, {}).get("attachment", [])
	var action_keys: Array = slots.get(ACTION_SLOT, {}).get("attachment", [])
	if body_keys.size() != 3 or action_keys.size() != 3:
		_errors.append("%s must contain exactly three atomic keys per character slot" % animation_name)
		return
	var times := [0.0, enter_time, exit_time]
	var body_names := [BODY_REGION, null, BODY_REGION]
	var action_names := [null, region_name, null]
	for index in 3:
		if (
			not _near(float(body_keys[index].get("time", -1.0)), float(times[index]))
			or not _near(float(action_keys[index].get("time", -1.0)), float(times[index]))
			or body_keys[index].get("name", "sentinel") != body_names[index]
			or action_keys[index].get("name", "sentinel") != action_names[index]
		):
			_errors.append("%s does not switch neutral/action/neutral atomically" % animation_name)
			break


func _validate_exact_event_time(
	animation: Dictionary,
	animation_name: String,
	event_name: String,
	expected_time: float,
) -> void:
	if animation.is_empty():
		return
	var matches := []
	for key: Dictionary in animation.get("events", []):
		if str(key.get("name", "")) == event_name:
			matches.append(key)
	if matches.size() != 1:
		_errors.append("%s must emit %s exactly once" % [animation_name, event_name])
		return
	if not _near(float(matches[0].get("time", -1.0)), expected_time):
		_errors.append(
			"%s/%s must fire at %.7f" % [animation_name, event_name, expected_time]
		)


func _validate_relaxed_boundaries(relaxed: Dictionary) -> void:
	if relaxed.is_empty():
		return
	var expected := {
		BODY_SLOT: [BODY_REGION, BODY_REGION],
		ACTION_SLOT: [null, null],
		DEATH_SLOT: [null, null],
	}
	for slot_name: String in expected:
		var keys: Array = relaxed.get("slots", {}).get(slot_name, {}).get("attachment", [])
		if keys.size() != 2:
			_errors.append("relaxed_loop must reset %s at both boundaries" % slot_name)
			continue
		for index in 2:
			var time := 0.0 if index == 0 else RELAXED_END
			if not _near(float(keys[index].get("time", -1.0)), time) or keys[index].get("name", "sentinel") != expected[slot_name][index]:
				_errors.append("relaxed_loop has an invalid %s reset at %.6f" % [slot_name, time])


func _validate_anchor_contract(
	animation: Dictionary,
	label: String,
	enter_time: float,
	pre_exit_time: float,
	exit_time: float,
) -> void:
	if animation.is_empty():
		return
	var duration := float(EXPECTED_ANIMATIONS[label])
	var times := [0.0, enter_time, pre_exit_time, exit_time, duration]
	for bone_name: String in [ARC_BONE, EYE_BONE]:
		var keys: Array = animation.get("bones", {}).get(bone_name, {}).get("translate", [])
		if keys.size() != times.size():
			_errors.append("%s/%s must contain exactly five pose-anchor keys" % [label, bone_name])
			continue
		for index in times.size():
			var expected_offset := (
				PEAK_ARC_OFFSET
				if bone_name == ARC_BONE and index in [1, 2]
				else Vector2.ZERO
			)
			if (
				not _near(float(keys[index].get("time", -1.0)), float(times[index]))
				or not _near(float(keys[index].get("x", 0.0)), expected_offset.x)
				or not _near(float(keys[index].get("y", 0.0)), expected_offset.y)
			):
				_errors.append("%s/%s has an invalid anchor key at index %d" % [label, bone_name, index])


func _validate_exactly_one_person(
	animation_name: String,
	animation: Dictionary,
	duration: float,
	setup_slots: Dictionary,
) -> void:
	var key_times: Array[float] = [0.0, duration]
	for slot_name: String in CHARACTER_SLOTS:
		for key: Dictionary in animation.get("slots", {}).get(slot_name, {}).get("attachment", []):
			key_times.append(clampf(float(key.get("time", 0.0)), 0.0, duration))
	key_times.sort()
	var unique_times: Array[float] = []
	for time: float in key_times:
		if unique_times.is_empty() or not _near(unique_times[-1], time):
			unique_times.append(time)
	var samples := unique_times.duplicate()
	for index in range(unique_times.size() - 1):
		if unique_times[index + 1] - unique_times[index] > EPSILON:
			samples.append((unique_times[index] + unique_times[index + 1]) * 0.5)
	samples.sort()
	for time: float in samples:
		var visible := 0
		for slot_name: String in CHARACTER_SLOTS:
			var setup_name: Variant = setup_slots.get(slot_name, {}).get("attachment", null)
			var current: Variant = _attachment_at_time(
				setup_name,
				animation.get("slots", {}).get(slot_name, {}).get("attachment", []),
				time
			)
			if current != null:
				visible += 1
		_visibility_samples += 1
		if visible != 1:
			_errors.append("%s at %.7f has %d visible character layers; expected one" % [animation_name, time, visible])


func _validate_atlas_contract(wrapper: Dictionary, skeleton: Dictionary) -> void:
	if str(wrapper.get("source_path", "")) != ROOT + "/vivhite_combat.atlas":
		_errors.append("Atlas wrapper is not action-set-local")
	var atlas_data := str(wrapper.get("atlas_data", ""))
	for spec: Dictionary in [
		{"page": "vivhite_combat_attack.png", "region": ATTACK_REGION},
		{"page": "vivhite_combat_attack_heavy.png", "region": HEAVY_REGION},
	]:
		var section := "\n".join(PackedStringArray([
			str(spec["page"]),
			"size:2048,2304",
			"filter:Linear,Linear",
			"pma:false",
			"repeat:none",
			str(spec["region"]),
			"bounds:16,16,1536,2272",
		]))
		if atlas_data.count("%s\n" % spec["page"]) != 1 or not atlas_data.contains(section):
			_errors.append("Atlas page/region contract changed: %s" % spec["page"])
		if atlas_data.count("%s\n" % spec["region"]) != 1:
			_errors.append("Atlas must declare exactly one region %s" % spec["region"])

	var tres := FileAccess.get_file_as_string(DATA_PATH)
	for required_path: String in [ATLAS_PATH, JSON_PATH]:
		if not tres.contains(required_path):
			_errors.append("Skeleton-data wrapper is missing %s" % required_path)
	for page_name: String in EXPECTED_PAGES:
		_validate_page(ROOT + "/" + page_name, EXPECTED_PAGES[page_name], page_name in [
			"vivhite_combat_attack.png", "vivhite_combat_attack_heavy.png",
		])
	# Reassert the output-side size invariant for both action attachments.
	var skins: Array = skeleton.get("skins", [])
	if not skins.is_empty():
		var actions: Dictionary = skins[0].get("attachments", {}).get(ACTION_SLOT, {})
		for region_name: String in [ATTACK_REGION, HEAVY_REGION]:
			var action: Dictionary = actions.get(region_name, {})
			if not action.is_empty() and (
				not _near(float(action.get("width", NAN)), ACTION_WORLD_SIZE.x)
				or not _near(float(action.get("height", NAN)), ACTION_WORLD_SIZE.y)
			):
				_errors.append("Atlas attachment lost frozen world dimensions: %s" % region_name)


func _validate_page(path: String, expected_size: Vector2i, require_action_region: bool) -> void:
	var image := Image.load_from_file(path)
	if image == null or image.is_empty():
		_errors.append("Atlas page could not be decoded: %s" % path)
		return
	if image.get_format() != Image.FORMAT_RGBA8:
		_errors.append("Atlas page must decode natively as RGBA8: %s" % path)
		return
	if image.get_size() != expected_size:
		_errors.append("Atlas page has wrong size %s: %s" % [image.get_size(), path])
	for corner: Vector2i in [
		Vector2i(0, 0), Vector2i(image.get_width() - 1, 0),
		Vector2i(0, image.get_height() - 1), Vector2i(image.get_width() - 1, image.get_height() - 1),
	]:
		if image.get_pixelv(corner).a8 != 0:
			_errors.append("Atlas page corner is not natively transparent: %s %s" % [path, corner])
	var used := image.get_used_rect()
	if not used.has_area():
		_errors.append("Atlas page contains no non-zero Alpha subject: %s" % path)
	elif require_action_region and not ACTION_REGION_RECT.encloses(used):
		_errors.append("Action page Alpha escapes declared region: %s %s" % [path, used])
	var bytes := image.get_data()
	var has_opaque := false
	for byte_index in range(3, bytes.size(), 4):
		if int(bytes[byte_index]) >= 250:
			has_opaque = true
			break
	if not has_opaque:
		_errors.append("Atlas page has no near-opaque subject pixels: %s" % path)


func _validate_runtime_contract() -> void:
	for type_name: String in ["SpineSprite", "SpineSkeletonDataResource", "SpineSkeletonFileResource", "SpineAtlasResource"]:
		if not ClassDB.class_exists(type_name):
			_errors.append("Game-compatible Spine class is unavailable: %s" % type_name)
	if not _errors.filter(func(message: String) -> bool: return message.contains("Spine class")).is_empty():
		return
	var data: Resource = ResourceLoader.load(DATA_PATH)
	if data == null or not data.is_class("SpineSkeletonDataResource"):
		_errors.append("Spine runtime could not load action-set skeleton data")
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
			_errors.append("Runtime duration mismatch for %s: %.7f" % [animation_name, duration])
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
	var skeleton: Object = sprite.call("get_skeleton")
	if state == null or skeleton == null:
		_errors.append("SpineSprite did not initialize for %s" % animation_name)
		sprite.queue_free()
		return
	state.call("set_animation", animation_name, false, 0)
	var samples: Array[float] = [0.0, duration * 0.5, duration]
	if animation_name == "attack":
		samples.append_array([ATTACK_ENTER - 0.0001, ATTACK_ENTER, ATTACK_EXIT - 0.0001, ATTACK_EXIT])
	elif animation_name == "attack_heavy":
		samples.append_array([HEAVY_ENTER - 0.0001, HEAVY_ENTER, HEAVY_EXIT - 0.0001, HEAVY_EXIT])
	samples.sort()
	var previous := 0.0
	for sample_time: float in samples:
		state.call("update", sample_time - previous)
		state.call("apply", skeleton)
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
		if left.size() != right.size():
			return false
		for key: Variant in left:
			if not right.has(key) or not _same_variant(left[key], right[key]):
				return false
		return true
	if left is Array:
		if left.size() != right.size():
			return false
		for index in left.size():
			if not _same_variant(left[index], right[index]):
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
		print("[hybrid-action-set] Read-only static and Spine runtime validation passed")
		print(JSON.stringify({
			"authored_file_count": EXPECTED_FILES.size(),
			"animation_count": EXPECTED_ANIMATIONS.size(),
			"attack_atomic_window": [ATTACK_ENTER, ATTACK_EXIT],
			"heavy_atomic_window": [HEAVY_ENTER, HEAVY_EXIT],
			"native_action_page_size": Vector2i(2048, 2304),
			"runtime_sample_count": _runtime_samples,
			"spine_version": "4.2.43",
			"visibility_sample_count": _visibility_samples,
		}, "  ", false))
		quit(0)
		return
	for message: String in _errors:
		push_error("[hybrid-action-set] %s" % message)
	quit(1)
