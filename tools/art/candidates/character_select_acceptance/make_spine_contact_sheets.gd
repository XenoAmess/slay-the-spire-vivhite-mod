extends SceneTree

## Builds offline review sheets from the five frames emitted by
## render_vivhite_character_select_preview.gd.  Transparent Spine-only frames
## are composited through a real Windows Vulkan viewport onto a game-like dark
## blue background; source PNGs and their Alpha are never modified.

const DEFAULT_INPUT := ".work/character-select-acceptance/spine-current"
const DEFAULT_OUTPUT := ".work/character-select-acceptance/spine-current/contact-sheets"
const SOURCE_SIZE := Vector2i(2560, 1200)
const COLUMNS := 3
const SCALE := 0.25
const GAP := 8
const PANEL_COLOR := Color("18222c")

var _errors: Array[String] = []
var _repo_root := ""
var _output_root := ""


func _initialize() -> void:
	call_deferred("_run")


func _fail(message: String) -> void:
	_errors.append(message)
	push_error("[character-select-contact-sheets] %s" % message)


func _parse_args() -> Dictionary:
	var options := {"input": DEFAULT_INPUT, "output": DEFAULT_OUTPUT}
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


func _below_work(requested: String) -> String:
	var work_root := _repo_root.path_join(".work").simplify_path()
	var resolved := requested
	if not resolved.is_absolute_path():
		resolved = _repo_root.path_join(resolved)
	resolved = resolved.simplify_path()
	var prefix := work_root.replace("\\", "/").to_lower().trim_suffix("/") + "/"
	if not resolved.replace("\\", "/").to_lower().begins_with(prefix):
		_fail("Path must stay below .work: %s" % resolved)
		return ""
	return resolved


func _png_paths(directory: String) -> Array[String]:
	var result: Array[String] = []
	var dir := DirAccess.open(directory)
	if dir == null:
		_fail("Could not open frame directory: %s" % directory)
		return result
	for file_name in dir.get_files():
		if file_name.to_lower().ends_with(".png"):
			result.append(directory.path_join(file_name).simplify_path())
	result.sort()
	if result.size() != 5:
		_fail("Expected exactly five PNG frames in %s, got %d." % [directory, result.size()])
	return result


func _load_frames(paths: Array[String]) -> Array[Dictionary]:
	var frames: Array[Dictionary] = []
	for path in paths:
		var image := Image.load_from_file(path)
		if image == null or image.is_empty():
			_fail("Could not load frame: %s" % path)
			continue
		if image.get_size() != SOURCE_SIZE:
			_fail("Frame %s is %s, expected %s." % [path, image.get_size(), SOURCE_SIZE])
		frames.append({
			"image": image,
			"path": path,
			"sha256": FileAccess.get_sha256(path),
		})
	return frames


func _render_sheet(frames: Array[Dictionary], output_name: String) -> Dictionary:
	var cell_size := Vector2i(
		int(round(SOURCE_SIZE.x * SCALE)),
		int(round(SOURCE_SIZE.y * SCALE)),
	)
	var rows := ceili(float(frames.size()) / float(COLUMNS))
	var sheet_size := Vector2i(
		COLUMNS * cell_size.x + (COLUMNS + 1) * GAP,
		rows * cell_size.y + (rows + 1) * GAP,
	)
	var viewport := SubViewport.new()
	viewport.size = sheet_size
	viewport.transparent_bg = false
	viewport.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	viewport.render_target_clear_mode = SubViewport.CLEAR_MODE_ALWAYS
	root.add_child(viewport)
	var canvas := Control.new()
	canvas.size = Vector2(sheet_size)
	viewport.add_child(canvas)

	var placements: Array[Dictionary] = []
	for index in range(frames.size()):
		var row := index / COLUMNS
		var column := index % COLUMNS
		var position := Vector2i(
			GAP + column * (cell_size.x + GAP),
			GAP + row * (cell_size.y + GAP),
		)
		var panel := ColorRect.new()
		panel.position = Vector2(position)
		panel.size = Vector2(cell_size)
		panel.color = PANEL_COLOR
		canvas.add_child(panel)
		var texture := TextureRect.new()
		texture.position = Vector2(position)
		texture.size = Vector2(cell_size)
		texture.texture = ImageTexture.create_from_image(frames[index].image)
		texture.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
		texture.stretch_mode = TextureRect.STRETCH_SCALE
		texture.texture_filter = CanvasItem.TEXTURE_FILTER_LINEAR
		canvas.add_child(texture)
		placements.append({
			"index": index,
			"path": str(frames[index].path).replace("\\", "/"),
			"sha256": frames[index].sha256,
			"rect": [position.x, position.y, cell_size.x, cell_size.y],
		})

	await process_frame
	await process_frame
	await RenderingServer.frame_post_draw
	var sheet := viewport.get_texture().get_image()
	if sheet == null or sheet.is_empty():
		_fail("Vulkan returned an empty contact sheet for %s." % output_name)
		viewport.queue_free()
		return {}
	if sheet.get_format() != Image.FORMAT_RGBA8:
		sheet.convert(Image.FORMAT_RGBA8)
	var output_path := _output_root.path_join(output_name).simplify_path()
	var save_error := sheet.save_png(output_path)
	if save_error != OK:
		_fail("Could not save %s: %s." % [output_path, error_string(save_error)])
	viewport.queue_free()
	await process_frame
	return {
		"path": output_path.replace("\\", "/"),
		"size": [sheet_size.x, sheet_size.y],
		"sourceover_background": PANEL_COLOR.to_html(false),
		"scale": SCALE,
		"placements": placements,
	}


func _write_report(report: Dictionary) -> void:
	DirAccess.make_dir_recursive_absolute(_output_root)
	var path := _output_root.path_join("report.json")
	var file := FileAccess.open(path, FileAccess.WRITE)
	if file == null:
		_fail("Could not write report: %s" % path)
		return
	file.store_string(JSON.stringify(report, "\t") + "\n")
	file.close()
	print("[character-select-contact-sheets] Report: %s" % path)


func _run() -> void:
	var options := _parse_args()
	_repo_root = _find_repo_root()
	if options.is_empty() or _repo_root.is_empty():
		quit(1)
		return
	var input_root := _below_work(str(options.input))
	_output_root = _below_work(str(options.output))
	if input_root.is_empty() or _output_root.is_empty():
		quit(1)
		return
	DirAccess.make_dir_recursive_absolute(_output_root)

	if DisplayServer.get_name() != "Windows":
		_fail("Expected Windows display server, got %s." % DisplayServer.get_name())
	if RenderingServer.get_current_rendering_driver_name().to_lower() != "vulkan":
		_fail("Expected Vulkan renderer.")
	var full_frames := _load_frames(_png_paths(input_root.path_join("frames")))
	var spine_frames := _load_frames(_png_paths(input_root.path_join("spine-only")))
	var hero_frames := _load_frames(_png_paths(input_root.path_join("hero-only")))
	var report := {
		"schema_version": 1,
		"success": false,
		"display_server": DisplayServer.get_name(),
		"rendering_driver": RenderingServer.get_current_rendering_driver_name(),
		"source_size": [SOURCE_SIZE.x, SOURCE_SIZE.y],
		"sheets": [],
		"errors": [],
	}
	if _errors.is_empty():
		report.sheets.append(await _render_sheet(full_frames, "animation-full-scene.png"))
		report.sheets.append(await _render_sheet(spine_frames, "animation-spine-sourceover.png"))
		report.sheets.append(await _render_sheet(hero_frames, "animation-hero-only-sourceover.png"))
	report.errors = _errors.duplicate()
	report.success = _errors.is_empty() and report.sheets.size() == 3
	_write_report(report)
	quit(0 if report.success else 1)
