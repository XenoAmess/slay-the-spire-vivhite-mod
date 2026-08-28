extends "../../compare/preview/render_combat_rig_compare.gd"

## Candidate-local Vulkan acceptance sampler for the V3 Hybrid attack body
## attachment. Each sample starts from the same idle_loop phase and then enters
## attack through the SpineAnimationState idle_loop -> attack mix declared by
## the candidate's original .tres. No staged/copy-rewritten candidate is used.

const EXACT_DATA_PATH := "res://tools/candidates/hybrid_attack_peak/vivhite_combat_skeleton_data.tres"
const DEFAULT_EXACT_OUTPUT := ".work/combat-rig-compare-preview/hybrid-attack-peak-exact"
const IDLE_PRE_ROLL := 0.50
const EXPECTED_IDLE_ATTACK_MIX := 0.10
const ATTACK_ENTER := 0.08
const ATTACK_EXIT := 0.20
const EPSILON := 0.00001
const BODY_SLOT := "vivhite_body"
const BODY_ATTACHMENT := "vivhite_combat_body"
const ACTION_SLOT := "vivhite_action_pose"
const ACTION_ATTACHMENT := "vivhite_combat_attack_peak"
const DEATH_SLOT := "vivhite_death_body"
const SUPPRESSED_VFX_SLOTS: Array[String] = ["slash_mesh", "eye_attach_slot"]
const EXACT_TIMES: Array[float] = [
	0.0,
	0.036,
	0.0799,
	0.08,
	0.0966667,
	0.1833333,
	0.1999,
	0.20,
	0.2001,
	0.23,
	0.43,
	0.4433333,
	0.8866667,
	1.1666667,
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
		"attack_window": [ATTACK_ENTER, ATTACK_EXIT],
		"base_pck": str(options["pck"]).replace("\\", "/"),
		"base_pck_sha256": FileAccess.get_sha256(str(options["pck"])) if FileAccess.file_exists(str(options["pck"])) else "",
		"candidate": EXACT_DATA_PATH,
		"candidate_sha256": FileAccess.get_sha256(EXACT_DATA_PATH) if FileAccess.file_exists(EXACT_DATA_PATH) else "",
		"canvas": [_canvas.x, _canvas.y],
		"contact_sheet": "",
		"contact_sheets": {},
		"display_server": DisplayServer.get_name(),
		"errors": [],
		"expected_idle_attack_mix": EXPECTED_IDLE_ATTACK_MIX,
		"frames": [],
		"generated_utc": Time.get_datetime_string_from_system(true),
		"idle_pre_roll": IDLE_PRE_ROLL,
		"origin": [_origin.x, _origin.y],
		"rendering_driver": RenderingServer.get_current_rendering_driver_name(),
		"requested_times": EXACT_TIMES,
		"scene_offset": [_scene_offset.x, _scene_offset.y],
		"scene_scale": _scene_scale,
		"schema_version": 1,
		"success": false,
	}
	if not _prepare_runtime(str(options["pck"])):
		report.errors = _errors.duplicate()
		_write_json(_output_root.path_join("summary.json"), report)
		quit(2)
		return

	var skeleton_data: Resource = ResourceLoader.load(EXACT_DATA_PATH)
	if skeleton_data == null or not skeleton_data.is_class("SpineSkeletonDataResource"):
		_fail("Could not load original candidate resource %s." % EXACT_DATA_PATH)
		report.errors = _errors.duplicate()
		_write_json(_output_root.path_join("summary.json"), report)
		quit(2)
		return
	var attack_animation: Object = skeleton_data.call("find_animation", "attack")
	if attack_animation == null:
		_fail("Candidate is missing attack animation.")
		report.errors = _errors.duplicate()
		_write_json(_output_root.path_join("summary.json"), report)
		quit(2)
		return
	var attack_duration := float(attack_animation.call("get_duration"))
	report["attack_duration"] = attack_duration
	if attack_duration + EPSILON < EXACT_TIMES[-1]:
		_fail("Attack duration %.7f is shorter than the final requested sample %.7f." % [attack_duration, EXACT_TIMES[-1]])

	var viewport := SubViewport.new()
	viewport.name = "VivhiteHybridAttackPeakExactViewport"
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
		var observed_mix: float = float(frame_report.get("idle_attack_mix_duration", -1.0))
		if observed_mix >= 0.0:
			observed_mix_durations.append(observed_mix)

	var composite_sheet_path := _output_root.path_join("contact-sheets/attack-exact-composite.png")
	var character_sheet_path := _output_root.path_join("contact-sheets/attack-exact-character-only.png")
	var composite_sheet_ok: bool = _write_contact_sheet(
		composite_images, composite_validity, composite_sheet_path, 7
	)
	var character_sheet_ok: bool = _write_contact_sheet(
		character_images, character_validity, character_sheet_path, 7
	)
	var sheet_ok: bool = composite_sheet_ok and character_sheet_ok
	report.contact_sheet = _relative_to_output(composite_sheet_path) if composite_sheet_ok else ""
	report.contact_sheets = {
		"character_only": _relative_to_output(character_sheet_path) if character_sheet_ok else "",
		"composite": _relative_to_output(composite_sheet_path) if composite_sheet_ok else "",
	}
	report["observed_idle_attack_mix_durations"] = observed_mix_durations
	var frame_count_ok: bool = report.frames.size() == EXACT_TIMES.size()
	var boundary_ok: bool = _validate_boundary_reports(report.frames)
	var character_only_ok: bool = (
		character_validity.size() == EXACT_TIMES.size()
		and character_validity.all(func(value: bool) -> bool: return value)
	)
	for frame_value: Variant in report.frames:
		var frame: Dictionary = frame_value
		if (
			not bool(frame.get("isolation_visual_contract_passed", false))
			or not bool(frame.get("suppressed_runtime_vfx", {}).get("passed", false))
		):
			character_only_ok = false
	var mix_ok: bool = not observed_mix_durations.is_empty()
	for duration: float in observed_mix_durations:
		if absf(duration - EXPECTED_IDLE_ATTACK_MIX) > EPSILON:
			mix_ok = false
			_fail("Runtime idle_loop -> attack mix was %.7f, expected %.7f." % [duration, EXPECTED_IDLE_ATTACK_MIX])
	report["boundary_contract_passed"] = boundary_ok
	report["character_boundary_comparisons"] = _character_boundary_comparisons(report.frames)
	report["character_only_contract_passed"] = character_only_ok
	report["frame_count_passed"] = frame_count_ok
	report["mix_contract_passed"] = mix_ok
	report.errors = _errors.duplicate()
	report.success = (
		frame_count_ok
		and boundary_ok
		and character_only_ok
		and mix_ok
		and sheet_ok
		and _errors.is_empty()
	)
	_write_json(_output_root.path_join("summary.json"), report)
	if bool(report.success):
		print("[hybrid-attack-peak-exact] Rendered and validated %d exact Vulkan transition samples." % report.frames.size())
		quit(0)
		return
	push_error("[hybrid-attack-peak-exact] Exact Vulkan transition acceptance failed.")
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
		_fail("Original Hybrid candidate .tres is missing: %s." % EXACT_DATA_PATH)
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
		_fail("Could not instantiate SpineSprite for exact sample %.7f." % sample_time)
		return {}
	stage.add_child(sprite)
	sprite.call("set_update_mode", SPINE_UPDATE_MODE_MANUAL)
	sprite.set("skeleton_data_res", skeleton_data)
	sprite.scale = Vector2(_scene_scale, _scene_scale)
	sprite.position = _origin + _scene_offset
	var state: Object = sprite.call("get_animation_state")
	var runtime_skeleton: Object = sprite.call("get_skeleton")
	if state == null or runtime_skeleton == null:
		_fail("SpineSprite did not create animation state/skeleton at %.7f." % sample_time)
		sprite.queue_free()
		return {}

	state.call("set_animation", "idle_loop", true, 0)
	state.call("update", IDLE_PRE_ROLL)
	state.call("apply", runtime_skeleton)
	sprite.call("update_skeleton", 0.0)
	var attack_entry: Variant = state.call("set_animation", "attack", false, 0)
	state.call("update", sample_time)
	state.call("apply", runtime_skeleton)
	sprite.call("update_skeleton", 0.0)

	var slot_report: Dictionary = _visible_character_slots(runtime_skeleton)
	var expected_attachment: String = ACTION_ATTACHMENT if sample_time >= ATTACK_ENTER - EPSILON and sample_time < ATTACK_EXIT - EPSILON else BODY_ATTACHMENT
	var expected_slot: String = ACTION_SLOT if expected_attachment == ACTION_ATTACHMENT else BODY_SLOT
	var visible_attachments: Array = slot_report["visible_attachments"]
	var attachment_contract_ok: bool = (
		visible_attachments.size() == 1
		and str(visible_attachments[0]["slot"]) == expected_slot
		and str(visible_attachments[0]["attachment"]) == expected_attachment
	)

	var composite := await _capture_render_layer(
		viewport,
		"composite",
		sample_time,
		sample_index,
	)
	if composite.is_empty():
		sprite.queue_free()
		return {}
	var suppression: Dictionary = _suppress_runtime_vfx(sprite, runtime_skeleton)
	var character_only := await _capture_render_layer(
		viewport,
		"character-only",
		sample_time,
		sample_index,
	)
	if character_only.is_empty():
		sprite.queue_free()
		return {}
	var expected_visual_change: bool = false
	for slot_name: String in SUPPRESSED_VFX_SLOTS:
		if suppression["before"].get(slot_name, null) != null:
			expected_visual_change = true
	var isolation_visual_ok: bool = (
		not expected_visual_change
		or str(composite["report"]["sha256"]) != str(character_only["report"]["sha256"])
	)
	if not isolation_visual_ok:
		_fail(
			"Character-only redraw at %.7f retained the composite pixels despite an attached VFX slot."
			% sample_time
		)
	var mix_duration: float = _track_entry_mix_duration(attack_entry)
	var frame_report := {
		"attachment_contract_passed": attachment_contract_ok,
		"character_only": character_only["report"],
		"composite": composite["report"],
		"expected_attachment": expected_attachment,
		"expected_slot": expected_slot,
		"idle_attack_mix_duration": mix_duration,
		"isolation_visual_change_expected": expected_visual_change,
		"isolation_visual_contract_passed": isolation_visual_ok,
		"passed": (
			bool(composite["report"]["passed"])
			and bool(character_only["report"]["passed"])
			and attachment_contract_ok
			and bool(suppression["passed"])
			and isolation_visual_ok
		),
		"requested_time": sample_time,
		"slot_attachments": slot_report["slot_attachments"],
		"suppressed_runtime_vfx": suppression,
		"visible_character_attachment_count": visible_attachments.size(),
		"visible_character_attachments": visible_attachments,
	}
	if not attachment_contract_ok:
		_fail(
			"At %.7f expected exactly %s=%s, observed %s."
			% [sample_time, expected_slot, expected_attachment, JSON.stringify(visible_attachments)]
		)
	if not bool(suppression["passed"]):
		_fail("Could not suppress both runtime VFX slots at %.7f." % sample_time)
	sprite.queue_free()
	await process_frame
	return {
		"character_image": character_only["image"],
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
	var alpha: Dictionary = _alpha_metrics(image)
	var relative_path := "frames/%s/attack/frame-%02d-t%.7f.png" % [
		layer_name, sample_index, sample_time,
	]
	var absolute_path := _output_root.path_join(relative_path)
	DirAccess.make_dir_recursive_absolute(absolute_path.get_base_dir())
	var save_error: Error = image.save_png(absolute_path)
	var render_ok: bool = (
		int(alpha.pixel_count) > 0
		and not bool(alpha.touches_canvas_edge)
		and save_error == OK
	)
	var bbox: Array = alpha.bbox
	var bottom_y: Variant = null
	if bbox.size() == 4 and int(bbox[2]) > 0 and int(bbox[3]) > 0:
		bottom_y = int(bbox[1]) + int(bbox[3]) - 1
	var layer_report := {
		"alpha_bbox": bbox,
		"alpha_bottom_y": bottom_y,
		"alpha_centroid": alpha.centroid,
		"alpha_metric_sample_size": alpha.metric_sample_size,
		"alpha_pixel_count_sampled": alpha.pixel_count,
		"alpha_weight_sampled": alpha.alpha_weight,
		"edge_alpha_pixels": alpha.edge_alpha_pixels,
		"non_empty": int(alpha.pixel_count) > 0,
		"passed": render_ok,
		"path": relative_path,
		"sha256": _image_sha256(image),
		"touches_canvas_edge": alpha.touches_canvas_edge,
	}
	if not render_ok:
		_fail("%s frame at %.7f was empty, clipped, or could not be saved." % [layer_name, sample_time])
	return {"image": image, "report": layer_report}


func _suppress_runtime_vfx(sprite: Node2D, runtime_skeleton: Object) -> Dictionary:
	var before := {}
	var after_initial_null := {}
	var after_mesh_refresh := {}
	var after_final_null := {}
	var original_colors := {}
	var final_colors := {}
	var passed := true
	for slot_name: String in SUPPRESSED_VFX_SLOTS:
		var slot: Variant = runtime_skeleton.call("find_slot", slot_name)
		if slot == null:
			_fail("Runtime SpineSkeleton could not find VFX slot %s." % slot_name)
			passed = false
			continue
		var slot_object := slot as Object
		before[slot_name] = _runtime_attachment_name(slot_object, slot_name)
		if not slot_object.has_method("set_attachment") or not slot_object.has_method("get_color") or not slot_object.has_method("set_color"):
			_fail("Runtime SpineSlot %s lacks attachment/color mutation methods." % slot_name)
			passed = false
			continue
		var original_color: Color = slot_object.call("get_color")
		original_colors[slot_name] = [original_color.r, original_color.g, original_color.b, original_color.a]
		slot_object.call("set_color", Color(original_color.r, original_color.g, original_color.b, 0.0))
		slot_object.call("set_attachment", null)
		after_initial_null[slot_name] = _runtime_attachment_name(slot_object, slot_name)
		if after_initial_null[slot_name] != null:
			_fail("Runtime VFX slot %s remained attached after temporary suppression." % slot_name)
			passed = false

	# SpineSprite caches one SpineMesh2D per draw-order slot. A bare slot change
	# updates the Spine object but not those cached meshes. update_skeleton(0)
	# rebuilds the mesh buffers/world transforms without advancing time. The
	# attachment timeline may reattach a VFX during that apply, so null it again
	# after the refresh; the cached VFX mesh remains valid but fully transparent.
	sprite.call("update_skeleton", 0.0)
	for slot_name: String in SUPPRESSED_VFX_SLOTS:
		var slot: Variant = runtime_skeleton.call("find_slot", slot_name)
		if slot == null:
			passed = false
			continue
		var slot_object := slot as Object
		after_mesh_refresh[slot_name] = _runtime_attachment_name(slot_object, slot_name)
		if slot_object.has_method("get_color") and slot_object.has_method("set_color"):
			var refreshed_color: Color = slot_object.call("get_color")
			slot_object.call("set_color", Color(refreshed_color.r, refreshed_color.g, refreshed_color.b, 0.0))
		if slot_object.has_method("set_attachment"):
			slot_object.call("set_attachment", null)
		after_final_null[slot_name] = _runtime_attachment_name(slot_object, slot_name)
		var final_color: Color = slot_object.call("get_color")
		final_colors[slot_name] = [final_color.r, final_color.g, final_color.b, final_color.a]
		if after_final_null[slot_name] != null or final_color.a > EPSILON:
			_fail("Runtime VFX slot %s was not null and fully hidden after mesh refresh." % slot_name)
			passed = false
	sprite.queue_redraw()
	return {
		"after_final_null": after_final_null,
		"after_initial_null": after_initial_null,
		"after_mesh_refresh": after_mesh_refresh,
		"before": before,
		"final_colors": final_colors,
		"original_colors": original_colors,
		"passed": passed,
		"slots": SUPPRESSED_VFX_SLOTS,
	}


func _visible_character_slots(runtime_skeleton: Object) -> Dictionary:
	var visible := []
	var attachments := {}
	for slot_name: String in [BODY_SLOT, ACTION_SLOT, DEATH_SLOT]:
		var attachment_name: Variant = _runtime_slot_attachment_name(runtime_skeleton, slot_name)
		attachments[slot_name] = attachment_name
		if attachment_name != null:
			visible.append({"attachment": attachment_name, "slot": slot_name})
	return {"slot_attachments": attachments, "visible_attachments": visible}


func _runtime_slot_attachment_name(runtime_skeleton: Object, slot_name: String) -> Variant:
	if not runtime_skeleton.has_method("find_slot"):
		_fail("Runtime SpineSkeleton exposes no find_slot method.")
		return "<unavailable>"
	var slot: Variant = runtime_skeleton.call("find_slot", slot_name)
	if slot == null:
		_fail("Runtime SpineSkeleton could not find slot %s." % slot_name)
		return "<missing>"
	return _runtime_attachment_name(slot as Object, slot_name)


func _runtime_attachment_name(slot: Object, slot_name: String) -> Variant:
	if not slot.has_method("get_attachment"):
		_fail("Runtime SpineSlot %s exposes no get_attachment method." % slot_name)
		return "<unavailable>"
	var attachment: Variant = slot.call("get_attachment")
	if attachment == null:
		return null
	if not (attachment as Object).has_method("get_attachment_name"):
		_fail("Runtime attachment in slot %s exposes no get_attachment_name method." % slot_name)
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


func _validate_boundary_reports(frame_values: Array) -> bool:
	var reports_by_time := {}
	var passed := true
	for value: Variant in frame_values:
		var frame: Dictionary = value
		reports_by_time[_time_key(float(frame["requested_time"]))] = frame
		if not bool(frame.get("passed", false)):
			passed = false
	for required_time: float in [0.0799, 0.08, 0.1999, 0.20, 0.2001]:
		if not reports_by_time.has(_time_key(required_time)):
			_fail("Missing exact boundary sample %.7f." % required_time)
			passed = false
	if not passed:
		return false
	for transition: Array in [[0.0799, 0.08], [0.1999, 0.20]]:
		var before: Dictionary = reports_by_time[_time_key(float(transition[0]))]
		var after: Dictionary = reports_by_time[_time_key(float(transition[1]))]
		if str(before["expected_attachment"]) == str(after["expected_attachment"]):
			_fail("Boundary expectation did not change across %.7f -> %.7f." % transition)
			passed = false
		if str(before["visible_character_attachments"]) == str(after["visible_character_attachments"]):
			_fail("Runtime attachment did not switch across %.7f -> %.7f." % transition)
			passed = false
	return passed


func _character_boundary_comparisons(frame_values: Array) -> Array:
	var reports_by_time := {}
	for value: Variant in frame_values:
		var frame: Dictionary = value
		reports_by_time[_time_key(float(frame["requested_time"]))] = frame
	var result := []
	for transition: Array in [[0.0799, 0.08], [0.1999, 0.20], [0.20, 0.2001]]:
		var before_time := float(transition[0])
		var after_time := float(transition[1])
		if not reports_by_time.has(_time_key(before_time)) or not reports_by_time.has(_time_key(after_time)):
			continue
		var before_frame: Dictionary = reports_by_time[_time_key(before_time)]
		var after_frame: Dictionary = reports_by_time[_time_key(after_time)]
		var before: Dictionary = before_frame["character_only"]
		var after: Dictionary = after_frame["character_only"]
		var before_bbox: Array = before["alpha_bbox"]
		var after_bbox: Array = after["alpha_bbox"]
		var bbox_delta := []
		for index in mini(before_bbox.size(), after_bbox.size()):
			bbox_delta.append(int(after_bbox[index]) - int(before_bbox[index]))
		var bottom_delta: Variant = null
		if before["alpha_bottom_y"] != null and after["alpha_bottom_y"] != null:
			bottom_delta = int(after["alpha_bottom_y"]) - int(before["alpha_bottom_y"])
		result.append({
			"after_alpha_bbox": after_bbox,
			"after_alpha_bottom_y": after["alpha_bottom_y"],
			"after_time": after_time,
			"alpha_bbox_delta": bbox_delta,
			"alpha_bottom_y_delta": bottom_delta,
			"before_alpha_bbox": before_bbox,
			"before_alpha_bottom_y": before["alpha_bottom_y"],
			"before_time": before_time,
			"sha256_changed": str(before["sha256"]) != str(after["sha256"]),
		})
	return result


func _time_key(value: float) -> String:
	return "%.7f" % value
