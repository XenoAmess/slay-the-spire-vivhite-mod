extends "../hybrid_attack_peak/render_attack_peak_exact.gd"

## Exact hidden Windows Vulkan acceptance for the V3 Hybrid cast pose. The
## composite uses the production EyeFire texture, shader parameters and
## SpineSlotNode transform contract; character-only explicitly removes slash,
## sigil, eye slot and the external EyeFire CanvasItem.

const CAST_DATA_PATH := "res://tools/candidates/hybrid_cast_set/vivhite_combat_skeleton_data.tres"
const DEFAULT_CAST_OUTPUT := ".work/combat-rig-compare-preview/hybrid-cast-exact"
const EXPECTED_IDLE_CAST_MIX := 0.05
const CAST_ENTER := 0.25
const CAST_EXIT := 0.60
const CLEAR_TIME := 1.222000026
const CAST_ATTACHMENT := "vivhite_combat_cast_peak"
const CAST_SIGIL_SLOT := "vivhite_magic_sigil"
const CAST_SIGIL_ATTACHMENT := "vivhite_combat_magic_sigil"
const CAST_EYE_SLOT := "eye_attach_slot"
const CAST_EYE_BONE := "vivhite_eye_anchor"
const EYE_ALIGNMENT_CROP := Rect2i(250, 300, 200, 150)
const EYE_ALIGNMENT_SCALE := 4
const CAST_SUPPRESSED_VFX_SLOTS: Array[String] = [
	"slash_mesh",
	CAST_EYE_SLOT,
	CAST_SIGIL_SLOT,
]
const CAST_EXACT_TIMES: Array[float] = [
	0.0,
	0.0999,
	0.10,
	0.2499,
	0.25,
	0.2667,
	0.48,
	0.5999,
	0.60,
	0.6001,
	1.2219,
	1.222,
	1.2221,
	1.5666667,
]

const EYE_FIRE_TEXTURE := "res://images/vfx/characters/ironclad_eye_fire_base.png"
const EYE_FIRE_SHADER := "res://shaders/vfx/vfx_stepped_shader_fire_flat.tres"
const FIRE_ZIGZAG := "res://images/vfx/fire/zigzag_fire_distortion.png"
const FIRE_TILE_NOISE := "res://images/vfx/tileable_noise_1.png"
const FIRE_GRADIENT := "res://images/vfx/environment/fire/basic_fire_gradient.png"
const FIRE_BOTTOM_MASK := "res://images/vfx/fire/fire_bottom_mask.png"
const FIRE_TRIANGLE_NOISE := "res://images/vfx/fire/triangle_noise_tile.png"


func _run_exact() -> void:
	var options := _parse_cast_args()
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
		"animation": "cast",
		"base_pck": str(options["pck"]).replace("\\", "/"),
		"base_pck_sha256": FileAccess.get_sha256(str(options["pck"])) if FileAccess.file_exists(str(options["pck"])) else "",
		"candidate": CAST_DATA_PATH,
		"candidate_sha256": FileAccess.get_sha256(CAST_DATA_PATH) if FileAccess.file_exists(CAST_DATA_PATH) else "",
		"canvas": [_canvas.x, _canvas.y],
		"cast_window": [CAST_ENTER, CAST_EXIT],
		"clear_time": CLEAR_TIME,
		"contact_sheets": {},
		"display_server": DisplayServer.get_name(),
		"errors": [],
		"expected_idle_cast_mix": EXPECTED_IDLE_CAST_MIX,
		"frames": [],
		"generated_utc": Time.get_datetime_string_from_system(true),
		"idle_pre_roll": IDLE_PRE_ROLL,
		"origin": [_origin.x, _origin.y],
		"rendering_driver": RenderingServer.get_current_rendering_driver_name(),
		"requested_times": CAST_EXACT_TIMES,
		"scene_offset": [_scene_offset.x, _scene_offset.y],
		"scene_scale": _scene_scale,
		"schema_version": 1,
		"success": false,
		"suppressed_vfx_slots": CAST_SUPPRESSED_VFX_SLOTS,
		"uses_production_eye_fire": true,
	}
	if not _prepare_cast_runtime(str(options["pck"])):
		report.errors = _errors.duplicate()
		_write_json(_output_root.path_join("summary.json"), report)
		quit(2)
		return

	var skeleton_data: Resource = ResourceLoader.load(CAST_DATA_PATH)
	if skeleton_data == null or not skeleton_data.is_class("SpineSkeletonDataResource"):
		_fail("Could not load cast-set resource %s." % CAST_DATA_PATH)
		report.errors = _errors.duplicate()
		_write_json(_output_root.path_join("summary.json"), report)
		quit(2)
		return
	var cast_animation: Object = skeleton_data.call("find_animation", "cast")
	if cast_animation == null:
		_fail("Candidate is missing cast animation.")
	else:
		report["cast_duration"] = float(cast_animation.call("get_duration"))

	var viewport := SubViewport.new()
	viewport.name = "VivhiteHybridCastExactViewport"
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
	var eye_images: Array[Image] = []
	var eye_validity: Array[bool] = []
	var eye_alignment_images: Array[Image] = []
	var eye_alignment_validity: Array[bool] = []
	var observed_mix_durations: Array[float] = []
	for index in CAST_EXACT_TIMES.size():
		var captured := await _capture_cast_transition_frame(
			stage, viewport, skeleton_data, CAST_EXACT_TIMES[index], index
		)
		if captured.is_empty():
			continue
		var frame_report: Dictionary = captured["report"]
		report.frames.append(frame_report)
		composite_images.append(captured["composite_image"] as Image)
		composite_validity.append(bool(frame_report["composite"]["passed"]))
		character_images.append(captured["character_image"] as Image)
		character_validity.append(bool(frame_report["character_only"]["passed"]))
		if captured.has("eye_image"):
			eye_images.append(captured["eye_image"] as Image)
			eye_validity.append(bool(frame_report["eye_only"]["passed"]))
			var alignment_zoom := (captured["composite_image"] as Image).get_region(EYE_ALIGNMENT_CROP)
			alignment_zoom.resize(
				EYE_ALIGNMENT_CROP.size.x * EYE_ALIGNMENT_SCALE,
				EYE_ALIGNMENT_CROP.size.y * EYE_ALIGNMENT_SCALE,
				Image.INTERPOLATE_LANCZOS
			)
			eye_alignment_images.append(alignment_zoom)
			eye_alignment_validity.append(bool(frame_report["eye_only"]["passed"]))
		var observed_mix := float(frame_report.get("idle_cast_mix_duration", -1.0))
		if observed_mix >= 0.0:
			observed_mix_durations.append(observed_mix)

	var composite_sheet_path := _output_root.path_join("contact-sheets/cast-exact-composite.png")
	var character_sheet_path := _output_root.path_join("contact-sheets/cast-exact-character-only.png")
	var eye_sheet_path := _output_root.path_join("contact-sheets/cast-exact-eye-only.png")
	var eye_alignment_sheet_path := _output_root.path_join("contact-sheets/cast-exact-eye-alignment.png")
	var composite_sheet_ok := _write_contact_sheet(composite_images, composite_validity, composite_sheet_path, 7)
	var character_sheet_ok := _write_contact_sheet(character_images, character_validity, character_sheet_path, 7)
	var eye_sheet_ok := _write_contact_sheet(eye_images, eye_validity, eye_sheet_path, 4)
	var eye_alignment_sheet_ok := _write_contact_sheet(
		eye_alignment_images, eye_alignment_validity, eye_alignment_sheet_path, 4
	)
	report.contact_sheets = {
		"character_only": _relative_to_output(character_sheet_path) if character_sheet_ok else "",
		"composite": _relative_to_output(composite_sheet_path) if composite_sheet_ok else "",
		"eye_alignment": _relative_to_output(eye_alignment_sheet_path) if eye_alignment_sheet_ok else "",
		"eye_only": _relative_to_output(eye_sheet_path) if eye_sheet_ok else "",
	}
	report["observed_idle_cast_mix_durations"] = observed_mix_durations
	var frame_count_ok: bool = report.frames.size() == CAST_EXACT_TIMES.size()
	var boundary_ok := _validate_cast_boundary_reports(report.frames)
	var character_only_ok: bool = (
		character_validity.size() == CAST_EXACT_TIMES.size()
		and character_validity.all(func(value: bool) -> bool: return value)
	)
	for frame_value: Variant in report.frames:
		var frame: Dictionary = frame_value
		if (
			not bool(frame.get("isolation_visual_contract_passed", false))
			or not bool(frame.get("suppressed_runtime_vfx", {}).get("passed", false))
		):
			character_only_ok = false
	var mix_ok := not observed_mix_durations.is_empty()
	for duration: float in observed_mix_durations:
		if absf(duration - EXPECTED_IDLE_CAST_MIX) > EPSILON:
			mix_ok = false
			_fail("Runtime idle_loop -> cast mix was %.7f, expected %.7f." % [duration, EXPECTED_IDLE_CAST_MIX])
	report["boundary_contract_passed"] = boundary_ok
	report["character_boundary_comparisons"] = _cast_character_boundary_comparisons(report.frames)
	report["character_only_contract_passed"] = character_only_ok
	report["eye_fire_active_sample_count"] = eye_images.size()
	report["eye_only_contract_passed"] = eye_sheet_ok and eye_validity.all(func(value: bool) -> bool: return value)
	report["frame_count_passed"] = frame_count_ok
	report["mix_contract_passed"] = mix_ok
	report.errors = _errors.duplicate()
	report.success = (
		frame_count_ok and boundary_ok and character_only_ok and mix_ok
		and composite_sheet_ok and character_sheet_ok and eye_sheet_ok and eye_alignment_sheet_ok
		and bool(report["eye_only_contract_passed"]) and _errors.is_empty()
	)
	_write_json(_output_root.path_join("summary.json"), report)
	if bool(report.success):
		print("[hybrid-cast-exact] Rendered and validated %d exact Vulkan transition samples." % report.frames.size())
		quit(0)
		return
	push_error("[hybrid-cast-exact] Exact Vulkan transition acceptance failed.")
	quit(1)


func _parse_cast_args() -> Dictionary:
	var options := {
		"height": DEFAULT_CANVAS.y,
		"origin-x": DEFAULT_ORIGIN.x,
		"origin-y": DEFAULT_ORIGIN.y,
		"output": DEFAULT_CAST_OUTPUT,
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
			"width", "height": options[name] = value.to_int()
			"scene-scale", "origin-x", "origin-y", "scene-offset-x", "scene-offset-y": options[name] = value.to_float()
			_: options[name] = value
		index += 1
	if int(options["width"]) < 64 or int(options["height"]) < 64:
		_fail("Canvas dimensions must both be at least 64 pixels.")
	if float(options["scene-scale"]) <= 0.0:
		_fail("Scene scale must be positive.")
	return options if _errors.is_empty() else {}


func _prepare_cast_runtime(pck_path: String) -> bool:
	if DisplayServer.get_name() == "headless":
		_fail("A Windows display with Vulkan is required; headless uses the dummy rasterizer.")
	var driver := RenderingServer.get_current_rendering_driver_name()
	if driver.to_lower() != "vulkan":
		_fail("Expected Vulkan, but Godot selected '%s'." % driver)
	if pck_path.is_empty() or not FileAccess.file_exists(pck_path):
		_fail("A valid base-game PCK is required via --pck or VIVHITE_STS2_PCK_PATH.")
	elif not ProjectSettings.load_resource_pack(pck_path, false):
		_fail("Could not mount base-game PCK '%s'." % pck_path)
	for type_name: String in ["SpineSprite", "SpineSkeletonDataResource", "SpineSlotNode"]:
		if not ClassDB.class_exists(type_name):
			_fail("The game's Spine GDExtension class '%s' is unavailable." % type_name)
	for path: String in [
		CAST_DATA_PATH, EYE_FIRE_TEXTURE, EYE_FIRE_SHADER, FIRE_ZIGZAG,
		FIRE_TILE_NOISE, FIRE_GRADIENT, FIRE_BOTTOM_MASK, FIRE_TRIANGLE_NOISE,
	]:
		if not ResourceLoader.exists(path):
			_fail("Required cast preview resource is missing: %s." % path)
	return _errors.is_empty()


func _capture_cast_transition_frame(
	stage: Node2D,
	viewport: SubViewport,
	skeleton_data: Resource,
	sample_time: float,
	sample_index: int,
) -> Dictionary:
	var sprite: Node2D = ClassDB.instantiate("SpineSprite") as Node2D
	if sprite == null:
		_fail("Could not instantiate SpineSprite for cast sample %.7f." % sample_time)
		return {}
	stage.add_child(sprite)
	sprite.call("set_update_mode", SPINE_UPDATE_MODE_MANUAL)
	sprite.set("skeleton_data_res", skeleton_data)
	sprite.scale = Vector2(_scene_scale, _scene_scale)
	sprite.position = _origin + _scene_offset
	var eye_nodes := _create_production_eye_fire(sprite)
	if eye_nodes.is_empty():
		sprite.queue_free()
		return {}
	var eye_slot := eye_nodes["slot"] as Node2D
	var eye_fire := eye_nodes["fire"] as CanvasItem
	var state: Object = sprite.call("get_animation_state")
	var runtime_skeleton: Object = sprite.call("get_skeleton")
	if state == null or runtime_skeleton == null:
		_fail("SpineSprite did not create cast animation state/skeleton at %.7f." % sample_time)
		sprite.queue_free()
		return {}

	state.call("set_animation", "idle_loop", true, 0)
	state.call("update", IDLE_PRE_ROLL)
	state.call("apply", runtime_skeleton)
	sprite.call("update_skeleton", 0.0)
	var cast_entry: Variant = state.call("set_animation", "cast", false, 0)
	state.call("update", sample_time)
	state.call("apply", runtime_skeleton)
	sprite.call("update_skeleton", 0.0)
	var eye_active := sample_time >= CAST_ENTER - EPSILON and sample_time < CLEAR_TIME - EPSILON
	eye_fire.visible = eye_active
	eye_fire.modulate = Color.WHITE

	var slot_report: Dictionary = _visible_character_slots(runtime_skeleton)
	var expected_attachment := CAST_ATTACHMENT if sample_time >= CAST_ENTER - EPSILON and sample_time < CAST_EXIT - EPSILON else BODY_ATTACHMENT
	var expected_slot := ACTION_SLOT if expected_attachment == CAST_ATTACHMENT else BODY_SLOT
	var visible_attachments: Array = slot_report["visible_attachments"]
	var attachment_contract_ok := (
		visible_attachments.size() == 1
		and str(visible_attachments[0]["slot"]) == expected_slot
		and str(visible_attachments[0]["attachment"]) == expected_attachment
	)
	var expected_sigil: Variant = CAST_SIGIL_ATTACHMENT if sample_time >= 0.10 - EPSILON and sample_time < CLEAR_TIME - EPSILON else null
	var observed_sigil: Variant = _runtime_slot_attachment_name(runtime_skeleton, CAST_SIGIL_SLOT)
	var sigil_contract_ok: bool = observed_sigil == expected_sigil
	var slash_contract_ok: bool = _runtime_slot_attachment_name(runtime_skeleton, "slash_mesh") == null

	var composite := await _capture_cast_render_layer(viewport, "composite", sample_time, sample_index, true)
	if composite.is_empty():
		sprite.queue_free()
		return {}
	var suppression := _suppress_cast_vfx(sprite, runtime_skeleton, eye_fire)
	var character_only := await _capture_cast_render_layer(viewport, "character-only", sample_time, sample_index, true)
	if character_only.is_empty():
		sprite.queue_free()
		return {}
	var expected_visual_change := expected_sigil != null or eye_active
	var isolation_visual_ok := (
		not expected_visual_change
		or str(composite["report"]["sha256"]) != str(character_only["report"]["sha256"])
	)
	if not isolation_visual_ok:
		_fail("Character-only cast redraw at %.7f retained active VFX pixels." % sample_time)

	var eye_only: Dictionary = {}
	if eye_active:
		if not _isolate_eye_fire(sprite, runtime_skeleton, eye_fire):
			sprite.queue_free()
			return {}
		eye_only = await _capture_cast_render_layer(viewport, "eye-only", sample_time, sample_index, true)
		if eye_only.is_empty():
			sprite.queue_free()
			return {}

	var frame_report := {
		"attachment_contract_passed": attachment_contract_ok,
		"character_only": character_only["report"],
		"composite": composite["report"],
		"expected_attachment": expected_attachment,
		"expected_eye_fire_visible": eye_active,
		"expected_sigil_attachment": expected_sigil,
		"expected_slot": expected_slot,
		"eye_fire_visible_in_composite": eye_active,
		"eye_slot_global_position": [eye_slot.global_position.x, eye_slot.global_position.y],
		"idle_cast_mix_duration": _track_entry_mix_duration(cast_entry),
		"isolation_visual_change_expected": expected_visual_change,
		"isolation_visual_contract_passed": isolation_visual_ok,
		"observed_sigil_attachment": observed_sigil,
		"passed": (
			bool(composite["report"]["passed"])
			and bool(character_only["report"]["passed"])
			and attachment_contract_ok and sigil_contract_ok and slash_contract_ok
			and bool(suppression["passed"]) and isolation_visual_ok
		),
		"requested_time": sample_time,
		"sigil_contract_passed": sigil_contract_ok,
		"slash_contract_passed": slash_contract_ok,
		"slot_attachments": slot_report["slot_attachments"],
		"suppressed_runtime_vfx": suppression,
		"visible_character_attachment_count": visible_attachments.size(),
		"visible_character_attachments": visible_attachments,
	}
	if not eye_only.is_empty():
		frame_report["eye_only"] = eye_only["report"]
	if not attachment_contract_ok:
		_fail("At %.7f expected exactly %s=%s, observed %s." % [sample_time, expected_slot, expected_attachment, JSON.stringify(visible_attachments)])
	if not sigil_contract_ok:
		_fail("At %.7f expected sigil %s, observed %s." % [sample_time, expected_sigil, observed_sigil])
	if not slash_contract_ok:
		_fail("At %.7f cast retained slash_mesh." % sample_time)
	if not bool(suppression["passed"]):
		_fail("Could not suppress all cast VFX at %.7f." % sample_time)
	sprite.queue_free()
	await process_frame
	var result := {
		"character_image": character_only["image"],
		"composite_image": composite["image"],
		"report": frame_report,
	}
	if not eye_only.is_empty():
		result["eye_image"] = eye_only["image"]
	return result


func _create_production_eye_fire(sprite: Node2D) -> Dictionary:
	var eye_slot: Node2D = ClassDB.instantiate("SpineSlotNode") as Node2D
	if eye_slot == null:
		_fail("Could not instantiate production SpineSlotNode for EyeFire.")
		return {}
	eye_slot.name = "EyeSlot"
	eye_slot.set("slot_name", CAST_EYE_SLOT)
	eye_slot.set("show_behind_parent", true)
	eye_slot.position = Vector2(349.7109, -659.5685)
	eye_slot.rotation = -0.14384604
	eye_slot.scale = Vector2(1.0095462, 1.0182862)
	eye_slot.skew = 0.0025269985
	sprite.add_child(eye_slot)

	var shader: Shader = ResourceLoader.load(EYE_FIRE_SHADER) as Shader
	var texture: Texture2D = ResourceLoader.load(EYE_FIRE_TEXTURE) as Texture2D
	if shader == null or texture == null:
		_fail("Could not load the production EyeFire shader or texture.")
		return {}
	var material := ShaderMaterial.new()
	material.shader = shader
	material.set_shader_parameter("OuterColor", Color(0.46, 0.1, 0.96, 1))
	material.set_shader_parameter("InnerColorStep", Vector2(0.24, 0.49))
	material.set_shader_parameter("Noise2Strength", 1.085)
	material.set_shader_parameter("Noise2Scaling", Vector2.ONE)
	material.set_shader_parameter("Noise2Panning", Vector2(0.4, 0.8))
	material.set_shader_parameter("Noise2Texture", ResourceLoader.load(FIRE_TILE_NOISE))
	material.set_shader_parameter("Noise1Strength", 0.435)
	material.set_shader_parameter("Noise1Scaling", Vector2(0.8, 0.8))
	material.set_shader_parameter("Noise1Panning", Vector2(0.2, 1.0))
	material.set_shader_parameter("Noise1Texture", ResourceLoader.load(FIRE_TRIANGLE_NOISE))
	material.set_shader_parameter("InvertNoiseMask", false)
	material.set_shader_parameter("NoiseMaskScale", Vector2(1.0, 1.305))
	material.set_shader_parameter("NoiseMaskOffset", Vector2(0.0, -0.77))
	material.set_shader_parameter("NoiseMask", ResourceLoader.load(FIRE_GRADIENT))
	material.set_shader_parameter("Distortion2Scale", Vector2.ONE)
	material.set_shader_parameter("Distortion2Panning", Vector2(0.4, 0.4))
	material.set_shader_parameter("Distortion2Texture", ResourceLoader.load(FIRE_TILE_NOISE))
	material.set_shader_parameter("Distortion2Strength", 0.17)
	material.set_shader_parameter("Distortion1Scale", Vector2.ONE)
	material.set_shader_parameter("Distortion1Panning", Vector2(0.0, 1.5))
	material.set_shader_parameter("Distortion1Texture", ResourceLoader.load(FIRE_ZIGZAG))
	material.set_shader_parameter("Distortion1Strength", -0.075)
	material.set_shader_parameter("DistortionMaskScale", Vector2(1.0, 2.0))
	material.set_shader_parameter("DistortionMaskOffset", Vector2(0.0, -0.72))
	material.set_shader_parameter("DistortionMask", ResourceLoader.load(FIRE_BOTTOM_MASK))
	material.set_shader_parameter("InnerColor", Color(0.32, 0.94, 1, 1))
	material.set_shader_parameter("OuterStep", Vector2(0.07, 0.17))

	var eye_fire := TextureRect.new()
	eye_fire.name = "EyeFire"
	eye_fire.material = material
	eye_fire.offset_left = -205.07704
	eye_fire.offset_top = -450.1532
	eye_fire.offset_right = 294.92322
	eye_fire.offset_bottom = 49.846893
	eye_fire.scale = Vector2(0.22, 0.28)
	eye_fire.texture = texture
	eye_fire.visible = false
	eye_slot.add_child(eye_fire)
	return {"fire": eye_fire, "slot": eye_slot}


func _capture_cast_render_layer(
	viewport: SubViewport,
	layer_name: String,
	sample_time: float,
	sample_index: int,
	require_non_empty: bool,
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
	var relative_path := "frames/%s/cast/frame-%02d-t%.7f.png" % [layer_name, sample_index, sample_time]
	var absolute_path := _output_root.path_join(relative_path)
	DirAccess.make_dir_recursive_absolute(absolute_path.get_base_dir())
	var save_error := image.save_png(absolute_path)
	var render_ok := (
		(not require_non_empty or int(alpha.pixel_count) > 0)
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


func _suppress_cast_vfx(sprite: Node2D, runtime_skeleton: Object, eye_fire: CanvasItem) -> Dictionary:
	var before := {}
	var after := {}
	var passed := true
	for slot_name: String in CAST_SUPPRESSED_VFX_SLOTS:
		var slot: Variant = runtime_skeleton.call("find_slot", slot_name)
		if slot == null:
			_fail("Runtime SpineSkeleton could not find VFX slot %s." % slot_name)
			passed = false
			continue
		var slot_object := slot as Object
		before[slot_name] = _runtime_attachment_name(slot_object, slot_name)
		if not slot_object.has_method("set_attachment") or not slot_object.has_method("set_color"):
			_fail("Runtime VFX slot %s lacks suppression methods." % slot_name)
			passed = false
			continue
		var color: Color = slot_object.call("get_color")
		slot_object.call("set_color", Color(color.r, color.g, color.b, 0.0))
		slot_object.call("set_attachment", null)
	eye_fire.visible = false
	eye_fire.modulate = Color(1, 1, 1, 0)
	sprite.call("update_skeleton", 0.0)
	for slot_name: String in CAST_SUPPRESSED_VFX_SLOTS:
		var slot: Variant = runtime_skeleton.call("find_slot", slot_name)
		if slot == null:
			passed = false
			continue
		var slot_object := slot as Object
		if slot_object.has_method("set_attachment"):
			slot_object.call("set_attachment", null)
		if slot_object.has_method("get_color") and slot_object.has_method("set_color"):
			var color: Color = slot_object.call("get_color")
			slot_object.call("set_color", Color(color.r, color.g, color.b, 0.0))
		after[slot_name] = _runtime_attachment_name(slot_object, slot_name)
		if after[slot_name] != null:
			passed = false
	sprite.queue_redraw()
	return {
		"after": after,
		"before": before,
		"external_eye_fire_hidden": not eye_fire.visible and eye_fire.modulate.a <= EPSILON,
		"passed": passed and not eye_fire.visible and eye_fire.modulate.a <= EPSILON,
		"slots": CAST_SUPPRESSED_VFX_SLOTS,
	}


func _isolate_eye_fire(sprite: Node2D, runtime_skeleton: Object, eye_fire: CanvasItem) -> bool:
	var passed := true
	for slot_name: String in [BODY_SLOT, ACTION_SLOT, DEATH_SLOT, "slash_mesh", CAST_SIGIL_SLOT]:
		var slot: Variant = runtime_skeleton.call("find_slot", slot_name)
		if slot == null:
			passed = false
			continue
		var slot_object := slot as Object
		if slot_object.has_method("set_color") and slot_object.has_method("get_color"):
			var color: Color = slot_object.call("get_color")
			slot_object.call("set_color", Color(color.r, color.g, color.b, 0.0))
		if slot_object.has_method("set_attachment"):
			slot_object.call("set_attachment", null)
	eye_fire.modulate = Color.WHITE
	eye_fire.visible = true
	sprite.call("update_skeleton", 0.0)
	sprite.queue_redraw()
	return passed


func _validate_cast_boundary_reports(frame_values: Array) -> bool:
	var by_time := {}
	var passed := true
	for value: Variant in frame_values:
		var frame: Dictionary = value
		by_time[_time_key(float(frame["requested_time"]))] = frame
		if not bool(frame.get("passed", false)):
			passed = false
	for required_time: float in [0.0999, 0.10, 0.2499, 0.25, 0.5999, 0.60, 0.6001, 1.2219, 1.222, 1.2221]:
		if not by_time.has(_time_key(required_time)):
			_fail("Missing exact cast boundary sample %.7f." % required_time)
			passed = false
	if not passed:
		return false
	for transition: Array in [[0.2499, 0.25], [0.5999, 0.60]]:
		var before: Dictionary = by_time[_time_key(float(transition[0]))]
		var after: Dictionary = by_time[_time_key(float(transition[1]))]
		if str(before["visible_character_attachments"]) == str(after["visible_character_attachments"]):
			_fail("Runtime cast person did not switch across %.7f -> %.7f." % transition)
			passed = false
	var sigil_before: Dictionary = by_time[_time_key(0.0999)]
	var sigil_after: Dictionary = by_time[_time_key(0.10)]
	if sigil_before["observed_sigil_attachment"] != null or sigil_after["observed_sigil_attachment"] != CAST_SIGIL_ATTACHMENT:
		_fail("Runtime sigil did not enter at 0.10.")
		passed = false
	var clear_before: Dictionary = by_time[_time_key(1.2219)]
	var clear_at: Dictionary = by_time[_time_key(1.222)]
	var clear_after: Dictionary = by_time[_time_key(1.2221)]
	if clear_before["observed_sigil_attachment"] != CAST_SIGIL_ATTACHMENT or clear_at["observed_sigil_attachment"] != null or clear_after["observed_sigil_attachment"] != null:
		_fail("Runtime sigil did not clear at 1.222000026.")
		passed = false
	return passed


func _cast_character_boundary_comparisons(frame_values: Array) -> Array:
	var by_time := {}
	for value: Variant in frame_values:
		var frame: Dictionary = value
		by_time[_time_key(float(frame["requested_time"]))] = frame
	var result := []
	for transition: Array in [[0.2499, 0.25], [0.5999, 0.60], [0.60, 0.6001]]:
		var before_time := float(transition[0])
		var after_time := float(transition[1])
		if not by_time.has(_time_key(before_time)) or not by_time.has(_time_key(after_time)):
			continue
		var before: Dictionary = by_time[_time_key(before_time)]["character_only"]
		var after: Dictionary = by_time[_time_key(after_time)]["character_only"]
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
