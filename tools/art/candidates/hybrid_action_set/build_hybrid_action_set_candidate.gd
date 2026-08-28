extends "res://candidates/hybrid_attack_peak/build_hybrid_attack_peak_candidate.gd"

## V3 Hybrid action-set milestone: retain the accepted neutral, attack and
## death layers, then add one independent rigid full-body heavy-attack pose to
## the same action slot. The candidate is isolated below tools/ and never
## writes the runtime skin, deployed mod, game directory, or live process.

const ACTION_SET_OUTPUT_ROOT := "Vivhite/tools/candidates/hybrid_action_set"
const ACTION_SET_RESOURCE_ROOT := "res://tools/candidates/hybrid_action_set"
const DEFAULT_HEAVY_SOURCE := (
	"assets/vivhite-ironclad/custom/combat/sources/"
	+ "vivhite-combat-attack-heavy-peak-v1.png"
)

const OUTPUT_HEAVY_PAGE := "vivhite_combat_attack_heavy.png"
const HEAVY_ATLAS_SIZE := Vector2i(2048, 2304)
const HEAVY_REGION_NAME := "vivhite_combat_attack_heavy_peak"
const HEAVY_REGION_POS := Vector2i(16, 16)
const HEAVY_REGION_SIZE := BODY_REGION_SIZE
const HEAVY_WORLD_SIZE := Vector2(BODY_WORLD_RECT.size.x, BODY_WORLD_RECT.size.y)

const HEAVY_POSE_ENTER_TIME := 0.12
const HEAVY_POSE_EXIT_TIME := 0.32
const HEAVY_POSE_PRE_EXIT_TIME := 0.3199
# A temporary 0106-as-action Vulkan render showed that the accepted attack
# correction lands on 0106's screen-right lead palm at the same fixed canvas
# transform. Reuse that measured `(210,30)` initial value; the dedicated heavy
# exact renderer remains the final calibration gate.
const HEAVY_ARC_PEAK_OFFSET := Vector2(210.0, 30.0)

var _heavy_source_path := ""
var _building_parent_phase := false


func _initialize() -> void:
	var args := OS.get_cmdline_user_args()
	if args.is_empty():
		args = PackedStringArray([COMMAND])
	if args[0] in ["-h", "--help", "help"]:
		_print_action_set_help()
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
	var output_root := _absolute_path(str(options.get("output-root", ACTION_SET_OUTPUT_ROOT)))
	if not _build(body_path, arc_path, sigil_path, output_root):
		quit(_fail(_last_error))
		return
	quit(0)


func _print_action_set_help() -> void:
	print("Build the isolated Vivhite V3 Hybrid attack + heavy action set:")
	print("  godot --headless --path tools/art --script res://candidates/hybrid_action_set/build_hybrid_action_set_candidate.gd -- build-combat")
	print("    [--body-source PATH] [--arc-source PATH] [--sigil-source PATH]")
	print("    [--death-source PATH] [--attack-source PATH] [--heavy-source PATH]")
	print("    [--output-root PATH]")


func _build(body_path: String, arc_path: String, sigil_path: String, output_root: String) -> bool:
	_last_error = ""
	for input: Dictionary in [
		{"label": "combat body master", "path": body_path},
		{"label": "V3 heavy-attack peak source", "path": _heavy_source_path},
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
	var heavy_source := Image.load_from_file(_heavy_source_path)
	var heavy_prepared := _prepare_registered_pose_region(heavy_source, neutral_reference)
	if heavy_prepared.is_empty():
		return false
	var heavy_page := _transparent_image(HEAVY_ATLAS_SIZE)
	heavy_page.blend_rect(
		heavy_prepared["image"],
		Rect2i(Vector2i.ZERO, HEAVY_REGION_SIZE),
		HEAVY_REGION_POS
	)

	# Reuse the accepted attack candidate's complete build path. Virtual builder
	# hooks below add the heavy attachment/timeline/atlas metadata. The inherited
	# writer first emits its six files; this builder then appends the seventh page
	# and rewrites only the candidate-local wrapper path before the final gate.
	_building_parent_phase = true
	if not super._build(body_path, arc_path, sigil_path, output_root):
		_building_parent_phase = false
		return false
	_building_parent_phase = false

	var heavy_page_path := output_root.path_join(OUTPUT_HEAVY_PAGE)
	var save_error := heavy_page.save_png(heavy_page_path)
	if save_error != OK:
		return _set_error("Could not save heavy atlas (%s): %s" % [error_string(save_error), heavy_page_path])

	var wrapper_path := output_root.path_join(OUTPUT_ATLAS)
	var wrapper: Variant = JSON.parse_string(FileAccess.get_file_as_string(wrapper_path))
	if not wrapper is Dictionary:
		return _set_error("Written action-set atlas wrapper could not be parsed")
	wrapper["source_path"] = "%s/vivhite_combat.atlas" % ACTION_SET_RESOURCE_ROOT
	if not _write_text(wrapper_path, JSON.stringify(wrapper, "", false) + "\n"):
		return false

	if not _validate_written(output_root):
		return false
	if not _validate_candidate_isolation(output_root):
		return false
	print("Built isolated Vivhite V3 Hybrid action-set candidate:")
	print("  neutral: %s (weighted mesh, read-only)" % body_path)
	print("  attack:  %s (rigid region, read-only)" % _attack_source_path)
	print("  heavy:   %s (rigid region, read-only)" % _heavy_source_path)
	print("  heavy switch: %.4f -> %.4f seconds; no RGBA crossfade" % [
		HEAVY_POSE_ENTER_TIME, HEAVY_POSE_EXIT_TIME,
	])
	print("  heavy canvas: frozen neutral contract %s -> region %s -> world %s" % [
		heavy_prepared["contract_rect"], HEAVY_REGION_SIZE, HEAVY_WORLD_SIZE,
	])
	print("  output: %s" % output_root)
	return true


func _build_atlas_data() -> String:
	return super._build_atlas_data() + "\n" + "\n".join(PackedStringArray([
		OUTPUT_HEAVY_PAGE,
		"size:%d,%d" % [HEAVY_ATLAS_SIZE.x, HEAVY_ATLAS_SIZE.y],
		"filter:Linear,Linear",
		"pma:false",
		"repeat:none",
		HEAVY_REGION_NAME,
		"bounds:%d,%d,%d,%d" % [
			HEAVY_REGION_POS.x, HEAVY_REGION_POS.y,
			HEAVY_REGION_SIZE.x, HEAVY_REGION_SIZE.y,
		],
	])) + "\n"


func _build_skeleton_json() -> Dictionary:
	var skeleton := super._build_skeleton_json()
	skeleton["skeleton"]["hash"] = "vivhite-hybrid-v3-action-set-v1"
	skeleton["skins"][0]["attachments"][SLOT_ACTION][HEAVY_REGION_NAME] = _region_attachment(
		HEAVY_REGION_NAME, HEAVY_WORLD_SIZE.x, HEAVY_WORLD_SIZE.y
	)
	return skeleton


func _build_animations() -> Dictionary:
	var animations := super._build_animations()
	var heavy: Dictionary = animations["attack_heavy"]
	heavy["slots"]["vivhite_body"] = {"attachment": [
		{"time": 0.0, "name": BODY_REGION_NAME},
		{"time": HEAVY_POSE_ENTER_TIME, "name": null},
		{"time": HEAVY_POSE_EXIT_TIME, "name": BODY_REGION_NAME},
	]}
	heavy["slots"][SLOT_ACTION] = {"attachment": [
		{"time": 0.0, "name": null},
		{"time": HEAVY_POSE_ENTER_TIME, "name": HEAVY_REGION_NAME},
		{"time": HEAVY_POSE_EXIT_TIME, "name": null},
	]}
	var duration := float(ANIMATION_DURATIONS["attack_heavy"])
	heavy["bones"][BONE_ARC]["translate"] = _heavy_anchor_contract(duration, HEAVY_ARC_PEAK_OFFSET)
	heavy["bones"][BONE_EYES] = {
		"translate": _heavy_anchor_contract(duration, Vector2.ZERO),
	}
	heavy["bones"][BONE_ACTION] = {
		"rotate": [
			{"time": 0.0, "value": 0.0},
			{"time": HEAVY_POSE_ENTER_TIME, "value": 0.0},
			{"time": 0.22, "value": 2.5},
			{"time": HEAVY_POSE_PRE_EXIT_TIME, "value": -1.5},
			{"time": HEAVY_POSE_EXIT_TIME, "value": 0.0},
			{"time": duration, "value": 0.0},
		],
	}
	return animations


func _heavy_anchor_contract(duration: float, peak_offset: Vector2) -> Array:
	return [
		{"time": 0.0, "x": 0.0, "y": 0.0},
		{"time": HEAVY_POSE_ENTER_TIME, "x": peak_offset.x, "y": peak_offset.y},
		{"time": HEAVY_POSE_PRE_EXIT_TIME, "x": peak_offset.x, "y": peak_offset.y},
		{"time": HEAVY_POSE_EXIT_TIME, "x": 0.0, "y": 0.0},
		{"time": duration, "x": 0.0, "y": 0.0},
	]


func _build_skeleton_data_tres() -> String:
	return super._build_skeleton_data_tres().replace(HYBRID_RESOURCE_ROOT, ACTION_SET_RESOURCE_ROOT)


func _validate_rig(skeleton: Dictionary, atlas_data: String) -> bool:
	# First prove that deleting only the new heavy layer recovers the already
	# accepted attack candidate contract. This keeps the second milestone from
	# silently changing neutral, attack, death, events, mixes or VFX semantics.
	var attack_baseline := skeleton.duplicate(true)
	attack_baseline["skins"][0]["attachments"][SLOT_ACTION].erase(HEAVY_REGION_NAME)
	var baseline_heavy: Dictionary = attack_baseline["animations"]["attack_heavy"]
	baseline_heavy["slots"].erase("vivhite_body")
	baseline_heavy["slots"][SLOT_ACTION] = {"attachment": [{"time": 0.0, "name": null}]}
	baseline_heavy["bones"].erase(BONE_ACTION)
	if not super._validate_rig(attack_baseline, atlas_data):
		return false

	var action_attachments: Dictionary = skeleton["skins"][0]["attachments"].get(SLOT_ACTION, {})
	if action_attachments.size() != 2:
		return _set_error("Action-set candidate must contain exactly attack and heavy attachments")
	for region_name: String in [ATTACK_REGION_NAME, HEAVY_REGION_NAME]:
		if not action_attachments.has(region_name):
			return _set_error("Action-set candidate is missing %s" % region_name)
		var attachment: Dictionary = action_attachments[region_name]
		if str(attachment.get("type", "region")) != "region":
			return _set_error("Action-set attachment must remain a rigid region: %s" % region_name)
		if (
			absf(float(attachment.get("width", NAN)) - HEAVY_WORLD_SIZE.x) > 0.00001
			or absf(float(attachment.get("height", NAN)) - HEAVY_WORLD_SIZE.y) > 0.00001
		):
			return _set_error("Action-set attachment lost the frozen neutral world size: %s" % region_name)
	if atlas_data.count("%s\n" % OUTPUT_HEAVY_PAGE) != 1:
		return _set_error("Heavy atlas page must be declared exactly once")
	if atlas_data.count("%s\n" % HEAVY_REGION_NAME) != 1:
		return _set_error("Heavy atlas region must be declared exactly once")
	return _validate_action_set_attachment_swaps(skeleton)


func _validate_action_set_attachment_swaps(skeleton: Dictionary) -> bool:
	for animation_name: String in ANIMATION_DURATIONS:
		var slots: Dictionary = skeleton["animations"][animation_name].get("slots", {})
		if not slots.has(SLOT_ACTION):
			return _set_error("Every action-set animation must explicitly reset the action slot: %s" % animation_name)
		if slots.get("vivhite_body", {}).has("rgba") or slots[SLOT_ACTION].has("rgba"):
			return _set_error("Full-body action swaps must not use RGBA crossfades: %s" % animation_name)
		if animation_name in ["attack", "attack_heavy"]:
			var region_name := ATTACK_REGION_NAME if animation_name == "attack" else HEAVY_REGION_NAME
			var enter_time := ATTACK_POSE_ENTER_TIME if animation_name == "attack" else HEAVY_POSE_ENTER_TIME
			var exit_time := ATTACK_POSE_EXIT_TIME if animation_name == "attack" else HEAVY_POSE_EXIT_TIME
			if not _validate_atomic_action_swap(slots, region_name, enter_time, exit_time, animation_name):
				return false
			continue
		var keys: Array = slots[SLOT_ACTION].get("attachment", [])
		if animation_name == "relaxed_loop":
			var duration := float(ANIMATION_DURATIONS["relaxed_loop"])
			if keys.size() != 2:
				return _set_error("relaxed_loop must clear the shared action slot at both boundaries")
			for index in 2:
				var expected_time := 0.0 if index == 0 else duration
				if (
					absf(float(keys[index].get("time", -1.0)) - expected_time) > 0.00001
					or keys[index].get("name", "sentinel") != null
				):
					return _set_error("relaxed_loop has an invalid action reset")
			continue
		if (
			keys.size() != 1
			or absf(float(keys[0].get("time", -1.0))) > 0.00001
			or keys[0].get("name", "sentinel") != null
		):
			return _set_error("Only attack/heavy may expose the shared action slot: %s" % animation_name)

	var heavy: Dictionary = skeleton["animations"]["attack_heavy"]
	if not _validate_event_time(heavy, "heavy_slash_start", HEAVY_POSE_ENTER_TIME):
		return false
	for anchor_bone: String in [BONE_ARC, BONE_EYES]:
		var keys: Array = heavy.get("bones", {}).get(anchor_bone, {}).get("translate", [])
		for required_time: float in [HEAVY_POSE_ENTER_TIME, HEAVY_POSE_PRE_EXIT_TIME, HEAVY_POSE_EXIT_TIME]:
			if _timeline_axis_value_at_time(keys, required_time, "x") == null:
				return _set_error("Heavy anchor %s is missing %.4f contract key" % [anchor_bone, required_time])
	return true


func _validate_atomic_action_swap(
	slots: Dictionary,
	region_name: String,
	enter_time: float,
	exit_time: float,
	animation_name: String,
) -> bool:
	var body_keys: Array = slots.get("vivhite_body", {}).get("attachment", [])
	var action_keys: Array = slots.get(SLOT_ACTION, {}).get("attachment", [])
	if body_keys.size() != 3 or action_keys.size() != 3:
		return _set_error("%s must use exactly three atomic keys per character slot" % animation_name)
	var times := [0.0, enter_time, exit_time]
	var body_names := [BODY_REGION_NAME, null, BODY_REGION_NAME]
	var action_names := [null, region_name, null]
	for index in 3:
		if (
			absf(float(body_keys[index].get("time", -1.0)) - float(times[index])) > 0.00001
			or absf(float(action_keys[index].get("time", -1.0)) - float(times[index])) > 0.00001
			or body_keys[index].get("name", "sentinel") != body_names[index]
			or action_keys[index].get("name", "sentinel") != action_names[index]
		):
			return _set_error("%s neutral/action slots must switch atomically" % animation_name)
	return true


func _validate_written(output_root: String) -> bool:
	var pages := [
		{"name": OUTPUT_PAGE, "size": ATLAS_SIZE},
		{"name": OUTPUT_DEATH_PAGE, "size": DEATH_ATLAS_SIZE},
		{"name": OUTPUT_ATTACK_PAGE, "size": ATTACK_ATLAS_SIZE},
	]
	if not _building_parent_phase:
		pages.append({"name": OUTPUT_HEAVY_PAGE, "size": HEAVY_ATLAS_SIZE})
	for output: Dictionary in pages:
		var image := Image.load_from_file(output_root.path_join(str(output["name"])))
		if (
			image == null or image.is_empty()
			or image.get_size() != output["size"]
			or image.get_format() != Image.FORMAT_RGBA8
		):
			return _set_error("Written action-set atlas page is invalid: %s" % output["name"])
	var decoded: Variant = JSON.parse_string(FileAccess.get_file_as_string(output_root.path_join(OUTPUT_JSON)))
	if not decoded is Dictionary:
		return _set_error("Written action-set Spine JSON could not be parsed")
	var atlas_decoded: Variant = JSON.parse_string(FileAccess.get_file_as_string(output_root.path_join(OUTPUT_ATLAS)))
	if not atlas_decoded is Dictionary:
		return _set_error("Written action-set atlas wrapper could not be parsed")
	if not _validate_rig(decoded, str(atlas_decoded.get("atlas_data", ""))):
		return false
	var tres := FileAccess.get_file_as_string(output_root.path_join(OUTPUT_DATA))
	for required: String in [
		"%s/vivhite_combat.spatlas" % ACTION_SET_RESOURCE_ROOT,
		"%s/vivhite_combat.spjson" % ACTION_SET_RESOURCE_ROOT,
	]:
		if not tres.contains(required):
			return _set_error("Written action-set skeleton-data wrapper is missing %s" % required)
	return true


func _validate_candidate_isolation(output_root: String) -> bool:
	var files := PackedStringArray()
	for file_name: String in DirAccess.get_files_at(output_root):
		if file_name.ends_with(".uid") or file_name.ends_with(".import"):
			continue
		files.append(file_name)
	var expected := PackedStringArray([
		OUTPUT_JSON,
		OUTPUT_ATLAS,
		OUTPUT_PAGE,
		OUTPUT_DEATH_PAGE,
		OUTPUT_ATTACK_PAGE,
		OUTPUT_DATA,
	])
	# A rebuild may enter the inherited six-file phase while the previous heavy
	# page is still present. Accept that one known stale page temporarily; it is
	# deterministically overwritten before the final seven-file gate.
	if not _building_parent_phase or FileAccess.file_exists(output_root.path_join(OUTPUT_HEAVY_PAGE)):
		expected.append(OUTPUT_HEAVY_PAGE)
	files.sort()
	expected.sort()
	if files != expected:
		return _set_error("Action-set output has unexpected authored files: %s" % files)
	for text_name: String in [OUTPUT_JSON, OUTPUT_ATLAS, OUTPUT_DATA]:
		var content := FileAccess.get_file_as_string(output_root.path_join(text_name))
		if content.contains("res://Vivhite/skins/ironclad/spine/combat"):
			return _set_error("Action-set candidate leaked a runtime combat path in %s" % text_name)
	if _building_parent_phase:
		return true
	var wrapper: Variant = JSON.parse_string(FileAccess.get_file_as_string(output_root.path_join(OUTPUT_ATLAS)))
	if not wrapper is Dictionary:
		return _set_error("Action-set atlas wrapper could not be parsed")
	if str(wrapper.get("source_path", "")) != "%s/vivhite_combat.atlas" % ACTION_SET_RESOURCE_ROOT:
		return _set_error("Action-set atlas wrapper is not candidate-local")
	return true
