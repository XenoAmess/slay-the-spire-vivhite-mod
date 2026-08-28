extends SceneTree

## Assemble the already accepted V3 milestones into one isolated five-page
## candidate. No source pixels are changed: each accepted semantic page is
## copied byte-for-byte. The reviewed donor deltas are merged into the
## cast-set Spine JSON, followed by the one proven NIroncladVfx bridge delta:
## clear stale external EyeFire when cast is restarted from its active window.

const COMMAND := "assemble-hybrid-v3-final"
const OUTPUT_ROOT := "Vivhite/tools/candidates/hybrid_v3_final"
const OUTPUT_RESOURCE_ROOT := "res://tools/candidates/hybrid_v3_final"
const CAST_ROOT := "Vivhite/tools/candidates/hybrid_cast_set"
const NEUTRAL_ROOT := "Vivhite/tools/candidates/hybrid_neutral_v3"
const HURT_ROOT := "Vivhite/tools/candidates/hybrid_hurt_neutral"
const DEATH_ROOT := "Vivhite/tools/candidates/hybrid_death_v3"
const ATTACK_ROOT := "Vivhite/tools/candidates/hybrid_attack_peak"
const HEAVY_ROOT := "Vivhite/tools/candidates/hybrid_action_set"

const JSON_FILE := "vivhite_combat.spjson"
const ATLAS_FILE := "vivhite_combat.spatlas"
const DATA_FILE := "vivhite_combat_skeleton_data.tres"
const PAGE_FILES: Array[String] = [
	"vivhite_combat.png",
	"vivhite_combat_death.png",
	"vivhite_combat_attack.png",
	"vivhite_combat_attack_heavy.png",
	"vivhite_combat_cast.png",
]
const AUTHORED_FILES: Array[String] = [
	JSON_FILE,
	ATLAS_FILE,
	DATA_FILE,
	"vivhite_combat.png",
	"vivhite_combat_death.png",
	"vivhite_combat_attack.png",
	"vivhite_combat_attack_heavy.png",
	"vivhite_combat_cast.png",
]
const REQUIRED_ANIMATIONS: Array[String] = [
	"idle_loop",
	"low_health_loop",
	"relaxed_loop",
	"attack",
	"attack_heavy",
	"cast",
	"hurt",
	"die",
]
const LOOP_ANIMATIONS: Array[String] = [
	"idle_loop",
	"low_health_loop",
	"relaxed_loop",
]
const ALL_ATTACHMENT_SLOTS: Array[String] = [
	"vivhite_body",
	"vivhite_action_pose",
	"vivhite_death_body",
	"slash_mesh",
	"vivhite_magic_sigil",
	"eye_attach_slot",
]
const SOURCE_HASHES := {
	"cast": "vivhite-hybrid-v3-cast-set-v1",
	"neutral": "vivhite-hybrid-v3-neutral-reset-v1",
	"hurt": "vivhite-hybrid-v3-hurt-neutral-v1",
	"death": "vivhite-hybrid-death-v3-grounded-atomic-v1",
}
const EXPECTED_SOURCE_SHA256 := {
	"cast/vivhite_combat.spjson": "0c8495f40fd8893da9f85c495fdabc49d1a94b29bb0d9633a116986b74cad1bc",
	"neutral/vivhite_combat.spjson": "333db68127dc48971127cc0f541bec48182a51ec868c8e32cd136dcc48734f3f",
	"hurt/vivhite_combat.spjson": "cd806668ec87784fc37c7264a4d28475f7b51b1440c4e3866f5cdc45ad8921f5",
	"death/vivhite_combat.spjson": "9dbc2bd2e582a309c625796714164ff9267e31342b40ce2092031d13abbe6ed5",
	"cast/vivhite_combat.spatlas": "6dc3426c7043b65bbb3e16a85dd31b4fcf66c66a114ecb46938e0267ae24b3ab",
	"cast/vivhite_combat_skeleton_data.tres": "fe503468225442498ab1644353023dad41ce7c0525eb0d00115b70a3c0c25507",
}
const EXPECTED_PAGE_SIZE := {
	"vivhite_combat.png": Vector2i(3072, 2304),
	"vivhite_combat_death.png": Vector2i(2048, 1536),
	"vivhite_combat_attack.png": Vector2i(2048, 2304),
	"vivhite_combat_attack_heavy.png": Vector2i(2048, 2304),
	"vivhite_combat_cast.png": Vector2i(2048, 2304),
}
const EXPECTED_PAGE_SHA256 := {
	"vivhite_combat.png": "fabdb49900d01af55ef8ff193824149a504019630e1f39afe692481ae52f6f5b",
	"vivhite_combat_death.png": "7c89552c69bb50eb94a3d5a10d4ca408a0546156ed72aa7a289f1cf25a9af33d",
	"vivhite_combat_attack.png": "17bfee690fbc7401487cba0d4e14ba311cdee8b9a03f1ada9144fbf4c7114dfb",
	"vivhite_combat_attack_heavy.png": "e245f4a17d506e97cd34abd19f55b6c8b884832d01396ecaa837beaf0a07720e",
	"vivhite_combat_cast.png": "65458604f022f0fd98d64737d130f7fc89e621032bf0677d24ccddef108b2b5e",
}

var _last_error := ""


func _initialize() -> void:
	call_deferred("_run")


func _run() -> void:
	var args := OS.get_cmdline_user_args()
	if args.is_empty():
		args = PackedStringArray([COMMAND])
	if args[0] in ["-h", "--help", "help"]:
		_print_help()
		quit(0)
		return
	if args[0] not in [COMMAND, "build-final"]:
		quit(_fail("Unknown command: %s" % args[0]))
		return
	var options := _parse_options(args)
	if options.is_empty() and args.size() > 1:
		quit(2)
		return
	var output_root := _absolute_path(str(options.get("output-root", OUTPUT_ROOT)))
	if not _build(output_root):
		quit(_fail(_last_error))
		return
	quit(0)


func _print_help() -> void:
	print("Build the isolated Vivhite Hybrid V3 final candidate:")
	print("  godot --headless --path tools/art --script res://candidates/hybrid_v3_final/build_hybrid_v3_final_candidate.gd -- assemble-hybrid-v3-final")
	print("    [--output-root PATH]")


func _parse_options(args: PackedStringArray) -> Dictionary:
	var result := {}
	var index := 1
	while index < args.size():
		var token := str(args[index])
		if not token.begins_with("--") or index + 1 >= args.size():
			_set_error("Expected --name value, got: %s" % token)
			return {}
		var name := token.trim_prefix("--")
		if name != "output-root":
			_set_error("Unknown option: %s" % token)
			return {}
		result[name] = args[index + 1]
		index += 2
	return result


func _build(output_root: String) -> bool:
	_last_error = ""
	var roots := {
		"cast": _absolute_path(CAST_ROOT),
		"neutral": _absolute_path(NEUTRAL_ROOT),
		"hurt": _absolute_path(HURT_ROOT),
		"death": _absolute_path(DEATH_ROOT),
		"attack": _absolute_path(ATTACK_ROOT),
		"heavy": _absolute_path(HEAVY_ROOT),
	}
	var source_files := _source_file_map(roots)
	var before := _snapshot_hashes(source_files)
	if before.is_empty():
		return false
	for label: String in EXPECTED_SOURCE_SHA256:
		if str(before.get(label, "")).to_lower() != str(EXPECTED_SOURCE_SHA256[label]):
			return _set_error("Accepted source milestone hash changed: %s" % label)

	var sources := {}
	for label: String in ["cast", "neutral", "hurt", "death"]:
		var decoded := _load_json(str(roots[label]).path_join(JSON_FILE), "%s Spine JSON" % label)
		if decoded.is_empty():
			return false
		sources[label] = decoded
	if not _validate_sources(sources, roots):
		return false

	var mkdir_error := DirAccess.make_dir_recursive_absolute(output_root)
	if mkdir_error != OK:
		return _set_error("Could not create final candidate directory (%s): %s" % [error_string(mkdir_error), output_root])
	if not _copy_frozen_bundle(roots, output_root):
		return false

	var skeleton: Dictionary = (sources.cast as Dictionary).duplicate(true)
	skeleton["skeleton"]["hash"] = "vivhite-hybrid-v3-final-v1"
	var animations: Dictionary = skeleton["animations"]
	for animation_name: String in LOOP_ANIMATIONS:
		animations[animation_name]["slots"] = (
			(sources.neutral as Dictionary)["animations"][animation_name]["slots"].duplicate(true)
		)
	animations["hurt"]["bones"] = (
		(sources.hurt as Dictionary)["animations"]["hurt"]["bones"].duplicate(true)
	)
	for bone_name: String in ["vivhite_rig", "vivhite_death_pose"]:
		animations["die"]["bones"][bone_name] = (
			(sources.death as Dictionary)["animations"]["die"]["bones"][bone_name].duplicate(true)
		)
	var cast_events: Array = animations["cast"].get("events", []).duplicate(true)
	cast_events.push_front({"time": 0.0, "name": "clear_vfx"})
	animations["cast"]["events"] = cast_events
	if not _validate_merged_skeleton(skeleton, sources):
		return false
	if not _write_text(
		output_root.path_join(JSON_FILE),
		JSON.stringify(skeleton, "", false) + "\n"
	):
		return false

	if not _rewrite_resource_paths(output_root):
		return false
	var after := _snapshot_hashes(source_files)
	if after.is_empty():
		return false
	if before != after:
		return _set_error("A frozen source candidate changed while the final bundle was assembled")
	if not _validate_written(output_root, roots):
		return false

	print("Built isolated Vivhite Hybrid V3 final candidate:")
	print("  structure/action/cast: %s" % CAST_ROOT)
	print("  neutral loop resets:   %s" % NEUTRAL_ROOT)
	print("  protective hurt:       %s" % HURT_ROOT)
	print("  grounded death:        %s" % DEATH_ROOT)
	print("  authored files: 8 (five atlas pages + Spine JSON/wrappers)")
	print("  output: %s" % output_root)
	return true


func _source_file_map(roots: Dictionary) -> Dictionary:
	var result := {}
	for file_name: String in AUTHORED_FILES:
		result["cast/%s" % file_name] = str(roots.cast).path_join(file_name)
	result["neutral/%s" % JSON_FILE] = str(roots.neutral).path_join(JSON_FILE)
	result["hurt/%s" % JSON_FILE] = str(roots.hurt).path_join(JSON_FILE)
	result["death/%s" % JSON_FILE] = str(roots.death).path_join(JSON_FILE)
	result["neutral/vivhite_combat.png"] = str(roots.neutral).path_join("vivhite_combat.png")
	result["death/vivhite_combat_death.png"] = str(roots.death).path_join("vivhite_combat_death.png")
	result["attack/vivhite_combat_attack.png"] = str(roots.attack).path_join("vivhite_combat_attack.png")
	result["heavy/vivhite_combat_attack_heavy.png"] = str(roots.heavy).path_join("vivhite_combat_attack_heavy.png")
	result["cast/vivhite_combat_cast.png"] = str(roots.cast).path_join("vivhite_combat_cast.png")
	return result


func _snapshot_hashes(files: Dictionary) -> Dictionary:
	var hashes := {}
	for label: String in files:
		var path := str(files[label])
		if not FileAccess.file_exists(path):
			_set_error("Required frozen source is missing: %s" % path)
			return {}
		var digest := FileAccess.get_sha256(path)
		if digest.is_empty():
			_set_error("Could not hash frozen source: %s" % path)
			return {}
		hashes[label] = digest
	return hashes


func _validate_sources(sources: Dictionary, roots: Dictionary) -> bool:
	for label: String in ["cast", "neutral", "hurt", "death"]:
		var skeleton: Dictionary = sources[label]
		if str(skeleton.get("skeleton", {}).get("spine", "")) != "4.2.43":
			return _set_error("%s source is not Spine 4.2.43" % label)
		if str(skeleton.get("skeleton", {}).get("hash", "")) != str(SOURCE_HASHES[label]):
			return _set_error("%s source hash marker is not the accepted milestone" % label)
		var animations: Dictionary = skeleton.get("animations", {})
		for animation_name: String in REQUIRED_ANIMATIONS:
			if not animations.has(animation_name):
				return _set_error("%s source is missing animation %s" % [label, animation_name])

	var cast: Dictionary = sources.cast
	var action_attachments: Dictionary = (
		cast.get("skins", [])[0].get("attachments", {}).get("vivhite_action_pose", {})
	)
	for required: String in [
		"vivhite_combat_attack_peak",
		"vivhite_combat_attack_heavy_peak",
		"vivhite_combat_cast_peak",
	]:
		if not action_attachments.has(required):
			return _set_error("Cast-set base is missing action attachment %s" % required)
	if action_attachments.size() != 3:
		return _set_error("Cast-set base must expose exactly three action attachments")

	var page_sources := _page_source_paths(roots)
	for page_name: String in PAGE_FILES:
		var page_path := str(page_sources[page_name])
		if FileAccess.get_sha256(page_path).to_lower() != str(EXPECTED_PAGE_SHA256[page_name]):
			return _set_error("Frozen semantic page hash changed: %s" % page_path)
		var image := Image.load_from_file(page_path)
		if (
			image == null
			or image.is_empty()
			or image.get_format() != Image.FORMAT_RGBA8
			or image.get_size() != EXPECTED_PAGE_SIZE[page_name]
		):
			return _set_error("Cast-set page is not the required RGBA8 size: %s" % page_path)
		for corner: Vector2i in [
			Vector2i.ZERO,
			Vector2i(image.get_width() - 1, 0),
			Vector2i(0, image.get_height() - 1),
			Vector2i(image.get_width() - 1, image.get_height() - 1),
		]:
			if image.get_pixelv(corner).a > 0.0:
				return _set_error("Cast-set page corner is not transparent: %s @ %s" % [page_path, corner])
	return true


func _validate_merged_skeleton(skeleton: Dictionary, sources: Dictionary) -> bool:
	if str(skeleton.get("skeleton", {}).get("hash", "")) != "vivhite-hybrid-v3-final-v1":
		return _set_error("Final skeleton hash marker was not written")
	if skeleton.get("bones", []).size() != 35 or skeleton.get("slots", []).size() != 6:
		return _set_error("Final skeleton must retain 35 bones and six slots")
	var animations: Dictionary = skeleton.get("animations", {})
	if animations.size() != REQUIRED_ANIMATIONS.size():
		return _set_error("Final skeleton must contain exactly eight animations")
	for animation_name: String in REQUIRED_ANIMATIONS:
		if not animations.has(animation_name):
			return _set_error("Final skeleton is missing animation %s" % animation_name)

	for animation_name: String in LOOP_ANIMATIONS:
		if animations[animation_name]["slots"] != (
			(sources.neutral as Dictionary)["animations"][animation_name]["slots"]
		):
			return _set_error("%s no longer matches the accepted six-slot boundary reset" % animation_name)
	if animations.hurt.get("bones", {}) != (sources.hurt as Dictionary)["animations"]["hurt"].get("bones", {}):
		return _set_error("Final hurt bone performance differs from the accepted protective hurt")
	for section: String in ["slots", "events"]:
		if animations.hurt.get(section, null) != (sources.cast as Dictionary)["animations"]["hurt"].get(section, null):
			return _set_error("Final hurt/%s must remain identical to the cast-set base" % section)
		if animations.die.get(section, null) != (sources.cast as Dictionary)["animations"]["die"].get(section, null):
			return _set_error("Final die/%s must remain identical to the cast-set base" % section)
	for bone_name: String in ["vivhite_rig", "vivhite_death_pose"]:
		if animations.die["bones"].get(bone_name, null) != (sources.death as Dictionary)["animations"]["die"]["bones"].get(bone_name, null):
			return _set_error("Final die/%s differs from the accepted grounded death" % bone_name)
	for animation_name: String in ["attack", "attack_heavy"]:
		for section: String in ["bones", "deform", "drawOrder", "events"]:
			if animations[animation_name].get(section, null) != (
				(sources.cast as Dictionary)["animations"][animation_name].get(section, null)
			):
				return _set_error("Final %s/%s differs from the accepted cast-set base" % [animation_name, section])
	for section: String in ["bones", "deform", "drawOrder"]:
		if animations.cast.get(section, null) != (
			(sources.cast as Dictionary)["animations"]["cast"].get(section, null)
		):
			return _set_error("Final cast/%s differs from the accepted cast-set base" % section)
	var expected_cast_events: Array = (
		(sources.cast as Dictionary)["animations"]["cast"].get("events", []).duplicate(true)
	)
	expected_cast_events.push_front({"time": 0.0, "name": "clear_vfx"})
	if animations.cast.get("events", []) != expected_cast_events:
		return _set_error("Final cast/events must add only clear_vfx@0 before the accepted cast-set events")
	# Prove that the assembler changed no field outside the reviewed deltas.
	var normalized: Dictionary = skeleton.duplicate(true)
	normalized["skeleton"]["hash"] = (sources.cast as Dictionary)["skeleton"]["hash"]
	for animation_name: String in LOOP_ANIMATIONS:
		normalized["animations"][animation_name]["slots"] = (
			(sources.cast as Dictionary)["animations"][animation_name]["slots"].duplicate(true)
		)
	normalized["animations"]["hurt"]["bones"] = (
		(sources.cast as Dictionary)["animations"]["hurt"]["bones"].duplicate(true)
	)
	for bone_name: String in ["vivhite_rig", "vivhite_death_pose"]:
		normalized["animations"]["die"]["bones"][bone_name] = (
			(sources.cast as Dictionary)["animations"]["die"]["bones"][bone_name].duplicate(true)
		)
	normalized["animations"]["cast"]["events"] = (
		(sources.cast as Dictionary)["animations"]["cast"]["events"].duplicate(true)
	)
	if normalized != (sources.cast as Dictionary):
		return _set_error("Final skeleton contains a change outside the reviewed donor fields and cast restart clear")
	return true


func _copy_frozen_bundle(roots: Dictionary, output_root: String) -> bool:
	var source_paths := {
		JSON_FILE: str(roots.cast).path_join(JSON_FILE),
		ATLAS_FILE: str(roots.cast).path_join(ATLAS_FILE),
		DATA_FILE: str(roots.cast).path_join(DATA_FILE),
	}
	source_paths.merge(_page_source_paths(roots))
	for file_name: String in AUTHORED_FILES:
		var bytes := FileAccess.get_file_as_bytes(str(source_paths[file_name]))
		var output := FileAccess.open(output_root.path_join(file_name), FileAccess.WRITE)
		if output == null:
			return _set_error("Could not open final candidate output: %s" % output_root.path_join(file_name))
		output.store_buffer(bytes)
	return true


func _page_source_paths(roots: Dictionary) -> Dictionary:
	return {
		"vivhite_combat.png": str(roots.neutral).path_join("vivhite_combat.png"),
		"vivhite_combat_death.png": str(roots.death).path_join("vivhite_combat_death.png"),
		"vivhite_combat_attack.png": str(roots.attack).path_join("vivhite_combat_attack.png"),
		"vivhite_combat_attack_heavy.png": str(roots.heavy).path_join("vivhite_combat_attack_heavy.png"),
		"vivhite_combat_cast.png": str(roots.cast).path_join("vivhite_combat_cast.png"),
	}


func _rewrite_resource_paths(output_root: String) -> bool:
	var atlas_path := output_root.path_join(ATLAS_FILE)
	var atlas := _load_json(atlas_path, "copied atlas wrapper")
	if atlas.is_empty():
		return false
	atlas["source_path"] = OUTPUT_RESOURCE_ROOT + "/vivhite_combat.atlas"
	if not _write_text(atlas_path, JSON.stringify(atlas, "", false) + "\n"):
		return false

	var data_path := output_root.path_join(DATA_FILE)
	var data := FileAccess.get_file_as_string(data_path)
	var old_root := "res://tools/candidates/hybrid_cast_set"
	if not data.contains(old_root):
		return _set_error("Copied skeleton-data wrapper does not reference the cast-set root")
	data = data.replace(old_root, OUTPUT_RESOURCE_ROOT)
	return _write_text(data_path, data)


func _validate_written(output_root: String, roots: Dictionary) -> bool:
	var files := PackedStringArray()
	for file_name: String in DirAccess.get_files_at(output_root):
		if file_name.ends_with(".uid") or file_name.ends_with(".import"):
			continue
		files.append(file_name)
	var expected := PackedStringArray()
	for file_name: String in AUTHORED_FILES:
		expected.append(file_name)
	files.sort()
	expected.sort()
	if files != expected:
		return _set_error("Final candidate must contain exactly eight authored files; got %s" % files)
	var page_sources := _page_source_paths(roots)
	for page_name: String in PAGE_FILES:
		if FileAccess.get_sha256(output_root.path_join(page_name)) != FileAccess.get_sha256(
			str(page_sources[page_name])
		):
			return _set_error("Final page is not byte-identical to its accepted semantic donor: %s" % page_name)
	var atlas := _load_json(output_root.path_join(ATLAS_FILE), "final atlas wrapper")
	if atlas.is_empty():
		return false
	if str(atlas.get("source_path", "")) != OUTPUT_RESOURCE_ROOT + "/vivhite_combat.atlas":
		return _set_error("Final atlas wrapper is not candidate-local")
	var data := FileAccess.get_file_as_string(output_root.path_join(DATA_FILE))
	for required: String in [
		OUTPUT_RESOURCE_ROOT + "/vivhite_combat.spatlas",
		OUTPUT_RESOURCE_ROOT + "/vivhite_combat.spjson",
	]:
		if not data.contains(required):
			return _set_error("Final skeleton-data wrapper is missing %s" % required)
	for text_name: String in [JSON_FILE, ATLAS_FILE, DATA_FILE]:
		var content := FileAccess.get_file_as_string(output_root.path_join(text_name))
		if content.contains("res://Vivhite/skins/ironclad/spine/combat"):
			return _set_error("Final candidate leaked a formal runtime path in %s" % text_name)
		if content.contains("res://tools/candidates/hybrid_cast_set"):
			return _set_error("Final candidate leaked the cast-set resource root in %s" % text_name)
	return true


func _load_json(path: String, label: String) -> Dictionary:
	if not FileAccess.file_exists(path):
		_set_error("Missing %s: %s" % [label, path])
		return {}
	var decoded: Variant = JSON.parse_string(FileAccess.get_file_as_string(path))
	if not decoded is Dictionary:
		_set_error("Could not parse %s: %s" % [label, path])
		return {}
	return decoded


func _write_text(path: String, content: String) -> bool:
	var output := FileAccess.open(path, FileAccess.WRITE)
	if output == null:
		return _set_error("Could not write final candidate file: %s" % path)
	output.store_string(content)
	return true


func _absolute_path(path: String) -> String:
	if path.is_absolute_path():
		return path.simplify_path()
	var root := ProjectSettings.globalize_path("res://").path_join("../..").simplify_path()
	return root.path_join(path).simplify_path()


func _set_error(message: String) -> bool:
	_last_error = message
	push_error("[hybrid-v3-final] %s" % message)
	return false


func _fail(message: String) -> int:
	if not message.is_empty():
		printerr("[hybrid-v3-final] %s" % message)
	return 1
