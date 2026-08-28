extends SceneTree

## Static gate for the diagnostic far-arm consumer.  It intentionally validates
## consumer geometry and Spine contracts only; it does not approve any character
## art and it never touches the runtime skin.

const COMMAND := "validate-semantic-left-arm-candidate"
const DEFAULT_ROOT := "Vivhite/tools/candidates/semantic_left_arm"
const JSON_FILE := "semantic_left_arm.spjson"
const ATLAS_FILE := "semantic_left_arm.spatlas"
const PAGE_FILE := "semantic_left_arm_graybox.png"
const DATA_FILE := "semantic_left_arm_skeleton_data.tres"
const CONTRACT_FILE := "contract.json"
const SPINE_VERSION := "4.2.43"
const EPSILON := 0.0001
const UPPER_REGION_ORIGIN := Vector2i(16, 16)
const FOREARM_REGION_ORIGIN := Vector2i(352, 16)

const BONE_TORSO := "semantic_far_torso_upper"
const BONE_CLAVICLE := "semantic_far_shoulder_cover"
const BONE_UPPER := "semantic_far_upper_arm"
const BONE_FOREARM_HAND := "semantic_far_forearm_hand"
const BONE_WRIST := "semantic_far_wrist_anchor"

const REQUIRED_ANIMATIONS := {
	"attack": 1.1666667,
	"attack_heavy": 1.5333334,
	"cast": 1.5666667,
	"die": 2.3333335,
	"hurt": 1.0,
	"idle_loop": 2.0,
	"low_health_loop": 1.4666667,
	"relaxed_loop": 12.000001,
}
const REQUIRED_EVENTS := ["attack_slash_start", "heavy_slash_start", "cast_eyes_start", "clear_vfx"]

var _errors: Array[String] = []


func _initialize() -> void:
	var args := OS.get_cmdline_user_args()
	if args.is_empty():
		args = PackedStringArray([COMMAND])
	if args[0] != COMMAND:
		push_error("Usage: validate-semantic-left-arm-candidate [--root PATH]")
		quit(2)
		return
	var root := DEFAULT_ROOT
	var index := 1
	while index < args.size():
		if str(args[index]) != "--root" or index + 1 >= args.size():
			push_error("Expected --root PATH")
			quit(2)
			return
		root = str(args[index + 1])
		index += 2
	var absolute_root := _absolute_repo_path(root)
	if absolute_root.replace("\\", "/").contains("/Vivhite/Vivhite/skins/ironclad"):
		_errors.append("Candidate root points into the runtime skin")
	_validate(absolute_root)
	if _errors.is_empty():
		print("[semantic-left-arm] Static contract passed: two pieces, frozen pivots/layers, eight animations, audited extremes.")
		quit(0)
		return
	for error: String in _errors:
		push_error("[semantic-left-arm] %s" % error)
	quit(1)


func _validate(root: String) -> void:
	for file_name in [JSON_FILE, ATLAS_FILE, PAGE_FILE, DATA_FILE, CONTRACT_FILE, "README.md"]:
		if not FileAccess.file_exists(root.path_join(file_name)):
			_errors.append("Missing authored candidate file: %s" % file_name)
	if not _errors.is_empty():
		return
	var skeleton := _read_json(root.path_join(JSON_FILE))
	var wrapper := _read_json(root.path_join(ATLAS_FILE))
	var contract := _read_json(root.path_join(CONTRACT_FILE))
	if skeleton.is_empty() or wrapper.is_empty() or contract.is_empty():
		return
	_validate_contract(contract)
	_validate_skeleton(skeleton)
	_validate_atlas(wrapper, root)
	_validate_tres(root.path_join(DATA_FILE))


func _validate_contract(contract: Dictionary) -> void:
	if str(contract.get("status", "")) != "diagnostic_graybox_only_not_publishable":
		_errors.append("Contract must remain explicitly non-publishable")
	if int(contract.get("paid_generation_calls", -1)) != 0:
		_errors.append("Diagnostic build unexpectedly records a paid generation call")
	var side: Dictionary = contract.get("side_contract", {})
	if str(side.get("screen_side", "")) != "screen-left":
		_errors.append("Screen side is not frozen to screen-left")
	if str(side.get("depth_side", "")) != "far arm behind torso":
		_errors.append("Depth side is not frozen to the far arm")
	if str(side.get("anatomical_side", "")) != "character-right":
		_errors.append("Anatomical side is not frozen to character-right")
	var source: Dictionary = contract.get("source_audit", {})
	if bool(source.get("publishable_independent_far_arm_source_found", true)):
		_errors.append("Contract falsely claims a publishable independent arm source exists")
	if not (source.get("usable_existing_sources", []) as Array).is_empty():
		_errors.append("Usable source list must stay empty until genuine independent art exists")
	var consumer: Dictionary = contract.get("consumer_contract", {})
	var order: Array = consumer.get("fixed_draw_order_back_to_front", [])
	if order != ["far_upper_arm", "far_forearm_hand", "torso_shoulder_cover"]:
		_errors.append("Frozen draw order changed")
	if not bool(consumer.get("two_piece_default", false)):
		_errors.append("Far arm default must remain the two-piece architecture")
	var layout: Dictionary = contract.get("diagnostic_output_layout", {})
	if str(layout.get("classification", "")).find("packed atlas page") < 0:
		_errors.append("Graybox output is no longer explicitly classified as a packed atlas page")
	if layout.get("regions", []) != [
		"gray_far_upper_arm",
		"gray_far_forearm_hand",
		"gray_torso_shoulder_cover",
		"gray_marker_shoulder",
		"gray_marker_elbow",
		"gray_marker_wrist",
	]:
		_errors.append("Graybox atlas region contract changed")
	if bool(layout.get("production_use", true)):
		_errors.append("Diagnostic atlas must remain forbidden from production use")
	var overlap: Dictionary = contract.get("hidden_overlap", {})
	for key in [
		"shoulder_upper_proximal_world_min",
		"upper_beyond_elbow_world_min",
		"forearm_before_elbow_world_min",
		"shared_elbow_solid_radius_world_min",
	]:
		if float(overlap.get(key, 0.0)) < 27.0:
			_errors.append("Hidden overlap %s fell below the 27-world-unit stress floor" % key)
	var expected_hash := "86ffd64a637d170e213879e72d986b707ee181d4812c8e3fb1eda4abfab98bd1"
	var source_path := _repo_root().path_join(str(source.get("runtime_builder_source", "")))
	if not FileAccess.file_exists(source_path):
		_errors.append("Frozen 0018-derived current builder source is missing")
	elif FileAccess.get_sha256(source_path).to_lower() != expected_hash:
		_errors.append("Current builder source hash drifted from accepted 0018")


func _validate_skeleton(skeleton: Dictionary) -> void:
	if str((skeleton.get("skeleton", {}) as Dictionary).get("spine", "")) != SPINE_VERSION:
		_errors.append("Spine version must be %s" % SPINE_VERSION)
	var skins: Array = skeleton.get("skins", [])
	if skins.size() != 1 or str((skins[0] as Dictionary).get("name", "")) != "default":
		_errors.append("Exactly one default skin is required")
	var bones := {}
	for bone_value: Variant in skeleton.get("bones", []):
		var bone := bone_value as Dictionary
		bones[str(bone.get("name", ""))] = bone
	var expected_parents := {
		BONE_TORSO: "root",
		BONE_CLAVICLE: BONE_TORSO,
		BONE_UPPER: BONE_CLAVICLE,
		BONE_FOREARM_HAND: BONE_UPPER,
		BONE_WRIST: BONE_FOREARM_HAND,
	}
	for bone_name: String in expected_parents:
		if not bones.has(bone_name):
			_errors.append("Missing bone %s" % bone_name)
		elif str((bones[bone_name] as Dictionary).get("parent", "")) != expected_parents[bone_name]:
			_errors.append("Parent mismatch for %s" % bone_name)
	if bones.has(BONE_UPPER):
		_validate_vec2(bones[BONE_UPPER], Vector2(18.083333, -10.366242), "clavicle->shoulder")
	if bones.has(BONE_FOREARM_HAND):
		_validate_vec2(bones[BONE_FOREARM_HAND], Vector2(-62.0, -121.803345), "shoulder->elbow")
	if bones.has(BONE_WRIST):
		_validate_vec2(bones[BONE_WRIST], Vector2(-98.166664, -98.479301), "elbow->wrist")

	var slot_names: Array[String] = []
	for slot_value: Variant in skeleton.get("slots", []):
		slot_names.append(str((slot_value as Dictionary).get("name", "")))
	for required_slot in ["far_upper_arm", "far_forearm_hand", "torso_shoulder_cover", "marker_shoulder", "marker_elbow", "marker_wrist", "slash_mesh", "eye_attach_slot"]:
		if not slot_names.has(required_slot):
			_errors.append("Missing slot %s" % required_slot)
	if slot_names.has("far_upper_arm") and slot_names.has("far_forearm_hand") and slot_names.has("torso_shoulder_cover"):
		if not (slot_names.find("far_upper_arm") < slot_names.find("far_forearm_hand") and slot_names.find("far_forearm_hand") < slot_names.find("torso_shoulder_cover")):
			_errors.append("Spine slot array violates far-upper -> forearm-hand -> torso order")

	var global_events: Dictionary = skeleton.get("events", {})
	for event_name: String in REQUIRED_EVENTS:
		if not global_events.has(event_name):
			_errors.append("Missing compatibility event %s" % event_name)
	var animations: Dictionary = skeleton.get("animations", {})
	if animations.size() != REQUIRED_ANIMATIONS.size():
		_errors.append("Candidate must expose exactly the eight combat animations")
	for animation_name: String in REQUIRED_ANIMATIONS:
		if not animations.has(animation_name):
			_errors.append("Missing animation %s" % animation_name)
			continue
		var actual_duration := _max_time(animations[animation_name])
		if absf(actual_duration - float(REQUIRED_ANIMATIONS[animation_name])) > EPSILON:
			_errors.append("Animation %s duration %.7f != %.7f" % [animation_name, actual_duration, REQUIRED_ANIMATIONS[animation_name]])
		if (animations[animation_name] as Dictionary).has("draworder") or (animations[animation_name] as Dictionary).has("drawOrder"):
			_errors.append("Far-arm diagnostic must not hide layer errors with drawOrder timelines")
	_validate_rotation_envelope(animations)
	_validate_event(animations.get("attack", {}), "attack_slash_start", 0.08)
	_validate_event(animations.get("attack_heavy", {}), "heavy_slash_start", 0.12)
	_validate_event(animations.get("cast", {}), "cast_eyes_start", 0.25)
	_validate_event(animations.get("die", {}), "clear_vfx", 0.0)


func _validate_vec2(bone: Dictionary, expected: Vector2, label: String) -> void:
	var actual := Vector2(float(bone.get("x", 0.0)), float(bone.get("y", 0.0)))
	if actual.distance_to(expected) > EPSILON:
		_errors.append("Frozen %s bind vector drifted: %s != %s" % [label, actual, expected])


func _validate_rotation_envelope(animations: Dictionary) -> void:
	var upper_values: Array[float] = []
	var forearm_values: Array[float] = []
	for animation_value: Variant in animations.values():
		var bones: Dictionary = (animation_value as Dictionary).get("bones", {})
		for pair in [[BONE_UPPER, upper_values], [BONE_FOREARM_HAND, forearm_values]]:
			var name := str(pair[0])
			if not bones.has(name):
				continue
			for frame_value: Variant in ((bones[name] as Dictionary).get("rotate", []) as Array):
				(pair[1] as Array).append(float((frame_value as Dictionary).get("value", 0.0)))
	if upper_values.is_empty() or absf(upper_values.min() - -35.0) > EPSILON or absf(upper_values.max() - 71.0) > EPSILON:
		_errors.append("Upper-arm envelope must remain exactly -35..+71 degrees")
	if forearm_values.is_empty() or absf(forearm_values.min() - -48.0) > EPSILON or absf(forearm_values.max() - 55.0) > EPSILON:
		_errors.append("Forearm-hand envelope must remain exactly -48..+55 degrees")


func _validate_event(animation: Dictionary, event_name: String, expected_time: float) -> void:
	for event_value: Variant in animation.get("events", []):
		var event := event_value as Dictionary
		if str(event.get("name", "")) == event_name and absf(float(event.get("time", -1.0)) - expected_time) <= EPSILON:
			return
	_errors.append("Missing %s at %.7f" % [event_name, expected_time])


func _validate_atlas(wrapper: Dictionary, root: String) -> void:
	if str(wrapper.get("source_path", "")) != "res://tools/candidates/semantic_left_arm/semantic_left_arm.atlas":
		_errors.append("Atlas source_path escaped the isolated candidate mount")
	var atlas_data := str(wrapper.get("atlas_data", ""))
	for required in [PAGE_FILE, "size:1024,512", "pma:false", "gray_far_upper_arm", "gray_far_forearm_hand", "gray_torso_shoulder_cover"]:
		if not atlas_data.contains(required):
			_errors.append("Atlas data is missing %s" % required)
	var page := Image.load_from_file(root.path_join(PAGE_FILE))
	if page == null or page.is_empty() or page.get_format() != Image.FORMAT_RGBA8:
		_errors.append("Graybox atlas page must decode directly as RGBA8")
		return
	if page.get_size() != Vector2i(1024, 512):
		_errors.append("Graybox atlas page size changed")
	for corner in [Vector2i(0, 0), Vector2i(1023, 0), Vector2i(0, 511), Vector2i(1023, 511)]:
		if page.get_pixelv(corner).a != 0.0:
			_errors.append("Graybox atlas corner is not transparent: %s" % corner)
	_validate_graybox_overlap_pixels(page)


func _validate_graybox_overlap_pixels(page: Image) -> void:
	# These probes bind the numeric overlap contract to the diagnostic pixels;
	# checking contract.json alone could otherwise let a future geometry rewrite
	# silently stop realizing the promised shoulder/elbow coverage.
	for x in 320:
		if page.get_pixelv(UPPER_REGION_ORIGIN + Vector2i(x, 48)).a <= 0.0:
			_errors.append("Upper-arm Alpha centerline is disconnected at x=%d" % x)
			break
	for x in 350:
		if page.get_pixelv(FOREARM_REGION_ORIGIN + Vector2i(x, 80)).a <= 0.0:
			_errors.append("Forearm-hand Alpha centerline is disconnected at x=%d" % x)
			break
	for probe in [
		UPPER_REGION_ORIGIN + Vector2i(0, 48),
		UPPER_REGION_ORIGIN + Vector2i(62, 3),
		UPPER_REGION_ORIGIN + Vector2i(62, 93),
		UPPER_REGION_ORIGIN + Vector2i(231, 48),
		UPPER_REGION_ORIGIN + Vector2i(319, 48),
		UPPER_REGION_ORIGIN + Vector2i(275, 4),
		UPPER_REGION_ORIGIN + Vector2i(275, 92),
		FOREARM_REGION_ORIGIN + Vector2i(0, 80),
		FOREARM_REGION_ORIGIN + Vector2i(22, 80),
		FOREARM_REGION_ORIGIN + Vector2i(106, 80),
		FOREARM_REGION_ORIGIN + Vector2i(64, 38),
		FOREARM_REGION_ORIGIN + Vector2i(64, 122),
	]:
		if page.get_pixelv(probe).a <= 0.0:
			_errors.append("Promised hidden-overlap/joint probe is transparent: %s" % probe)


func _validate_tres(path: String) -> void:
	var text := FileAccess.get_file_as_string(path)
	for required in [
		"res://tools/candidates/semantic_left_arm/semantic_left_arm.spatlas",
		"res://tools/candidates/semantic_left_arm/semantic_left_arm.spjson",
		"default_mix = 0.05",
	]:
		if not text.contains(required):
			_errors.append("Skeleton data wrapper is missing %s" % required)


func _max_time(value: Variant) -> float:
	var result := 0.0
	if value is Dictionary:
		for key: Variant in (value as Dictionary):
			if str(key) == "time":
				result = maxf(result, float((value as Dictionary)[key]))
			else:
				result = maxf(result, _max_time((value as Dictionary)[key]))
	elif value is Array:
		for child: Variant in value:
			result = maxf(result, _max_time(child))
	return result


func _read_json(path: String) -> Dictionary:
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(path))
	if not parsed is Dictionary:
		_errors.append("Invalid JSON: %s" % path)
		return {}
	return parsed as Dictionary


func _absolute_repo_path(path: String) -> String:
	if path.is_absolute_path():
		return path.simplify_path()
	return _repo_root().path_join(path).simplify_path()


func _repo_root() -> String:
	return ProjectSettings.globalize_path("res://").path_join("../..").simplify_path()
