extends "../../compare/preview/render_combat_rig_compare.gd"

## Hidden Windows/Vulkan renderer for the isolated head-layer probe. It mounts
## the base PCK only to reproduce the game's resource environment; it never
## starts, focuses, deploys to, or controls the game process.

const DATA_PATH := "res://tools/candidates/semantic_butterfly/semantic_butterfly_skeleton_data.tres"
const DEFAULT_PROBE_OUTPUT := ".work/semantic-butterfly-vulkan"
const BUTTERFLY_UNDER_SLOT := "semantic_butterfly_under_front_hair_probe"
const BUTTERFLY_FRONT_SLOT := "semantic_butterfly_front"
const BUTTERFLY_ATTACHMENT := "semantic_butterfly"
const SAMPLES := [
	{"label": "setup-under", "animation": "idle_loop", "time": 0.0, "expected": "under"},
	{"label": "setup-front-ab", "animation": "layer_probe_front", "time": 0.0, "expected": "front"},
	{"label": "idle-local-negative", "animation": "idle_loop", "time": 0.5, "expected": "under"},
	{"label": "idle-local-positive", "animation": "idle_loop", "time": 1.5, "expected": "under"},
	{"label": "heavy-head-negative", "animation": "attack_heavy", "time": 0.12, "expected": "under"},
	{"label": "conservative-max-negative", "animation": "max_negative", "time": 0.0, "expected": "under"},
	{"label": "conservative-max-negative-front-ab", "animation": "max_negative_front", "time": 0.0, "expected": "front"},
	{"label": "hurt-head-positive", "animation": "hurt", "time": 0.1, "expected": "under"},
	{"label": "death-visible-positive", "animation": "die", "time": 1.0499, "expected": "under"},
	{"label": "conservative-max-positive", "animation": "max_positive", "time": 0.0, "expected": "under"},
	{"label": "conservative-max-positive-front-ab", "animation": "max_positive_front", "time": 0.0, "expected": "front"},
	{"label": "death-detached", "animation": "die", "time": 1.05, "expected": "none"},
	{"label": "shop-random-1p37", "animation": "relaxed_loop", "time": 1.37, "expected": "under"},
	{"label": "shop-random-5p4", "animation": "relaxed_loop", "time": 5.4, "expected": "under"},
	{"label": "shop-random-9p9", "animation": "relaxed_loop", "time": 9.9, "expected": "under"},
	{"label": "shop-loop-end", "animation": "relaxed_loop", "time": 12.000001, "expected": "under"},
]


func _initialize() -> void:
	if DisplayServer.get_name() != "headless":
		DisplayServer.window_set_flag(DisplayServer.WINDOW_FLAG_NO_FOCUS, true)
		DisplayServer.window_set_position(Vector2i(-32000, -32000))
	call_deferred("_run_probe")


func _run_probe() -> void:
	var options := _parse_probe_args()
	if options.is_empty():
		quit(2)
		return
	_output_root = _safe_output_root(str(options.output))
	if _output_root.is_empty():
		quit(2)
		return
	_canvas = Vector2i(int(options.width), int(options.height))
	_scene_scale = float(options.scene_scale)
	_origin = Vector2(float(options.origin_x), float(options.origin_y))
	DirAccess.make_dir_recursive_absolute(_output_root)

	if DisplayServer.get_name() == "headless":
		_fail("A Windows display with Vulkan is required; headless uses the dummy rasterizer.")
	if RenderingServer.get_current_rendering_driver_name().to_lower() != "vulkan":
		_fail("Expected Vulkan, got %s." % RenderingServer.get_current_rendering_driver_name())
	var pck := str(options.pck)
	if pck.is_empty() or not FileAccess.file_exists(pck) or not ProjectSettings.load_resource_pack(pck, false):
		_fail("Could not mount the base-game PCK.")
	for type_name: String in ["SpineSprite", "SpineSkeletonDataResource"]:
		if not ClassDB.class_exists(type_name):
			_fail("Missing game-compatible Spine class %s." % type_name)
	var data: Resource = ResourceLoader.load(DATA_PATH)
	if data == null or not data.is_class("SpineSkeletonDataResource"):
		_fail("Could not load semantic butterfly skeleton data.")
	if not _errors.is_empty():
		_write_probe_summary([], false)
		quit(2)
		return

	var viewport := SubViewport.new()
	viewport.size = _canvas
	viewport.transparent_bg = true
	viewport.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	viewport.render_target_clear_mode = SubViewport.CLEAR_MODE_ALWAYS
	root.add_child(viewport)
	var stage := Node2D.new()
	viewport.add_child(stage)

	var reports := []
	var images: Array[Image] = []
	var validity: Array[bool] = []
	for index in SAMPLES.size():
		var result: Dictionary = await _capture_sample(stage, viewport, data, SAMPLES[index], index)
		if result.is_empty():
			continue
		reports.append(result.report)
		images.append(result.image)
		validity.append(bool(result.report.passed))
	var contact_sheet_path := _output_root.path_join("contact-sheets/semantic-butterfly-head-layers.png")
	var sheet_ok := _write_contact_sheet(images, validity, contact_sheet_path, 4)
	var success := reports.size() == SAMPLES.size() and validity.all(func(value: bool) -> bool: return value) and sheet_ok and _errors.is_empty()
	_write_probe_summary(reports, success, _relative_to_output(contact_sheet_path) if sheet_ok else "")
	if success:
		print("[semantic-butterfly] Vulkan probe passed %d/%d head-layer samples." % [reports.size(), SAMPLES.size()])
		quit(0)
		return
	push_error("[semantic-butterfly] Vulkan probe failed.")
	quit(1)


func _capture_sample(stage: Node2D, viewport: SubViewport, data: Resource, sample: Dictionary, index: int) -> Dictionary:
	var sprite: Node2D = ClassDB.instantiate("SpineSprite") as Node2D
	if sprite == null:
		_fail("Could not instantiate SpineSprite for %s." % sample.label)
		return {}
	stage.add_child(sprite)
	sprite.call("set_update_mode", SPINE_UPDATE_MODE_MANUAL)
	sprite.set("skeleton_data_res", data)
	sprite.scale = Vector2(_scene_scale, _scene_scale)
	sprite.position = _origin
	var state: Object = sprite.call("get_animation_state")
	var skeleton: Object = sprite.call("get_skeleton")
	if state == null or skeleton == null:
		_fail("Spine runtime did not initialize for %s." % sample.label)
		sprite.queue_free()
		return {}
	state.call("set_animation", str(sample.animation), false, 0)
	state.call("update", float(sample.time))
	state.call("apply", skeleton)
	sprite.call("update_skeleton", 0.0)

	var under: Variant = _attachment_name(skeleton, BUTTERFLY_UNDER_SLOT)
	var front: Variant = _attachment_name(skeleton, BUTTERFLY_FRONT_SLOT)
	var expected: String = str(sample.expected)
	var slot_ok: bool = (
		(expected == "front" and under == null and front == BUTTERFLY_ATTACHMENT)
		or (expected == "under" and under == BUTTERFLY_ATTACHMENT and front == null)
		or (expected == "none" and under == null and front == null)
	)
	await process_frame
	RenderingServer.force_draw(false)
	await RenderingServer.frame_post_draw
	var image: Image = viewport.get_texture().get_image()
	if image == null or image.is_empty():
		_fail("Renderer returned an empty image for %s." % sample.label)
		sprite.queue_free()
		return {}
	if image.get_format() != Image.FORMAT_RGBA8:
		image.convert(Image.FORMAT_RGBA8)
	var alpha: Dictionary = _alpha_metrics(image)
	var path := "frames/%02d-%s.png" % [index, sample.label]
	var absolute_path := _output_root.path_join(path)
	DirAccess.make_dir_recursive_absolute(absolute_path.get_base_dir())
	var save_ok: bool = image.save_png(absolute_path) == OK
	var visual_ok: bool = int(alpha.pixel_count) > 0 and not bool(alpha.touches_canvas_edge)
	var passed: bool = slot_ok and visual_ok and save_ok
	if not passed:
		_fail("Sample %s failed: slot_ok=%s visual_ok=%s save_ok=%s." % [sample.label, slot_ok, visual_ok, save_ok])
	var report := {
		"label": sample.label,
		"animation": sample.animation,
		"time": sample.time,
		"expected_butterfly_layer": expected,
		"under_attachment": under,
		"front_attachment": front,
		"visible_butterfly_count": int(under != null) + int(front != null),
		"alpha_bbox": alpha.bbox,
		"alpha_centroid": alpha.centroid,
		"touches_canvas_edge": alpha.touches_canvas_edge,
		"path": path,
		"sha256": _image_sha256(image),
		"passed": passed,
	}
	sprite.queue_free()
	await process_frame
	return {"image": image, "report": report}


func _attachment_name(skeleton: Object, slot_name: String) -> Variant:
	var slot: Variant = skeleton.call("find_slot", slot_name)
	if slot == null:
		_fail("Runtime skeleton is missing slot %s." % slot_name)
		return "<missing>"
	var attachment: Variant = (slot as Object).call("get_attachment")
	if attachment == null:
		return null
	return str((attachment as Object).call("get_attachment_name"))


func _parse_probe_args() -> Dictionary:
	var options := {
		"output": DEFAULT_PROBE_OUTPUT,
		"pck": OS.get_environment("VIVHITE_STS2_PCK_PATH"),
		"width": 640,
		"height": 520,
		"scene_scale": 0.28,
		"origin_x": 320.0,
		"origin_y": 270.0,
	}
	var args := OS.get_cmdline_user_args()
	var index := 0
	while index < args.size():
		if index + 1 >= args.size() or not str(args[index]).begins_with("--"):
			_fail("Expected '--name value'.")
			return {}
		var name := str(args[index]).trim_prefix("--").replace("-", "_")
		if not options.has(name):
			_fail("Unknown option %s." % args[index])
			return {}
		index += 1
		var value := str(args[index])
		if name in ["width", "height"]:
			options[name] = value.to_int()
		elif name in ["scene_scale", "origin_x", "origin_y"]:
			options[name] = value.to_float()
		else:
			options[name] = value
		index += 1
	return options


func _write_probe_summary(frames: Array, success: bool, contact_sheet := "") -> void:
	var report := {
		"schema": 1,
		"candidate": DATA_PATH,
		"display_server": DisplayServer.get_name(),
		"rendering_driver": RenderingServer.get_current_rendering_driver_name(),
		"scene_scale": _scene_scale,
		"canvas": [_canvas.x, _canvas.y],
		"samples": frames,
		"contact_sheet": contact_sheet,
		"errors": _errors,
		"success": success,
	}
	_write_json(_output_root.path_join("summary.json"), report)
