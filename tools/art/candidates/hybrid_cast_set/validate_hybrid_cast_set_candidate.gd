extends SceneTree

## Independent read-only static + Spine-runtime gate for the isolated V3 cast
## set. It never rebuilds, deploys, or controls the game.

const ROOT := "res://tools/candidates/hybrid_cast_set"
const BASELINE_ROOT := "res://tools/candidates/hybrid_action_set"
const DATA_PATH := ROOT + "/vivhite_combat_skeleton_data.tres"
const JSON_PATH := ROOT + "/vivhite_combat.spjson"
const ATLAS_PATH := ROOT + "/vivhite_combat.spatlas"
const BASELINE_JSON_PATH := BASELINE_ROOT + "/vivhite_combat.spjson"
const BASELINE_ATLAS_PATH := BASELINE_ROOT + "/vivhite_combat.spatlas"

const EXPECTED_FILES := [
	"vivhite_combat.png",
	"vivhite_combat.spatlas",
	"vivhite_combat.spjson",
	"vivhite_combat_attack.png",
	"vivhite_combat_attack_heavy.png",
	"vivhite_combat_cast.png",
	"vivhite_combat_death.png",
	"vivhite_combat_skeleton_data.tres",
]
const EXPECTED_PAGES := {
	"vivhite_combat.png": Vector2i(3072, 2304),
	"vivhite_combat_attack.png": Vector2i(2048, 2304),
	"vivhite_combat_attack_heavy.png": Vector2i(2048, 2304),
	"vivhite_combat_cast.png": Vector2i(2048, 2304),
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
	"attack_slash_start", "heavy_slash_start", "cast_eyes_start", "clear_vfx",
]

const BODY_BONE := "vivhite_rig"
const BODY_SLOT := "vivhite_body"
const BODY_REGION := "vivhite_combat_body"
const ACTION_BONE := "vivhite_action_pose_root"
const ACTION_SLOT := "vivhite_action_pose"
const ATTACK_REGION := "vivhite_combat_attack_peak"
const HEAVY_REGION := "vivhite_combat_attack_heavy_peak"
const CAST_REGION := "vivhite_combat_cast_peak"
const DEATH_SLOT := "vivhite_death_body"
const DEATH_REGION := "vivhite_combat_death_side"
const SLASH_SLOT := "slash_mesh"
const SIGIL_SLOT := "vivhite_magic_sigil"
const SIGIL_REGION := "vivhite_combat_magic_sigil"
const EYE_SLOT := "eye_attach_slot"
const EYE_BONE := "vivhite_eye_anchor"

const CAST_ENTER := 0.25
const CAST_EXIT := 0.60
const CAST_PRE_EXIT := 0.5999
const SIGIL_ENTER := 0.10
const CLEAR_TIME := 1.222000026
const CAST_DURATION := 1.5666667
const RELAXED_END := 12.000001
const EYE_OFFSET := Vector2(194.0, -292.0)
const EYE_NEUTRAL_OFFSET := Vector2(72.0, -282.0)
const EYE_PRE_CLEAR := 1.2219
const ACTION_WORLD_SIZE := Vector2(868.0, 1302.0)
const ACTION_REGION_RECT := Rect2i(16, 16, 1536, 2272)
const EPSILON := 0.00002

var _errors: Array[String] = []
var _runtime_samples := 0
var _visibility_samples := 0


func _initialize() -> void:
	var skeleton := _load_dictionary(JSON_PATH, "cast-set Spine JSON")
	var baseline := _load_dictionary(BASELINE_JSON_PATH, "action-set baseline JSON")
	var wrapper := _load_dictionary(ATLAS_PATH, "cast-set atlas wrapper")
	var baseline_wrapper := _load_dictionary(BASELINE_ATLAS_PATH, "action-set baseline atlas wrapper")
	_validate_file_set()
	if not skeleton.is_empty() and not baseline.is_empty():
		_validate_baseline_preservation(skeleton, baseline)
		_validate_skeleton(skeleton)
		_validate_animations(skeleton)
	if not wrapper.is_empty() and not baseline_wrapper.is_empty():
		_validate_atlas(wrapper, baseline_wrapper)
	_validate_runtime()
	_finish()


func _validate_file_set() -> void:
	var files: Array[String] = []
	for file_name: String in DirAccess.get_files_at(ROOT):
		if file_name.ends_with(".uid") or file_name.ends_with(".import"):
			continue
		files.append(file_name)
	files.sort()
	var expected: Array[String] = []
	for file_name: String in EXPECTED_FILES:
		expected.append(file_name)
	expected.sort()
	if files != expected:
		_errors.append("Expected exactly eight authored cast-set files, got %s" % files)
	for page_name: String in EXPECTED_PAGES:
		_validate_page(ROOT + "/" + page_name, EXPECTED_PAGES[page_name], page_name in [
			"vivhite_combat_attack.png",
			"vivhite_combat_attack_heavy.png",
			"vivhite_combat_cast.png",
		])
	for inherited_page: String in [
		"vivhite_combat.png",
		"vivhite_combat_attack.png",
		"vivhite_combat_attack_heavy.png",
		"vivhite_combat_death.png",
	]:
		var candidate_path := ROOT + "/" + inherited_page
		var baseline_path := BASELINE_ROOT + "/" + inherited_page
		if FileAccess.file_exists(candidate_path) and FileAccess.file_exists(baseline_path):
			if FileAccess.get_sha256(candidate_path) != FileAccess.get_sha256(baseline_path):
				_errors.append("Inherited page changed from action-set baseline: %s" % inherited_page)


func _validate_baseline_preservation(skeleton: Dictionary, baseline: Dictionary) -> void:
	var stripped := skeleton.duplicate(true)
	stripped["skeleton"]["hash"] = baseline.get("skeleton", {}).get("hash", "")
	var action_attachments: Dictionary = stripped.get("skins", [])[0].get("attachments", {}).get(ACTION_SLOT, {})
	action_attachments.erase(CAST_REGION)
	stripped["animations"]["cast"] = baseline.get("animations", {}).get("cast", {}).duplicate(true)
	stripped["animations"]["relaxed_loop"] = baseline.get("animations", {}).get("relaxed_loop", {}).duplicate(true)
	if not _same_variant(stripped, baseline):
		_errors.append("Removing the cast delta did not recover the frozen action-set JSON")


func _validate_skeleton(skeleton: Dictionary) -> void:
	if str(skeleton.get("skeleton", {}).get("spine", "")) != "4.2.43":
		_errors.append("Spine source version must remain 4.2.43")
	var bones := _named_dictionaries(skeleton.get("bones", []))
	var slots := _named_dictionaries(skeleton.get("slots", []))
	for bone_name: String in [BODY_BONE, ACTION_BONE, EYE_BONE]:
		if not bones.has(bone_name):
			_errors.append("Missing required bone: %s" % bone_name)
	for slot_name: String in [BODY_SLOT, ACTION_SLOT, DEATH_SLOT, SLASH_SLOT, SIGIL_SLOT, EYE_SLOT]:
		if not slots.has(slot_name):
			_errors.append("Missing required slot: %s" % slot_name)
	if bones.has(ACTION_BONE):
		var action_bone: Dictionary = bones[ACTION_BONE]
		if str(action_bone.get("parent", "")) != BODY_BONE:
			_errors.append("Shared action root must remain a direct child of vivhite_rig")
		if not _near(float(action_bone.get("x", NAN)), 0.0) or not _near(float(action_bone.get("y", NAN)), 590.0):
			_errors.append("Shared action root lost the frozen neutral center")
	if bones.has(EYE_BONE) and str(bones[EYE_BONE].get("parent", "")) != BODY_BONE:
		_errors.append("Eye anchor must directly follow vivhite_rig")
	var slot_bones := {
		BODY_SLOT: BODY_BONE,
		ACTION_SLOT: ACTION_BONE,
		SLASH_SLOT: "vivhite_magic_arc",
		SIGIL_SLOT: "vivhite_magic_sigil",
		EYE_SLOT: EYE_BONE,
	}
	for slot_name: String in slot_bones:
		if slots.has(slot_name) and str(slots[slot_name].get("bone", "")) != str(slot_bones[slot_name]):
			_errors.append("Slot %s is bound to the wrong bone" % slot_name)
	if slots.has(BODY_SLOT) and str(slots[BODY_SLOT].get("attachment", "")) != BODY_REGION:
		_errors.append("Neutral body must remain the setup attachment")
	for hidden_slot: String in [ACTION_SLOT, DEATH_SLOT]:
		if slots.has(hidden_slot) and slots[hidden_slot].has("attachment"):
			_errors.append("Setup pose must keep %s empty" % hidden_slot)

	var skins: Array = skeleton.get("skins", [])
	if skins.size() != 1 or str(skins[0].get("name", "")) != "default":
		_errors.append("Cast set must contain exactly the default skin")
		return
	var attachments: Dictionary = skins[0].get("attachments", {})
	var actions: Dictionary = attachments.get(ACTION_SLOT, {})
	var expected_actions := [ATTACK_REGION, HEAVY_REGION, CAST_REGION]
	if _sorted_keys(actions) != _sorted_strings(expected_actions):
		_errors.append("Action slot must contain exactly attack, heavy and cast regions")
	for region_name: String in expected_actions:
		var action: Dictionary = actions.get(region_name, {})
		if str(action.get("type", "region")) != "region" or str(action.get("path", "")) != region_name:
			_errors.append("Action attachment must remain one rigid region: %s" % region_name)
		if (
			not _near(float(action.get("width", NAN)), ACTION_WORLD_SIZE.x)
			or not _near(float(action.get("height", NAN)), ACTION_WORLD_SIZE.y)
		):
			_errors.append("Action attachment lost frozen world size: %s" % region_name)
	var event_names := _sorted_keys(skeleton.get("events", {}))
	if event_names != _sorted_strings(EXPECTED_EVENTS):
		_errors.append("Top-level event definitions changed: %s" % event_names)


func _validate_animations(skeleton: Dictionary) -> void:
	var animations: Dictionary = skeleton.get("animations", {})
	if _sorted_keys(animations) != _sorted_strings(EXPECTED_ANIMATIONS.keys()):
		_errors.append("Cast set must retain exactly the eight animations")
		return
	var setup_slots := _named_dictionaries(skeleton.get("slots", []))
	for animation_name: String in EXPECTED_ANIMATIONS:
		var animation: Dictionary = animations.get(animation_name, {})
		_validate_no_person_crossfade(animation_name, animation)
		_validate_exactly_one_person(
			animation_name, animation, float(EXPECTED_ANIMATIONS[animation_name]), setup_slots
		)
	var cast: Dictionary = animations.get("cast", {})
	_validate_atomic_swap(cast)
	_validate_cast_events(cast)
	_validate_cast_vfx(cast)
	_validate_eye_anchor(cast)
	_validate_relaxed(animations.get("relaxed_loop", {}))


func _validate_atomic_swap(cast: Dictionary) -> void:
	var body_keys: Array = cast.get("slots", {}).get(BODY_SLOT, {}).get("attachment", [])
	var action_keys: Array = cast.get("slots", {}).get(ACTION_SLOT, {}).get("attachment", [])
	if body_keys.size() != 3 or action_keys.size() != 3:
		_errors.append("cast must contain exactly three atomic keys per character slot")
		return
	var times := [0.0, CAST_ENTER, CAST_EXIT]
	var body_names := [BODY_REGION, null, BODY_REGION]
	var action_names := [null, CAST_REGION, null]
	for index in 3:
		if (
			not _near(float(body_keys[index].get("time", -1.0)), float(times[index]))
			or not _near(float(action_keys[index].get("time", -1.0)), float(times[index]))
			or body_keys[index].get("name", "sentinel") != body_names[index]
			or action_keys[index].get("name", "sentinel") != action_names[index]
		):
			_errors.append("cast does not switch neutral/action/neutral atomically")
			break


func _validate_cast_events(cast: Dictionary) -> void:
	for spec: Dictionary in [
		{"name": "cast_eyes_start", "time": CAST_ENTER},
		{"name": "clear_vfx", "time": CLEAR_TIME},
	]:
		var matches := []
		for event: Dictionary in cast.get("events", []):
			if str(event.get("name", "")) == str(spec["name"]):
				matches.append(event)
		if matches.size() != 1 or not _near(float(matches[0].get("time", -1.0)), float(spec["time"])):
			_errors.append("cast/%s must fire exactly once at %.9f" % [spec["name"], spec["time"]])


func _validate_cast_vfx(cast: Dictionary) -> void:
	var slots: Dictionary = cast.get("slots", {})
	var sigil: Array = slots.get(SIGIL_SLOT, {}).get("attachment", [])
	var sigil_times := [0.0, SIGIL_ENTER, CLEAR_TIME]
	var sigil_names := [null, SIGIL_REGION, null]
	if sigil.size() != 3:
		_errors.append("Cast sigil must contain exactly null/show/null keys")
	else:
		for index in 3:
			if (
				not _near(float(sigil[index].get("time", -1.0)), float(sigil_times[index]))
				or sigil[index].get("name", "sentinel") != sigil_names[index]
			):
				_errors.append("Cast sigil lifecycle changed at index %d" % index)
	var slash: Array = slots.get(SLASH_SLOT, {}).get("attachment", [])
	if (
		slash.size() != 1
		or not _near(float(slash[0].get("time", -1.0)), 0.0)
		or slash[0].get("name", "sentinel") != null
	):
		_errors.append("cast must explicitly clear slash_mesh at t=0")


func _validate_eye_anchor(cast: Dictionary) -> void:
	var keys: Array = cast.get("bones", {}).get(EYE_BONE, {}).get("translate", [])
	var times := [
		0.0, CAST_ENTER, CAST_PRE_EXIT, CAST_EXIT,
		EYE_PRE_CLEAR, CLEAR_TIME, CAST_DURATION,
	]
	if keys.size() != times.size():
		_errors.append("Cast eye anchor must contain exactly seven pose/VFX lifecycle keys")
		return
	for index in times.size():
		var expected := Vector2.ZERO
		if index in [1, 2]:
			expected = EYE_OFFSET
		elif index in [3, 4]:
			expected = EYE_NEUTRAL_OFFSET
		if (
			not _near(float(keys[index].get("time", -1.0)), float(times[index]))
			or not _near(float(keys[index].get("x", 0.0)), expected.x)
			or not _near(float(keys[index].get("y", 0.0)), expected.y)
		):
			_errors.append("Cast eye anchor key is invalid at index %d" % index)


func _validate_relaxed(relaxed: Dictionary) -> void:
	var expected := {
		BODY_SLOT: [BODY_REGION, BODY_REGION],
		ACTION_SLOT: [null, null],
		DEATH_SLOT: [null, null],
		SLASH_SLOT: [null, null],
		SIGIL_SLOT: [null, null],
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


func _validate_no_person_crossfade(animation_name: String, animation: Dictionary) -> void:
	for slot_name: String in [BODY_SLOT, ACTION_SLOT, DEATH_SLOT]:
		var timelines: Dictionary = animation.get("slots", {}).get(slot_name, {})
		for forbidden: String in ["rgba", "rgb", "alpha", "color", "twoColor"]:
			if timelines.has(forbidden):
				_errors.append("%s/%s uses forbidden character crossfade %s" % [animation_name, slot_name, forbidden])


func _validate_exactly_one_person(
	animation_name: String,
	animation: Dictionary,
	duration: float,
	setup_slots: Dictionary,
) -> void:
	var key_times: Array[float] = [0.0, duration]
	for slot_name: String in [BODY_SLOT, ACTION_SLOT, DEATH_SLOT]:
		for key: Dictionary in animation.get("slots", {}).get(slot_name, {}).get("attachment", []):
			key_times.append(clampf(float(key.get("time", 0.0)), 0.0, duration))
	key_times.sort()
	var unique: Array[float] = []
	for time: float in key_times:
		if unique.is_empty() or not _near(unique[-1], time):
			unique.append(time)
	var samples := unique.duplicate()
	for index in range(unique.size() - 1):
		if unique[index + 1] - unique[index] > EPSILON:
			samples.append((unique[index] + unique[index + 1]) * 0.5)
	for time: float in samples:
		var visible := 0
		for slot_name: String in [BODY_SLOT, ACTION_SLOT, DEATH_SLOT]:
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
			_errors.append("%s at %.7f has %d visible character layers" % [animation_name, time, visible])


func _validate_atlas(wrapper: Dictionary, baseline_wrapper: Dictionary) -> void:
	if str(wrapper.get("source_path", "")) != ROOT + "/vivhite_combat.atlas":
		_errors.append("Atlas wrapper is not cast-set-local")
	var atlas_data := str(wrapper.get("atlas_data", ""))
	var baseline_data := str(baseline_wrapper.get("atlas_data", ""))
	if not atlas_data.begins_with(baseline_data):
		_errors.append("Cast atlas no longer preserves the action-set atlas prefix")
	var section := "\n".join(PackedStringArray([
		"vivhite_combat_cast.png",
		"size:2048,2304",
		"filter:Linear,Linear",
		"pma:false",
		"repeat:none",
		CAST_REGION,
		"bounds:16,16,1536,2272",
	]))
	if atlas_data.count("vivhite_combat_cast.png\n") != 1 or not atlas_data.contains(section):
		_errors.append("Cast atlas page/region contract changed")
	if atlas_data.count("%s\n" % CAST_REGION) != 1:
		_errors.append("Cast atlas must declare its region exactly once")
	var tres := FileAccess.get_file_as_string(DATA_PATH)
	for required_path: String in [ATLAS_PATH, JSON_PATH]:
		if not tres.contains(required_path):
			_errors.append("Skeleton-data wrapper is missing %s" % required_path)


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
			_errors.append("Atlas page corner is not transparent: %s %s" % [path, corner])
	var used := image.get_used_rect()
	if not used.has_area():
		_errors.append("Atlas page contains no non-zero Alpha subject: %s" % path)
	elif require_action_region and not ACTION_REGION_RECT.encloses(used):
		_errors.append("Action page Alpha escapes declared region: %s %s" % [path, used])


func _validate_runtime() -> void:
	for type_name: String in ["SpineSprite", "SpineSkeletonDataResource", "SpineSkeletonFileResource", "SpineAtlasResource"]:
		if not ClassDB.class_exists(type_name):
			_errors.append("Game-compatible Spine class is unavailable: %s" % type_name)
	if not _errors.filter(func(message: String) -> bool: return message.contains("Spine class")).is_empty():
		return
	var data: Resource = ResourceLoader.load(DATA_PATH)
	if data == null or not data.is_class("SpineSkeletonDataResource"):
		_errors.append("Spine runtime could not load cast-set skeleton data")
		return
	if str(data.call("get_version")) != "4.2.43":
		_errors.append("Runtime Spine version must be 4.2.43")
	if data.call("get_animations").size() != EXPECTED_ANIMATIONS.size():
		_errors.append("Runtime must expose exactly eight animations")
	for animation_name: String in EXPECTED_ANIMATIONS:
		var animation: Object = data.call("find_animation", animation_name)
		if animation == null:
			_errors.append("Runtime is missing animation %s" % animation_name)
			continue
		var duration := float(animation.call("get_duration"))
		if not _near(duration, float(EXPECTED_ANIMATIONS[animation_name])):
			_errors.append("Runtime duration mismatch for %s: %.7f" % [animation_name, duration])
		_sample_runtime_animation(data, animation_name, duration)
	for slot_name: String in [BODY_SLOT, ACTION_SLOT, DEATH_SLOT, SLASH_SLOT, SIGIL_SLOT, EYE_SLOT]:
		if data.call("find_slot", slot_name) == null:
			_errors.append("Runtime is missing slot %s" % slot_name)
	for event_name: String in EXPECTED_EVENTS:
		if data.call("find_event", event_name) == null:
			_errors.append("Runtime is missing event %s" % event_name)


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
	var samples: Array[float] = [0.0, duration * 0.5, duration]
	if animation_name == "cast":
		samples = [0.0, 0.0999, 0.10, 0.2499, 0.25, 0.2667, 0.48, 0.5999, 0.60, 0.6001, 1.222, 1.2221, duration]
	samples.sort()
	for sample_time: float in samples:
		state.call("set_animation", animation_name, false, 0)
		state.call("update", sample_time)
		state.call("apply", skeleton)
		sprite.call("update_skeleton", 0.0)
		var visible := 0
		for slot_name: String in [BODY_SLOT, ACTION_SLOT, DEATH_SLOT]:
			if _runtime_attachment_name(skeleton, slot_name) != null:
				visible += 1
		if visible != 1:
			_errors.append("Runtime %s at %.7f has %d visible people" % [animation_name, sample_time, visible])
		if animation_name == "cast":
			var expected_person := CAST_REGION if sample_time >= CAST_ENTER - EPSILON and sample_time < CAST_EXIT - EPSILON else BODY_REGION
			var actual_person: Variant = _runtime_attachment_name(skeleton, ACTION_SLOT) if expected_person == CAST_REGION else _runtime_attachment_name(skeleton, BODY_SLOT)
			if actual_person != expected_person:
				_errors.append("Runtime cast person mismatch at %.7f: %s" % [sample_time, actual_person])
			var expected_sigil: Variant = SIGIL_REGION if sample_time >= SIGIL_ENTER - EPSILON and sample_time < CLEAR_TIME - EPSILON else null
			if _runtime_attachment_name(skeleton, SIGIL_SLOT) != expected_sigil:
				_errors.append("Runtime cast sigil mismatch at %.7f" % sample_time)
			if _runtime_attachment_name(skeleton, SLASH_SLOT) != null:
				_errors.append("Runtime cast retained slash_mesh at %.7f" % sample_time)
		_runtime_samples += 1
	sprite.queue_free()


func _runtime_attachment_name(skeleton: Object, slot_name: String) -> Variant:
	var slot: Variant = skeleton.call("find_slot", slot_name)
	if slot == null:
		return "<missing>"
	var attachment: Variant = (slot as Object).call("get_attachment")
	if attachment == null:
		return null
	return str((attachment as Object).call("get_attachment_name"))


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
		print("[hybrid-cast-set] Read-only static and Spine runtime validation passed")
		print(JSON.stringify({
			"authored_file_count": EXPECTED_FILES.size(),
			"animation_count": EXPECTED_ANIMATIONS.size(),
			"cast_atomic_window": [CAST_ENTER, CAST_EXIT],
			"cast_eye_offset": EYE_OFFSET,
			"cast_neutral_eye_offset": EYE_NEUTRAL_OFFSET,
			"cast_sigil_window": [SIGIL_ENTER, CLEAR_TIME],
			"native_cast_page_size": Vector2i(2048, 2304),
			"runtime_sample_count": _runtime_samples,
			"spine_version": "4.2.43",
			"visibility_sample_count": _visibility_samples,
		}, "  ", false))
		quit(0)
		return
	for message: String in _errors:
		push_error("[hybrid-cast-set] %s" % message)
	quit(1)
