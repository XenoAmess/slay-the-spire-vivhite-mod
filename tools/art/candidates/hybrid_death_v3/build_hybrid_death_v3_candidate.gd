extends "../whole_mesh/build_whole_mesh_candidate.gd"

## Offline-only V3 death continuity candidate. It keeps the dedicated 0029
## side-collapse illustration, but replaces the old hover-then-drop handoff
## with a low articulated contraction, one atomic body swap, immediate solid
## contact, and a small damped rebound. Nothing below the live skin path is
## written by this builder.

const DEATH_V3_OUTPUT_ROOT := "Vivhite/tools/candidates/hybrid_death_v3"
const DEATH_V3_RESOURCE_ROOT := "res://tools/candidates/hybrid_death_v3"
const DEATH_V3_SOURCE_SHA256 := "9b391e6dae9ac1e85d05d77b3b0e7e286bf2f0b613e164c714a99054ec12a17b"

# The last weighted-mesh silhouette is moved onto the same ground/contact
# family as the rigid side pose. These are authored Spine units; the scene
# remains fixed at .28.
const DEATH_V3_PRE_SWAP_ROOT_X := -396.0
const DEATH_V3_PRE_SWAP_ROOT_Y := 150.0
const DEATH_V3_PRE_SWAP_ROTATION := -50.0
const DEATH_V3_IMPACT_X := -4.0
const DEATH_V3_IMPACT_Y := -7.0
const DEATH_V3_REBOUND_X := 5.0
const DEATH_V3_REBOUND_Y := 14.0
const DEATH_V3_DAMP_X := 1.5
const DEATH_V3_DAMP_Y := 3.0

var _inside_parent_build := false


func _initialize() -> void:
	var args := OS.get_cmdline_user_args()
	if args.is_empty():
		args = PackedStringArray([COMMAND])
	if args[0] in ["-h", "--help", "help"]:
		_print_death_v3_help()
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
	var output_root := _absolute_path(str(options.get("output-root", DEATH_V3_OUTPUT_ROOT)))
	if FileAccess.get_sha256(_death_source_path).to_lower() != DEATH_V3_SOURCE_SHA256:
		quit(_fail("V3 death must consume the frozen, unmodified 0029 source"))
		return
	if not _build(body_path, arc_path, sigil_path, output_root):
		quit(_fail(_last_error))
		return
	quit(0)


func _print_death_v3_help() -> void:
	print("Build the isolated Vivhite V3 death-continuity candidate:")
	print("  godot --headless --path tools/art --script res://candidates/hybrid_death_v3/build_hybrid_death_v3_candidate.gd -- build-combat")
	print("    [--body-source PATH] [--arc-source PATH] [--sigil-source PATH]")
	print("    [--death-source PATH] [--output-root PATH]")


func _build(body_path: String, arc_path: String, sigil_path: String, output_root: String) -> bool:
	_inside_parent_build = true
	if not super._build(body_path, arc_path, sigil_path, output_root):
		_inside_parent_build = false
		return false
	_inside_parent_build = false

	# The inherited writer temporarily points the atlas wrapper at whole_mesh.
	# Rewrite that metadata to this isolated bundle, then re-run exact checks.
	var atlas_path := output_root.path_join(OUTPUT_ATLAS)
	var wrapper = JSON.parse_string(FileAccess.get_file_as_string(atlas_path))
	if not wrapper is Dictionary:
		return _set_error("V3 death atlas wrapper could not be parsed for isolation rewrite")
	wrapper["source_path"] = "%s/vivhite_combat.atlas" % DEATH_V3_RESOURCE_ROOT
	if not _write_text(atlas_path, JSON.stringify(wrapper, "", false) + "\n"):
		return false
	if not _validate_written(output_root):
		return false
	if not _validate_candidate_isolation(output_root):
		return false
	print("Built isolated Vivhite V3 death-continuity candidate:")
	print("  source: %s (frozen 0029 whole-body side pose)" % _death_source_path)
	print("  handoff: %.4f -> %.4f seconds; atomic and grounded" % [DEATH_PRE_SWAP_TIME, DEATH_SWAP_TIME])
	print("  output: %s" % output_root)
	return true


func _build_skeleton_json() -> Dictionary:
	var skeleton := super._build_skeleton_json()
	skeleton["skeleton"]["hash"] = "vivhite-hybrid-death-v3-grounded-atomic-v1"
	return skeleton


func _whole_mesh_die() -> Dictionary:
	var animation := super._whole_mesh_die()
	var bones: Dictionary = animation["bones"]
	var root_translate: Array = bones[BONE_RIG]["translate"]
	_set_translate_key(root_translate, DEATH_PREP_TIME, -215.0, 48.0)
	_set_translate_key(
		root_translate,
		DEATH_PRE_SWAP_TIME,
		DEATH_V3_PRE_SWAP_ROOT_X,
		DEATH_V3_PRE_SWAP_ROOT_Y,
	)
	var root_rotate: Array = bones[BONE_RIG]["rotate"]
	_set_rotate_key(root_rotate, DEATH_PREP_TIME, -31.0)
	_set_rotate_key(root_rotate, DEATH_PRE_SWAP_TIME, DEATH_V3_PRE_SWAP_ROTATION)

	# The side pose is already calibrated to the solid painted contact edge at
	# setup. Show it there immediately; the following negative-y impact is a
	# two-pixel downward compression at .28, followed by a four-pixel rebound.
	var landing: Array = bones[BONE_DEATH]["translate"]
	_set_translate_key(landing, 0.0, 0.0, 0.0)
	_set_translate_key(landing, 0.82, 0.0, 0.0)
	_set_translate_key(landing, DEATH_SWAP_TIME, 0.0, 0.0)
	_set_translate_key(landing, DEATH_CONTACT_TIME, DEATH_V3_IMPACT_X, DEATH_V3_IMPACT_Y)
	_set_translate_key(landing, DEATH_REBOUND_TIME, DEATH_V3_REBOUND_X, DEATH_V3_REBOUND_Y)
	_set_translate_key(landing, DEATH_DAMP_TIME, DEATH_V3_DAMP_X, DEATH_V3_DAMP_Y)
	_set_translate_key(landing, DEATH_SETTLE_TIME, 0.0, 0.0)
	_set_translate_key(landing, float(ANIMATION_DURATIONS["die"]), 0.0, 0.0)
	return animation


func _set_translate_key(keys: Array, time: float, x: float, y: float) -> void:
	for key: Dictionary in keys:
		if absf(float(key.get("time", 0.0)) - time) <= 0.00001:
			key["x"] = x
			key["y"] = y
			return
	push_error("V3 death builder could not find translate key %.7f" % time)


func _set_rotate_key(keys: Array, time: float, value: float) -> void:
	for key: Dictionary in keys:
		if absf(float(key.get("time", 0.0)) - time) <= 0.00001:
			key["value"] = value
			return
	push_error("V3 death builder could not find rotate key %.7f" % time)


func _build_skeleton_data_tres() -> String:
	return super._build_skeleton_data_tres().replace(CANDIDATE_RESOURCE_ROOT, DEATH_V3_RESOURCE_ROOT)


func _validate_rig(skeleton: Dictionary, atlas_data: String) -> bool:
	# Reuse every hierarchy, animation, event, mesh, atlas and easing assertion
	# from whole_mesh by presenting only its historical numeric death calibration
	# to that validator. The untouched candidate is checked against V3 below.
	var baseline: Dictionary = skeleton.duplicate(true)
	var baseline_die: Dictionary = baseline["animations"]["die"]
	_set_translate_key(
		baseline_die["bones"][BONE_RIG]["translate"],
		DEATH_PRE_SWAP_TIME,
		-360.0,
		150.0,
	)
	_set_rotate_key(baseline_die["bones"][BONE_RIG]["rotate"], DEATH_PRE_SWAP_TIME, -47.0)
	var baseline_landing: Array = baseline_die["bones"][BONE_DEATH]["translate"]
	_set_translate_key(baseline_landing, DEATH_SWAP_TIME, -18.0, DEATH_SWAP_OFFSET_Y)
	_set_translate_key(baseline_landing, DEATH_CONTACT_TIME, 0.0, 0.0)
	_set_translate_key(baseline_landing, DEATH_REBOUND_TIME, 7.0, 11.0)
	_set_translate_key(baseline_landing, DEATH_DAMP_TIME, 1.5, 2.5)
	if not super._validate_rig(baseline, atlas_data):
		return false

	var die: Dictionary = skeleton["animations"]["die"]
	var root_translate: Array = die["bones"][BONE_RIG]["translate"]
	var root_rotate: Array = die["bones"][BONE_RIG]["rotate"]
	if not _near_axis(root_translate, DEATH_PRE_SWAP_TIME, "x", DEATH_V3_PRE_SWAP_ROOT_X):
		return _set_error("V3 death pre-swap x lost its contact alignment")
	if not _near_axis(root_translate, DEATH_PRE_SWAP_TIME, "y", DEATH_V3_PRE_SWAP_ROOT_Y):
		return _set_error("V3 death pre-swap y lost its low grounded contraction")
	if not _near_value(root_rotate, DEATH_PRE_SWAP_TIME, DEATH_V3_PRE_SWAP_ROTATION):
		return _set_error("V3 death pre-swap tilt changed")
	var landing: Array = die["bones"][BONE_DEATH]["translate"]
	for contract: Array in [
		[DEATH_SWAP_TIME, 0.0, 0.0],
		[DEATH_CONTACT_TIME, DEATH_V3_IMPACT_X, DEATH_V3_IMPACT_Y],
		[DEATH_REBOUND_TIME, DEATH_V3_REBOUND_X, DEATH_V3_REBOUND_Y],
		[DEATH_DAMP_TIME, DEATH_V3_DAMP_X, DEATH_V3_DAMP_Y],
		[DEATH_SETTLE_TIME, 0.0, 0.0],
		[float(ANIMATION_DURATIONS["die"]), 0.0, 0.0],
	]:
		if (
			not _near_axis(landing, float(contract[0]), "x", float(contract[1]))
			or not _near_axis(landing, float(contract[0]), "y", float(contract[2]))
		):
			return _set_error("V3 death landing contract changed at %.7f" % float(contract[0]))
	return true


func _near_axis(keys: Array, time: float, axis: String, expected: float) -> bool:
	var value = _timeline_axis_value_at_time(keys, time, axis)
	return value != null and absf(float(value) - expected) <= 0.00001


func _near_value(keys: Array, time: float, expected: float) -> bool:
	var value = _timeline_value_at_time(keys, time)
	return value != null and absf(float(value) - expected) <= 0.00001


func _validate_written(output_root: String) -> bool:
	var page := Image.load_from_file(output_root.path_join(OUTPUT_PAGE))
	if page == null or page.is_empty() or page.get_size() != ATLAS_SIZE or page.get_format() != Image.FORMAT_RGBA8:
		return _set_error("Written V3 neutral/VFX atlas is not 3072x2304 RGBA8")
	var death_page := Image.load_from_file(output_root.path_join(OUTPUT_DEATH_PAGE))
	if (
		death_page == null or death_page.is_empty()
		or death_page.get_size() != DEATH_ATLAS_SIZE
		or death_page.get_format() != Image.FORMAT_RGBA8
	):
		return _set_error("Written V3 death atlas is not 2048x1536 RGBA8")
	var decoded = JSON.parse_string(FileAccess.get_file_as_string(output_root.path_join(OUTPUT_JSON)))
	var atlas_decoded = JSON.parse_string(FileAccess.get_file_as_string(output_root.path_join(OUTPUT_ATLAS)))
	if not decoded is Dictionary or not atlas_decoded is Dictionary:
		return _set_error("Written V3 death candidate JSON is unreadable")
	if not _validate_rig(decoded, str(atlas_decoded.get("atlas_data", ""))):
		return false
	var tres := FileAccess.get_file_as_string(output_root.path_join(OUTPUT_DATA))
	for required: String in [
		"%s/vivhite_combat.spatlas" % DEATH_V3_RESOURCE_ROOT,
		"%s/vivhite_combat.spjson" % DEATH_V3_RESOURCE_ROOT,
	]:
		if not tres.contains(required):
			return _set_error("Written V3 skeleton-data wrapper is missing %s" % required)
	return true


func _validate_candidate_isolation(output_root: String) -> bool:
	var files := PackedStringArray()
	for file_name: String in DirAccess.get_files_at(output_root):
		if file_name.ends_with(".uid") or file_name.ends_with(".import"):
			continue
		files.append(file_name)
	var expected := PackedStringArray([OUTPUT_JSON, OUTPUT_ATLAS, OUTPUT_PAGE, OUTPUT_DEATH_PAGE, OUTPUT_DATA])
	files.sort()
	expected.sort()
	if files != expected:
		return _set_error("V3 death output must be one self-contained five-file directory; got %s" % files)
	for text_name: String in [OUTPUT_JSON, OUTPUT_ATLAS, OUTPUT_DATA]:
		var text := FileAccess.get_file_as_string(output_root.path_join(text_name))
		if text.contains("res://Vivhite/skins/ironclad/spine/combat"):
			return _set_error("V3 death candidate leaked a runtime combat path in %s" % text_name)
	var wrapper = JSON.parse_string(FileAccess.get_file_as_string(output_root.path_join(OUTPUT_ATLAS)))
	var source_path := str(wrapper.get("source_path", "")) if wrapper is Dictionary else ""
	if _inside_parent_build:
		if source_path not in [
			"%s/vivhite_combat.atlas" % CANDIDATE_RESOURCE_ROOT,
			"%s/vivhite_combat.atlas" % DEATH_V3_RESOURCE_ROOT,
		]:
			return _set_error("V3 death interim atlas wrapper points outside known candidate roots")
	elif source_path != "%s/vivhite_combat.atlas" % DEATH_V3_RESOURCE_ROOT:
		return _set_error("V3 death atlas wrapper is not candidate-local")
	return true
