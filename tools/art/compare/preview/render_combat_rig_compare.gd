extends SceneTree

## Offline, fixed-layout renderer for comparing alternate Vivhite combat rigs.
##
## The captured PNGs are the Vulkan SubViewport output verbatim.  This script
## never edits source pixels, synthesizes alpha, removes backgrounds, or packs
## runtime atlases.

const DEFAULT_CANVAS := Vector2i(1280, 900)
const DEFAULT_OUTPUT := ".work/combat-rig-compare-preview"
const DEFAULT_SCENE_SCALE := 0.28
const DEFAULT_AUTHORED_CHARACTER_SCALE := 0.70
const DEFAULT_ORIGIN := Vector2(320.0, 700.0)
const DEFAULT_SCENE_OFFSET := Vector2(5.0, -19.0)
const MIN_SAMPLE_COUNT := 5
const ALPHA_THRESHOLD := 1
const ALPHA_METRIC_MAX_DIMENSION := 256
const SPINE_UPDATE_MODE_MANUAL := 2
const DIFF_MAX_DIMENSION := 320
const DIFF_PIXEL_THRESHOLD := 16
const CONTACT_TILE := Vector2i(256, 180)
const CONTACT_GAP := 8
const CONTACT_PADDING := 12

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
const REQUIRED_SLOTS: Array[String] = ["slash_mesh", "eye_attach_slot"]
const REQUIRED_EVENTS: Array[String] = [
	"attack_slash_start",
	"heavy_slash_start",
	"cast_eyes_start",
	"clear_vfx",
]

var _errors: Array[String] = []
var _output_root := ""
var _canvas := DEFAULT_CANVAS
var _sample_count := MIN_SAMPLE_COUNT
var _scene_scale := DEFAULT_SCENE_SCALE
var _authored_character_scale := DEFAULT_AUTHORED_CHARACTER_SCALE
var _origin := DEFAULT_ORIGIN
var _scene_offset := DEFAULT_SCENE_OFFSET


func _initialize() -> void:
	# The wrapper starts Godot with SW_HIDE and an off-screen position. Keep the
	# Vulkan window renderable (a hidden/minimized Window stops emitting reliable
	# frame_post_draw signals after the first capture), but make it unfocusable and
	# leave it far outside every normal desktop coordinate.
	if DisplayServer.get_name() != "headless":
		DisplayServer.window_set_flag(DisplayServer.WINDOW_FLAG_NO_FOCUS, true)
		DisplayServer.window_set_position(Vector2i(-32000, -32000))
	call_deferred("_run")


func _run() -> void:
	var options := _parse_args()
	if options.is_empty():
		quit(2)
		return
	_output_root = _safe_output_root(str(options.output))
	if _output_root.is_empty():
		quit(2)
		return
	_canvas = Vector2i(int(options.width), int(options.height))
	_sample_count = int(options.samples)
	_scene_scale = float(options["scene-scale"])
	_authored_character_scale = float(options["authored-character-scale"])
	_origin = Vector2(float(options["origin-x"]), float(options["origin-y"]))
	_scene_offset = Vector2(float(options["scene-offset-x"]), float(options["scene-offset-y"]))
	if bool(options["self-test"]):
		quit(_self_test())
		return
	await _render_manifest(options)


func _parse_args() -> Dictionary:
	var options := {
		"authored-character-scale": DEFAULT_AUTHORED_CHARACTER_SCALE,
		"height": DEFAULT_CANVAS.y,
		"manifest": "",
		"origin-x": DEFAULT_ORIGIN.x,
		"origin-y": DEFAULT_ORIGIN.y,
		"output": DEFAULT_OUTPUT,
		"pck": OS.get_environment("VIVHITE_STS2_PCK_PATH"),
		"samples": MIN_SAMPLE_COUNT,
		"scene-offset-x": DEFAULT_SCENE_OFFSET.x,
		"scene-offset-y": DEFAULT_SCENE_OFFSET.y,
		"scene-scale": DEFAULT_SCENE_SCALE,
		"self-test": false,
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
			"width", "height", "samples":
				options[name] = value.to_int()
			"scene-scale", "authored-character-scale", "origin-x", "origin-y", \
			"scene-offset-x", "scene-offset-y":
				options[name] = value.to_float()
			"self-test":
				options[name] = value.to_lower() in ["1", "true", "yes"]
			_:
				options[name] = value
		index += 1
	if int(options.width) < 64 or int(options.height) < 64:
		_fail("Canvas dimensions must both be at least 64 pixels.")
	if int(options.samples) < MIN_SAMPLE_COUNT:
		_fail("At least %d samples per animation are required." % MIN_SAMPLE_COUNT)
	if float(options["scene-scale"]) <= 0.0:
		_fail("Scene scale must be positive.")
	if absf(float(options["authored-character-scale"]) - DEFAULT_AUTHORED_CHARACTER_SCALE) > 0.00001:
		_fail(
			"This comparison contract is fixed at authored character scale %.2f; got %.4f."
			% [DEFAULT_AUTHORED_CHARACTER_SCALE, options["authored-character-scale"]]
		)
	return options if _errors.is_empty() else {}


func _safe_output_root(requested: String) -> String:
	var repo_dir := _repository_root()
	var work_dir := repo_dir.path_join(".work").simplify_path()
	var output := requested
	if output.is_empty():
		output = repo_dir.path_join(DEFAULT_OUTPUT)
	elif not output.is_absolute_path():
		output = repo_dir.path_join(output)
	output = output.simplify_path()
	var required_prefix := work_dir.replace("\\", "/").trim_suffix("/") + "/"
	if not output.replace("\\", "/").begins_with(required_prefix):
		_fail("Output must stay below '%s', got '%s'." % [work_dir, output])
		return ""
	return output


func _render_manifest(options: Dictionary) -> void:
	var report := _base_report()
	if DisplayServer.get_name() == "headless":
		_fail("A Windows display with Vulkan is required; Godot headless only exposes the dummy rasterizer.")
	var rendering_driver := RenderingServer.get_current_rendering_driver_name()
	report["display_server"] = DisplayServer.get_name()
	report["rendering_driver"] = rendering_driver
	if rendering_driver.to_lower() != "vulkan":
		_fail("Expected Vulkan, but Godot selected '%s'." % rendering_driver)

	var pck_path := str(options.pck).simplify_path()
	report["base_pck"] = pck_path.replace("\\", "/")
	report["base_pck_sha256"] = FileAccess.get_sha256(pck_path) if FileAccess.file_exists(pck_path) else ""
	if pck_path.is_empty() or not FileAccess.file_exists(pck_path):
		_fail("A valid base-game PCK is required via --pck or VIVHITE_STS2_PCK_PATH.")
	elif not ProjectSettings.load_resource_pack(pck_path, false):
		_fail("Could not mount base-game PCK '%s'." % pck_path)

	for type_name in ["SpineSprite", "SpineSkeletonDataResource"]:
		if not ClassDB.class_exists(type_name):
			_fail("The game's Spine GDExtension class '%s' is unavailable." % type_name)
	var manifest := _load_json(str(options.manifest))
	if manifest.is_empty():
		_fail("Candidate manifest is missing or invalid: %s" % options.manifest)
	var candidates: Array = manifest.get("candidates", []) as Array
	if candidates.size() < 2:
		_fail("Comparison requires at least two candidates; manifest contains %d." % candidates.size())
	if not _errors.is_empty():
		report.errors = _errors.duplicate()
		_write_json(_output_root.path_join("summary.json"), report)
		quit(2)
		return

	var viewport := SubViewport.new()
	viewport.name = "VivhiteCombatRigCompareViewport"
	viewport.size = _canvas
	viewport.transparent_bg = true
	viewport.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	viewport.render_target_clear_mode = SubViewport.CLEAR_MODE_ALWAYS
	root.add_child(viewport)
	var stage := Node2D.new()
	viewport.add_child(stage)

	for candidate_value in candidates:
		if typeof(candidate_value) != TYPE_DICTIONARY:
			_fail("Candidate manifest contains a non-dictionary entry.")
			continue
		var candidate_report := await _render_candidate(
			stage,
			viewport,
			candidate_value as Dictionary,
		)
		report.candidates.append(candidate_report)

	report["pairwise"] = _pairwise_candidate_metrics(report.candidates)
	report.errors = _errors.duplicate()
	report["success"] = _errors.is_empty()
	_write_json(_output_root.path_join("summary.json"), report)
	_write_html(report)
	if _errors.is_empty():
		print(
			"[combat-rig-compare] Rendered %d candidates x %d animations x %d samples with Vulkan."
			% [candidates.size(), REQUIRED_ANIMATIONS.size(), _sample_count]
		)
		quit(0)
		return
	quit(1)


func _base_report() -> Dictionary:
	return {
		"authored_character_scale": _authored_character_scale,
		"canvas": [_canvas.x, _canvas.y],
		"candidates": [],
		"contract": {
			"default_skin": "default",
			"events": REQUIRED_EVENTS,
			"animations": REQUIRED_ANIMATIONS,
			"slots": REQUIRED_SLOTS,
		},
		"display_server": "",
		"errors": [],
		"generated_utc": Time.get_datetime_string_from_system(true),
		"origin": [_origin.x, _origin.y],
		"pairwise": [],
		"rendering_driver": "",
		"sample_count": _sample_count,
		"sample_fractions": _sample_fractions(),
		"scene_offset": [_scene_offset.x, _scene_offset.y],
		"scene_scale": _scene_scale,
		"schema_version": 1,
		"success": false,
	}


func _render_candidate(stage: Node2D, viewport: SubViewport, candidate: Dictionary) -> Dictionary:
	var name := str(candidate.get("name", "unnamed"))
	var slug := _safe_component(str(candidate.get("slug", name)))
	var resource_path := str(candidate.get("resource", ""))
	var candidate_errors: Array[String] = []
	var candidate_report := {
		"animations": [],
		"contact_sheet": "",
		"contract": {},
		"errors": candidate_errors,
		"name": name,
		"passed": false,
		"resource": resource_path,
		"slug": slug,
		"source": candidate.get("source", {}),
	}
	if resource_path.is_empty() or not ResourceLoader.exists(resource_path):
		_candidate_fail(candidate_errors, name, "Skeleton-data resource does not exist: %s" % resource_path)
		return candidate_report
	var skeleton_data: Resource = ResourceLoader.load(resource_path)
	if skeleton_data == null or not skeleton_data.is_class("SpineSkeletonDataResource"):
		_candidate_fail(candidate_errors, name, "Could not load SpineSkeletonDataResource '%s'." % resource_path)
		return candidate_report

	var contract := _validate_spine_contract(skeleton_data)
	candidate_report.contract = contract
	for issue_value in contract.issues:
		_candidate_fail(candidate_errors, name, str(issue_value))
	if not candidate_errors.is_empty():
		return candidate_report

	var all_images: Array[Image] = []
	var all_frame_validity: Array[bool] = []
	for animation_name in REQUIRED_ANIMATIONS:
		var animation: Object = skeleton_data.call("find_animation", animation_name)
		var duration := float(animation.call("get_duration"))
		var animation_report := {
			"duration": duration,
			"frames": [],
			"name": animation_name,
			"safe_name": _safe_component(animation_name),
		}
		var images: Array[Image] = []
		var diff_payloads: Array[Dictionary] = []
		for sample_index in _sample_count:
			var fraction := float(sample_index) / float(_sample_count - 1)
			var captured := await _capture_frame(
				stage,
				viewport,
				skeleton_data,
				animation_name,
				duration,
				fraction,
				sample_index,
				slug,
			)
			if captured.is_empty():
				continue
			var image: Image = captured.image
			var frame_report: Dictionary = captured.report
			images.append(image)
			diff_payloads.append(_make_diff_payload(image))
			animation_report.frames.append(frame_report)
			all_images.append(image)
			all_frame_validity.append(bool(frame_report.passed))
		_finalize_animation_metrics(animation_report, diff_payloads)
		if not bool(animation_report.varying):
			_candidate_fail(candidate_errors, name, "Animation '%s' produced no changing samples." % animation_name)
		var sheet_path := _output_root.path_join(
			"%s/contact-sheets/%s.png" % [slug, _safe_component(animation_name)]
		)
		if not _write_contact_sheet(images, _frame_validity(animation_report.frames), sheet_path, _sample_count):
			_candidate_fail(candidate_errors, name, "Could not write contact sheet for '%s'." % animation_name)
		animation_report["contact_sheet"] = _relative_to_output(sheet_path)
		candidate_report.animations.append(animation_report)

	var master_sheet_path := _output_root.path_join("%s/contact-sheet.png" % slug)
	if not _write_contact_sheet(
		all_images,
		all_frame_validity,
		master_sheet_path,
		_sample_count,
	):
		_candidate_fail(candidate_errors, name, "Could not write candidate contact sheet.")
	candidate_report.contact_sheet = _relative_to_output(master_sheet_path)
	candidate_report["motion_summary"] = _candidate_motion_summary(candidate_report.animations)
	candidate_report.passed = candidate_errors.is_empty()
	return candidate_report


func _validate_spine_contract(skeleton_data: Resource) -> Dictionary:
	var issues: Array[String] = []
	var animations := _named_items(skeleton_data.call("get_animations"))
	var skins := _named_items(skeleton_data.call("get_skins"))
	var slots := _named_items(skeleton_data.call("get_slots"))
	var events := _named_items(skeleton_data.call("get_events"))
	if not skins.has("default"):
		issues.append("Missing default skin.")
	for animation_name in REQUIRED_ANIMATIONS:
		if not animations.has(animation_name):
			issues.append("Missing animation '%s'." % animation_name)
	for slot_name in REQUIRED_SLOTS:
		if skeleton_data.call("find_slot", slot_name) == null:
			issues.append("Missing slot '%s'." % slot_name)
	for event_name in REQUIRED_EVENTS:
		if skeleton_data.call("find_event", event_name) == null:
			issues.append("Missing event '%s'." % event_name)
		elif not events.has(event_name):
			# SpineEventData does not expose get_name() on every 4.2 Godot
			# binding build, while find_event() is the authoritative lookup.
			events[event_name] = true
	var skeleton_file_value: Variant = skeleton_data.get("skeleton_file_res")
	var atlas_value: Variant = skeleton_data.get("atlas_res")
	var skeleton_resource := ""
	var atlas_resource := ""
	if skeleton_file_value is Resource:
		skeleton_resource = (skeleton_file_value as Resource).resource_path
	else:
		issues.append("Skeleton data exposes no skeleton_file_res.")
	if atlas_value is Resource:
		atlas_resource = (atlas_value as Resource).resource_path
	else:
		issues.append("Skeleton data exposes no atlas_res.")
	return {
		"animation_count": animations.size(),
		"animation_names": _sorted_keys(animations),
		"atlas_resource": atlas_resource,
		"event_count": events.size(),
		"event_names": _sorted_keys(events),
		"issues": issues,
		"passed": issues.is_empty(),
		"skeleton_bounds": {
			"height": float(skeleton_data.call("get_height")),
			"width": float(skeleton_data.call("get_width")),
			"x": float(skeleton_data.call("get_x")),
			"y": float(skeleton_data.call("get_y")),
		},
		"skeleton_resource": skeleton_resource,
		"skin_count": skins.size(),
		"skin_names": _sorted_keys(skins),
		"slot_count": slots.size(),
		"slot_names": _sorted_keys(slots),
		"spine_version": str(skeleton_data.call("get_version")),
	}


func _capture_frame(
	stage: Node2D,
	viewport: SubViewport,
	skeleton_data: Resource,
	animation_name: String,
	duration: float,
	fraction: float,
	sample_index: int,
	candidate_slug: String,
) -> Dictionary:
	var sprite: Node2D = ClassDB.instantiate("SpineSprite") as Node2D
	if sprite == null:
		_fail("Could not instantiate SpineSprite for %s/%s." % [candidate_slug, animation_name])
		return {}
	stage.add_child(sprite)
	sprite.call("set_update_mode", SPINE_UPDATE_MODE_MANUAL)
	sprite.set("skeleton_data_res", skeleton_data)
	sprite.scale = Vector2(_scene_scale, _scene_scale)
	sprite.position = _origin + _scene_offset
	var state: Object = sprite.call("get_animation_state")
	if state == null:
		_fail("SpineSprite did not create animation state for %s/%s." % [candidate_slug, animation_name])
		sprite.queue_free()
		return {}
	state.call("set_animation", animation_name, false, 0)
	var sample_time := clampf(duration * fraction, 0.0, duration)
	sprite.call("update_skeleton", sample_time)
	await process_frame
	RenderingServer.force_draw(false)
	await RenderingServer.frame_post_draw
	var image := viewport.get_texture().get_image()
	if image == null or image.is_empty():
		_fail("Renderer returned an empty image for %s/%s at %.6f." % [candidate_slug, animation_name, fraction])
		sprite.queue_free()
		return {}
	if image.get_format() != Image.FORMAT_RGBA8:
		image.convert(Image.FORMAT_RGBA8)
	var alpha := _alpha_metrics(image)
	var relative_path := "%s/frames/%s/frame-%02d-t%.6f.png" % [
		candidate_slug,
		_safe_component(animation_name),
		sample_index,
		fraction,
	]
	var absolute_path := _output_root.path_join(relative_path)
	DirAccess.make_dir_recursive_absolute(absolute_path.get_base_dir())
	var save_error := image.save_png(absolute_path)
	if save_error != OK:
		_fail("Could not save '%s': %s." % [absolute_path, error_string(save_error)])
	var frame_report := {
		"alpha_bbox": alpha.bbox,
		"alpha_centroid": alpha.centroid,
		"alpha_metric_sample_size": alpha.metric_sample_size,
		"alpha_pixel_count_sampled": alpha.pixel_count,
		"alpha_weight_sampled": alpha.alpha_weight,
		"edge_alpha_pixels": alpha.edge_alpha_pixels,
		"fraction": fraction,
		"non_empty": alpha.pixel_count > 0,
		"passed": alpha.pixel_count > 0 and not alpha.touches_canvas_edge and save_error == OK,
		"path": relative_path.replace("\\", "/"),
		"sample_time": sample_time,
		"sha256": _image_sha256(image),
		"touches_canvas_edge": alpha.touches_canvas_edge,
	}
	sprite.queue_free()
	await process_frame
	return {"image": image, "report": frame_report}


func _alpha_metrics(image: Image) -> Dictionary:
	var source_width := image.get_width()
	var source_height := image.get_height()
	# get_used_rect() is implemented in native Godot code and returns the exact
	# non-transparent bounds for the unmodified full-resolution capture.  The
	# alpha-weighted centroid is measured on a bounded proxy and mapped back to
	# source pixels; looping over every 1280x900 byte in GDScript made an 80-frame
	# comparison take tens of minutes without improving visual acceptance.
	var exact_bbox: Rect2i = image.get_used_rect()
	var metric_image: Image = image.duplicate()
	var metric_width := source_width
	var metric_height := source_height
	var longest := maxi(metric_width, metric_height)
	if longest > ALPHA_METRIC_MAX_DIMENSION:
		var metric_scale := float(ALPHA_METRIC_MAX_DIMENSION) / float(longest)
		metric_width = maxi(1, int(round(float(metric_width) * metric_scale)))
		metric_height = maxi(1, int(round(float(metric_height) * metric_scale)))
		metric_image.resize(metric_width, metric_height, Image.INTERPOLATE_BILINEAR)
	metric_image.convert(Image.FORMAT_RGBA8)
	var data := metric_image.get_data()
	var pixel_count := 0
	var alpha_weight := 0.0
	var weighted_x := 0.0
	var weighted_y := 0.0
	var edge_pixels := {"bottom": 0, "left": 0, "right": 0, "top": 0}
	for pixel_index in metric_width * metric_height:
		var alpha := int(data[pixel_index * 4 + 3])
		if alpha <= ALPHA_THRESHOLD:
			continue
		var x := pixel_index % metric_width
		var y := pixel_index / metric_width
		var weight := float(alpha) / 255.0
		pixel_count += 1
		alpha_weight += weight
		weighted_x += float(x) * weight
		weighted_y += float(y) * weight
		if x == 0:
			edge_pixels.left += 1
		if x == metric_width - 1:
			edge_pixels.right += 1
		if y == 0:
			edge_pixels.top += 1
		if y == metric_height - 1:
			edge_pixels.bottom += 1
	var bbox := [exact_bbox.position.x, exact_bbox.position.y, exact_bbox.size.x, exact_bbox.size.y]
	var centroid := [null, null]
	if pixel_count > 0:
		var source_per_metric_x := float(source_width) / float(metric_width)
		var source_per_metric_y := float(source_height) / float(metric_height)
		centroid = [
			(weighted_x / maxf(alpha_weight, 0.000001) + 0.5) * source_per_metric_x - 0.5,
			(weighted_y / maxf(alpha_weight, 0.000001) + 0.5) * source_per_metric_y - 0.5,
		]
	var touches := exact_bbox.has_area() and (
		exact_bbox.position.x <= 0
		or exact_bbox.position.y <= 0
		or exact_bbox.end.x >= source_width
		or exact_bbox.end.y >= source_height
	)
	return {
		"alpha_weight": alpha_weight,
		"bbox": bbox,
		"centroid": centroid,
		"edge_alpha_pixels": edge_pixels,
		"metric_sample_size": [metric_width, metric_height],
		"pixel_count": pixel_count,
		"touches_canvas_edge": touches,
	}


func _finalize_animation_metrics(animation_report: Dictionary, payloads: Array[Dictionary]) -> void:
	var frames: Array = animation_report.frames
	var unique_hashes := {}
	var maximum_changed_ratio := 0.0
	var changes_from_first := []
	for index in frames.size():
		var frame: Dictionary = frames[index]
		unique_hashes[str(frame.sha256)] = true
		var diff := {"changed_pixel_ratio": 0.0, "mean_absolute_rgba": 0.0}
		if index > 0 and not payloads.is_empty():
			diff = _compare_diff_payloads(payloads[0], payloads[index])
		maximum_changed_ratio = maxf(maximum_changed_ratio, float(diff.changed_pixel_ratio))
		changes_from_first.append(diff)
		frame["difference_from_first"] = diff
	animation_report["frame_changes_from_first"] = changes_from_first
	animation_report["maximum_changed_pixel_ratio"] = maximum_changed_ratio
	animation_report["maximum_centroid_displacement_from_first_px"] = _maximum_centroid_displacement(frames, false)
	animation_report["maximum_pairwise_centroid_displacement_px"] = _maximum_centroid_displacement(frames, true)
	animation_report["unique_frame_hashes"] = unique_hashes.size()
	animation_report["varying"] = unique_hashes.size() >= 2 and maximum_changed_ratio > 0.0
	animation_report["passed"] = bool(animation_report.varying) and _all_frames_pass(frames)


func _make_diff_payload(source: Image) -> Dictionary:
	var image: Image = source.duplicate()
	var width: int = image.get_width()
	var height: int = image.get_height()
	var longest: int = maxi(width, height)
	if longest > DIFF_MAX_DIMENSION:
		var scale := float(DIFF_MAX_DIMENSION) / float(longest)
		width = maxi(1, int(round(float(width) * scale)))
		height = maxi(1, int(round(float(height) * scale)))
		image.resize(width, height, Image.INTERPOLATE_BILINEAR)
	image.convert(Image.FORMAT_RGBA8)
	return {"data": image.get_data(), "height": height, "width": width}


func _compare_diff_payloads(first: Dictionary, second: Dictionary) -> Dictionary:
	if int(first.width) != int(second.width) or int(first.height) != int(second.height):
		return {"changed_pixel_ratio": 1.0, "mean_absolute_rgba": 1.0}
	var first_data: PackedByteArray = first.data
	var second_data: PackedByteArray = second.data
	var pixel_count := int(first.width) * int(first.height)
	var changed_pixels := 0
	var absolute_total := 0
	for pixel_index in pixel_count:
		var byte_index := pixel_index * 4
		var pixel_difference := 0
		for channel in 4:
			var difference := absi(int(first_data[byte_index + channel]) - int(second_data[byte_index + channel]))
			pixel_difference += difference
			absolute_total += difference
		if pixel_difference >= DIFF_PIXEL_THRESHOLD:
			changed_pixels += 1
	return {
		"changed_pixel_ratio": float(changed_pixels) / float(maxi(1, pixel_count)),
		"mean_absolute_rgba": float(absolute_total) / float(maxi(1, pixel_count * 4 * 255)),
	}


func _maximum_centroid_displacement(frames: Array, pairwise: bool) -> float:
	var maximum := 0.0
	if frames.size() < 2:
		return maximum
	for left_index in frames.size():
		var left_centroid: Array = frames[left_index].alpha_centroid
		if left_centroid[0] == null:
			continue
		var start := left_index + 1 if pairwise else frames.size()
		var end := frames.size()
		if not pairwise:
			if left_index > 0:
				continue
			start = 1
		for right_index in range(start, end):
			var right_centroid: Array = frames[right_index].alpha_centroid
			if right_centroid[0] == null:
				continue
			var delta := Vector2(
				float(right_centroid[0]) - float(left_centroid[0]),
				float(right_centroid[1]) - float(left_centroid[1]),
			)
			maximum = maxf(maximum, delta.length())
	return maximum


func _candidate_motion_summary(animations: Array) -> Dictionary:
	var maximum_centroid := 0.0
	var maximum_changed := 0.0
	var failed := []
	for animation_value in animations:
		var animation: Dictionary = animation_value
		maximum_centroid = maxf(maximum_centroid, float(animation.maximum_pairwise_centroid_displacement_px))
		maximum_changed = maxf(maximum_changed, float(animation.maximum_changed_pixel_ratio))
		if not bool(animation.passed):
			failed.append(str(animation.name))
	return {
		"failed_animations": failed,
		"maximum_changed_pixel_ratio": maximum_changed,
		"maximum_pairwise_centroid_displacement_px": maximum_centroid,
	}


func _pairwise_candidate_metrics(candidates: Array) -> Array:
	var result := []
	for left_index in candidates.size():
		for right_index in range(left_index + 1, candidates.size()):
			var left: Dictionary = candidates[left_index]
			var right: Dictionary = candidates[right_index]
			var animation_deltas := []
			for animation_name in REQUIRED_ANIMATIONS:
				var left_animation := _find_animation(left.animations, animation_name)
				var right_animation := _find_animation(right.animations, animation_name)
				if left_animation.is_empty() or right_animation.is_empty():
					continue
				animation_deltas.append({
					"animation": animation_name,
					"maximum_centroid_displacement_delta_px": (
						float(right_animation.maximum_pairwise_centroid_displacement_px)
						- float(left_animation.maximum_pairwise_centroid_displacement_px)
					),
					"maximum_changed_pixel_ratio_delta": (
						float(right_animation.maximum_changed_pixel_ratio)
						- float(left_animation.maximum_changed_pixel_ratio)
					),
				})
			result.append({
				"animation_deltas": animation_deltas,
				"left": str(left.name),
				"right": str(right.name),
			})
	return result


func _write_contact_sheet(
	images: Array[Image],
	validity: Array[bool],
	path: String,
	columns: int,
) -> bool:
	if images.is_empty() or columns <= 0:
		return false
	var actual_columns := mini(columns, images.size())
	var rows := int(ceil(float(images.size()) / float(actual_columns)))
	var sheet_size := Vector2i(
		CONTACT_PADDING * 2 + actual_columns * CONTACT_TILE.x + (actual_columns - 1) * CONTACT_GAP,
		CONTACT_PADDING * 2 + rows * CONTACT_TILE.y + (rows - 1) * CONTACT_GAP,
	)
	var sheet := Image.create(sheet_size.x, sheet_size.y, false, Image.FORMAT_RGBA8)
	sheet.fill(Color("11131c"))
	for index in images.size():
		var column := index % actual_columns
		var row := index / actual_columns
		var origin := Vector2i(
			CONTACT_PADDING + column * (CONTACT_TILE.x + CONTACT_GAP),
			CONTACT_PADDING + row * (CONTACT_TILE.y + CONTACT_GAP),
		)
		var border := Color("35d0d0") if validity[index] else Color("ef476f")
		sheet.fill_rect(Rect2i(origin, CONTACT_TILE), border)
		var interior := Rect2i(origin + Vector2i(3, 3), CONTACT_TILE - Vector2i(6, 6))
		sheet.fill_rect(interior, Color("202432"))
		var source: Image = images[index]
		var scale := minf(
			float(interior.size.x) / float(source.get_width()),
			float(interior.size.y) / float(source.get_height()),
		)
		var target_size := Vector2i(
			maxi(1, int(round(float(source.get_width()) * scale))),
			maxi(1, int(round(float(source.get_height()) * scale))),
		)
		var thumbnail := source.duplicate()
		thumbnail.resize(target_size.x, target_size.y, Image.INTERPOLATE_LANCZOS)
		var destination := interior.position + (interior.size - target_size) / 2
		sheet.blend_rect(thumbnail, Rect2i(Vector2i.ZERO, target_size), destination)
	DirAccess.make_dir_recursive_absolute(path.get_base_dir())
	return sheet.save_png(path) == OK


func _write_html(report: Dictionary) -> void:
	var lines := PackedStringArray([
		"<!doctype html>",
		"<meta charset=\"utf-8\">",
		"<title>Vivhite combat rig comparison</title>",
		"<style>body{font:14px system-ui;background:#11131c;color:#eef;margin:24px}section{margin-bottom:28px}img{max-width:100%;background:#202432;border:1px solid #4d556f}code{color:#9ee} .bad{color:#ff718a}</style>",
		"<h1>Vivhite combat rig comparison</h1>",
		"<p>Fixed canvas %dx%d; scene scale %.2f; authored character scale %.2f; %d samples per animation.</p>" % [
			_canvas.x, _canvas.y, _scene_scale, _authored_character_scale, _sample_count,
		],
	])
	for candidate_value in report.candidates:
		var candidate: Dictionary = candidate_value
		lines.append("<section><h2>%s</h2>" % _html_escape(str(candidate.name)))
		if not bool(candidate.passed):
			lines.append("<p class=\"bad\">FAILED: %s</p>" % _html_escape("; ".join(candidate.errors)))
		if not str(candidate.contact_sheet).is_empty():
			lines.append("<img src=\"%s\" alt=\"%s contact sheet\">" % [
				_html_escape(str(candidate.contact_sheet)), _html_escape(str(candidate.name)),
			])
		lines.append("</section>")
	lines.append("<p>See <code>summary.json</code> for alpha bounds, edge contact, frame changes, centroids, and maximum displacement.</p>")
	var file := FileAccess.open(_output_root.path_join("index.html"), FileAccess.WRITE)
	if file != null:
		file.store_string("\n".join(lines) + "\n")


func _self_test() -> int:
	DirAccess.make_dir_recursive_absolute(_output_root)
	var frames := []
	var images: Array[Image] = []
	var payloads: Array[Dictionary] = []
	for index in _sample_count:
		var image := Image.create(_canvas.x, _canvas.y, false, Image.FORMAT_RGBA8)
		image.fill(Color(0.0, 0.0, 0.0, 0.0))
		image.fill_rect(Rect2i(300 + index * 12, 320, 280, 420), Color("c8b8ff"))
		var alpha := _alpha_metrics(image)
		frames.append({
			"alpha_bbox": alpha.bbox,
			"alpha_centroid": alpha.centroid,
			"passed": not alpha.touches_canvas_edge and alpha.pixel_count > 0,
			"sha256": _image_sha256(image),
		})
		images.append(image)
		payloads.append(_make_diff_payload(image))
	var animation_report := {"frames": frames, "name": "fixture"}
	_finalize_animation_metrics(animation_report, payloads)
	var sheet_path := _output_root.path_join("self-test-contact-sheet.png")
	var passed := (
		bool(animation_report.passed)
		and float(animation_report.maximum_pairwise_centroid_displacement_px) > 0.0
		and _write_contact_sheet(images, _frame_validity(frames), sheet_path, _sample_count)
	)
	_write_json(_output_root.path_join("self-test.json"), {
		"animation": animation_report,
		"contact_sheet": _relative_to_output(sheet_path),
		"passed": passed,
	})
	print("[combat-rig-compare] Self-test %s." % ("passed" if passed else "failed"))
	return 0 if passed else 1


func _sample_fractions() -> Array[float]:
	var fractions: Array[float] = []
	for index in _sample_count:
		fractions.append(float(index) / float(_sample_count - 1))
	return fractions


func _named_items(items: Variant) -> Dictionary:
	var names := {}
	if items == null:
		return names
	for item in items:
		if item != null and item.has_method("get_name"):
			names[str(item.call("get_name"))] = true
	return names


func _sorted_keys(values: Dictionary) -> Array[String]:
	var result: Array[String] = []
	for value in values:
		result.append(str(value))
	result.sort()
	return result


func _frame_validity(frames: Array) -> Array[bool]:
	var result: Array[bool] = []
	for frame_value in frames:
		result.append(bool(frame_value.passed))
	return result


func _all_frames_pass(frames: Array) -> bool:
	if frames.size() != _sample_count:
		return false
	for frame_value in frames:
		if not bool(frame_value.passed):
			return false
	return true


func _find_animation(animations: Array, name: String) -> Dictionary:
	for animation_value in animations:
		if str(animation_value.name) == name:
			return animation_value as Dictionary
	return {}


func _safe_component(value: String) -> String:
	var result := value.to_lower()
	for character in ["/", "\\", ":", "*", "?", "\"", "<", ">", "|", " ", "="]:
		result = result.replace(character, "-")
	while result.contains("--"):
		result = result.replace("--", "-")
	return result.trim_prefix("-").trim_suffix("-")


func _image_sha256(image: Image) -> String:
	var context := HashingContext.new()
	if context.start(HashingContext.HASH_SHA256) != OK:
		return ""
	if context.update(image.get_data()) != OK:
		return ""
	return context.finish().hex_encode()


func _load_json(path: String) -> Dictionary:
	if path.is_empty() or not FileAccess.file_exists(path):
		return {}
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(path))
	return parsed as Dictionary if typeof(parsed) == TYPE_DICTIONARY else {}


func _write_json(path: String, value: Variant) -> bool:
	DirAccess.make_dir_recursive_absolute(path.get_base_dir())
	var file := FileAccess.open(path, FileAccess.WRITE)
	if file == null:
		_fail("Could not open JSON output '%s'." % path)
		return false
	file.store_string(JSON.stringify(value, "  ", true) + "\n")
	return true


func _candidate_fail(candidate_errors: Array[String], candidate_name: String, message: String) -> void:
	candidate_errors.append(message)
	_fail("[%s] %s" % [candidate_name, message])


func _relative_to_output(path: String) -> String:
	var root_path := _output_root.replace("\\", "/").trim_suffix("/")
	var normalized := path.replace("\\", "/")
	return normalized.trim_prefix(root_path + "/") if normalized.begins_with(root_path + "/") else normalized


func _repository_root() -> String:
	return ProjectSettings.globalize_path("res://").path_join("..").simplify_path()


func _html_escape(value: String) -> String:
	return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\"", "&quot;")


func _fail(message: String) -> void:
	_errors.append(message)
	push_error("[combat-rig-compare] %s" % message)
