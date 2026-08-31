extends SceneTree

const DEFAULT_RESOURCE := "res://Vivhite/skins/ironclad/spine/combat/vivhite_combat_skeleton_data.tres"
const DEFAULT_ANIMATION := "idle_loop"
const DEFAULT_SIZE := Vector2i(1024, 1024)
const MARGIN := 0.08
const SPINE_UPDATE_MODE_MANUAL := 2

var _exit_code := 0


func _initialize() -> void:
	# Exact-time acceptance frames must neither receive focus nor advance while
	# waiting for Vulkan draw completion. Keep the helper off-screen and put the
	# SpineSprite in manual update mode below.
	if DisplayServer.get_name() != "headless":
		DisplayServer.window_set_flag(DisplayServer.WINDOW_FLAG_NO_FOCUS, true)
		DisplayServer.window_set_position(Vector2i(-32000, -32000))
	call_deferred("_render_preview")


func _fail(message: String) -> void:
	push_error("[ironclad-preview] %s" % message)
	_exit_code = 1


func _parse_args() -> Dictionary:
	var options := {
		"resource": DEFAULT_RESOURCE,
		"animation": DEFAULT_ANIMATION,
		"time": 0.0,
		"width": DEFAULT_SIZE.x,
		"height": DEFAULT_SIZE.y,
		"scale": 0.0,
		"x": NAN,
		"y": NAN,
		"output": "",
		"pck": OS.get_environment("VIVHITE_STS2_PCK_PATH"),
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
			"time", "scale", "x", "y":
				options[name] = value.to_float()
			"width", "height":
				options[name] = value.to_int()
			_:
				options[name] = value
		index += 1
	return options


func _safe_output_path(requested: String, animation: String, time: float) -> String:
	var project_dir := ProjectSettings.globalize_path("res://").simplify_path()
	var repo_dir := project_dir.path_join("..").simplify_path()
	var work_dir := repo_dir.path_join(".work").simplify_path()
	var output := requested
	if output.is_empty():
		var safe_animation := animation.replace("/", "-").replace("\\", "-")
		output = work_dir.path_join(
			"ironclad-skin-preview/%s-%.3f.png" % [safe_animation, time]
		)
	elif not output.is_absolute_path():
		output = repo_dir.path_join(output)
	output = output.simplify_path()
	var required_prefix := work_dir.trim_suffix("/").trim_suffix("\\") + "/"
	if not output.replace("\\", "/").begins_with(required_prefix.replace("\\", "/")):
		_fail("Output must stay below '%s', got '%s'." % [work_dir, output])
		return ""
	return output


func _render_preview() -> void:
	var options := _parse_args()
	if options.is_empty():
		quit(_exit_code)
		return

	var output_path := _safe_output_path(
		str(options.output),
		str(options.animation),
		float(options.time),
	)
	if output_path.is_empty():
		quit(_exit_code)
		return
	if int(options.width) < 64 or int(options.height) < 64:
		_fail("Preview dimensions must both be at least 64 pixels.")
		quit(_exit_code)
		return
	if DisplayServer.get_name() == "headless":
		_fail(
			"The official Windows Godot headless display uses the dummy rasterizer; "
			+ "Spine can be loaded and sampled, but no ViewportTexture exists to save. "
			+ "Run this script later with an isolated real display driver, or use a Godot "
			+ "build that provides an offscreen renderer."
		)
		quit(_exit_code)
		return

	var pck_path := str(options.pck)
	if pck_path.is_empty() or not FileAccess.file_exists(pck_path):
		_fail("A valid base-game PCK is required via --pck or VIVHITE_STS2_PCK_PATH.")
		quit(_exit_code)
		return
	if not ProjectSettings.load_resource_pack(pck_path, false):
		_fail("Could not mount base-game PCK '%s'." % pck_path)
		quit(_exit_code)
		return

	for type_name in ["SpineSprite", "SpineSkeletonDataResource"]:
		if not ClassDB.class_exists(type_name):
			_fail("Spine GDExtension class '%s' is unavailable." % type_name)
	if _exit_code != 0:
		quit(_exit_code)
		return

	var data_path := str(options.resource)
	var skeleton_data: Resource = ResourceLoader.load(data_path)
	if skeleton_data == null or not skeleton_data.is_class("SpineSkeletonDataResource"):
		_fail("Could not load SpineSkeletonDataResource '%s'." % data_path)
		quit(_exit_code)
		return
	var animation_name := str(options.animation)
	var animation: Object = skeleton_data.call("find_animation", animation_name)
	if animation == null:
		_fail("Animation '%s' does not exist in '%s'." % [animation_name, data_path])
		quit(_exit_code)
		return

	var size := Vector2i(int(options.width), int(options.height))
	root.size = size
	root.content_scale_size = size
	root.transparent_bg = true

	var viewport := SubViewport.new()
	viewport.name = "OfflinePreviewViewport"
	viewport.size = size
	viewport.transparent_bg = true
	viewport.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	viewport.render_target_clear_mode = SubViewport.CLEAR_MODE_ALWAYS
	root.add_child(viewport)

	var stage := Node2D.new()
	viewport.add_child(stage)
	var sprite: Node2D = ClassDB.instantiate("SpineSprite") as Node2D
	if sprite == null:
		_fail("Could not instantiate SpineSprite.")
		quit(_exit_code)
		return
	stage.add_child(sprite)
	sprite.call("set_update_mode", SPINE_UPDATE_MODE_MANUAL)
	sprite.set("skeleton_data_res", skeleton_data)

	var bounds_position := Vector2(
		float(skeleton_data.call("get_x")),
		-float(skeleton_data.call("get_y")) - float(skeleton_data.call("get_height")),
	)
	var bounds_size := Vector2(
		maxf(1.0, float(skeleton_data.call("get_width"))),
		maxf(1.0, float(skeleton_data.call("get_height"))),
	)
	var fitted_scale := (1.0 - MARGIN * 2.0) * minf(
		float(size.x) / bounds_size.x,
		float(size.y) / bounds_size.y,
	)
	var requested_scale := float(options.scale)
	var render_scale := fitted_scale if requested_scale <= 0.0 else requested_scale
	sprite.scale = Vector2(render_scale, render_scale)
	var fitted_position := Vector2(size) * 0.5 - (bounds_position + bounds_size * 0.5) * render_scale
	sprite.position = Vector2(
		fitted_position.x if is_nan(float(options.x)) else float(options.x),
		fitted_position.y if is_nan(float(options.y)) else float(options.y),
	)

	var state: Object = sprite.call("get_animation_state")
	if state == null:
		_fail("SpineSprite did not create an animation state.")
		quit(_exit_code)
		return
	state.call("set_animation", animation_name, false, 0)
	var sample_time := clampf(float(options.time), 0.0, float(animation.call("get_duration")))
	if sample_time > 0.0:
		state.call("update", sample_time)
		state.call("apply", sprite.call("get_skeleton"))
	sprite.call("update_skeleton", 0.0)

	await process_frame
	await process_frame
	RenderingServer.force_draw(false, 0.0)
	var image := viewport.get_texture().get_image()
	if image == null or image.is_empty():
		_fail("Headless renderer returned an empty image.")
		quit(_exit_code)
		return
	DirAccess.make_dir_recursive_absolute(output_path.get_base_dir())
	var save_error := image.save_png(output_path)
	if save_error != OK:
		_fail("Could not save '%s' (error %d)." % [output_path, save_error])
		quit(_exit_code)
		return

	print(JSON.stringify({
		"animation": animation_name,
		"output": output_path,
		"resource": data_path,
		"sample_time": sample_time,
		"size": [size.x, size.y],
		"spine_version": str(skeleton_data.call("get_version")),
	}))
	quit(0)
