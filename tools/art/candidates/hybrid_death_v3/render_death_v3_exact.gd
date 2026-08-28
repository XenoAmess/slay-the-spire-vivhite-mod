extends "../../compare/preview/render_combat_rig_compare.gd"

## Exact hidden-Vulkan acceptance for the V3 death handoff. Every frame enters
## die through the authored hurt -> die state transition, records runtime slot
## visibility, and captures both composite and character-only pixels. Solid
## body bounds use Alpha >= 128 so faint whole-body glow cannot masquerade as
## the physical contact edge.

const EXACT_DATA_PATH := "res://tools/candidates/hybrid_death_v3/vivhite_combat_skeleton_data.tres"
const DEFAULT_EXACT_OUTPUT := ".work/combat-rig-compare-preview/hybrid-death-v3-exact"
const BODY_SLOT := "vivhite_body"
const BODY_ATTACHMENT := "vivhite_combat_body"
const DEATH_SLOT := "vivhite_death_body"
const DEATH_ATTACHMENT := "vivhite_combat_death_side"
const SUPPRESSED_VFX_SLOTS: Array[String] = ["slash_mesh", "eye_attach_slot"]
const HURT_PRE_ROLL := 0.50
const EXPECTED_HURT_DIE_MIX := 0.0
const SWAP_TIME := 1.05
const PRE_SWAP_TIME := 1.0499
const POST_SWAP_TIME := 1.0501
const IMPACT_TIME := 1.1666667
const REBOUND_TIME := 1.30
const DAMP_TIME := 1.55
const SETTLE_TIME := 1.80
const END_TIME := 2.3333335
const SOLID_ALPHA_THRESHOLD := 128
const MAX_SOLID_LEFT_JUMP_PX := 16
const MAX_SOLID_BOTTOM_JUMP_PX := 16
const EPSILON := 0.00001
const EXACT_TIMES: Array[float] = [
	0.0,
	0.18,
	0.46,
	0.82,
	0.94,
	1.0,
	PRE_SWAP_TIME,
	SWAP_TIME,
	POST_SWAP_TIME,
	1.10,
	IMPACT_TIME,
	REBOUND_TIME,
	DAMP_TIME,
	SETTLE_TIME,
	1.90,
	END_TIME,
]


func _initialize() -> void:
	if DisplayServer.get_name() != "headless":
		DisplayServer.window_set_flag(DisplayServer.WINDOW_FLAG_NO_FOCUS, true)
		DisplayServer.window_set_position(Vector2i(-32000, -32000))
	call_deferred("_run_exact")


func _run_exact() -> void:
	var options := _parse_exact_args()
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

	var report := {
		"base_pck": str(options["pck"]).replace("\\", "/"),
		"base_pck_sha256": FileAccess.get_sha256(str(options["pck"])) if FileAccess.file_exists(str(options["pck"])) else "",
		"candidate": EXACT_DATA_PATH,
		"candidate_sha256": FileAccess.get_sha256(EXACT_DATA_PATH) if FileAccess.file_exists(EXACT_DATA_PATH) else "",
		"canvas": [_canvas.x, _canvas.y],
		"contact_sheets": {},
		"display_server": DisplayServer.get_name(),
		"errors": [],
		"expected_hurt_die_mix": EXPECTED_HURT_DIE_MIX,
		"frames": [],
		"generated_utc": Time.get_datetime_string_from_system(true),
		"hurt_pre_roll": HURT_PRE_ROLL,
		"origin": [_origin.x, _origin.y],
		"rendering_driver": RenderingServer.get_current_rendering_driver_name(),
		"requested_times": EXACT_TIMES,
		"scene_offset": [_scene_offset.x, _scene_offset.y],
		"scene_scale": _scene_scale,
		"schema_version": 1,
		"solid_alpha_threshold": SOLID_ALPHA_THRESHOLD,
		"success": false,
		"swap_time": SWAP_TIME,
	}
	if not _prepare_runtime(str(options["pck"])):
		report.errors = _errors.duplicate()
		_write_json(_output_root.path_join("summary.json"), report)
		quit(2)
		return

	var skeleton_data: Resource = ResourceLoader.load(EXACT_DATA_PATH)
	if skeleton_data == null or not skeleton_data.is_class("SpineSkeletonDataResource"):
		_fail("Could not load original V3 death candidate %s." % EXACT_DATA_PATH)
		report.errors = _errors.duplicate()
		_write_json(_output_root.path_join("summary.json"), report)
		quit(2)
		return
	var die_animation: Object = skeleton_data.call("find_animation", "die")
	if die_animation == null:
		_fail("Candidate is missing die animation.")
		report.errors = _errors.duplicate()
		_write_json(_output_root.path_join("summary.json"), report)
		quit(2)
		return
	var duration := float(die_animation.call("get_duration"))
	report["die_duration"] = duration
	if absf(duration - END_TIME) > EPSILON:
		_fail("Die duration %.7f differs from %.7f." % [duration, END_TIME])

	var viewport := SubViewport.new()
	viewport.name = "VivhiteHybridDeathV3ExactViewport"
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
	var observed_mix_durations: Array[float] = []
	for index in EXACT_TIMES.size():
		var captured := await _capture_transition_frame(
			stage,
			viewport,
			skeleton_data,
			EXACT_TIMES[index],
			index,
		)
		if captured.is_empty():
			continue
		var frame_report: Dictionary = captured["report"]
		report.frames.append(frame_report)
		composite_images.append(captured["composite_image"] as Image)
		composite_validity.append(bool(frame_report["composite"]["passed"]))
		character_images.append(captured["character_image"] as Image)
		character_validity.append(bool(frame_report["character_only"]["passed"]))
		var observed_mix := float(frame_report.get("hurt_die_mix_duration", -1.0))
		if observed_mix >= 0.0:
			observed_mix_durations.append(observed_mix)

	var composite_sheet_path := _output_root.path_join("contact-sheets/die-exact-composite.png")
	var character_sheet_path := _output_root.path_join("contact-sheets/die-exact-character-only.png")
	var composite_sheet_ok := _write_contact_sheet(
		composite_images,
		composite_validity,
		composite_sheet_path,
		8,
	)
	var character_sheet_ok := _write_contact_sheet(
		character_images,
		character_validity,
		character_sheet_path,
		8,
	)
	report.contact_sheets = {
		"character_only": _relative_to_output(character_sheet_path) if character_sheet_ok else "",
		"composite": _relative_to_output(composite_sheet_path) if composite_sheet_ok else "",
	}
	report["observed_hurt_die_mix_durations"] = observed_mix_durations
	var frame_count_ok: bool = (report.frames as Array).size() == EXACT_TIMES.size()
	var render_ok: bool = (
		composite_validity.size() == EXACT_TIMES.size()
		and character_validity.size() == EXACT_TIMES.size()
		and composite_validity.all(func(value: bool) -> bool: return value)
		and character_validity.all(func(value: bool) -> bool: return value)
	)
	var mix_ok := not observed_mix_durations.is_empty()
	for mix_duration: float in observed_mix_durations:
		if absf(mix_duration - EXPECTED_HURT_DIE_MIX) > EPSILON:
			mix_ok = false
			_fail("Runtime hurt -> die mix was %.7f, expected %.7f." % [mix_duration, EXPECTED_HURT_DIE_MIX])
	var boundary: Dictionary = _validate_boundary_reports(report.frames)
	report["boundary_contract"] = boundary
	report["frame_count_passed"] = frame_count_ok
	report["mix_contract_passed"] = mix_ok
	report["render_contract_passed"] = render_ok
	report.errors = _errors.duplicate()
	report.success = (
		frame_count_ok
		and render_ok
		and mix_ok
		and bool(boundary.get("passed", false))
		and composite_sheet_ok
		and character_sheet_ok
		and _errors.is_empty()
	)
	_write_json(_output_root.path_join("summary.json"), report)
	if bool(report.success):
		print("[hybrid-death-v3-exact] Rendered and validated %d exact Vulkan samples." % report.frames.size())
		quit(0)
		return
	push_error("[hybrid-death-v3-exact] Exact Vulkan acceptance failed.")
	quit(1)


func _parse_exact_args() -> Dictionary:
	var options := {
		"height": DEFAULT_CANVAS.y,
		"origin-x": DEFAULT_ORIGIN.x,
		"origin-y": DEFAULT_ORIGIN.y,
		"output": DEFAULT_EXACT_OUTPUT,
		"pck": OS.get_environment("VIVHITE_STS2_PCK_PATH"),
		"scene-offset-x": DEFAULT_SCENE_OFFSET.x,
		"scene-offset-y": DEFAULT_SCENE_OFFSET.y,
		"scene-scale": DEFAULT_SCENE_SCALE,
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
	if int(options["width"]) < 64 or int(options["height"]) < 64:
		_fail("Canvas dimensions must both be at least 64 pixels.")
	if float(options["scene-scale"]) <= 0.0:
		_fail("Scene scale must be positive.")
	return options if _errors.is_empty() else {}


func _prepare_runtime(pck_path: String) -> bool:
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
			_fail("The game's Spine GDExtension class '%s' is unavailable." % type_name)
	if not ResourceLoader.exists(EXACT_DATA_PATH):
		_fail("Original V3 death candidate .tres is missing: %s." % EXACT_DATA_PATH)
	return _errors.is_empty()


func _capture_transition_frame(
	stage: Node2D,
	viewport: SubViewport,
	skeleton_data: Resource,
	sample_time: float,
	sample_index: int,
) -> Dictionary:
	var sprite: Node2D = ClassDB.instantiate("SpineSprite") as Node2D
	if sprite == null:
		_fail("Could not instantiate SpineSprite at %.7f." % sample_time)
		return {}
	stage.add_child(sprite)
	sprite.call("set_update_mode", SPINE_UPDATE_MODE_MANUAL)
	sprite.set("skeleton_data_res", skeleton_data)
	sprite.scale = Vector2(_scene_scale, _scene_scale)
	sprite.position = _origin + _scene_offset
	var state: Object = sprite.call("get_animation_state")
	var runtime_skeleton: Object = sprite.call("get_skeleton")
	if state == null or runtime_skeleton == null:
		_fail("SpineSprite did not create state/skeleton at %.7f." % sample_time)
		sprite.queue_free()
		return {}

	state.call("set_animation", "hurt", false, 0)
	state.call("update", HURT_PRE_ROLL)
	state.call("apply", runtime_skeleton)
	sprite.call("update_skeleton", 0.0)
	var die_entry: Variant = state.call("set_animation", "die", false, 0)
	state.call("update", sample_time)
	state.call("apply", runtime_skeleton)
	sprite.call("update_skeleton", 0.0)

	var slots := _visible_character_slots(runtime_skeleton)
	var expected_attachment := DEATH_ATTACHMENT if sample_time >= SWAP_TIME - EPSILON else BODY_ATTACHMENT
	var expected_slot := DEATH_SLOT if expected_attachment == DEATH_ATTACHMENT else BODY_SLOT
	var visible: Array = slots["visible_attachments"]
	var attachment_ok := (
		visible.size() == 1
		and str(visible[0]["slot"]) == expected_slot
		and str(visible[0]["attachment"]) == expected_attachment
	)

	var composite := await _capture_render_layer(viewport, "composite", sample_time, sample_index)
	if composite.is_empty():
		sprite.queue_free()
		return {}
	var suppression := _suppress_runtime_vfx(sprite, runtime_skeleton)
	var character := await _capture_render_layer(viewport, "character-only", sample_time, sample_index)
	if character.is_empty():
		sprite.queue_free()
		return {}
	var frame_report := {
		"attachment_contract_passed": attachment_ok,
		"character_only": character["report"],
		"composite": composite["report"],
		"expected_attachment": expected_attachment,
		"expected_slot": expected_slot,
		"hurt_die_mix_duration": _track_entry_mix_duration(die_entry),
		"passed": (
			attachment_ok
			and bool(composite["report"]["passed"])
			and bool(character["report"]["passed"])
			and bool(suppression["passed"])
		),
		"requested_time": sample_time,
		"slot_attachments": slots["slot_attachments"],
		"suppressed_runtime_vfx": suppression,
		"visible_character_attachment_count": visible.size(),
		"visible_character_attachments": visible,
	}
	if not attachment_ok:
		_fail("At %.7f expected exactly %s=%s, observed %s." % [
			sample_time,
			expected_slot,
			expected_attachment,
			JSON.stringify(visible),
		])
	sprite.queue_free()
	await process_frame
	return {
		"character_image": character["image"],
		"composite_image": composite["image"],
		"report": frame_report,
	}


func _capture_render_layer(
	viewport: SubViewport,
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
	var alpha := _alpha_metrics(image)
	var solid := _solid_alpha_metrics(image, SOLID_ALPHA_THRESHOLD)
	var relative_path := "frames/%s/die/frame-%02d-t%.7f.png" % [layer_name, sample_index, sample_time]
	var absolute_path := _output_root.path_join(relative_path)
	DirAccess.make_dir_recursive_absolute(absolute_path.get_base_dir())
	var save_error := image.save_png(absolute_path)
	var render_ok := (
		int(alpha.pixel_count) > 0
		and int(solid.pixel_count) > 0
		and not bool(alpha.touches_canvas_edge)
		and save_error == OK
	)
	var report := {
		"alpha_bbox": alpha.bbox,
		"alpha_centroid": alpha.centroid,
		"alpha_pixel_count_sampled": alpha.pixel_count,
		"non_empty": int(alpha.pixel_count) > 0,
		"passed": render_ok,
		"path": relative_path,
		"sha256": _image_sha256(image),
		"solid_bbox": solid.bbox,
		"solid_bottom_y": solid.bottom_y,
		"solid_left_x": solid.left_x,
		"solid_pixel_count": solid.pixel_count,
		"solid_right_x": solid.right_x,
		"solid_top_y": solid.top_y,
		"touches_canvas_edge": alpha.touches_canvas_edge,
	}
	if not render_ok:
		_fail("%s frame at %.7f was empty, clipped, lacked a solid body, or could not be saved." % [layer_name, sample_time])
	return {"image": image, "report": report}


func _solid_alpha_metrics(image: Image, threshold: int) -> Dictionary:
	var source: Image = image.duplicate()
	if source.get_format() != Image.FORMAT_RGBA8:
		source.convert(Image.FORMAT_RGBA8)
	var used: Rect2i = source.get_used_rect()
	var minimum_x: int = source.get_width()
	var minimum_y: int = source.get_height()
	var maximum_x: int = -1
	var maximum_y: int = -1
	var pixel_count: int = 0
	var data: PackedByteArray = source.get_data()
	var width: int = source.get_width()
	for y in range(used.position.y, used.end.y):
		for x in range(used.position.x, used.end.x):
			var alpha := int(data[(y * width + x) * 4 + 3])
			if alpha < threshold:
				continue
			pixel_count += 1
			minimum_x = mini(minimum_x, x)
			minimum_y = mini(minimum_y, y)
			maximum_x = maxi(maximum_x, x)
			maximum_y = maxi(maximum_y, y)
	var bbox := []
	if pixel_count > 0:
		bbox = [minimum_x, minimum_y, maximum_x - minimum_x + 1, maximum_y - minimum_y + 1]
	return {
		"bbox": bbox,
		"bottom_y": maximum_y if pixel_count > 0 else null,
		"left_x": minimum_x if pixel_count > 0 else null,
		"pixel_count": pixel_count,
		"right_x": maximum_x if pixel_count > 0 else null,
		"top_y": minimum_y if pixel_count > 0 else null,
	}


func _suppress_runtime_vfx(sprite: Node2D, runtime_skeleton: Object) -> Dictionary:
	var before := {}
	var after := {}
	var passed := true
	for slot_name: String in SUPPRESSED_VFX_SLOTS:
		var slot: Variant = runtime_skeleton.call("find_slot", slot_name)
		if slot == null:
			_fail("Runtime skeleton could not find VFX slot %s." % slot_name)
			passed = false
			continue
		var slot_object := slot as Object
		before[slot_name] = _runtime_attachment_name(slot_object, slot_name)
		if not slot_object.has_method("set_attachment") or not slot_object.has_method("get_color") or not slot_object.has_method("set_color"):
			_fail("Runtime VFX slot %s lacks attachment/color methods." % slot_name)
			passed = false
			continue
		var color: Color = slot_object.call("get_color")
		slot_object.call("set_color", Color(color.r, color.g, color.b, 0.0))
		slot_object.call("set_attachment", null)
	sprite.call("update_skeleton", 0.0)
	for slot_name: String in SUPPRESSED_VFX_SLOTS:
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
		after[slot_name] = _runtime_attachment_name(slot_object, slot_name)
		var final_color: Color = slot_object.call("get_color")
		if after[slot_name] != null or final_color.a > EPSILON:
			passed = false
	sprite.queue_redraw()
	return {"after": after, "before": before, "passed": passed, "slots": SUPPRESSED_VFX_SLOTS}


func _visible_character_slots(runtime_skeleton: Object) -> Dictionary:
	var visible := []
	var attachments := {}
	for slot_name: String in [BODY_SLOT, DEATH_SLOT]:
		var attachment_name: Variant = _runtime_slot_attachment_name(runtime_skeleton, slot_name)
		attachments[slot_name] = attachment_name
		if attachment_name != null:
			visible.append({"attachment": attachment_name, "slot": slot_name})
	return {"slot_attachments": attachments, "visible_attachments": visible}


func _runtime_slot_attachment_name(runtime_skeleton: Object, slot_name: String) -> Variant:
	var slot: Variant = runtime_skeleton.call("find_slot", slot_name)
	if slot == null:
		_fail("Runtime skeleton could not find slot %s." % slot_name)
		return "<missing>"
	return _runtime_attachment_name(slot as Object, slot_name)


func _runtime_attachment_name(slot: Object, slot_name: String) -> Variant:
	if not slot.has_method("get_attachment"):
		_fail("Runtime slot %s exposes no get_attachment method." % slot_name)
		return "<unavailable>"
	var attachment: Variant = slot.call("get_attachment")
	if attachment == null:
		return null
	if not (attachment as Object).has_method("get_attachment_name"):
		_fail("Runtime attachment in %s exposes no attachment name." % slot_name)
		return "<unavailable>"
	return str((attachment as Object).call("get_attachment_name"))


func _track_entry_mix_duration(entry: Variant) -> float:
	if entry == null or not entry is Object:
		return -1.0
	var object := entry as Object
	for method_name: String in ["get_mix_duration", "get_mix_duration_seconds"]:
		if object.has_method(method_name):
			return float(object.call(method_name))
	return -1.0


func _validate_boundary_reports(frame_values: Array) -> Dictionary:
	var by_time := {}
	var passed := true
	for value: Variant in frame_values:
		var frame: Dictionary = value
		by_time[_time_key(float(frame["requested_time"]))] = frame
		if not bool(frame.get("passed", false)):
			passed = false
	for required: float in [PRE_SWAP_TIME, SWAP_TIME, POST_SWAP_TIME, IMPACT_TIME, REBOUND_TIME, SETTLE_TIME, END_TIME]:
		if not by_time.has(_time_key(required)):
			_fail("Missing exact death landmark %.7f." % required)
			passed = false
	if not passed:
		return {"passed": false}

	var before: Dictionary = by_time[_time_key(PRE_SWAP_TIME)]
	var at_swap: Dictionary = by_time[_time_key(SWAP_TIME)]
	var after: Dictionary = by_time[_time_key(POST_SWAP_TIME)]
	if str(before["visible_character_attachments"]) == str(after["visible_character_attachments"]):
		_fail("Death attachment did not change across the atomic boundary.")
		passed = false
	for frame: Dictionary in [before, at_swap, after]:
		if int(frame.get("visible_character_attachment_count", 0)) != 1:
			_fail("Death boundary exposed other than one character at %.7f." % float(frame["requested_time"]))
			passed = false

	var before_solid: Dictionary = before["character_only"]
	var after_solid: Dictionary = after["character_only"]
	var left_jump: int = absi(int(after_solid["solid_left_x"]) - int(before_solid["solid_left_x"]))
	var bottom_jump: int = absi(int(after_solid["solid_bottom_y"]) - int(before_solid["solid_bottom_y"]))
	if left_jump > MAX_SOLID_LEFT_JUMP_PX:
		_fail("Solid death handoff moved horizontally %d px; limit is %d." % [left_jump, MAX_SOLID_LEFT_JUMP_PX])
		passed = false
	if bottom_jump > MAX_SOLID_BOTTOM_JUMP_PX:
		_fail("Solid death handoff moved vertically %d px; limit is %d." % [bottom_jump, MAX_SOLID_BOTTOM_JUMP_PX])
		passed = false

	var impact: Dictionary = by_time[_time_key(IMPACT_TIME)]["character_only"]
	var rebound: Dictionary = by_time[_time_key(REBOUND_TIME)]["character_only"]
	var settle: Dictionary = by_time[_time_key(SETTLE_TIME)]["character_only"]
	var end: Dictionary = by_time[_time_key(END_TIME)]["character_only"]
	var swap_bottom: int = int(after_solid["solid_bottom_y"])
	var impact_bottom: int = int(impact["solid_bottom_y"])
	var rebound_bottom: int = int(rebound["solid_bottom_y"])
	var settle_bottom: int = int(settle["solid_bottom_y"])
	var end_bottom: int = int(end["solid_bottom_y"])
	var grounded_ok: bool = (
		abs(swap_bottom - settle_bottom) <= 2
		and impact_bottom >= settle_bottom
		and rebound_bottom < settle_bottom
		and abs(end_bottom - settle_bottom) <= 1
	)
	if not grounded_ok:
		_fail("Death landing did not remain grounded through impact/rebound/settle: %s" % [
			swap_bottom,
			impact_bottom,
			rebound_bottom,
			settle_bottom,
			end_bottom,
		])
		passed = false
	return {
		"after_solid_bbox": after_solid["solid_bbox"],
		"alpha_left_jump_px": abs(int(after_solid["alpha_bbox"][0]) - int(before_solid["alpha_bbox"][0])),
		"before_solid_bbox": before_solid["solid_bbox"],
		"grounded_bottom_sequence_px": [swap_bottom, impact_bottom, rebound_bottom, settle_bottom, end_bottom],
		"grounded_contract_passed": grounded_ok,
		"passed": passed,
		"solid_bottom_jump_px": bottom_jump,
		"solid_left_jump_px": left_jump,
	}


func _time_key(value: float) -> String:
	return "%.7f" % value
