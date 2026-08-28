extends "../../compare/preview/render_combat_rig_compare.gd"

## Exact hidden Windows/Vulkan neutral renderer. Every sample starts from an
## intentionally dirty character/VFX slot state, then enters one of the three
## neutral loops at an exact track time. Captures are the unmodified Vulkan
## output; opaque game-green contact sheets are diagnostic SourceOver copies.

const DATA_PATH := "res://tools/candidates/hybrid_neutral_v3/vivhite_combat_skeleton_data.tres"
const DEFAULT_EXACT_OUTPUT := ".work/combat-rig-compare-preview/hybrid-neutral-v3-exact"
const BODY_SLOT := "vivhite_body"
const BODY_REGION := "vivhite_combat_body"
const ACTION_SLOT := "vivhite_action_pose"
const ATTACK_REGION := "vivhite_combat_attack_peak"
const DEATH_SLOT := "vivhite_death_body"
const DEATH_REGION := "vivhite_combat_death_side"
const SLASH_SLOT := "slash_mesh"
const SLASH_REGION := "vivhite_combat_magic_arc"
const SIGIL_SLOT := "vivhite_magic_sigil"
const SIGIL_REGION := "vivhite_combat_magic_sigil"
const EYE_SLOT := "eye_attach_slot"
const CHARACTER_SLOTS := [BODY_SLOT, ACTION_SLOT, DEATH_SLOT]
const HIDDEN_SLOTS := [ACTION_SLOT, DEATH_SLOT, SLASH_SLOT, SIGIL_SLOT, EYE_SLOT]
const ANCHOR_BONES := [
	"vivhite_eye_anchor",
	"vivhite_hair_left",
	"vivhite_hair_right",
	"vivhite_skirt_left",
	"vivhite_skirt_center",
	"vivhite_skirt_right",
	"vivhite_foot_left",
	"vivhite_foot_right",
]
const VANILLA_CAPTURE_HEIGHT_PX := 252.0
const SAMPLES := [
	{"label": "idle-000", "animation": "idle_loop", "time": 0.0},
	{"label": "idle-025", "animation": "idle_loop", "time": 0.5},
	{"label": "idle-050", "animation": "idle_loop", "time": 1.0},
	{"label": "idle-075", "animation": "idle_loop", "time": 1.5},
	{"label": "idle-100", "animation": "idle_loop", "time": 2.0},
	{"label": "low-000", "animation": "low_health_loop", "time": 0.0},
	{"label": "low-025", "animation": "low_health_loop", "time": 0.366666675},
	{"label": "low-050", "animation": "low_health_loop", "time": 0.73333335},
	{"label": "low-075", "animation": "low_health_loop", "time": 1.100000025},
	{"label": "low-100", "animation": "low_health_loop", "time": 1.4666667},
	{"label": "shop-000", "animation": "relaxed_loop", "time": 0.0},
	{"label": "shop-random-1p37", "animation": "relaxed_loop", "time": 1.37},
	{"label": "shop-025", "animation": "relaxed_loop", "time": 3.00000025},
	{"label": "shop-preview-5p4", "animation": "relaxed_loop", "time": 5.4},
	{"label": "shop-050", "animation": "relaxed_loop", "time": 6.0000005},
	{"label": "shop-075", "animation": "relaxed_loop", "time": 9.00000075},
	{"label": "shop-random-9p9", "animation": "relaxed_loop", "time": 9.9},
	{"label": "shop-pre-end", "animation": "relaxed_loop", "time": 11.9999},
	{"label": "shop-loop-end", "animation": "relaxed_loop", "time": 12.000001},
]
const PROXY_MAX_DIMENSION := 512
const SOLID_THRESHOLDS := [1, 16, 128, 240]
const EPSILON := 0.00002


func _initialize() -> void:
	if DisplayServer.get_name() != "headless":
		DisplayServer.window_set_flag(DisplayServer.WINDOW_FLAG_NO_FOCUS, true)
		DisplayServer.window_set_position(Vector2i(-32000, -32000))
	call_deferred("_run_neutral")


func _run_neutral() -> void:
	var options := _parse_neutral_args()
	if options.is_empty():
		quit(2)
		return
	_output_root = _safe_output_root(str(options.output))
	if _output_root.is_empty():
		quit(2)
		return
	_canvas = Vector2i(int(options.width), int(options.height))
	_scene_scale = float(options["scene-scale"])
	_origin = Vector2(float(options["origin-x"]), float(options["origin-y"]))
	_scene_offset = Vector2(float(options["scene-offset-x"]), float(options["scene-offset-y"]))
	DirAccess.make_dir_recursive_absolute(_output_root)
	if not _prepare_neutral_runtime(str(options.pck)):
		_write_neutral_summary([], {}, false, {})
		quit(2)
		return
	var data: Resource = ResourceLoader.load(DATA_PATH)
	if data == null or not data.is_class("SpineSkeletonDataResource"):
		_fail("Could not load V3 neutral skeleton data.")
		_write_neutral_summary([], {}, false, {})
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
		var capture: Dictionary = await _capture_neutral_sample(stage, viewport, data, SAMPLES[index], index)
		if capture.is_empty():
			continue
		reports.append(capture.report)
		images.append(capture.image)
		validity.append(bool(capture.report.passed))

	var summaries := _summarize_animations(reports)
	var contact_sheets := _write_neutral_contact_sheets(reports, images, validity)
	var all_reports_pass := reports.size() == SAMPLES.size() and validity.all(func(value: bool) -> bool: return value)
	var all_animations_pass := true
	for animation_name: String in summaries:
		if not bool(summaries[animation_name].passed):
			all_animations_pass = false
	var success := all_reports_pass and all_animations_pass and not contact_sheets.is_empty() and _errors.is_empty()
	_write_neutral_summary(reports, summaries, success, contact_sheets)
	if success:
		print("[hybrid-neutral-v3] Hidden Vulkan passed %d/%d exact neutral samples." % [reports.size(), SAMPLES.size()])
		quit(0)
		return
	push_error("[hybrid-neutral-v3] Hidden Vulkan neutral acceptance failed.")
	quit(1)


func _prepare_neutral_runtime(pck_path: String) -> bool:
	if DisplayServer.get_name() == "headless":
		_fail("A Windows display with Vulkan is required; headless uses the dummy rasterizer.")
	if RenderingServer.get_current_rendering_driver_name().to_lower() != "vulkan":
		_fail("Expected Vulkan, got %s." % RenderingServer.get_current_rendering_driver_name())
	if pck_path.is_empty() or not FileAccess.file_exists(pck_path) or not ProjectSettings.load_resource_pack(pck_path, false):
		_fail("Could not mount the base-game PCK.")
	for type_name: String in ["SpineSprite", "SpineSkeletonDataResource"]:
		if not ClassDB.class_exists(type_name):
			_fail("Missing game-compatible Spine class %s." % type_name)
	if not ResourceLoader.exists(DATA_PATH):
		_fail("Neutral candidate .tres is missing: %s." % DATA_PATH)
	return _errors.is_empty()


func _capture_neutral_sample(
	stage: Node2D,
	viewport: SubViewport,
	data: Resource,
	sample: Dictionary,
	index: int,
) -> Dictionary:
	var sprite: Node2D = ClassDB.instantiate("SpineSprite") as Node2D
	if sprite == null:
		_fail("Could not instantiate SpineSprite for %s." % sample.label)
		return {}
	stage.add_child(sprite)
	sprite.call("set_update_mode", SPINE_UPDATE_MODE_MANUAL)
	sprite.set("skeleton_data_res", data)
	sprite.scale = Vector2(_scene_scale, _scene_scale)
	sprite.position = _origin + _scene_offset
	var state: Object = sprite.call("get_animation_state")
	var skeleton: Object = sprite.call("get_skeleton")
	if state == null or skeleton == null:
		_fail("Spine runtime did not initialize for %s." % sample.label)
		sprite.queue_free()
		return {}

	var dirty_before := _dirty_runtime_slots(skeleton)
	var entry: Object = state.call("set_animation", str(sample.animation), true, 0)
	entry.call("set_track_time", float(sample.time))
	state.call("update", 0.0)
	state.call("apply", skeleton)
	sprite.call("update_skeleton", 0.0)

	var attachments := {}
	for slot_name: String in [BODY_SLOT, ACTION_SLOT, DEATH_SLOT, SLASH_SLOT, SIGIL_SLOT, EYE_SLOT]:
		attachments[slot_name] = _attachment_name(skeleton, slot_name)
	var visible_people := 0
	for slot_name: String in CHARACTER_SLOTS:
		visible_people += int(attachments[slot_name] != null)
	var attachment_ok: bool = visible_people == 1 and attachments[BODY_SLOT] == BODY_REGION
	for slot_name: String in HIDDEN_SLOTS:
		attachment_ok = attachment_ok and attachments[slot_name] == null

	var anchors := _capture_anchors(skeleton, sprite.position)
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
	var alpha := _alpha_metrics(image)
	var solids := _solid_metrics(image)
	var core_bbox: Array = solids["128"].bbox
	var visible_bbox: Array = solids["16"].bbox
	var size_ok := _bbox_size_in_range(core_bbox, Vector2i(170, 300), Vector2i(260, 390))
	var eye_ok := _point_in_bbox(anchors["vivhite_eye_anchor"].screen, visible_bbox, 8.0)
	var feet_ok := (
		_point_in_bbox(anchors["vivhite_foot_left"].screen, visible_bbox, 36.0)
		and _point_in_bbox(anchors["vivhite_foot_right"].screen, visible_bbox, 36.0)
	)
	var visual_ok := int(alpha.pixel_count) > 0 and not bool(alpha.touches_canvas_edge) and size_ok and eye_ok and feet_ok
	var relative_path := "frames/%s/%02d-%s.png" % [sample.animation, index, sample.label]
	var absolute_path := _output_root.path_join(relative_path)
	DirAccess.make_dir_recursive_absolute(absolute_path.get_base_dir())
	var save_ok := image.save_png(absolute_path) == OK
	var passed: bool = attachment_ok and visual_ok and save_ok and bool(dirty_before.passed)
	if not passed:
		_fail("Sample %s failed: dirty=%s attachments=%s visual=%s save=%s." % [sample.label, dirty_before.passed, attachment_ok, visual_ok, save_ok])
	var report := {
		"label": sample.label,
		"animation": sample.animation,
		"requested_track_time": sample.time,
		"runtime_animation_time": float(entry.call("get_animation_time")),
		"runtime_track_time": float(entry.call("get_track_time")),
		"dirty_before": dirty_before,
		"attachments_after_seek": attachments,
		"visible_character_attachment_count": visible_people,
		"anchors": anchors,
		"alpha_bbox": alpha.bbox,
		"alpha_centroid": alpha.centroid,
		"solid_alpha": solids,
		"touches_canvas_edge": alpha.touches_canvas_edge,
		"identity_size_gate": size_ok,
		"eye_anchor_gate": eye_ok,
		"foot_anchor_gate": feet_ok,
		"path": relative_path,
		"sha256": _image_sha256(image),
		"passed": passed,
	}
	sprite.queue_free()
	await process_frame
	return {"image": image, "report": report}


func _dirty_runtime_slots(skeleton: Object) -> Dictionary:
	_set_slot(skeleton, BODY_SLOT, null)
	_set_slot(skeleton, ACTION_SLOT, ATTACK_REGION)
	_set_slot(skeleton, DEATH_SLOT, DEATH_REGION)
	_set_slot(skeleton, SLASH_SLOT, SLASH_REGION)
	_set_slot(skeleton, SIGIL_SLOT, SIGIL_REGION)
	var observed := {}
	for slot_name: String in [BODY_SLOT, ACTION_SLOT, DEATH_SLOT, SLASH_SLOT, SIGIL_SLOT]:
		observed[slot_name] = _attachment_name(skeleton, slot_name)
	return {
		"attachments": observed,
		"passed": (
			observed[BODY_SLOT] == null
			and observed[ACTION_SLOT] == ATTACK_REGION
			and observed[DEATH_SLOT] == DEATH_REGION
			and observed[SLASH_SLOT] == SLASH_REGION
			and observed[SIGIL_SLOT] == SIGIL_REGION
		),
	}


func _set_slot(skeleton: Object, slot_name: String, attachment_name: Variant) -> void:
	var slot: Variant = skeleton.call("find_slot", slot_name)
	if slot == null:
		_fail("Runtime skeleton is missing slot %s." % slot_name)
		return
	if attachment_name == null:
		(slot as Object).call("set_attachment", null)
		return
	var attachment: Variant = skeleton.call("get_attachment_by_slot_name", slot_name, attachment_name)
	if attachment == null:
		_fail("Runtime cannot resolve %s/%s." % [slot_name, attachment_name])
		return
	(slot as Object).call("set_attachment", attachment)


func _attachment_name(skeleton: Object, slot_name: String) -> Variant:
	var slot: Variant = skeleton.call("find_slot", slot_name)
	if slot == null:
		_fail("Runtime skeleton is missing slot %s." % slot_name)
		return "<missing>"
	var attachment: Variant = (slot as Object).call("get_attachment")
	if attachment == null:
		return null
	return str((attachment as Object).call("get_attachment_name"))


func _capture_anchors(skeleton: Object, sprite_position: Vector2) -> Dictionary:
	var result := {}
	for bone_name: String in ANCHOR_BONES:
		var bone: Variant = skeleton.call("find_bone", bone_name)
		if bone == null:
			_fail("Runtime skeleton is missing anchor bone %s." % bone_name)
			continue
		var object := bone as Object
		var world := Vector2(float(object.call("get_world_x")), float(object.call("get_world_y")))
		# Spine's imported world Y is already expressed in Godot's screen-space direction.
		var screen := sprite_position + Vector2(world.x * _scene_scale, world.y * _scene_scale)
		result[bone_name] = {
			"world": [world.x, world.y],
			"screen": [screen.x, screen.y],
			"world_rotation": float(object.call("get_world_rotation_x")),
		}
	return result


func _solid_metrics(source: Image) -> Dictionary:
	var image := source.duplicate()
	var source_size := source.get_size()
	var longest := maxi(source_size.x, source_size.y)
	if longest > PROXY_MAX_DIMENSION:
		var factor := float(PROXY_MAX_DIMENSION) / float(longest)
		image.resize(
			maxi(1, int(round(source_size.x * factor))),
			maxi(1, int(round(source_size.y * factor))),
			Image.INTERPOLATE_BILINEAR
		)
	image.convert(Image.FORMAT_RGBA8)
	var size: Vector2i = image.get_size()
	var bytes: PackedByteArray = image.get_data()
	var mins := {}
	var maxs := {}
	var counts := {}
	for threshold: int in SOLID_THRESHOLDS:
		mins[threshold] = Vector2i(size.x, size.y)
		maxs[threshold] = Vector2i(-1, -1)
		counts[threshold] = 0
	for y in size.y:
		var row: int = y * size.x * 4
		for x in size.x:
			var alpha := int(bytes[row + x * 4 + 3])
			for threshold: int in SOLID_THRESHOLDS:
				if alpha < threshold:
					continue
				counts[threshold] = int(counts[threshold]) + 1
				var min_point: Vector2i = mins[threshold]
				var max_point: Vector2i = maxs[threshold]
				mins[threshold] = Vector2i(mini(min_point.x, x), mini(min_point.y, y))
				maxs[threshold] = Vector2i(maxi(max_point.x, x), maxi(max_point.y, y))
	var result := {}
	var scale := Vector2(float(source_size.x) / float(size.x), float(source_size.y) / float(size.y))
	for threshold: int in SOLID_THRESHOLDS:
		var min_point: Vector2i = mins[threshold]
		var max_point: Vector2i = maxs[threshold]
		var bbox := []
		if max_point.x >= min_point.x:
			var start := Vector2(floor(min_point.x * scale.x), floor(min_point.y * scale.y))
			var end := Vector2(ceil((max_point.x + 1) * scale.x), ceil((max_point.y + 1) * scale.y))
			bbox = [int(start.x), int(start.y), int(end.x - start.x), int(end.y - start.y)]
		result[str(threshold)] = {"bbox": bbox, "proxy_pixel_count": counts[threshold]}
	return result


func _bbox_size_in_range(bbox: Array, minimum: Vector2i, maximum: Vector2i) -> bool:
	return bbox.size() == 4 and int(bbox[2]) >= minimum.x and int(bbox[2]) <= maximum.x and int(bbox[3]) >= minimum.y and int(bbox[3]) <= maximum.y


func _point_in_bbox(point_value: Variant, bbox: Array, margin: float) -> bool:
	if not point_value is Array or point_value.size() != 2 or bbox.size() != 4:
		return false
	var point := Vector2(float(point_value[0]), float(point_value[1]))
	return (
		point.x >= float(bbox[0]) - margin
		and point.y >= float(bbox[1]) - margin
		and point.x <= float(bbox[0] + bbox[2]) + margin
		and point.y <= float(bbox[1] + bbox[3]) + margin
	)


func _summarize_animations(reports: Array) -> Dictionary:
	var result := {}
	for animation_name: String in ["idle_loop", "low_health_loop", "relaxed_loop"]:
		var frames := reports.filter(func(frame: Dictionary) -> bool: return str(frame.animation) == animation_name)
		var hashes := {}
		var core_widths: Array[float] = []
		var core_heights: Array[float] = []
		var core_bottoms: Array[float] = []
		var hair_rotations: Array[float] = []
		var skirt_rotations: Array[float] = []
		for frame: Dictionary in frames:
			hashes[str(frame.sha256)] = true
			var bbox: Array = frame.solid_alpha["128"].bbox
			if bbox.size() == 4:
				core_widths.append(float(bbox[2]))
				core_heights.append(float(bbox[3]))
				core_bottoms.append(float(bbox[1] + bbox[3] - 1))
			hair_rotations.append(float(frame.anchors["vivhite_hair_left"].world_rotation))
			skirt_rotations.append(float(frame.anchors["vivhite_skirt_left"].world_rotation))
		var motion_ok := hashes.size() >= 2
		var hair_motion := _range(hair_rotations)
		var skirt_motion := _range(skirt_rotations)
		var inertia_ok := hair_motion > 0.25 and (animation_name == "low_health_loop" or skirt_motion > 0.15)
		var floor_stability := _range(core_bottoms)
		var floor_ok := floor_stability <= 22.0
		var all_frames := frames.size() > 0 and frames.all(func(frame: Dictionary) -> bool: return bool(frame.passed))
		result[animation_name] = {
			"frame_count": frames.size(),
			"unique_frame_hashes": hashes.size(),
			"core_width_px_range": [_minimum(core_widths), _maximum(core_widths)],
			"core_height_px_range": [_minimum(core_heights), _maximum(core_heights)],
			"core_bottom_y_range": [_minimum(core_bottoms), _maximum(core_bottoms)],
			"core_bottom_drift_px": floor_stability,
			"hair_left_world_rotation_range_deg": hair_motion,
			"skirt_left_world_rotation_range_deg": skirt_motion,
			"motion_gate": motion_ok,
			"inertia_gate": inertia_ok,
			"floor_stability_gate": floor_ok,
			"passed": all_frames and motion_ok and inertia_ok and floor_ok,
		}
	return result


func _write_neutral_contact_sheets(reports: Array, images: Array[Image], validity: Array[bool]) -> Dictionary:
	var result := {}
	var all_path := _output_root.path_join("contact-sheets/neutral-all-transparent-on-dark.png")
	if not _write_contact_sheet(images, validity, all_path, 5):
		_fail("Could not write neutral transparent contact sheet.")
		return {}
	result["all_dark"] = _relative_to_output(all_path)
	var game_images: Array[Image] = []
	for image: Image in images:
		var composite := Image.create(image.get_width(), image.get_height(), false, Image.FORMAT_RGBA8)
		composite.fill(Color("243a32"))
		composite.blend_rect(image, Rect2i(Vector2i.ZERO, image.get_size()), Vector2i.ZERO)
		game_images.append(composite)
	var game_path := _output_root.path_join("contact-sheets/neutral-all-game-green-sourceover.png")
	if not _write_contact_sheet(game_images, validity, game_path, 5):
		_fail("Could not write neutral game-green SourceOver contact sheet.")
		return {}
	result["all_game_green"] = _relative_to_output(game_path)
	for animation_name: String in ["idle_loop", "low_health_loop", "relaxed_loop"]:
		var selected_images: Array[Image] = []
		var selected_validity: Array[bool] = []
		for index in reports.size():
			if str(reports[index].animation) == animation_name:
				selected_images.append(images[index])
				selected_validity.append(validity[index])
		var path := _output_root.path_join("contact-sheets/%s.png" % animation_name)
		if not _write_contact_sheet(selected_images, selected_validity, path, 5):
			_fail("Could not write %s contact sheet." % animation_name)
			return {}
		result[animation_name] = _relative_to_output(path)
	return result


func _parse_neutral_args() -> Dictionary:
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
			_fail("Expected '--name value', got %s." % key)
			return {}
		var name := key.trim_prefix("--")
		if not options.has(name):
			_fail("Unknown option %s." % key)
			return {}
		index += 1
		var value := str(args[index])
		if name in ["width", "height"]:
			options[name] = value.to_int()
		elif name in ["scene-scale", "origin-x", "origin-y", "scene-offset-x", "scene-offset-y"]:
			options[name] = value.to_float()
		else:
			options[name] = value
		index += 1
	return options


func _write_neutral_summary(frames: Array, animations: Dictionary, success: bool, contact_sheets: Dictionary) -> void:
	var baseline_height := 0.0
	for frame: Dictionary in frames:
		if str(frame.label) == "idle-000":
			var bbox: Array = frame.solid_alpha["128"].bbox
			if bbox.size() == 4:
				baseline_height = float(bbox[3])
	var report := {
		"schema": 1,
		"candidate": DATA_PATH,
		"display_server": DisplayServer.get_name(),
		"rendering_driver": RenderingServer.get_current_rendering_driver_name(),
		"scene_scale": _scene_scale,
		"authored_character_scale": 0.70,
		"canvas": [_canvas.x, _canvas.y],
		"frames": frames,
		"animations": animations,
		"contact_sheets": contact_sheets,
		"size_comparison": {
			"neutral_idle_core_height_px": baseline_height,
			"vanilla_ironclad_reference_height_px": VANILLA_CAPTURE_HEIGHT_PX,
			"height_ratio_to_vanilla_reference": baseline_height / VANILLA_CAPTURE_HEIGHT_PX if baseline_height > 0.0 else 0.0,
		},
		"errors": _errors,
		"success": success,
	}
	_write_json(_output_root.path_join("summary.json"), report)


func _range(values: Array[float]) -> float:
	return _maximum(values) - _minimum(values) if not values.is_empty() else 0.0


func _minimum(values: Array[float]) -> float:
	if values.is_empty():
		return 0.0
	var result := values[0]
	for value: float in values:
		result = minf(result, value)
	return result


func _maximum(values: Array[float]) -> float:
	if values.is_empty():
		return 0.0
	var result := values[0]
	for value: float in values:
		result = maxf(result, value)
	return result
