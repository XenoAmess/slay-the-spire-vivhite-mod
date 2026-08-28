extends SceneTree

## Hidden Windows/Vulkan acceptance renderer for the four user-exempted
## multiplayer hand textures. It reproduces the base-game hand_image.tscn
## TextureRect geometry (383x1072, keep-aspect-centered) without starting the
## game. All captures are written below .work/ and never feed an asset pipeline.

const CELL := Vector2i(383, 1072)
const HEADER_HEIGHT := 64
const SOURCE_SIZE := Vector2i(422, 1200)
const GESTURES: Array[String] = ["point", "rock", "paper", "scissors"]
const LABELS: Array[String] = ["POINT", "ROCK", "PAPER", "SCISSORS"]
const BACKGROUNDS := [
	{"id": "black", "color": Color.BLACK},
	{"id": "white", "color": Color.WHITE},
	{"id": "gameplay", "color": Color.TRANSPARENT},
]
const POINTING_PIVOT := Vector2(163.0, 10.0)
const FIGHTING_PIVOT := Vector2(197.0, 600.0)
const GRAB_MARKER_IN_TEXTURE_RECT := Vector2(175.0, 222.0)

var _errors: Array[String] = []
var _repo_root := ""
var _output_root := ""


func _initialize() -> void:
	if DisplayServer.get_name() != "headless":
		DisplayServer.window_set_flag(DisplayServer.WINDOW_FLAG_NO_FOCUS, true)
		DisplayServer.window_set_position(Vector2i(-32000, -32000))
	call_deferred("_run")


func _fail(message: String) -> void:
	_errors.append(message)
	push_error("[multiplayer-gesture-vulkan] %s" % message)


func _parse_args() -> Dictionary:
	var options := {"output": ".work/multiplayer-ui-acceptance/vulkan", "gameplay-background": ""}
	var args := OS.get_cmdline_user_args()
	var index := 0
	while index < args.size():
		if index + 1 >= args.size() or not str(args[index]).begins_with("--"):
			_fail("Expected '--name value', got '%s'." % str(args[index]))
			return {}
		var name := str(args[index]).trim_prefix("--")
		if not options.has(name):
			_fail("Unknown option '--%s'." % name)
			return {}
		options[name] = str(args[index + 1])
		index += 2
	return options


func _find_repo_root() -> String:
	var current := ProjectSettings.globalize_path("res://").simplify_path()
	for _depth in range(8):
		if FileAccess.file_exists(current.path_join("AGENTS.md")):
			return current
		var parent := current.get_base_dir()
		if parent == current:
			break
		current = parent
	_fail("Could not locate repository root.")
	return ""


func _safe_output(requested: String) -> String:
	var work_root := _repo_root.path_join(".work").simplify_path()
	var output := requested
	if not output.is_absolute_path():
		output = _repo_root.path_join(output)
	output = output.simplify_path()
	var prefix := work_root.replace("\\", "/").to_lower().trim_suffix("/") + "/"
	if not output.replace("\\", "/").to_lower().begins_with(prefix):
		_fail("Output must stay below .work: %s" % output)
		return ""
	return output


func _load_image(path: String, expected_size: Vector2i) -> Image:
	var image := Image.load_from_file(path)
	if image == null or image.is_empty():
		_fail("Could not load image: %s" % path)
		return Image.new()
	if image.get_format() != Image.FORMAT_RGBA8:
		image.convert(Image.FORMAT_RGBA8)
	if image.get_size() != expected_size:
		_fail("Image %s is %s, expected %s." % [path, image.get_size(), expected_size])
	return image


func _alpha_metrics(image: Image) -> Dictionary:
	var corners := [
		image.get_pixel(0, 0).a8,
		image.get_pixel(image.get_width() - 1, 0).a8,
		image.get_pixel(0, image.get_height() - 1).a8,
		image.get_pixel(image.get_width() - 1, image.get_height() - 1).a8,
	]
	var used := image.get_used_rect()
	return {
		"corners": corners,
		"used_rect": [used.position.x, used.position.y, used.size.x, used.size.y],
	}


func _add_header(canvas: Control) -> void:
	var header := ColorRect.new()
	header.position = Vector2.ZERO
	header.size = Vector2(CELL.x * GESTURES.size(), HEADER_HEIGHT)
	header.color = Color("181b23")
	canvas.add_child(header)
	for index in GESTURES.size():
		var label := Label.new()
		label.text = LABELS[index]
		label.position = Vector2(index * CELL.x + 14, 16)
		label.add_theme_font_size_override("font_size", 22)
		label.add_theme_color_override("font_color", Color.WHITE)
		canvas.add_child(label)


func _add_cross(canvas: Control, position: Vector2, color: Color) -> void:
	var horizontal := ColorRect.new()
	horizontal.position = position - Vector2(18, 1.5)
	horizontal.size = Vector2(36, 3)
	horizontal.color = color
	canvas.add_child(horizontal)
	var vertical := ColorRect.new()
	vertical.position = position - Vector2(1.5, 18)
	vertical.size = Vector2(3, 36)
	vertical.color = color
	canvas.add_child(vertical)


func _render_sheet(
	background: Dictionary,
	gesture_textures: Array[Texture2D],
	gameplay_image: Image,
	draw_pivots: bool,
	variant_id := "",
) -> Dictionary:
	var canvas_size := Vector2i(CELL.x * GESTURES.size(), HEADER_HEIGHT + CELL.y)
	var viewport := SubViewport.new()
	viewport.size = canvas_size
	viewport.transparent_bg = false
	viewport.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	viewport.render_target_clear_mode = SubViewport.CLEAR_MODE_ALWAYS
	root.add_child(viewport)
	var canvas := Control.new()
	canvas.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	viewport.add_child(canvas)
	_add_header(canvas)

	for index in GESTURES.size():
		var cell_position := Vector2(index * CELL.x, HEADER_HEIGHT)
		if str(background.id) == "gameplay":
			var gameplay := TextureRect.new()
			gameplay.position = cell_position
			gameplay.size = Vector2(CELL)
			gameplay.texture = ImageTexture.create_from_image(gameplay_image)
			gameplay.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
			gameplay.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_COVERED
			gameplay.texture_filter = CanvasItem.TEXTURE_FILTER_LINEAR
			gameplay.mouse_filter = Control.MOUSE_FILTER_IGNORE
			canvas.add_child(gameplay)
		else:
			var panel := ColorRect.new()
			panel.position = cell_position
			panel.size = Vector2(CELL)
			panel.color = background.color
			canvas.add_child(panel)

		var gesture := TextureRect.new()
		gesture.position = cell_position
		gesture.size = Vector2(CELL)
		gesture.texture = gesture_textures[index]
		gesture.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
		gesture.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_CENTERED
		gesture.texture_filter = CanvasItem.TEXTURE_FILTER_LINEAR
		gesture.mouse_filter = Control.MOUSE_FILTER_IGNORE
		canvas.add_child(gesture)
		if draw_pivots:
			_add_cross(canvas, cell_position + POINTING_PIVOT, Color("ff5050"))
			_add_cross(canvas, cell_position + FIGHTING_PIVOT, Color("ffd228"))
			_add_cross(canvas, cell_position + GRAB_MARKER_IN_TEXTURE_RECT, Color("32e6ff"))

	await process_frame
	await process_frame
	RenderingServer.force_draw(false)
	await RenderingServer.frame_post_draw
	var capture := viewport.get_texture().get_image()
	if capture == null or capture.is_empty():
		_fail("Vulkan returned an empty %s sheet." % str(background.id))
		viewport.queue_free()
		await process_frame
		return {}
	if capture.get_format() != Image.FORMAT_RGBA8:
		capture.convert(Image.FORMAT_RGBA8)
	var variant := "-%s" % variant_id if not variant_id.is_empty() else ""
	var suffix := "-pivots" if draw_pivots else ""
	var file_name := "sourceover-%s%s-actual-383x1072%s.png" % [
		str(background.id), variant, suffix,
	]
	var output_path := _output_root.path_join(file_name)
	var save_error := capture.save_png(output_path)
	if save_error != OK:
		_fail("Could not save %s: %s" % [output_path, error_string(save_error)])
	viewport.queue_free()
	await process_frame
	return {
		"file": file_name,
		"size": [capture.get_width(), capture.get_height()],
		"sha256": FileAccess.get_sha256(output_path),
	}


func _write_json(path: String, value: Dictionary) -> void:
	var file := FileAccess.open(path, FileAccess.WRITE)
	if file == null:
		_fail("Could not write report: %s" % path)
		return
	file.store_string(JSON.stringify(value, "\t") + "\n")
	file.close()


func _run() -> void:
	var options := _parse_args()
	_repo_root = _find_repo_root()
	if options.is_empty() or _repo_root.is_empty():
		quit(2)
		return
	_output_root = _safe_output(str(options.output))
	if _output_root.is_empty():
		quit(2)
		return
	DirAccess.make_dir_recursive_absolute(_output_root)

	var report := {
		"schema_version": 1,
		"success": false,
		"display_server": DisplayServer.get_name(),
		"rendering_driver": RenderingServer.get_current_rendering_driver_name(),
		"consumer_texture_rect": [CELL.x, CELL.y],
		"source_size": [SOURCE_SIZE.x, SOURCE_SIZE.y],
		"stretch_mode": "keep-aspect-centered",
		"gestures": [],
		"sheets": [],
		"errors": [],
		"multiplayer_end_to_end": "not tested; requires a second client",
	}
	if DisplayServer.get_name() != "Windows":
		_fail("Expected Windows display server, got %s." % DisplayServer.get_name())
	if RenderingServer.get_current_rendering_driver_name().to_lower() != "vulkan":
		_fail("Expected Vulkan rendering driver.")

	var gesture_textures: Array[Texture2D] = []
	var vanilla_textures: Array[Texture2D] = []
	report["vanilla_comparison"] = []
	for gesture_name in GESTURES:
		var relative := "Vivhite/Vivhite/skins/ironclad/multiplayer/%s.png" % gesture_name
		var resource_path := "res://Vivhite/skins/ironclad/multiplayer/%s.png" % gesture_name
		var runtime_path := _repo_root.path_join(relative).simplify_path()
		var approved_path := _repo_root.path_join(
			"assets/vivhite-ironclad/custom/ui/multiplayer/%s.png" % gesture_name
		).simplify_path()
		var exception_path := _repo_root.path_join(
			"assets/vivhite-ironclad/legacy-contaminated/2026-08-27/custom/ui/multiplayer/%s.png"
			% gesture_name
		).simplify_path()
		var image := _load_image(runtime_path, SOURCE_SIZE)
		var vanilla_path := _repo_root.path_join(
			"assets/ironclad-v0.111.0/ui/multiplayer/%s.png" % gesture_name
		).simplify_path()
		var vanilla_image := _load_image(vanilla_path, SOURCE_SIZE)
		vanilla_textures.append(ImageTexture.create_from_image(vanilla_image))
		if not ResourceLoader.exists(resource_path):
			_fail("Godot ResourceLoader cannot see %s." % resource_path)
			gesture_textures.append(ImageTexture.create_from_image(image))
		else:
			var loaded_resource: Resource = ResourceLoader.load(resource_path)
			if not loaded_resource is Texture2D:
				_fail("%s did not import as Texture2D." % resource_path)
				gesture_textures.append(ImageTexture.create_from_image(image))
			else:
				var texture := loaded_resource as Texture2D
				if texture.get_size() != Vector2(SOURCE_SIZE):
					_fail("Imported %s is %s, expected %s." % [resource_path, texture.get_size(), SOURCE_SIZE])
				gesture_textures.append(texture)
		var runtime_hash := FileAccess.get_sha256(runtime_path)
		var approved_hash := FileAccess.get_sha256(approved_path)
		var exception_hash := FileAccess.get_sha256(exception_path)
		if runtime_hash.is_empty() or runtime_hash != approved_hash or runtime_hash != exception_hash:
			_fail("%s is not byte-identical across exception source, approved source, and runtime." % gesture_name)
		var alpha := _alpha_metrics(image)
		if alpha.corners != [0, 0, 0, 0]:
			_fail("%s has a non-transparent source corner: %s." % [gesture_name, alpha.corners])
		report.gestures.append({
			"id": gesture_name,
			"runtime": relative,
			"resource_path": resource_path,
			"resource_loader_texture2d": (
				ResourceLoader.exists(resource_path)
				and ResourceLoader.load(resource_path) is Texture2D
			),
			"sha256": runtime_hash,
			"size": [image.get_width(), image.get_height()],
			"alpha": alpha,
			"exact_exception_approved_runtime_copy": (
				runtime_hash == approved_hash and runtime_hash == exception_hash
			),
		})
		report.vanilla_comparison.append({
			"id": gesture_name,
			"path": vanilla_path.replace("\\", "/"),
			"sha256": FileAccess.get_sha256(vanilla_path),
			"size": [vanilla_image.get_width(), vanilla_image.get_height()],
			"alpha": _alpha_metrics(vanilla_image),
		})

	var gameplay_path := str(options["gameplay-background"]).simplify_path()
	var gameplay := _load_image(gameplay_path, Vector2i(1920, 1080))
	if not gameplay.is_empty():
		report["gameplay_background"] = {
			"path": gameplay_path.replace("\\", "/"),
			"sha256": FileAccess.get_sha256(gameplay_path),
			"use": "SourceOver inspection only; never an asset input",
		}

	for background: Dictionary in BACKGROUNDS:
		report.sheets.append(await _render_sheet(background, gesture_textures, gameplay, false))
	report.sheets.append(await _render_sheet(BACKGROUNDS[2], gesture_textures, gameplay, true))
	report.sheets.append(await _render_sheet(
		BACKGROUNDS[2], vanilla_textures, gameplay, true, "vanilla-comparison"
	))
	report.errors = _errors.duplicate()
	report.success = (
		_errors.is_empty()
		and report.gestures.size() == GESTURES.size()
		and report.sheets.size() == BACKGROUNDS.size() + 2
	)
	_write_json(_output_root.path_join("report.json"), report)
	if bool(report.success):
		print("[multiplayer-gesture-vulkan] Rendered four actual-size Vulkan contact sheets.")
		quit(0)
		return
	quit(1)
