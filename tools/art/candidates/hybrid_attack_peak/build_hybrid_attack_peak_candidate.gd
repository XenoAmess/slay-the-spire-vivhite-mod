extends "res://candidates/whole_mesh/build_whole_mesh_candidate.gd"

## V3 Hybrid proof: keep the proven weighted neutral body for every loop and
## atomically expose one independently generated rigid full-body attack pose
## only while the ordinary magic-ribbon hit is fully visible. This builder is
## isolated from the historical whole_mesh output and never writes live assets.

const HYBRID_OUTPUT_ROOT := "Vivhite/tools/candidates/hybrid_attack_peak"
const HYBRID_RESOURCE_ROOT := "res://tools/candidates/hybrid_attack_peak"
const DEFAULT_ATTACK_SOURCE := (
	"assets/vivhite-ironclad/custom/combat/sources/"
	+ "vivhite-combat-attack-peak-v1.png"
)

const OUTPUT_ATTACK_PAGE := "vivhite_combat_attack.png"
const ATTACK_ATLAS_SIZE := Vector2i(2048, 2304)
const ATTACK_REGION_NAME := "vivhite_combat_attack_peak"
const ATTACK_REGION_POS := Vector2i(16, 16)
const ATTACK_REGION_SIZE := BODY_REGION_SIZE
const ATTACK_WORLD_SIZE := Vector2(BODY_WORLD_RECT.size.x, BODY_WORLD_RECT.size.y)
const ATTACK_SETUP_CENTER := Vector2(
	BODY_WORLD_RECT.position.x + BODY_WORLD_RECT.size.x * 0.5,
	BODY_WORLD_RECT.position.y + BODY_WORLD_RECT.size.y * 0.5
)

const BONE_ACTION := "vivhite_action_pose_root"
const SLOT_ACTION := "vivhite_action_pose"
const ATTACK_POSE_ENTER_TIME := 0.08
# Source contract: NIroncladVfx keeps the slash fully visible until 0.23. End
# the rigid peak at 0.20 while that attention cue is still stable, and leave a
# 0.03-second cushion before its fade starts. SlashVfxSlot renders behind the
# character, so continuity must stand on its own; the ribbon is not a mask.
const ATTACK_POSE_EXIT_TIME := 0.20
const ATTACK_POSE_PRE_EXIT_TIME := 0.1999
# Measured against the hidden Vulkan composite, not the raw source canvas:
# attempt 0104's open palm lands about 59 screen pixels to the right and
# 8 pixels above the neutral-pose arc origin at the unchanged scene scale .28.
# Keep this pose-local correction atomic with the body attachment swap.
const ATTACK_ARC_PEAK_OFFSET := Vector2(210.0, 30.0)

var _attack_source_path := ""


func _initialize() -> void:
	var args := OS.get_cmdline_user_args()
	if args.is_empty():
		args = PackedStringArray([COMMAND])
	if args[0] in ["-h", "--help", "help"]:
		_print_hybrid_help()
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
	var output_root := _absolute_path(str(options.get("output-root", HYBRID_OUTPUT_ROOT)))
	if not _build(body_path, arc_path, sigil_path, output_root):
		quit(_fail(_last_error))
		return
	quit(0)


func _print_hybrid_help() -> void:
	print("Build the isolated Vivhite V3 hybrid attack-peak candidate:")
	print("  godot --headless --path tools/art --script res://candidates/hybrid_attack_peak/build_hybrid_attack_peak_candidate.gd -- build-combat")
	print("    [--body-source PATH] [--arc-source PATH] [--sigil-source PATH]")
	print("    [--death-source PATH] [--attack-source PATH] [--output-root PATH]")


func _build(body_path: String, arc_path: String, sigil_path: String, output_root: String) -> bool:
	_last_error = ""
	var inputs := [
		{"label": "combat body master", "path": body_path, "size": BODY_REGION_SIZE},
		{"label": "combat magic arc", "path": arc_path, "size": ARC_REGION_SIZE},
		{"label": "shared magic sigil", "path": sigil_path, "size": SIGIL_REGION_SIZE},
		{"label": "side-collapse death source", "path": _death_source_path, "size": DEATH_REGION_SIZE},
		{"label": "V3 attack-peak source", "path": _attack_source_path, "size": ATTACK_REGION_SIZE},
	]
	var decoded_images: Array[Image] = []
	for input: Dictionary in inputs:
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
		decoded_images.append(image)
	var prepared := []
	for index in inputs.size():
		var input: Dictionary = inputs[index]
		var region := (
			_prepare_registered_pose_region(decoded_images[index], decoded_images[0])
			if index in [0, 4]
			else _prepare_region(decoded_images[index], input["size"], str(input["label"]))
		)
		if region.is_empty():
			return false
		prepared.append(region)
	if (
		FileAccess.get_sha256(body_path) == FileAccess.get_sha256(_attack_source_path)
		and prepared[0]["image"].get_data() != prepared[4]["image"].get_data()
	):
		return _set_error("Identical neutral/action gray-box sources did not preserve byte-identical packed geometry")

	var page := _transparent_image(ATLAS_SIZE)
	page.blend_rect(prepared[0]["image"], Rect2i(Vector2i.ZERO, BODY_REGION_SIZE), BODY_REGION_POS)
	page.blend_rect(prepared[1]["image"], Rect2i(Vector2i.ZERO, ARC_REGION_SIZE), ARC_REGION_POS)
	page.blend_rect(prepared[2]["image"], Rect2i(Vector2i.ZERO, SIGIL_REGION_SIZE), SIGIL_REGION_POS)
	var death_page := _transparent_image(DEATH_ATLAS_SIZE)
	death_page.blend_rect(prepared[3]["image"], Rect2i(Vector2i.ZERO, DEATH_REGION_SIZE), DEATH_REGION_POS)
	var attack_page := _transparent_image(ATTACK_ATLAS_SIZE)
	attack_page.blend_rect(prepared[4]["image"], Rect2i(Vector2i.ZERO, ATTACK_REGION_SIZE), ATTACK_REGION_POS)

	var skeleton := _build_skeleton_json()
	var atlas_data := _build_atlas_data()
	if not _validate_rig(skeleton, atlas_data):
		return false
	if not _make_dir(output_root):
		return false
	for output: Dictionary in [
		{"name": OUTPUT_PAGE, "image": page},
		{"name": OUTPUT_DEATH_PAGE, "image": death_page},
		{"name": OUTPUT_ATTACK_PAGE, "image": attack_page},
	]:
		var output_path := output_root.path_join(str(output["name"]))
		var save_error: Error = output["image"].save_png(output_path)
		if save_error != OK:
			return _set_error("Could not save atlas (%s): %s" % [error_string(save_error), output_path])
	var skeleton_path := output_root.path_join(OUTPUT_JSON)
	if not _write_text(skeleton_path, JSON.stringify(skeleton, "  ", false) + "\n"):
		return false
	var atlas_wrapper := {
		"atlas_data": atlas_data,
		"normal_texture_prefix": "n",
		"source_path": "%s/vivhite_combat.atlas" % HYBRID_RESOURCE_ROOT,
		"specular_texture_prefix": "s",
	}
	if not _write_text(output_root.path_join(OUTPUT_ATLAS), JSON.stringify(atlas_wrapper, "", false) + "\n"):
		return false
	if not _write_text(output_root.path_join(OUTPUT_DATA), _build_skeleton_data_tres()):
		return false
	if not _validate_written(output_root):
		return false
	if not _validate_candidate_isolation(output_root):
		return false
	print("Built isolated Vivhite V3 hybrid attack-peak candidate:")
	print("  neutral: %s (weighted mesh, read-only)" % body_path)
	print("  attack:  %s (rigid region, read-only)" % _attack_source_path)
	print("  switch:  %.4f -> %.4f seconds; no RGBA crossfade" % [ATTACK_POSE_ENTER_TIME, ATTACK_POSE_EXIT_TIME])
	print("  canvas:  frozen neutral contract %s -> region %s -> world %s" % [
		prepared[4]["contract_rect"], ATTACK_REGION_SIZE, ATTACK_WORLD_SIZE,
	])
	print("  output:  %s" % output_root)
	return true


func _prepare_registered_pose_region(source: Image, neutral_reference: Image) -> Dictionary:
	# Neither neutral nor action gets Alpha-bbox normalization. Both preserve the
	# complete model-produced source canvas through one frozen transform. This
	# keeps pixel density and coordinates comparable, retains native soft Alpha,
	# and prevents a new pose from silently filling its atlas region by itself.
	if source.get_size() != neutral_reference.get_size():
		return _error_dictionary(
			"V3 action source canvas %s must match neutral master canvas %s"
			% [source.get_size(), neutral_reference.get_size()]
		)
	var contract_rect := Rect2i(Vector2i.ZERO, neutral_reference.get_size())
	var source_bounds := _alpha_bounds(source)
	if source_bounds.size.x <= 0 or source_bounds.size.y <= 0:
		return _error_dictionary("V3 registered pose source contains no non-zero Alpha pixels")
	var cropped := source.get_region(contract_rect)
	var available := ATTACK_REGION_SIZE - Vector2i(REGION_MARGIN * 2, REGION_MARGIN * 2)
	var factor := minf(1.0, minf(
		float(available.x) / float(contract_rect.size.x),
		float(available.y) / float(contract_rect.size.y)
	))
	var packed_size := Vector2i(
		maxi(1, int(round(contract_rect.size.x * factor))),
		maxi(1, int(round(contract_rect.size.y * factor)))
	)
	if cropped.get_size() != packed_size:
		cropped.resize(packed_size.x, packed_size.y, Image.INTERPOLATE_LANCZOS)
	var destination := Vector2i(
		(ATTACK_REGION_SIZE.x - packed_size.x) / 2,
		ATTACK_REGION_SIZE.y - REGION_MARGIN - packed_size.y
	)
	var region := _transparent_image(ATTACK_REGION_SIZE)
	region.blend_rect(cropped, Rect2i(Vector2i.ZERO, packed_size), destination)
	var packed_bounds := _alpha_bounds(region)
	if (
		packed_bounds.position.x < 1 or packed_bounds.position.y < 1
		or packed_bounds.end.x >= ATTACK_REGION_SIZE.x - 1
		or packed_bounds.end.y >= ATTACK_REGION_SIZE.y - 1
	):
		return _error_dictionary("Prepared V3 attack pose touches its atlas-region edge: %s" % packed_bounds)
	return {
		"image": region,
		"source_bounds": source_bounds,
		"contract_rect": contract_rect,
		"packed_size": packed_size,
	}


func _build_atlas_data() -> String:
	return super._build_atlas_data() + "\n" + "\n".join(PackedStringArray([
		OUTPUT_ATTACK_PAGE,
		"size:%d,%d" % [ATTACK_ATLAS_SIZE.x, ATTACK_ATLAS_SIZE.y],
		"filter:Linear,Linear",
		"pma:false",
		"repeat:none",
		ATTACK_REGION_NAME,
		"bounds:%d,%d,%d,%d" % [ATTACK_REGION_POS.x, ATTACK_REGION_POS.y, ATTACK_REGION_SIZE.x, ATTACK_REGION_SIZE.y],
	])) + "\n"


func _build_skeleton_json() -> Dictionary:
	var skeleton := super._build_skeleton_json()
	skeleton["skeleton"]["hash"] = "vivhite-hybrid-v3-attack-peak-v1"
	skeleton["slots"].insert(2, {"name": SLOT_ACTION, "bone": BONE_ACTION})
	skeleton["skins"][0]["attachments"][SLOT_ACTION] = {
		ATTACK_REGION_NAME: _region_attachment(ATTACK_REGION_NAME, ATTACK_WORLD_SIZE.x, ATTACK_WORLD_SIZE.y),
	}
	return skeleton


func _build_bones() -> Array:
	var bones := super._build_bones()
	for bone: Dictionary in bones:
		var name := str(bone["name"])
		if name == BONE_ARC:
			bone["parent"] = BONE_RIG
			var anchor := _scaled_character_anchor(Vector2(840.0, 1750.0))
			bone["x"] = anchor.x
			bone["y"] = anchor.y
			bone["rotation"] = -5.0
		elif name == BONE_EYES:
			bone["parent"] = BONE_RIG
			var anchor := _scaled_character_anchor(Vector2(20.0, 1555.0))
			bone["x"] = anchor.x
			bone["y"] = anchor.y
	bones.append({
		"name": BONE_ACTION,
		"parent": BONE_RIG,
		"x": ATTACK_SETUP_CENTER.x,
		"y": ATTACK_SETUP_CENTER.y,
	})
	return bones


func _build_animations() -> Dictionary:
	var animations := super._build_animations()
	for animation_name: String in animations:
		var animation: Dictionary = animations[animation_name]
		var slots: Dictionary = animation.get("slots", {})
		slots[SLOT_ACTION] = {"attachment": [{"time": 0.0, "name": null}]}
		animation["slots"] = slots
	var relaxed: Dictionary = animations["relaxed_loop"]
	var relaxed_duration := float(ANIMATION_DURATIONS["relaxed_loop"])
	relaxed["slots"]["vivhite_body"] = {"attachment": [
		{"time": 0.0, "name": BODY_REGION_NAME},
		{"time": relaxed_duration, "name": BODY_REGION_NAME},
	]}
	relaxed["slots"][SLOT_ACTION] = {"attachment": [
		{"time": 0.0, "name": null},
		{"time": relaxed_duration, "name": null},
	]}
	relaxed["slots"][SLOT_DEATH] = {"attachment": [
		{"time": 0.0, "name": null},
		{"time": relaxed_duration, "name": null},
	]}
	var attack: Dictionary = animations["attack"]
	attack["slots"]["vivhite_body"] = {"attachment": [
		{"time": 0.0, "name": BODY_REGION_NAME},
		{"time": ATTACK_POSE_ENTER_TIME, "name": null},
		{"time": ATTACK_POSE_EXIT_TIME, "name": BODY_REGION_NAME},
	]}
	attack["slots"][SLOT_ACTION] = {"attachment": [
		{"time": 0.0, "name": null},
		{"time": ATTACK_POSE_ENTER_TIME, "name": ATTACK_REGION_NAME},
		{"time": ATTACK_POSE_EXIT_TIME, "name": null},
	]}
	# The attack image and its runtime VFX anchors change on the same authored
	# boundaries. EyeFire is not emitted by attack, so its neutral offset remains
	# zero; the arc receives the measured open-palm correction.
	var duration := float(ANIMATION_DURATIONS["attack"])
	attack["bones"][BONE_ARC]["translate"] = _anchor_contract(duration, ATTACK_ARC_PEAK_OFFSET)
	attack["bones"][BONE_EYES] = {"translate": _anchor_contract(duration, Vector2.ZERO)}
	attack["bones"][BONE_ACTION] = {
		"rotate": [
			{"time": 0.0, "value": 0.0},
			{"time": ATTACK_POSE_ENTER_TIME, "value": 0.0},
			{"time": 0.15, "value": 2.0},
			{"time": ATTACK_POSE_PRE_EXIT_TIME, "value": -1.5},
			{"time": ATTACK_POSE_EXIT_TIME, "value": 0.0},
			{"time": duration, "value": 0.0},
		],
	}
	return animations


func _anchor_contract(duration: float, peak_offset: Vector2) -> Array:
	return [
		{"time": 0.0, "x": 0.0, "y": 0.0},
		{"time": ATTACK_POSE_ENTER_TIME, "x": peak_offset.x, "y": peak_offset.y},
		{"time": ATTACK_POSE_PRE_EXIT_TIME, "x": peak_offset.x, "y": peak_offset.y},
		{"time": ATTACK_POSE_EXIT_TIME, "x": 0.0, "y": 0.0},
		{"time": duration, "x": 0.0, "y": 0.0},
	]


func _build_skeleton_data_tres() -> String:
	return super._build_skeleton_data_tres().replace(CANDIDATE_RESOURCE_ROOT, HYBRID_RESOURCE_ROOT)


func _validate_rig(skeleton: Dictionary, atlas_data: String) -> bool:
	# The whole-mesh validator intentionally forbids non-death body switches.
	# Validate an exact deep copy with only the new attack body timeline removed,
	# then validate the Hybrid contract against the untouched source structure.
	var baseline: Dictionary = skeleton.duplicate(true)
	baseline["animations"]["attack"]["slots"].erase("vivhite_body")
	baseline["animations"]["relaxed_loop"]["slots"].erase("vivhite_body")
	baseline["animations"]["relaxed_loop"]["slots"].erase(SLOT_DEATH)
	if not super._validate_rig(baseline, atlas_data):
		return false
	var bone_parents := {}
	for bone: Dictionary in skeleton["bones"]:
		bone_parents[str(bone["name"])] = str(bone.get("parent", ""))
	if str(bone_parents.get(BONE_ACTION, "<missing>")) != BONE_RIG:
		return _set_error("Hybrid attack-pose bone must be a direct child of vivhite_rig")
	for anchor_bone: String in [BONE_ARC, BONE_EYES]:
		if str(bone_parents.get(anchor_bone, "<missing>")) != BONE_RIG:
			return _set_error("Hybrid VFX anchor must follow vivhite_rig: %s" % anchor_bone)
	var slot_bones := {}
	for slot: Dictionary in skeleton["slots"]:
		slot_bones[str(slot["name"])] = str(slot["bone"])
	if str(slot_bones.get(SLOT_ACTION, "<missing>")) != BONE_ACTION:
		return _set_error("Hybrid action slot must be bound to the attack-pose bone")
	var action_attachments: Dictionary = skeleton["skins"][0]["attachments"].get(SLOT_ACTION, {})
	if action_attachments.size() != 1 or not action_attachments.has(ATTACK_REGION_NAME):
		return _set_error("Hybrid candidate must contain exactly one attack-peak attachment")
	if str(action_attachments[ATTACK_REGION_NAME].get("type", "region")) != "region":
		return _set_error("Attack-peak attachment must remain one rigid region")
	if atlas_data.count("%s\n" % OUTPUT_ATTACK_PAGE) != 1:
		return _set_error("Attack atlas page must be declared exactly once")
	if atlas_data.count("%s\n" % ATTACK_REGION_NAME) != 1:
		return _set_error("Attack atlas region must be declared exactly once")
	return _validate_attack_attachment_swap(skeleton)


func _validate_attack_attachment_swap(skeleton: Dictionary) -> bool:
	for animation_name: String in ANIMATION_DURATIONS:
		var slots: Dictionary = skeleton["animations"][animation_name].get("slots", {})
		if not slots.has(SLOT_ACTION):
			return _set_error("Every Hybrid animation must explicitly reset the action slot: %s" % animation_name)
		var action_keys: Array = slots[SLOT_ACTION].get("attachment", [])
		if animation_name == "relaxed_loop":
			var duration := float(ANIMATION_DURATIONS["relaxed_loop"])
			var body_keys: Array = slots.get("vivhite_body", {}).get("attachment", [])
			var death_keys: Array = slots.get(SLOT_DEATH, {}).get("attachment", [])
			if action_keys.size() != 2 or body_keys.size() != 2 or death_keys.size() != 2:
				return _set_error("relaxed_loop must reassert neutral/action/death visibility at both cycle boundaries")
			for index in 2:
				var expected_time := 0.0 if index == 0 else duration
				if (
					absf(float(action_keys[index].get("time", -1.0)) - expected_time) > 0.00001
					or action_keys[index].get("name", "sentinel") != null
					or absf(float(body_keys[index].get("time", -1.0)) - expected_time) > 0.00001
					or str(body_keys[index].get("name", "")) != BODY_REGION_NAME
					or absf(float(death_keys[index].get("time", -1.0)) - expected_time) > 0.00001
					or death_keys[index].get("name", "sentinel") != null
				):
					return _set_error("relaxed_loop boundary must show only the neutral body")
			continue
		if animation_name != "attack":
			if (
				action_keys.size() != 1
				or absf(float(action_keys[0].get("time", -1.0))) > 0.00001
				or action_keys[0].get("name", "sentinel") != null
			):
				return _set_error("Only attack may expose the action attachment: %s" % animation_name)
			continue
		var body_keys: Array = slots.get("vivhite_body", {}).get("attachment", [])
		if body_keys.size() != 3 or action_keys.size() != 3:
			return _set_error("attack must use exactly three atomic attachment keys per body slot")
		var expected_times := [0.0, ATTACK_POSE_ENTER_TIME, ATTACK_POSE_EXIT_TIME]
		var expected_body_names := [BODY_REGION_NAME, null, BODY_REGION_NAME]
		var expected_action_names := [null, ATTACK_REGION_NAME, null]
		for index in 3:
			if (
				absf(float(body_keys[index].get("time", -1.0)) - float(expected_times[index])) > 0.00001
				or absf(float(action_keys[index].get("time", -1.0)) - float(expected_times[index])) > 0.00001
				or body_keys[index].get("name", "sentinel") != expected_body_names[index]
				or action_keys[index].get("name", "sentinel") != expected_action_names[index]
			):
				return _set_error("attack neutral/action slots must switch atomically with one visible body")
		if slots["vivhite_body"].has("rgba") or slots[SLOT_ACTION].has("rgba"):
			return _set_error("Hybrid full-body swap must not use RGBA crossfades")
	var attack: Dictionary = skeleton["animations"]["attack"]
	if not _validate_event_time(attack, "attack_slash_start", ATTACK_POSE_ENTER_TIME):
		return false
	for anchor_bone: String in [BONE_ARC, BONE_EYES]:
		var keys: Array = attack.get("bones", {}).get(anchor_bone, {}).get("translate", [])
		for required_time: float in [ATTACK_POSE_ENTER_TIME, ATTACK_POSE_PRE_EXIT_TIME, ATTACK_POSE_EXIT_TIME]:
			if _timeline_axis_value_at_time(keys, required_time, "x") == null:
				return _set_error("Hybrid anchor %s is missing %.4f contract key" % [anchor_bone, required_time])
	return true


func _validate_written(output_root: String) -> bool:
	for output: Dictionary in [
		{"name": OUTPUT_PAGE, "size": ATLAS_SIZE},
		{"name": OUTPUT_DEATH_PAGE, "size": DEATH_ATLAS_SIZE},
		{"name": OUTPUT_ATTACK_PAGE, "size": ATTACK_ATLAS_SIZE},
	]:
		var image := Image.load_from_file(output_root.path_join(str(output["name"])))
		if (
			image == null or image.is_empty()
			or image.get_size() != output["size"]
			or image.get_format() != Image.FORMAT_RGBA8
		):
			return _set_error("Written Hybrid atlas page is invalid: %s" % output["name"])
	var decoded = JSON.parse_string(FileAccess.get_file_as_string(output_root.path_join(OUTPUT_JSON)))
	if not decoded is Dictionary:
		return _set_error("Written Hybrid Spine JSON could not be parsed")
	var atlas_decoded = JSON.parse_string(FileAccess.get_file_as_string(output_root.path_join(OUTPUT_ATLAS)))
	if not atlas_decoded is Dictionary:
		return _set_error("Written Hybrid atlas wrapper could not be parsed")
	if not _validate_rig(decoded, str(atlas_decoded.get("atlas_data", ""))):
		return false
	var tres := FileAccess.get_file_as_string(output_root.path_join(OUTPUT_DATA))
	for required: String in [
		"%s/vivhite_combat.spatlas" % HYBRID_RESOURCE_ROOT,
		"%s/vivhite_combat.spjson" % HYBRID_RESOURCE_ROOT,
	]:
		if not tres.contains(required):
			return _set_error("Written Hybrid skeleton-data wrapper is missing %s" % required)
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
	files.sort()
	expected.sort()
	if files != expected:
		return _set_error("Hybrid output must be one self-contained six-file directory; got %s" % files)
	for text_name: String in [OUTPUT_JSON, OUTPUT_ATLAS, OUTPUT_DATA]:
		var text := FileAccess.get_file_as_string(output_root.path_join(text_name))
		if text.contains("res://Vivhite/skins/ironclad/spine/combat"):
			return _set_error("Hybrid candidate leaked a runtime combat path in %s" % text_name)
	var wrapper = JSON.parse_string(FileAccess.get_file_as_string(output_root.path_join(OUTPUT_ATLAS)))
	if str(wrapper.get("source_path", "")) != "%s/vivhite_combat.atlas" % HYBRID_RESOURCE_ROOT:
		return _set_error("Hybrid atlas wrapper is not candidate-local")
	return true
