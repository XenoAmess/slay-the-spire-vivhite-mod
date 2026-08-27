extends SceneTree

## Captures the Vulkan SubViewport output verbatim. This tool never edits source
## colors, synthesizes alpha, or removes checkerboard/background pixels.

const CONTRACT_PATH := "res://tools/ironclad-skin.contract.json"
const DEFAULT_SIZE := Vector2i(1024, 1024)
const DEFAULT_OUTPUT := ".work/ironclad-render-acceptance"
const EXPECTED_SET_COUNT := 4
const EXPECTED_ANIMATION_COUNT := 15
const MARGIN := 0.08
const SPINE_UPDATE_MODE_MANUAL := 2
const SAMPLE_FRACTIONS: Array[float] = [0.0, 0.25, 0.5, 0.75, 1.0]
const LEGACY_FALLBACK_RIGS := {
	"rest_site": "res://animations/rest_site/ironclad/restsite_ironclad.skel",
	"character_select": "res://animations/character_select/ironclad/characterselect_ironclad.skel",
}

var _errors: Array[String] = []
var _output_root := ""


func _initialize() -> void:
	call_deferred("_render_acceptance_batch")


func _fail(message: String) -> void:
	_errors.append(message)
	push_error("[ironclad-render-acceptance] %s" % message)


func _parse_args() -> Dictionary:
	var options := {
		"contract": CONTRACT_PATH,
		"expected-animation-count": EXPECTED_ANIMATION_COUNT,
		"expected-set-count": EXPECTED_SET_COUNT,
		"height": DEFAULT_SIZE.y,
		"output": DEFAULT_OUTPUT,
		"pck": OS.get_environment("VIVHITE_STS2_PCK_PATH"),
		"rig-mode": "strict",
		"width": DEFAULT_SIZE.x,
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
			"width", "height", "expected-set-count", "expected-animation-count":
				options[name] = value.to_int()
			_:
				options[name] = value
		index += 1
	return options


func _safe_output_root(requested: String) -> String:
	var project_dir := ProjectSettings.globalize_path("res://").simplify_path()
	var repo_dir := project_dir.path_join("..").simplify_path()
	var work_dir := repo_dir.path_join(".work").simplify_path()
	var output := requested
	if output.is_empty():
		output = repo_dir.path_join(DEFAULT_OUTPUT)
	elif not output.is_absolute_path():
		output = repo_dir.path_join(output)
	output = output.simplify_path()
	var normalized_output := output.replace("\\", "/")
	var required_prefix := work_dir.replace("\\", "/").trim_suffix("/") + "/"
	if not normalized_output.begins_with(required_prefix):
		_fail("Output must stay below '%s', got '%s'." % [work_dir, output])
		return ""
	return output


func _load_contract(path: String) -> Dictionary:
	if not FileAccess.file_exists(path):
		_fail("Contract does not exist: %s" % path)
		return {}
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(path))
	if typeof(parsed) != TYPE_DICTIONARY:
		_fail("Contract is not a JSON dictionary: %s" % path)
		return {}
	return parsed as Dictionary


func _resource_path(resource_root: String, relative_path: String) -> String:
	return "res://%s/%s" % [
		resource_root.trim_prefix("/").trim_suffix("/"),
		relative_path.trim_prefix("/"),
	]


func _rig_kind(path: String) -> String:
	var normalized := path.replace("\\", "/").to_lower()
	if (
		normalized.begins_with("res://vivhite/skins/ironclad/")
		and normalized.ends_with(".spjson")
	):
		return "private_spjson"
	if normalized.begins_with("res://animations/") and normalized.ends_with(".skel"):
		return "legacy_vanilla_skel"
	if normalized.begins_with("res://vivhite/skins/ironclad/"):
		return "private_other"
	return "external_other"


func _migration_status(rig_kind: String, declared_rig_kind: String, fallback_constructed: bool) -> String:
	if fallback_constructed:
		return "temporary_legacy_fallback_for_combat_partial"
	match rig_kind:
		"private_spjson":
			return "custom_private_rig"
		"legacy_vanilla_skel":
			if declared_rig_kind == "private_spjson":
				return "declared_private_rig_not_active"
			return "legacy_vanilla_dependency"
		_:
			return "unsupported_rig_source"


func _safe_component(value: String) -> String:
	var result := value
	for character in ["/", "\\", ":", "*", "?", "\"", "<", ">", "|", " "]:
		result = result.replace(character, "-")
	while result.contains("--"):
		result = result.replace("--", "-")
	return result.trim_prefix("-").trim_suffix("-")


func _image_sha256(image: Image) -> String:
	var context := HashingContext.new()
	var start_error := context.start(HashingContext.HASH_SHA256)
	if start_error != OK:
		_fail("Could not start SHA-256 context (error %d)." % start_error)
		return ""
	var update_error := context.update(image.get_data())
	if update_error != OK:
		_fail("Could not hash rendered image (error %d)." % update_error)
		return ""
	return context.finish().hex_encode()


func _used_rect_report(rect: Rect2i) -> Dictionary:
	return {
		"height": rect.size.y,
		"width": rect.size.x,
		"x": rect.position.x,
		"y": rect.position.y,
	}


func _fit_sprite(sprite: Node2D, skeleton_data: Resource, size: Vector2i) -> Dictionary:
	var bounds_position := Vector2(
		float(skeleton_data.call("get_x")),
		-float(skeleton_data.call("get_y")) - float(skeleton_data.call("get_height")),
	)
	var bounds_size := Vector2(
		maxf(1.0, float(skeleton_data.call("get_width"))),
		maxf(1.0, float(skeleton_data.call("get_height"))),
	)
	var render_scale := (1.0 - MARGIN * 2.0) * minf(
		float(size.x) / bounds_size.x,
		float(size.y) / bounds_size.y,
	)
	sprite.scale = Vector2(render_scale, render_scale)
	sprite.position = Vector2(size) * 0.5 - (bounds_position + bounds_size * 0.5) * render_scale
	return {
		"height": bounds_size.y,
		"render_scale": render_scale,
		"width": bounds_size.x,
		"x": bounds_position.x,
		"y": bounds_position.y,
	}


func _capture_frame(
	stage: Node2D,
	viewport: SubViewport,
	skeleton_data: Resource,
	animation_name: String,
	duration: float,
	fraction: float,
	sample_index: int,
	set_name: String,
	animation_dir: String,
	size: Vector2i,
) -> Dictionary:
	var sprite: Node2D = ClassDB.instantiate("SpineSprite") as Node2D
	if sprite == null:
		_fail("Could not instantiate SpineSprite for %s/%s." % [set_name, animation_name])
		return {}
	stage.add_child(sprite)
	sprite.call("set_update_mode", SPINE_UPDATE_MODE_MANUAL)
	sprite.set("skeleton_data_res", skeleton_data)
	var fit := _fit_sprite(sprite, skeleton_data, size)

	var state: Object = sprite.call("get_animation_state")
	if state == null:
		_fail("SpineSprite did not create animation state for %s/%s." % [set_name, animation_name])
		sprite.queue_free()
		return {}
	state.call("set_animation", animation_name, false, 0)
	var sample_time := clampf(duration * fraction, 0.0, duration)
	sprite.call("update_skeleton", sample_time)

	await RenderingServer.frame_post_draw
	var image := viewport.get_texture().get_image()
	if image == null or image.is_empty():
		_fail("Renderer returned an empty image for %s/%s at %.6f." % [set_name, animation_name, fraction])
		sprite.queue_free()
		return {}
	if image.get_format() != Image.FORMAT_RGBA8:
		image.convert(Image.FORMAT_RGBA8)

	var relative_path := "frames/%s/%s/frame-%02d-t%.6f.png" % [
		_safe_component(set_name),
		animation_dir,
		sample_index,
		fraction,
	]
	var absolute_path := _output_root.path_join(relative_path).simplify_path()
	DirAccess.make_dir_recursive_absolute(absolute_path.get_base_dir())
	var save_error := image.save_png(absolute_path)
	if save_error != OK:
		_fail("Could not save '%s' (error %d)." % [absolute_path, save_error])

	var used_rect := image.get_used_rect()
	var non_empty := used_rect.has_area()
	var touches_canvas_edge := non_empty and (
		used_rect.position.x <= 0
		or used_rect.position.y <= 0
		or used_rect.end.x >= size.x
		or used_rect.end.y >= size.y
	)
	var frame_report := {
		"fit": fit,
		"fraction": fraction,
		"non_empty": non_empty,
		"path": relative_path.replace("\\", "/"),
		"sample_time": sample_time,
		"sha256": _image_sha256(image),
		"touches_canvas_edge": touches_canvas_edge,
		"used_rect": _used_rect_report(used_rect),
	}
	sprite.queue_free()
	await process_frame
	return frame_report


func _write_report(report: Dictionary) -> bool:
	if _output_root.is_empty():
		return false
	DirAccess.make_dir_recursive_absolute(_output_root)
	var report_path := _output_root.path_join("report.json")
	var file := FileAccess.open(report_path, FileAccess.WRITE)
	if file == null:
		_fail("Could not open report for writing: %s" % report_path)
		return false
	file.store_string(JSON.stringify(report, "\t") + "\n")
	file.close()
	print("[ironclad-render-acceptance] Report: %s" % report_path)
	return true


func _render_acceptance_batch() -> void:
	var options := _parse_args()
	if options.is_empty():
		quit(1)
		return
	_output_root = _safe_output_root(str(options.output))
	if _output_root.is_empty():
		quit(1)
		return

	var size := Vector2i(int(options.width), int(options.height))
	if size.x < 64 or size.y < 64:
		_fail("Preview dimensions must both be at least 64 pixels.")
		quit(1)
		return
	var rig_mode := str(options["rig-mode"]).to_lower().replace("-", "_")
	if rig_mode not in ["strict", "combat_partial"]:
		_fail("--rig-mode must be 'strict' or 'combat_partial', got '%s'." % options["rig-mode"])
		quit(1)
		return
	if DisplayServer.get_name() == "headless":
		_fail(
			"A real Vulkan display is required. The headless display uses a dummy rasterizer "
			+ "and cannot produce ViewportTexture frames."
		)
		quit(1)
		return
	var rendering_driver := RenderingServer.get_current_rendering_driver_name()
	if rendering_driver.to_lower() != "vulkan":
		_fail("Expected Vulkan, but Godot selected '%s'." % rendering_driver)
		quit(1)
		return

	var pck_path := str(options.pck)
	if pck_path.is_empty() or not FileAccess.file_exists(pck_path):
		_fail("A valid base-game PCK is required via --pck or VIVHITE_STS2_PCK_PATH.")
		quit(1)
		return
	if not ProjectSettings.load_resource_pack(pck_path, false):
		_fail("Could not mount base-game PCK '%s'." % pck_path)
		quit(1)
		return

	for type_name in ["SpineSprite", "SpineSkeletonDataResource"]:
		if not ClassDB.class_exists(type_name):
			_fail("Spine GDExtension class '%s' is unavailable." % type_name)
	if not _errors.is_empty():
		quit(1)
		return

	var contract := _load_contract(str(options.contract))
	if contract.is_empty():
		quit(1)
		return
	var spine_sets: Array = contract.get("spineSets", []) as Array
	var expected_set_count := int(options["expected-set-count"])
	var expected_animation_count := int(options["expected-animation-count"])
	if expected_set_count < 1 or expected_animation_count < 1:
		_fail("Expected set and animation counts must both be positive.")
	if spine_sets.size() != expected_set_count:
		_fail("Contract contains %d Spine sets; expected %d." % [spine_sets.size(), expected_set_count])
	var animation_count := 0
	for value in spine_sets:
		if typeof(value) == TYPE_DICTIONARY:
			animation_count += (value.get("animations", []) as Array).size()
	if animation_count != expected_animation_count:
		_fail("Contract contains %d animations; expected %d." % [animation_count, expected_animation_count])
	if not _errors.is_empty():
		quit(1)
		return

	root.size = size
	root.content_scale_size = size
	root.transparent_bg = true
	root.title = "Vivhite Ironclad render acceptance (offline)"

	var viewport := SubViewport.new()
	viewport.name = "IroncladRenderAcceptanceViewport"
	viewport.size = size
	viewport.transparent_bg = true
	viewport.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	viewport.render_target_clear_mode = SubViewport.CLEAR_MODE_ALWAYS
	root.add_child(viewport)
	var stage := Node2D.new()
	viewport.add_child(stage)

	var report := {
		"animation_count": animation_count,
		"display_server": DisplayServer.get_name(),
		"errors": [],
		"frame_size": [size.x, size.y],
		"generated_utc": Time.get_datetime_string_from_system(true),
		"output_root": _output_root.replace("\\", "/"),
		"rendering_driver": rendering_driver,
		"rig_mode": rig_mode,
		"rig_summary": {
			"declared_private_not_active_sets": [],
			"fallback_constructed_sets": [],
			"legacy_sets": [],
			"private_spjson_sets": [],
			"unsupported_sets": [],
		},
		"sample_fractions": SAMPLE_FRACTIONS,
		"schema_version": 1,
		"sets": [],
	}
	var resource_root := str(contract.get("resourceRoot", "")).trim_prefix("/").trim_suffix("/")
	for set_value in spine_sets:
		var set_data := set_value as Dictionary
		var set_name := str(set_data.get("name", ""))
		var skeleton_path := _resource_path(resource_root, str(set_data.get("skeletonData", "")))
		var declared_rig_path := str(set_data.get("skeletonResource", ""))
		var declared_rig_kind := _rig_kind(declared_rig_path)
		var skeleton_data: Resource = ResourceLoader.load(skeleton_path)
		var fallback_constructed := false
		if (
			(skeleton_data == null or not skeleton_data.is_class("SpineSkeletonDataResource"))
			and rig_mode == "combat_partial"
			and LEGACY_FALLBACK_RIGS.has(set_name)
		):
			var atlas_path := _resource_path(resource_root, str(set_data.get("atlas", "")))
			var atlas_resource: Resource = ResourceLoader.load(atlas_path)
			var fallback_rig_path := str(LEGACY_FALLBACK_RIGS[set_name])
			var fallback_rig: Resource = ResourceLoader.load(fallback_rig_path)
			var fallback_value: Variant = ClassDB.instantiate("SpineSkeletonDataResource")
			if (
				fallback_value is Resource
				and atlas_resource != null
				and atlas_resource.is_class("SpineAtlasResource")
				and fallback_rig != null
				and fallback_rig.is_class("SpineSkeletonFileResource")
			):
				skeleton_data = fallback_value
				skeleton_data.set("atlas_res", atlas_resource)
				skeleton_data.set("skeleton_file_res", fallback_rig)
				fallback_constructed = true
		if skeleton_data == null or not skeleton_data.is_class("SpineSkeletonDataResource"):
			_fail("Could not load SpineSkeletonDataResource '%s'." % skeleton_path)
			continue
		var rig_value: Variant = skeleton_data.get("skeleton_file_res")
		if not rig_value is Resource:
			_fail("Spine data '%s' exposes no skeleton_file_res for set '%s'." % [skeleton_path, set_name])
			continue
		var rig_resource: Resource = rig_value
		if not rig_resource.is_class("SpineSkeletonFileResource"):
			_fail("Loaded rig for '%s' is not a SpineSkeletonFileResource." % set_name)
			continue
		var rig_path := rig_resource.resource_path
		var rig_kind := _rig_kind(rig_path)
		if set_name == "combat" and rig_kind != "private_spjson":
			_fail(
				"Combat must use the private .spjson rig, but its loaded .tres resolves to '%s'." % rig_path
			)
			continue
		if rig_kind == "private_spjson":
			report.rig_summary.private_spjson_sets.append(set_name)
		elif rig_kind == "legacy_vanilla_skel":
			report.rig_summary.legacy_sets.append(set_name)
			if fallback_constructed:
				report.rig_summary.fallback_constructed_sets.append(set_name)
			if declared_rig_kind == "private_spjson":
				report.rig_summary.declared_private_not_active_sets.append(set_name)
		else:
			report.rig_summary.unsupported_sets.append(set_name)
			_fail("Set '%s' loaded unsupported rig resource '%s'." % [set_name, rig_path])
			continue

		var set_report := {
			"animations": [],
			"data_source": "temporary_in_memory" if fallback_constructed else "contract_tres",
			"declared_skeleton_resource": declared_rig_path,
			"migration_status": _migration_status(rig_kind, declared_rig_kind, fallback_constructed),
			"name": set_name,
			"resource": skeleton_path,
			"rig_kind": rig_kind,
			"skeleton_resource": rig_path,
			"spine_version": str(skeleton_data.call("get_version")),
		}
		for animation_value in set_data.get("animations", []):
			var animation_name := str(animation_value)
			var animation: Object = skeleton_data.call("find_animation", animation_name)
			if animation == null:
				_fail("Animation '%s' does not exist in '%s'." % [animation_name, skeleton_path])
				continue
			var duration := float(animation.call("get_duration"))
			var animation_dir := _safe_component(animation_name)
			var animation_report := {
				"duration": duration,
				"frames": [],
				"name": animation_name,
				"safe_name": animation_dir,
			}
			for sample_index in range(SAMPLE_FRACTIONS.size()):
				var fraction := SAMPLE_FRACTIONS[sample_index]
				var frame_report: Dictionary = await _capture_frame(
					stage,
					viewport,
					skeleton_data,
					animation_name,
					duration,
					fraction,
					sample_index,
					set_name,
					animation_dir,
					size,
				)
				if not frame_report.is_empty():
					animation_report.frames.append(frame_report)
			set_report.animations.append(animation_report)
		report.sets.append(set_report)

	var legacy_sets: Array = report.rig_summary.legacy_sets
	var private_sets: Array = report.rig_summary.private_spjson_sets
	var unsupported_sets: Array = report.rig_summary.unsupported_sets
	var full_migration_ready := (
		legacy_sets.is_empty()
		and unsupported_sets.is_empty()
		and private_sets.size() == spine_sets.size()
	)
	if rig_mode == "strict" and not full_migration_ready:
		_fail(
			"Strict acceptance forbids legacy vanilla rigs; still loaded: %s." % ", ".join(legacy_sets)
		)
	report["acceptance_scope"] = "full" if rig_mode == "strict" else "combat_only"
	report["full_migration_ready"] = full_migration_ready
	report.errors = _errors.duplicate()
	report["success"] = _errors.is_empty()
	_write_report(report)
	if _errors.is_empty():
		print(
			"[ironclad-render-acceptance] Rendered %d animations x %d samples with Vulkan." % [
				animation_count,
				SAMPLE_FRACTIONS.size(),
			]
		)
		quit(0)
		return
	quit(1)
