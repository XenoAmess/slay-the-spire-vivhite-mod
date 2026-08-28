extends "../../compare/preview/render_combat_rig_compare.gd"

## Single-animation, exact-time Windows/Vulkan sampler for the assembled V3
## candidate. Each invocation renders one of the eight production animations.
## The default time profiles are copied from the already accepted neutral,
## attack, heavy, cast, hurt and death samplers; --times permits a focused
## comma-separated probe without changing the candidate or its pixels.

const DATA_PATH := "res://tools/candidates/hybrid_v3_final/vivhite_combat_skeleton_data.tres"
const JSON_PATH := "res://tools/candidates/hybrid_v3_final/vivhite_combat.spjson"
const ATLAS_PATH := "res://tools/candidates/hybrid_v3_final/vivhite_combat.spatlas"
const DEFAULT_EXACT_OUTPUT := ".work/combat-rig-compare-preview/hybrid-v3-final-exact"
const EPSILON := 0.00002
const PRE_ROLL := 0.50

const BODY_SLOT := "vivhite_body"
const BODY_ATTACHMENT := "vivhite_combat_body"
const ACTION_SLOT := "vivhite_action_pose"
const DEATH_SLOT := "vivhite_death_body"
const DEATH_ATTACHMENT := "vivhite_combat_death_side"
const SLASH_SLOT := "slash_mesh"
const SLASH_ATTACHMENT := "vivhite_combat_magic_arc"
const SIGIL_SLOT := "vivhite_magic_sigil"
const SIGIL_ATTACHMENT := "vivhite_combat_magic_sigil"
const EYE_SLOT := "eye_attach_slot"

const ATTACK_ATTACHMENT := "vivhite_combat_attack_peak"
const HEAVY_ATTACHMENT := "vivhite_combat_attack_heavy_peak"
const CAST_ATTACHMENT := "vivhite_combat_cast_peak"

const CHARACTER_SLOTS: Array[String] = [BODY_SLOT, ACTION_SLOT, DEATH_SLOT]
const VFX_SLOTS: Array[String] = [SLASH_SLOT, SIGIL_SLOT, EYE_SLOT]
const ALL_SLOTS: Array[String] = [
	BODY_SLOT,
	ACTION_SLOT,
	DEATH_SLOT,
	SLASH_SLOT,
	SIGIL_SLOT,
	EYE_SLOT,
]
const SUPPORTED_ANIMATIONS: Array[String] = [
	"idle_loop",
	"low_health_loop",
	"relaxed_loop",
	"attack",
	"attack_heavy",
	"cast",
	"hurt",
	"die",
]


func _initialize() -> void:
	if DisplayServer.get_name() != "headless":
		DisplayServer.window_set_flag(DisplayServer.WINDOW_FLAG_NO_FOCUS, true)
		DisplayServer.window_set_position(Vector2i(-32000, -32000))
	call_deferred("_run_final_exact")


func _run_final_exact() -> void:
	var options := _parse_final_args()
	if options.is_empty():
		quit(2)
		return
	_output_root = _safe_output_root(str(options["output"]))
	if _output_root.is_empty():
		quit(2)
		return
	_canvas = Vector2i(int(options["width"]), int(options["height"]))
	_scene_scale = float(options["scene-scale"])
	_origin = Vector2(float(options["origin-x"]), float(options["origin-y"]))
	_scene_offset = Vector2(float(options["scene-offset-x"]), float(options["scene-offset-y"]))
	DirAccess.make_dir_recursive_absolute(_output_root)

	var animation_name := str(options["animation"])
	var requested_times := _parse_requested_times(str(options["times"]), animation_name)
	var report := _base_final_report(options, animation_name, requested_times)
	if requested_times.is_empty():
		report["errors"] = _errors.duplicate()
		_write_json(_output_root.path_join("summary.json"), report)
		quit(2)
		return
	if not _prepare_final_runtime(str(options["pck"])):
		report["errors"] = _errors.duplicate()
		_write_json(_output_root.path_join("summary.json"), report)
		quit(2)
		return

	var skeleton_data: Resource = ResourceLoader.load(DATA_PATH)
	if skeleton_data == null or not skeleton_data.is_class("SpineSkeletonDataResource"):
		_fail("Could not load assembled V3 final SpineSkeletonDataResource %s." % DATA_PATH)
		report["errors"] = _errors.duplicate()
		_write_json(_output_root.path_join("summary.json"), report)
		quit(2)
		return
	var animation: Object = skeleton_data.call("find_animation", animation_name)
	if animation == null:
		_fail("Final candidate is missing animation '%s'." % animation_name)
		report["errors"] = _errors.duplicate()
		_write_json(_output_root.path_join("summary.json"), report)
		quit(2)
		return
	var duration := float(animation.call("get_duration"))
	report["animation_duration"] = duration
	for sample_time: float in requested_times:
		if sample_time < 0.0 or sample_time > duration + EPSILON:
			_fail(
				"Requested %s time %.7f is outside [0, %.7f]."
				% [animation_name, sample_time, duration]
			)
	if not _errors.is_empty():
		report["errors"] = _errors.duplicate()
		_write_json(_output_root.path_join("summary.json"), report)
		quit(2)
		return

	var viewport := SubViewport.new()
	viewport.name = "VivhiteHybridV3FinalExactViewport"
	viewport.size = _canvas
	viewport.transparent_bg = true
	viewport.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	viewport.render_target_clear_mode = SubViewport.CLEAR_MODE_ALWAYS
	root.add_child(viewport)
	var stage := Node2D.new()
	viewport.add_child(stage)

	var composite_images: Array[Image] = []
	var composite_validity: Array[bool] = []
	var character_images: Array[Image] = []
	var character_validity: Array[bool] = []
	for index in requested_times.size():
		var captured := await _capture_final_sample(
			stage,
			viewport,
			skeleton_data,
			animation_name,
			requested_times[index],
			index,
		)
		if captured.is_empty():
			continue
		var frame_report: Dictionary = captured["report"]
		(report["frames"] as Array).append(frame_report)
		composite_images.append(captured["composite_image"] as Image)
		composite_validity.append(bool(frame_report["composite"]["passed"]))
		character_images.append(captured["character_image"] as Image)
		character_validity.append(bool(frame_report["character_only"]["passed"]))

	var composite_sheet_path := _output_root.path_join(
		"contact-sheets/%s-exact-composite.png" % _safe_component(animation_name)
	)
	var character_sheet_path := _output_root.path_join(
		"contact-sheets/%s-exact-character-only.png" % _safe_component(animation_name)
	)
	var columns := mini(8, requested_times.size())
	var composite_sheet_ok := _write_contact_sheet(
		composite_images, composite_validity, composite_sheet_path, columns
	)
	var character_sheet_ok := _write_contact_sheet(
		character_images, character_validity, character_sheet_path, columns
	)
	report["contact_sheets"] = {
		"character_only": _relative_to_output(character_sheet_path) if character_sheet_ok else "",
		"composite": _relative_to_output(composite_sheet_path) if composite_sheet_ok else "",
	}

	var frames: Array = report["frames"]
	var frame_count_ok := frames.size() == requested_times.size()
	var single_character_ok := frame_count_ok
	var attachment_ok := frame_count_ok
	var bbox_ok := frame_count_ok
	var vfx_suppression_ok := frame_count_ok
	var mix_ok := frame_count_ok
	for frame_value: Variant in frames:
		var frame: Dictionary = frame_value
		single_character_ok = single_character_ok and bool(frame["single_character_contract_passed"])
		attachment_ok = attachment_ok and bool(frame["attachment_contract_passed"])
		bbox_ok = bbox_ok and bool(frame["bbox_contract_passed"])
		vfx_suppression_ok = (
			vfx_suppression_ok and bool(frame["vfx_suppression"]["passed"])
		)
		mix_ok = mix_ok and bool(frame["mix_contract_passed"])
	report["attachment_contract_passed"] = attachment_ok
	report["bbox_contract_passed"] = bbox_ok
	report["character_only_contract_passed"] = (
		bbox_ok
		and character_validity.size() == requested_times.size()
		and character_validity.all(func(value: bool) -> bool: return value)
	)
	report["frame_count_passed"] = frame_count_ok
	report["mix_contract_passed"] = mix_ok
	report["single_character_contract_passed"] = single_character_ok
	report["vfx_suppression_contract_passed"] = vfx_suppression_ok
	report["errors"] = _errors.duplicate()
	report["success"] = (
		frame_count_ok
		and single_character_ok
		and attachment_ok
		and bbox_ok
		and vfx_suppression_ok
		and mix_ok
		and composite_sheet_ok
		and character_sheet_ok
		and _errors.is_empty()
	)
	_write_json(_output_root.path_join("summary.json"), report)
	if bool(report["success"]):
		print(
			"[hybrid-v3-final-exact] %s passed %d exact Vulkan samples."
			% [animation_name, frames.size()]
		)
		quit(0)
		return
	push_error("[hybrid-v3-final-exact] Exact Vulkan acceptance failed for %s." % animation_name)
	quit(1)


func _parse_final_args() -> Dictionary:
	var options := {
		"animation": "",
		"height": DEFAULT_CANVAS.y,
		"origin-x": DEFAULT_ORIGIN.x,
		"origin-y": DEFAULT_ORIGIN.y,
		"output": DEFAULT_EXACT_OUTPUT,
		"pck": OS.get_environment("VIVHITE_STS2_PCK_PATH"),
		"scene-offset-x": DEFAULT_SCENE_OFFSET.x,
		"scene-offset-y": DEFAULT_SCENE_OFFSET.y,
		"scene-scale": DEFAULT_SCENE_SCALE,
		"times": "",
		"width": DEFAULT_CANVAS.x,
	}
	var args := OS.get_cmdline_user_args()
	var index := 0
	while index < args.size():
		var key := str(args[index])
		if not key.begins_with("--") or index + 1 >= args.size():
			_fail("Expected '--name value', got '%s'." % key)
			return {}
		var name := key.trim_prefix("--")
		if not options.has(name):
			_fail("Unknown option '%s'." % key)
			return {}
		index += 1
		var value := str(args[index])
		match name:
			"width", "height":
				options[name] = value.to_int()
			"scene-scale", "origin-x", "origin-y", "scene-offset-x", "scene-offset-y":
				options[name] = value.to_float()
			_:
				options[name] = value
		index += 1
	var animation_name := str(options["animation"])
	if not SUPPORTED_ANIMATIONS.has(animation_name):
		_fail(
			"--animation must be one of %s; got '%s'."
			% [JSON.stringify(SUPPORTED_ANIMATIONS), animation_name]
		)
	if int(options["width"]) < 64 or int(options["height"]) < 64:
		_fail("Canvas dimensions must both be at least 64 pixels.")
	if float(options["scene-scale"]) <= 0.0:
		_fail("Scene scale must be positive.")
	return options if _errors.is_empty() else {}


func _parse_requested_times(value: String, animation_name: String) -> Array[float]:
	if value.strip_edges().is_empty():
		return _default_times(animation_name)
	var result: Array[float] = []
	for component_value: String in value.split(",", false):
		var component := component_value.strip_edges()
		if component.is_empty() or not component.is_valid_float():
			_fail("Invalid --times component '%s'." % component_value)
			return []
		var sample_time := component.to_float()
		if sample_time < 0.0:
			_fail("Exact sample times cannot be negative: %.7f." % sample_time)
			return []
		if not result.is_empty() and sample_time <= result[-1] + EPSILON:
			_fail("Exact sample times must be strictly increasing.")
			return []
		result.append(sample_time)
	return result


func _default_times(animation_name: String) -> Array[float]:
	match animation_name:
		"idle_loop":
			return _as_float_array([0.0, 0.5, 1.0, 1.5, 2.0])
		"low_health_loop":
			return _as_float_array([0.0, 0.366666675, 0.73333335, 1.100000025, 1.4666667])
		"relaxed_loop":
			return _as_float_array([
				0.0, 1.37, 3.00000025, 5.4, 6.0000005,
				9.00000075, 9.9, 11.9999, 12.000001,
			])
		"attack":
			return _as_float_array([
				0.0, 0.036, 0.0799, 0.08, 0.0966667, 0.1833333, 0.1999,
				0.20, 0.2001, 0.23, 0.43, 0.4433333, 0.8866667, 1.1666667,
			])
		"attack_heavy":
			return _as_float_array([
				0.0, 0.054, 0.1199, 0.12, 0.1367, 0.20, 0.3199,
				0.32, 0.3201, 0.3367, 0.47, 0.659333362, 1.165333384, 1.5333334,
			])
		"cast":
			return _as_float_array([
				0.0, 0.0999, 0.10, 0.2499, 0.25, 0.2667, 0.48,
				0.5999, 0.60, 0.6001, 1.2219, 1.222, 1.2221, 1.5666667,
			])
		"hurt":
			return _as_float_array([0.0, 0.10, 0.16, 0.28, 0.46, 0.70, 1.0])
		"die":
			return _as_float_array([
				0.0, 0.18, 0.46, 0.82, 0.94, 1.0, 1.0499, 1.05,
				1.0501, 1.10, 1.1666667, 1.30, 1.55, 1.80, 1.90, 2.3333335,
			])
	return []


func _as_float_array(values: Array) -> Array[float]:
	var result: Array[float] = []
	for value: Variant in values:
		result.append(float(value))
	return result


func _base_final_report(options: Dictionary, animation_name: String, times: Array[float]) -> Dictionary:
	var pck_path := str(options["pck"])
	return {
		"animation": animation_name,
		"animation_duration": 0.0,
		"attachment_contract_passed": false,
		"base_pck": pck_path.replace("\\", "/"),
		"base_pck_sha256": FileAccess.get_sha256(pck_path) if FileAccess.file_exists(pck_path) else "",
		"bbox_contract_passed": false,
		"candidate": DATA_PATH,
		"candidate_atlas_sha256": FileAccess.get_sha256(ATLAS_PATH) if FileAccess.file_exists(ATLAS_PATH) else "",
		"candidate_json_sha256": FileAccess.get_sha256(JSON_PATH) if FileAccess.file_exists(JSON_PATH) else "",
		"candidate_tres_sha256": FileAccess.get_sha256(DATA_PATH) if FileAccess.file_exists(DATA_PATH) else "",
		"canvas": [_canvas.x, _canvas.y],
		"character_only_contract_passed": false,
		"contact_sheets": {},
		"display_server": DisplayServer.get_name(),
		"errors": [],
		"frame_count_passed": false,
		"frames": [],
		"generated_utc": Time.get_datetime_string_from_system(true),
		"mix_contract_passed": false,
		"origin": [_origin.x, _origin.y],
		"profile_source": _profile_source(animation_name),
		"rendering_driver": RenderingServer.get_current_rendering_driver_name(),
		"requested_times": times,
		"scene_offset": [_scene_offset.x, _scene_offset.y],
		"scene_scale": _scene_scale,
		"schema_version": 1,
		"single_character_contract_passed": false,
		"success": false,
		"vfx_suppression_contract_passed": false,
	}


func _profile_source(animation_name: String) -> String:
	if animation_name in ["idle_loop", "low_health_loop", "relaxed_loop"]:
		return "hybrid_neutral_v3 exact profile"
	if animation_name == "attack":
		return "hybrid_attack_peak exact profile"
	if animation_name == "attack_heavy":
		return "hybrid_action_set heavy exact profile"
	if animation_name == "cast":
		return "hybrid_cast_set exact profile"
	if animation_name == "hurt":
		return "hybrid_hurt_neutral authored landmark profile"
	return "hybrid_death_v3 exact profile"


func _prepare_final_runtime(pck_path: String) -> bool:
	if DisplayServer.get_name() == "headless":
		_fail("A Windows display with Vulkan is required; headless uses the dummy rasterizer.")
	var driver := RenderingServer.get_current_rendering_driver_name()
	if driver.to_lower() != "vulkan":
		_fail("Expected Vulkan, but Godot selected '%s'." % driver)
	if pck_path.is_empty() or not FileAccess.file_exists(pck_path):
		_fail("A valid base-game PCK is required via --pck or VIVHITE_STS2_PCK_PATH.")
	elif not ProjectSettings.load_resource_pack(pck_path, false):
		_fail("Could not mount base-game PCK '%s'." % pck_path)
	for type_name: String in ["SpineSprite", "SpineSkeletonDataResource"]:
		if not ClassDB.class_exists(type_name):
			_fail("The game-compatible Spine GDExtension class '%s' is unavailable." % type_name)
	if not ResourceLoader.exists(DATA_PATH):
		_fail("Assembled V3 final candidate .tres is missing or unimported: %s." % DATA_PATH)
	return _errors.is_empty()


func _capture_final_sample(
	stage: Node2D,
	viewport: SubViewport,
	skeleton_data: Resource,
	animation_name: String,
	sample_time: float,
	sample_index: int,
) -> Dictionary:
	var sprite: Node2D = ClassDB.instantiate("SpineSprite") as Node2D
	if sprite == null:
		_fail("Could not instantiate SpineSprite for %s at %.7f." % [animation_name, sample_time])
		return {}
	stage.add_child(sprite)
	sprite.call("set_update_mode", SPINE_UPDATE_MODE_MANUAL)
	sprite.set("skeleton_data_res", skeleton_data)
	sprite.scale = Vector2(_scene_scale, _scene_scale)
	sprite.position = _origin + _scene_offset
	var state: Object = sprite.call("get_animation_state")
	var runtime_skeleton: Object = sprite.call("get_skeleton")
	if state == null or runtime_skeleton == null:
		_fail("Spine runtime did not initialize for %s at %.7f." % [animation_name, sample_time])
		sprite.queue_free()
		return {}

	var applied := _apply_exact_time(
		sprite, state, runtime_skeleton, animation_name, sample_time
	)
	if applied.is_empty():
		sprite.queue_free()
		return {}
	var expected := _expected_attachments(animation_name, sample_time)
	var observed := _observe_attachments(runtime_skeleton)
	var visible_characters: Array = observed["visible_character_attachments"]
	var single_character_ok := visible_characters.size() == 1
	var attachment_ok := single_character_ok and _attachments_match(
		observed["all_slot_attachments"], expected
	)
	var expected_mix := _expected_mix(animation_name)
	var observed_mix := float(applied["mix_duration"])
	var mix_ok := expected_mix < 0.0 or absf(observed_mix - expected_mix) <= EPSILON
	if not attachment_ok:
		_fail(
			"%s at %.7f expected attachments %s, observed %s."
			% [animation_name, sample_time, JSON.stringify(expected), JSON.stringify(observed)]
		)
	if not mix_ok:
		_fail(
			"%s entry mix at %.7f was %.7f, expected %.7f."
			% [animation_name, sample_time, observed_mix, expected_mix]
		)

	var composite := await _capture_render_layer(
		viewport, animation_name, "composite", sample_time, sample_index
	)
	if composite.is_empty():
		sprite.queue_free()
		return {}
	var suppression := _suppress_final_vfx(sprite, runtime_skeleton)
	var character := await _capture_render_layer(
		viewport, animation_name, "character-only", sample_time, sample_index
	)
	if character.is_empty():
		sprite.queue_free()
		return {}
	var bbox_ok := bool(composite["report"]["passed"]) and bool(character["report"]["passed"])
	var frame_passed := (
		single_character_ok
		and attachment_ok
		and mix_ok
		and bbox_ok
		and bool(suppression["passed"])
	)
	var frame_report := {
		"all_slot_attachments": observed["all_slot_attachments"],
		"attachment_contract_passed": attachment_ok,
		"bbox_contract_passed": bbox_ok,
		"character_only": character["report"],
		"composite": composite["report"],
		"expected_attachments": expected,
		"expected_mix_duration": expected_mix if expected_mix >= 0.0 else null,
		"mix_contract_passed": mix_ok,
		"observed_mix_duration": observed_mix if observed_mix >= 0.0 else null,
		"passed": frame_passed,
		"predecessor": applied["predecessor"],
		"requested_time": sample_time,
		"runtime_animation_time": applied["animation_time"],
		"runtime_track_time": applied["track_time"],
		"single_character_contract_passed": single_character_ok,
		"vfx_suppression": suppression,
		"visible_attachment_count": int(observed["visible_attachment_count"]),
		"visible_attachments": observed["visible_attachments"],
		"visible_character_attachment_count": visible_characters.size(),
		"visible_character_attachments": visible_characters,
	}
	sprite.queue_free()
	await process_frame
	return {
		"character_image": character["image"],
		"composite_image": composite["image"],
		"report": frame_report,
	}


func _apply_exact_time(
	sprite: Node2D,
	state: Object,
	runtime_skeleton: Object,
	animation_name: String,
	sample_time: float,
) -> Dictionary:
	var entry: Variant = null
	var predecessor: Variant = null
	if animation_name in ["idle_loop", "low_health_loop", "relaxed_loop"]:
		_dirty_neutral_slots(runtime_skeleton)
		entry = state.call("set_animation", animation_name, true, 0)
		if entry == null or not (entry as Object).has_method("set_track_time"):
			_fail("Spine track entry cannot seek %s." % animation_name)
			return {}
		(entry as Object).call("set_track_time", sample_time)
		state.call("update", 0.0)
		state.call("apply", runtime_skeleton)
		sprite.call("update_skeleton", 0.0)
	else:
		predecessor = "hurt" if animation_name == "die" else "idle_loop"
		state.call("set_animation", predecessor, predecessor == "idle_loop", 0)
		state.call("update", PRE_ROLL)
		state.call("apply", runtime_skeleton)
		sprite.call("update_skeleton", 0.0)
		entry = state.call("set_animation", animation_name, false, 0)
		state.call("update", sample_time)
		state.call("apply", runtime_skeleton)
		sprite.call("update_skeleton", 0.0)
	if entry == null:
		_fail("Spine did not return a track entry for %s." % animation_name)
		return {}
	var entry_object := entry as Object
	return {
		"animation_time": (
			float(entry_object.call("get_animation_time"))
			if entry_object.has_method("get_animation_time") else sample_time
		),
		"mix_duration": _track_entry_mix_duration(entry),
		"predecessor": predecessor,
		"track_time": (
			float(entry_object.call("get_track_time"))
			if entry_object.has_method("get_track_time") else sample_time
		),
	}


func _expected_mix(animation_name: String) -> float:
	match animation_name:
		"attack":
			return 0.10
		"attack_heavy":
			return 0.02
		"cast":
			return 0.05
		"hurt":
			return 0.03
		"die":
			return 0.0
	return -1.0


func _track_entry_mix_duration(entry: Variant) -> float:
	if entry == null or not entry is Object:
		return -1.0
	var object := entry as Object
	for method_name: String in ["get_mix_duration", "get_mix_duration_seconds"]:
		if object.has_method(method_name):
			return float(object.call(method_name))
	return -1.0


func _expected_attachments(animation_name: String, sample_time: float) -> Dictionary:
	var result := {
		BODY_SLOT: BODY_ATTACHMENT,
		ACTION_SLOT: null,
		DEATH_SLOT: null,
		SLASH_SLOT: null,
		SIGIL_SLOT: null,
		EYE_SLOT: null,
	}
	match animation_name:
		"attack":
			if sample_time >= 0.08 - EPSILON and sample_time < 0.20 - EPSILON:
				result[BODY_SLOT] = null
				result[ACTION_SLOT] = ATTACK_ATTACHMENT
			if sample_time >= 0.08 - EPSILON and sample_time < 0.886666692 - EPSILON:
				result[SLASH_SLOT] = SLASH_ATTACHMENT
		"attack_heavy":
			if sample_time >= 0.12 - EPSILON and sample_time < 0.32 - EPSILON:
				result[BODY_SLOT] = null
				result[ACTION_SLOT] = HEAVY_ATTACHMENT
			if sample_time >= 0.12 - EPSILON and sample_time < 1.165333384 - EPSILON:
				result[SLASH_SLOT] = SLASH_ATTACHMENT
		"cast":
			if sample_time >= 0.25 - EPSILON and sample_time < 0.60 - EPSILON:
				result[BODY_SLOT] = null
				result[ACTION_SLOT] = CAST_ATTACHMENT
			if sample_time >= 0.10 - EPSILON and sample_time < 1.222000026 - EPSILON:
				result[SIGIL_SLOT] = SIGIL_ATTACHMENT
		"die":
			if sample_time >= 1.05 - EPSILON:
				result[BODY_SLOT] = null
				result[DEATH_SLOT] = DEATH_ATTACHMENT
	return result


func _observe_attachments(runtime_skeleton: Object) -> Dictionary:
	var all := {}
	var visible := []
	var visible_characters := []
	for slot_name: String in ALL_SLOTS:
		var attachment_name: Variant = _attachment_name(runtime_skeleton, slot_name)
		all[slot_name] = attachment_name
		if attachment_name != null:
			var item := {"attachment": attachment_name, "slot": slot_name}
			visible.append(item)
			if CHARACTER_SLOTS.has(slot_name):
				visible_characters.append(item)
	return {
		"all_slot_attachments": all,
		"visible_attachment_count": visible.size(),
		"visible_attachments": visible,
		"visible_character_attachments": visible_characters,
	}


func _attachments_match(observed: Dictionary, expected: Dictionary) -> bool:
	for slot_name: String in ALL_SLOTS:
		if observed.get(slot_name, "<missing>") != expected.get(slot_name, "<missing>"):
			return false
	return true


func _dirty_neutral_slots(runtime_skeleton: Object) -> void:
	_set_slot_attachment(runtime_skeleton, BODY_SLOT, null)
	_set_slot_attachment(runtime_skeleton, ACTION_SLOT, ATTACK_ATTACHMENT)
	_set_slot_attachment(runtime_skeleton, DEATH_SLOT, DEATH_ATTACHMENT)
	_set_slot_attachment(runtime_skeleton, SLASH_SLOT, SLASH_ATTACHMENT)
	_set_slot_attachment(runtime_skeleton, SIGIL_SLOT, SIGIL_ATTACHMENT)
	_set_slot_attachment(runtime_skeleton, EYE_SLOT, null)


func _set_slot_attachment(
	runtime_skeleton: Object, slot_name: String, attachment_name: Variant
) -> void:
	var slot: Variant = runtime_skeleton.call("find_slot", slot_name)
	if slot == null:
		_fail("Runtime skeleton is missing slot %s." % slot_name)
		return
	if attachment_name == null:
		(slot as Object).call("set_attachment", null)
		return
	var attachment: Variant = runtime_skeleton.call(
		"get_attachment_by_slot_name", slot_name, attachment_name
	)
	if attachment == null:
		_fail("Runtime cannot resolve %s/%s." % [slot_name, attachment_name])
		return
	(slot as Object).call("set_attachment", attachment)


func _attachment_name(runtime_skeleton: Object, slot_name: String) -> Variant:
	var slot: Variant = runtime_skeleton.call("find_slot", slot_name)
	if slot == null:
		_fail("Runtime skeleton is missing slot %s." % slot_name)
		return "<missing>"
	var slot_object := slot as Object
	if not slot_object.has_method("get_attachment"):
		_fail("Runtime slot %s exposes no get_attachment method." % slot_name)
		return "<unavailable>"
	var attachment: Variant = slot_object.call("get_attachment")
	if attachment == null:
		return null
	var attachment_object := attachment as Object
	if not attachment_object.has_method("get_attachment_name"):
		_fail("Runtime attachment in %s exposes no attachment name." % slot_name)
		return "<unavailable>"
	return str(attachment_object.call("get_attachment_name"))


func _suppress_final_vfx(sprite: Node2D, runtime_skeleton: Object) -> Dictionary:
	var before := {}
	var after := {}
	var final_alpha := {}
	var passed := true
	for slot_name: String in VFX_SLOTS:
		var slot: Variant = runtime_skeleton.call("find_slot", slot_name)
		if slot == null:
			_fail("Runtime skeleton cannot suppress missing VFX slot %s." % slot_name)
			passed = false
			continue
		var slot_object := slot as Object
		before[slot_name] = _attachment_name(runtime_skeleton, slot_name)
		if (
			not slot_object.has_method("set_attachment")
			or not slot_object.has_method("get_color")
			or not slot_object.has_method("set_color")
		):
			_fail("Runtime VFX slot %s lacks attachment/color mutation methods." % slot_name)
			passed = false
			continue
		var color: Color = slot_object.call("get_color")
		slot_object.call("set_color", Color(color.r, color.g, color.b, 0.0))
		slot_object.call("set_attachment", null)
	sprite.call("update_skeleton", 0.0)
	for slot_name: String in VFX_SLOTS:
		var slot: Variant = runtime_skeleton.call("find_slot", slot_name)
		if slot == null:
			passed = false
			continue
		var slot_object := slot as Object
		if slot_object.has_method("get_color") and slot_object.has_method("set_color"):
			var color: Color = slot_object.call("get_color")
			slot_object.call("set_color", Color(color.r, color.g, color.b, 0.0))
		if slot_object.has_method("set_attachment"):
			slot_object.call("set_attachment", null)
		after[slot_name] = _attachment_name(runtime_skeleton, slot_name)
		var color_after: Color = slot_object.call("get_color")
		final_alpha[slot_name] = color_after.a
		if after[slot_name] != null or color_after.a > EPSILON:
			passed = false
	sprite.queue_redraw()
	return {
		"after": after,
		"before": before,
		"final_alpha": final_alpha,
		"passed": passed,
		"slots": VFX_SLOTS,
	}


func _capture_render_layer(
	viewport: SubViewport,
	animation_name: String,
	layer_name: String,
	sample_time: float,
	sample_index: int,
) -> Dictionary:
	await process_frame
	RenderingServer.force_draw(false)
	await RenderingServer.frame_post_draw
	var image: Image = viewport.get_texture().get_image()
	if image == null or image.is_empty():
		_fail("Renderer returned an empty %s image at %.7f." % [layer_name, sample_time])
		return {}
	if image.get_format() != Image.FORMAT_RGBA8:
		image.convert(Image.FORMAT_RGBA8)
	var alpha: Dictionary = _alpha_metrics(image)
	var relative_path := "frames/%s/%s/frame-%02d-t%.7f.png" % [
		_safe_component(animation_name),
		layer_name,
		sample_index,
		sample_time,
	]
	var absolute_path := _output_root.path_join(relative_path)
	DirAccess.make_dir_recursive_absolute(absolute_path.get_base_dir())
	var save_error := image.save_png(absolute_path)
	var render_ok := (
		int(alpha["pixel_count"]) > 0
		and not bool(alpha["touches_canvas_edge"])
		and save_error == OK
	)
	var layer_report := {
		"alpha_bbox": alpha["bbox"],
		"alpha_centroid": alpha["centroid"],
		"alpha_metric_sample_size": alpha["metric_sample_size"],
		"alpha_pixel_count_sampled": alpha["pixel_count"],
		"alpha_weight_sampled": alpha["alpha_weight"],
		"edge_alpha_pixels": alpha["edge_alpha_pixels"],
		"non_empty": int(alpha["pixel_count"]) > 0,
		"passed": render_ok,
		"path": relative_path,
		"sha256": _image_sha256(image),
		"touches_canvas_edge": alpha["touches_canvas_edge"],
	}
	if not render_ok:
		_fail(
			"%s/%s at %.7f was empty, clipped, or could not be saved."
			% [animation_name, layer_name, sample_time]
		)
	return {"image": image, "report": layer_report}
