extends "res://candidates/hybrid_action_set/build_hybrid_action_set_candidate.gd"

## V3 Hybrid cast-set milestone. Keep the accepted neutral, attack, heavy and
## death contracts byte-for-byte, then add one rigid full-body cast pose to the
## shared action slot. This builder is isolated below tools/ and never writes
## the runtime skin, deployed mod, game directory, or live process.

const CAST_SET_OUTPUT_ROOT := "Vivhite/tools/candidates/hybrid_cast_set"
const CAST_SET_RESOURCE_ROOT := "res://tools/candidates/hybrid_cast_set"
const DEFAULT_CAST_SOURCE := (
	"assets/vivhite-ironclad/custom/combat/sources/"
	+ "vivhite-combat-cast-peak-v1.png"
)

const OUTPUT_CAST_PAGE := "vivhite_combat_cast.png"
const CAST_ATLAS_SIZE := Vector2i(2048, 2304)
const CAST_REGION_NAME := "vivhite_combat_cast_peak"
const CAST_REGION_POS := Vector2i(16, 16)
const CAST_REGION_SIZE := BODY_REGION_SIZE
const CAST_WORLD_SIZE := Vector2(BODY_WORLD_RECT.size.x, BODY_WORLD_RECT.size.y)

const CAST_POSE_ENTER_TIME := 0.25
const CAST_POSE_EXIT_TIME := 0.60
const CAST_POSE_PRE_EXIT_TIME := 0.5999
const CAST_SIGIL_ENTER_TIME := 0.10
const CAST_CLEAR_TIME := 1.222000026
const CAST_EYE_PRE_CLEAR_TIME := 1.2219

# 0107's anatomical eye midpoint first yielded (+40,+40) from the fixed-canvas
# map. The production EyeFire shader, however, draws its visible flame about
# 43 screen pixels left and 93 pixels above that slot at scene scale .28. The
# hidden Vulkan contact sheet therefore applies the inverse visual correction
# here: the flame tip/base now meets the actual cast eyes instead of floating
# above the head. This is a consumer-space calibration, not source recropping.
const CAST_EYE_PEAK_OFFSET := Vector2(194.0, -292.0)
# The event outlives the rigid pose. Once the neutral body returns at .60,
# keep the same production flame connected to that body's visible eyes until
# clear_vfx. The .60 key is therefore a second pose-specific calibration,
# followed by an effectively atomic reset immediately before clear_vfx.
const CAST_EYE_NEUTRAL_OFFSET := Vector2(72.0, -282.0)

var _cast_source_path := ""
var _building_action_set_phase := false


func _initialize() -> void:
	var args := OS.get_cmdline_user_args()
	if args.is_empty():
		args = PackedStringArray([COMMAND])
	if args[0] in ["-h", "--help", "help"]:
		_print_cast_set_help()
		quit(0)
		return
	if args[0] != COMMAND:
		quit(_fail("Unknown command: %s" % args[0]))
		return
	var options := _parse_options(args)
	if options.is_empty() and args.size() > 1:
		quit(2)
		return
	var body_path := _absolute_path(str(options.get("body-source", DEFAULT_BODY_SOURCE)))
	var arc_path := _absolute_path(str(options.get("arc-source", DEFAULT_ARC_SOURCE)))
	var sigil_path := _absolute_path(str(options.get("sigil-source", DEFAULT_SIGIL_SOURCE)))
	_death_source_path = _absolute_path(str(options.get("death-source", DEFAULT_DEATH_SOURCE)))
	_attack_source_path = _absolute_path(str(options.get("attack-source", DEFAULT_ATTACK_SOURCE)))
	_heavy_source_path = _absolute_path(str(options.get("heavy-source", DEFAULT_HEAVY_SOURCE)))
	_cast_source_path = _absolute_path(str(options.get("cast-source", DEFAULT_CAST_SOURCE)))
	var output_root := _absolute_path(str(options.get("output-root", CAST_SET_OUTPUT_ROOT)))
	if not _build(body_path, arc_path, sigil_path, output_root):
		quit(_fail(_last_error))
		return
	quit(0)


func _print_cast_set_help() -> void:
	print("Build the isolated Vivhite V3 Hybrid attack + heavy + cast set:")
	print("  godot --headless --path tools/art --script res://candidates/hybrid_cast_set/build_hybrid_cast_set_candidate.gd -- build-combat")
	print("    [--body-source PATH] [--arc-source PATH] [--sigil-source PATH]")
	print("    [--death-source PATH] [--attack-source PATH] [--heavy-source PATH]")
	print("    [--cast-source PATH] [--output-root PATH]")


func _build(body_path: String, arc_path: String, sigil_path: String, output_root: String) -> bool:
	_last_error = ""
	for input: Dictionary in [
		{"label": "combat body master", "path": body_path},
		{"label": "V3 cast peak source", "path": _cast_source_path},
	]:
		var path := str(input["path"])
		if not FileAccess.file_exists(path):
			return _set_error("Required %s does not exist: %s" % [input["label"], path])
		var image := Image.load_from_file(path)
		if image == null or image.is_empty():
			return _set_error("Could not decode %s: %s" % [input["label"], path])
		if image.get_format() != Image.FORMAT_RGBA8:
			return _set_error("%s must decode directly as RGBA8: %s" % [input["label"], path])
		if not _validate_native_alpha(image, path, str(input["label"])):
			return false

	var neutral_reference := Image.load_from_file(body_path)
	var cast_source := Image.load_from_file(_cast_source_path)
	var cast_prepared := _prepare_registered_pose_region(cast_source, neutral_reference)
	if cast_prepared.is_empty():
		return false
	var cast_page := _transparent_image(CAST_ATLAS_SIZE)
	cast_page.blend_rect(
		cast_prepared["image"],
		Rect2i(Vector2i.ZERO, CAST_REGION_SIZE),
		CAST_REGION_POS
	)

	# Reuse the frozen action-set build. Virtual hooks already add cast metadata;
	# the cast page itself is appended only after the seven-file parent milestone
	# has rebuilt and passed its own read-only gates.
	_building_action_set_phase = true
	if not super._build(body_path, arc_path, sigil_path, output_root):
		_building_action_set_phase = false
		return false
	_building_action_set_phase = false

	var cast_page_path := output_root.path_join(OUTPUT_CAST_PAGE)
	var save_error := cast_page.save_png(cast_page_path)
	if save_error != OK:
		return _set_error("Could not save cast atlas (%s): %s" % [error_string(save_error), cast_page_path])

	var wrapper_path := output_root.path_join(OUTPUT_ATLAS)
	var wrapper: Variant = JSON.parse_string(FileAccess.get_file_as_string(wrapper_path))
	if not wrapper is Dictionary:
		return _set_error("Written cast-set atlas wrapper could not be parsed")
	wrapper["source_path"] = "%s/vivhite_combat.atlas" % CAST_SET_RESOURCE_ROOT
	if not _write_text(wrapper_path, JSON.stringify(wrapper, "", false) + "\n"):
		return false

	if not _validate_written(output_root):
		return false
	if not _validate_candidate_isolation(output_root):
		return false
	print("Built isolated Vivhite V3 Hybrid cast-set candidate:")
	print("  neutral: %s (weighted mesh, read-only)" % body_path)
	print("  attack:  %s (rigid region, read-only)" % _attack_source_path)
	print("  heavy:   %s (rigid region, read-only)" % _heavy_source_path)
	print("  cast:    %s (rigid region, read-only)" % _cast_source_path)
	print("  cast switch: %.4f -> %.4f seconds; no RGBA crossfade" % [
		CAST_POSE_ENTER_TIME, CAST_POSE_EXIT_TIME,
	])
	print("  cast eye offset: %s" % CAST_EYE_PEAK_OFFSET)
	print("  cast canvas: frozen neutral contract %s -> region %s -> world %s" % [
		cast_prepared["contract_rect"], CAST_REGION_SIZE, CAST_WORLD_SIZE,
	])
	print("  output: %s" % output_root)
	return true


func _build_atlas_data() -> String:
	return super._build_atlas_data() + "\n" + "\n".join(PackedStringArray([
		OUTPUT_CAST_PAGE,
		"size:%d,%d" % [CAST_ATLAS_SIZE.x, CAST_ATLAS_SIZE.y],
		"filter:Linear,Linear",
		"pma:false",
		"repeat:none",
		CAST_REGION_NAME,
		"bounds:%d,%d,%d,%d" % [
			CAST_REGION_POS.x, CAST_REGION_POS.y,
			CAST_REGION_SIZE.x, CAST_REGION_SIZE.y,
		],
	])) + "\n"


func _build_skeleton_json() -> Dictionary:
	var skeleton := super._build_skeleton_json()
	skeleton["skeleton"]["hash"] = "vivhite-hybrid-v3-cast-set-v1"
	skeleton["skins"][0]["attachments"][SLOT_ACTION][CAST_REGION_NAME] = _region_attachment(
		CAST_REGION_NAME, CAST_WORLD_SIZE.x, CAST_WORLD_SIZE.y
	)
	return skeleton


func _build_animations() -> Dictionary:
	var animations := super._build_animations()
	var cast: Dictionary = animations["cast"]
	cast["slots"]["vivhite_body"] = {"attachment": [
		{"time": 0.0, "name": BODY_REGION_NAME},
		{"time": CAST_POSE_ENTER_TIME, "name": null},
		{"time": CAST_POSE_EXIT_TIME, "name": BODY_REGION_NAME},
	]}
	cast["slots"][SLOT_ACTION] = {"attachment": [
		{"time": 0.0, "name": null},
		{"time": CAST_POSE_ENTER_TIME, "name": CAST_REGION_NAME},
		{"time": CAST_POSE_EXIT_TIME, "name": null},
	]}
	# A cast never owns the slash ribbon. Clear it explicitly before the sigil
	# and EyeFire lifecycle begins so interrupted attack state cannot leak in.
	cast["slots"]["slash_mesh"] = {"attachment": [
		{"time": 0.0, "name": null},
	]}
	var duration := float(ANIMATION_DURATIONS["cast"])
	cast["bones"][BONE_EYES] = {
		"translate": _cast_eye_anchor_contract(duration, CAST_EYE_PEAK_OFFSET),
	}
	cast["bones"][BONE_ACTION] = {"rotate": [
		{"time": 0.0, "value": 0.0},
		{"time": CAST_POSE_ENTER_TIME, "value": 0.0},
		{"time": 0.48, "value": 1.5},
		{"time": CAST_POSE_PRE_EXIT_TIME, "value": -1.0},
		{"time": CAST_POSE_EXIT_TIME, "value": 0.0},
		{"time": duration, "value": 0.0},
	]}

	# Merchant random-seek safety: both relaxed-loop boundaries restore exactly
	# one neutral person and explicitly clear every authored VFX attachment.
	var relaxed: Dictionary = animations["relaxed_loop"]
	var relaxed_duration := float(ANIMATION_DURATIONS["relaxed_loop"])
	for slot_name: String in ["slash_mesh", "vivhite_magic_sigil"]:
		relaxed["slots"][slot_name] = {"attachment": [
			{"time": 0.0, "name": null},
			{"time": relaxed_duration, "name": null},
		]}
	return animations


func _cast_eye_anchor_contract(duration: float, peak_offset: Vector2) -> Array:
	return [
		{"time": 0.0, "x": 0.0, "y": 0.0},
		{"time": CAST_POSE_ENTER_TIME, "x": peak_offset.x, "y": peak_offset.y},
		{"time": CAST_POSE_PRE_EXIT_TIME, "x": peak_offset.x, "y": peak_offset.y},
		{"time": CAST_POSE_EXIT_TIME, "x": CAST_EYE_NEUTRAL_OFFSET.x, "y": CAST_EYE_NEUTRAL_OFFSET.y},
		{"time": CAST_EYE_PRE_CLEAR_TIME, "x": CAST_EYE_NEUTRAL_OFFSET.x, "y": CAST_EYE_NEUTRAL_OFFSET.y},
		{"time": CAST_CLEAR_TIME, "x": 0.0, "y": 0.0},
		{"time": duration, "x": 0.0, "y": 0.0},
	]


func _build_skeleton_data_tres() -> String:
	return super._build_skeleton_data_tres().replace(ACTION_SET_RESOURCE_ROOT, CAST_SET_RESOURCE_ROOT)


func _validate_rig(skeleton: Dictionary, atlas_data: String) -> bool:
	# Removing only the cast layer must recover the already frozen action-set
	# contract. This guards attack, heavy, death, mixes and event semantics.
	var action_baseline := skeleton.duplicate(true)
	action_baseline["skins"][0]["attachments"][SLOT_ACTION].erase(CAST_REGION_NAME)
	var baseline_cast: Dictionary = action_baseline["animations"]["cast"]
	baseline_cast["slots"].erase("vivhite_body")
	baseline_cast["slots"].erase("slash_mesh")
	baseline_cast["slots"][SLOT_ACTION] = {"attachment": [{"time": 0.0, "name": null}]}
	baseline_cast["bones"].erase(BONE_ACTION)
	baseline_cast["bones"].erase(BONE_EYES)
	var baseline_relaxed: Dictionary = action_baseline["animations"]["relaxed_loop"]
	baseline_relaxed["slots"].erase("slash_mesh")
	baseline_relaxed["slots"].erase("vivhite_magic_sigil")
	if not super._validate_rig(action_baseline, atlas_data):
		return false

	var action_attachments: Dictionary = skeleton["skins"][0]["attachments"].get(SLOT_ACTION, {})
	if action_attachments.size() != 3:
		return _set_error("Cast-set action slot must contain exactly attack, heavy and cast attachments")
	for region_name: String in [ATTACK_REGION_NAME, HEAVY_REGION_NAME, CAST_REGION_NAME]:
		if not action_attachments.has(region_name):
			return _set_error("Cast-set candidate is missing %s" % region_name)
		var attachment: Dictionary = action_attachments[region_name]
		if str(attachment.get("type", "region")) != "region":
			return _set_error("Cast-set attachment must remain a rigid region: %s" % region_name)
		if (
			absf(float(attachment.get("width", NAN)) - CAST_WORLD_SIZE.x) > 0.00001
			or absf(float(attachment.get("height", NAN)) - CAST_WORLD_SIZE.y) > 0.00001
		):
			return _set_error("Cast-set attachment lost the frozen neutral world size: %s" % region_name)
	if atlas_data.count("%s\n" % OUTPUT_CAST_PAGE) != 1:
		return _set_error("Cast atlas page must be declared exactly once")
	if atlas_data.count("%s\n" % CAST_REGION_NAME) != 1:
		return _set_error("Cast atlas region must be declared exactly once")
	return _validate_cast_contract(skeleton)


func _validate_cast_contract(skeleton: Dictionary) -> bool:
	var cast: Dictionary = skeleton["animations"]["cast"]
	if not _validate_atomic_action_swap(
		cast["slots"], CAST_REGION_NAME,
		CAST_POSE_ENTER_TIME, CAST_POSE_EXIT_TIME, "cast"
	):
		return false
	if not _validate_event_time(cast, "cast_eyes_start", CAST_POSE_ENTER_TIME):
		return false
	if not _validate_event_time(cast, "clear_vfx", CAST_CLEAR_TIME):
		return false
	var sigil_keys: Array = cast.get("slots", {}).get("vivhite_magic_sigil", {}).get("attachment", [])
	if sigil_keys.size() != 3:
		return _set_error("Cast sigil must contain exactly null/show/null keys")
	var sigil_times := [0.0, CAST_SIGIL_ENTER_TIME, CAST_CLEAR_TIME]
	var sigil_names := [null, SIGIL_REGION_NAME, null]
	for index in 3:
		if (
			absf(float(sigil_keys[index].get("time", -1.0)) - float(sigil_times[index])) > 0.00001
			or sigil_keys[index].get("name", "sentinel") != sigil_names[index]
		):
			return _set_error("Cast sigil lifecycle changed at index %d" % index)
	var slash_keys: Array = cast.get("slots", {}).get("slash_mesh", {}).get("attachment", [])
	if (
		slash_keys.size() != 1
		or absf(float(slash_keys[0].get("time", -1.0))) > 0.00001
		or slash_keys[0].get("name", "sentinel") != null
	):
		return _set_error("Cast must explicitly clear slash_mesh at t=0")
	var eye_keys: Array = cast.get("bones", {}).get(BONE_EYES, {}).get("translate", [])
	var expected_times := [
		0.0, CAST_POSE_ENTER_TIME, CAST_POSE_PRE_EXIT_TIME,
		CAST_POSE_EXIT_TIME, CAST_EYE_PRE_CLEAR_TIME, CAST_CLEAR_TIME,
		float(ANIMATION_DURATIONS["cast"]),
	]
	if eye_keys.size() != expected_times.size():
		return _set_error("Cast eye anchor must contain exactly seven pose/VFX lifecycle keys")
	for index in expected_times.size():
		var expected_offset := Vector2.ZERO
		if index in [1, 2]:
			expected_offset = CAST_EYE_PEAK_OFFSET
		elif index in [3, 4]:
			expected_offset = CAST_EYE_NEUTRAL_OFFSET
		if (
			absf(float(eye_keys[index].get("time", -1.0)) - float(expected_times[index])) > 0.00001
			or absf(float(eye_keys[index].get("x", 0.0)) - expected_offset.x) > 0.00001
			or absf(float(eye_keys[index].get("y", 0.0)) - expected_offset.y) > 0.00001
		):
			return _set_error("Cast eye anchor key is invalid at index %d" % index)
	var relaxed: Dictionary = skeleton["animations"]["relaxed_loop"]
	var relaxed_duration := float(ANIMATION_DURATIONS["relaxed_loop"])
	for slot_name: String in ["slash_mesh", "vivhite_magic_sigil"]:
		var keys: Array = relaxed.get("slots", {}).get(slot_name, {}).get("attachment", [])
		if keys.size() != 2:
			return _set_error("relaxed_loop must clear %s at both boundaries" % slot_name)
		for index in 2:
			var expected_time := 0.0 if index == 0 else relaxed_duration
			if (
				absf(float(keys[index].get("time", -1.0)) - expected_time) > 0.00001
				or keys[index].get("name", "sentinel") != null
			):
				return _set_error("relaxed_loop has an invalid %s reset" % slot_name)
	return true


func _validate_written(output_root: String) -> bool:
	var pages := [
		{"name": OUTPUT_PAGE, "size": ATLAS_SIZE},
		{"name": OUTPUT_DEATH_PAGE, "size": DEATH_ATLAS_SIZE},
		{"name": OUTPUT_ATTACK_PAGE, "size": ATTACK_ATLAS_SIZE},
	]
	if not _building_parent_phase:
		pages.append({"name": OUTPUT_HEAVY_PAGE, "size": HEAVY_ATLAS_SIZE})
	if not _building_action_set_phase:
		pages.append({"name": OUTPUT_CAST_PAGE, "size": CAST_ATLAS_SIZE})
	for output: Dictionary in pages:
		var image := Image.load_from_file(output_root.path_join(str(output["name"])))
		if (
			image == null or image.is_empty()
			or image.get_size() != output["size"]
			or image.get_format() != Image.FORMAT_RGBA8
		):
			return _set_error("Written cast-set atlas page is invalid: %s" % output["name"])
	var decoded: Variant = JSON.parse_string(FileAccess.get_file_as_string(output_root.path_join(OUTPUT_JSON)))
	if not decoded is Dictionary:
		return _set_error("Written cast-set Spine JSON could not be parsed")
	var atlas_decoded: Variant = JSON.parse_string(FileAccess.get_file_as_string(output_root.path_join(OUTPUT_ATLAS)))
	if not atlas_decoded is Dictionary:
		return _set_error("Written cast-set atlas wrapper could not be parsed")
	if not _validate_rig(decoded, str(atlas_decoded.get("atlas_data", ""))):
		return false
	var tres := FileAccess.get_file_as_string(output_root.path_join(OUTPUT_DATA))
	for required: String in [
		"%s/vivhite_combat.spatlas" % CAST_SET_RESOURCE_ROOT,
		"%s/vivhite_combat.spjson" % CAST_SET_RESOURCE_ROOT,
	]:
		if not tres.contains(required):
			return _set_error("Written cast-set skeleton-data wrapper is missing %s" % required)
	return true


func _validate_candidate_isolation(output_root: String) -> bool:
	var files := PackedStringArray()
	for file_name: String in DirAccess.get_files_at(output_root):
		if file_name.ends_with(".uid") or file_name.ends_with(".import"):
			continue
		files.append(file_name)
	var allowed := PackedStringArray([
		OUTPUT_JSON, OUTPUT_ATLAS, OUTPUT_PAGE, OUTPUT_DEATH_PAGE,
		OUTPUT_ATTACK_PAGE, OUTPUT_HEAVY_PAGE, OUTPUT_CAST_PAGE, OUTPUT_DATA,
	])
	for file_name: String in files:
		if file_name not in allowed:
			return _set_error("Cast-set output has unexpected authored file: %s" % file_name)
	for required_name: String in [OUTPUT_JSON, OUTPUT_ATLAS, OUTPUT_PAGE, OUTPUT_DEATH_PAGE, OUTPUT_ATTACK_PAGE, OUTPUT_DATA]:
		if required_name not in files:
			return _set_error("Cast-set output is missing authored file: %s" % required_name)
	if not _building_parent_phase and OUTPUT_HEAVY_PAGE not in files:
		return _set_error("Cast-set output is missing heavy page after parent build")
	if not _building_action_set_phase and OUTPUT_CAST_PAGE not in files:
		return _set_error("Cast-set output is missing cast page after final build")
	if not _building_parent_phase and not _building_action_set_phase and files.size() != allowed.size():
		return _set_error("Final cast-set output must contain exactly eight authored files")
	for text_name: String in [OUTPUT_JSON, OUTPUT_ATLAS, OUTPUT_DATA]:
		var content := FileAccess.get_file_as_string(output_root.path_join(text_name))
		if content.contains("res://Vivhite/skins/ironclad/spine/combat"):
			return _set_error("Cast-set candidate leaked a runtime combat path in %s" % text_name)
	if _building_parent_phase or _building_action_set_phase:
		return true
	var wrapper: Variant = JSON.parse_string(FileAccess.get_file_as_string(output_root.path_join(OUTPUT_ATLAS)))
	if not wrapper is Dictionary:
		return _set_error("Cast-set atlas wrapper could not be parsed")
	if str(wrapper.get("source_path", "")) != "%s/vivhite_combat.atlas" % CAST_SET_RESOURCE_ROOT:
		return _set_error("Cast-set atlas wrapper is not candidate-local")
	return true
