extends SceneTree

## Offline acceptance probe for the five Ironclad-replacement UI textures.
## It reads the tracked PNGs without changing their pixels, renders every
## texture at its authored consumer size through a real Windows Vulkan
## SubViewport on black/white/game-blue backgrounds, and writes only below
## .work/. This probe never starts the game or calls an image-generation API.

const DEFAULT_OUTPUT := ".work/character-select-acceptance/ui-current"
const DEFAULT_PCK := "G:/SteamLibrary/steamapps/common/Slay the Spire 2/SlayTheSpire2.pck"
const CELL_PADDING := 16
const COLUMN_GAP := 8
const ROW_GAP := 8
const BACKGROUNDS := [
	{"name": "black", "color": Color(0.0, 0.0, 0.0, 1.0)},
	{"name": "white", "color": Color(1.0, 1.0, 1.0, 1.0)},
	{"name": "game_blue_gray", "color": Color("18222c")},
]
const ASSETS := [
	{
		"id": "icon",
		"runtime": "Vivhite/Vivhite/skins/ironclad/ui/icon.png",
		"approved": "assets/vivhite-ironclad/approved/ui/icon.png",
		"vanilla": "assets/ironclad-v0.111.0/ui/icon.png",
		"width": 85,
		"height": 85,
		"consumer": "CharacterModel.IconTexturePath and Texture2D IconPath wrapper",
	},
	{
		"id": "icon_outline",
		"runtime": "Vivhite/Vivhite/skins/ironclad/ui/icon_outline.png",
		"approved": "assets/vivhite-ironclad/approved/ui/icon_outline.png",
		"vanilla": "assets/ironclad-v0.111.0/ui/icon_outline.png",
		"width": 85,
		"height": 85,
		"consumer": "CharacterModel.IconOutlineTexturePath",
	},
	{
		"id": "select",
		"runtime": "Vivhite/Vivhite/skins/ironclad/ui/select.png",
		"approved": "assets/vivhite-ironclad/approved/ui/select.png",
		"vanilla": "assets/ironclad-v0.111.0/ui/select.png",
		"width": 132,
		"height": 195,
		"consumer": "NCharacterSelectButton unlocked %Icon TextureRect",
	},
	{
		"id": "select_locked",
		"runtime": "Vivhite/Vivhite/skins/ironclad/ui/select_locked.png",
		"approved": "assets/vivhite-ironclad/approved/ui/select_locked.png",
		"vanilla": "assets/ironclad-v0.111.0/ui/select_locked.png",
		"width": 132,
		"height": 195,
		"consumer": "NCharacterSelectButton locked %Icon TextureRect",
	},
	{
		"id": "map_marker",
		"runtime": "Vivhite/Vivhite/skins/ironclad/ui/map_marker.png",
		"approved": "assets/vivhite-ironclad/approved/ui/map_marker.png",
		"vanilla": "assets/ironclad-v0.111.0/ui/map_marker.png",
		"width": 49,
		"height": 64,
		"consumer": "NMapMarker TextureRect; centered by -Size.X/2 and y=-35",
	},
]

var _errors: Array[String] = []
var _warnings: Array[String] = []
var _repo_root := ""
var _output_root := ""


func _initialize() -> void:
	call_deferred("_run")


func _fail(message: String) -> void:
	_errors.append(message)
	push_error("[character-select-ui-acceptance] %s" % message)


func _warn(message: String) -> void:
	_warnings.append(message)
	push_warning("[character-select-ui-acceptance] %s" % message)


func _parse_args() -> Dictionary:
	var options := {"output": DEFAULT_OUTPUT, "pck": DEFAULT_PCK}
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


func _alpha_metrics(image: Image) -> Dictionary:
	var used := image.get_used_rect()
	var corners := [
		image.get_pixel(0, 0).a8,
		image.get_pixel(image.get_width() - 1, 0).a8,
		image.get_pixel(0, image.get_height() - 1).a8,
		image.get_pixel(image.get_width() - 1, image.get_height() - 1).a8,
	]
	var alpha_positive := 0
	var alpha_opaque := 0
	var edges := {
		"top": {"positive": 0, "visible_16": 0, "opaque_240": 0, "max_alpha": 0},
		"right": {"positive": 0, "visible_16": 0, "opaque_240": 0, "max_alpha": 0},
		"bottom": {"positive": 0, "visible_16": 0, "opaque_240": 0, "max_alpha": 0},
		"left": {"positive": 0, "visible_16": 0, "opaque_240": 0, "max_alpha": 0},
	}
	for y in range(image.get_height()):
		for x in range(image.get_width()):
			var alpha := image.get_pixel(x, y).a8
			if alpha > 0:
				alpha_positive += 1
			if alpha >= 240:
				alpha_opaque += 1
			var edge_names: Array[String] = []
			if y == 0:
				edge_names.append("top")
			if x == image.get_width() - 1:
				edge_names.append("right")
			if y == image.get_height() - 1:
				edge_names.append("bottom")
			if x == 0:
				edge_names.append("left")
			for edge_name in edge_names:
				var edge: Dictionary = edges[edge_name]
				edge.max_alpha = maxi(int(edge.max_alpha), alpha)
				if alpha > 0:
					edge.positive = int(edge.positive) + 1
				if alpha >= 16:
					edge.visible_16 = int(edge.visible_16) + 1
				if alpha >= 240:
					edge.opaque_240 = int(edge.opaque_240) + 1
	var touches_edge := used.has_area() and (
		used.position.x <= 0
		or used.position.y <= 0
		or used.end.x >= image.get_width()
		or used.end.y >= image.get_height()
	)
	return {
		"alpha_positive": alpha_positive,
		"alpha_opaque_240": alpha_opaque,
		"corners_alpha": corners,
		"edges": edges,
		"touches_edge": touches_edge,
		"used_rect": {
			"x": used.position.x,
			"y": used.position.y,
			"width": used.size.x,
			"height": used.size.y,
		},
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
	print("[character-select-ui-acceptance] Report: %s" % path)


func _run() -> void:
	var options := _parse_args()
	_repo_root = _find_repo_root()
	if options.is_empty() or _repo_root.is_empty():
		quit(1)
		return
	_output_root = _safe_output(str(options.output))
	if _output_root.is_empty():
		quit(1)
		return

	var report := {
		"schema_version": 1,
		"success": false,
		"display_server": DisplayServer.get_name(),
		"rendering_driver": RenderingServer.get_current_rendering_driver_name(),
		"base_pck": str(options.pck).replace("\\", "/"),
		"output_root": _output_root.replace("\\", "/"),
		"assets": [],
		"backgrounds": [],
		"contact_sheet": "ui-actual-size-sourceover.png",
		"errors": [],
		"warnings": [],
	}
	if DisplayServer.get_name() != "Windows":
		_fail("Expected Windows display server, got %s." % DisplayServer.get_name())
	if RenderingServer.get_current_rendering_driver_name().to_lower() != "vulkan":
		_fail("Expected Vulkan renderer.")
	var pck_path := str(options.pck).simplify_path()
	if not FileAccess.file_exists(pck_path) or not ProjectSettings.load_resource_pack(pck_path, false):
		_fail("Could not mount base-game PCK: %s" % pck_path)

	var loaded: Array[Dictionary] = []
	var max_width := 0
	var sheet_height := ROW_GAP
	for asset: Dictionary in ASSETS:
		var runtime_abs := _repo_root.path_join(str(asset.runtime)).simplify_path()
		var approved_abs := _repo_root.path_join(str(asset.approved)).simplify_path()
		var vanilla_abs := _repo_root.path_join(str(asset.vanilla)).simplify_path()
		var image := Image.load_from_file(runtime_abs)
		if image == null or image.is_empty():
			_fail("Could not load runtime PNG: %s" % asset.runtime)
			continue
		if image.get_format() != Image.FORMAT_RGBA8:
			image.convert(Image.FORMAT_RGBA8)
		var expected := Vector2i(int(asset.width), int(asset.height))
		if image.get_size() != expected:
			_fail("%s is %s, expected %s." % [asset.id, image.get_size(), expected])
		var runtime_sha := FileAccess.get_sha256(runtime_abs)
		var approved_sha := FileAccess.get_sha256(approved_abs)
		if runtime_sha.is_empty() or runtime_sha != approved_sha:
			_fail("%s is not byte-identical to its approved source." % asset.id)
		var alpha := _alpha_metrics(image)
		var vanilla_image := Image.load_from_file(vanilla_abs)
		var vanilla_reference := {}
		if vanilla_image == null or vanilla_image.is_empty():
			_fail("Could not load vanilla reference PNG: %s" % asset.vanilla)
		else:
			if vanilla_image.get_format() != Image.FORMAT_RGBA8:
				vanilla_image.convert(Image.FORMAT_RGBA8)
			if vanilla_image.get_size() != expected:
				_fail("Vanilla %s is %s, expected %s." % [asset.id, vanilla_image.get_size(), expected])
			vanilla_reference = {
				"path": asset.vanilla,
				"size": [vanilla_image.get_width(), vanilla_image.get_height()],
				"sha256": FileAccess.get_sha256(vanilla_abs),
				"alpha": _alpha_metrics(vanilla_image),
			}
		if alpha.alpha_positive <= 0 or alpha.alpha_opaque_240 <= 0:
			_fail("%s has no visible opaque subject." % asset.id)
		if alpha.corners_alpha != [0, 0, 0, 0]:
			_fail("%s has a non-transparent corner: %s." % [asset.id, alpha.corners_alpha])
		if alpha.touches_edge:
			# The art contract treats edge contact as a clipping warning that must be
			# visually checked, not an automatic Alpha failure.  The native-size
			# SourceOver sheet is the decisive evidence for these fixed-size UI
			# consumers; keep the exact edge counts in the JSON for review.
			_warn("%s touches a source edge; inspect its native-size SourceOver row." % asset.id)
		var item := {
			"id": asset.id,
			"consumer": asset.consumer,
			"runtime_path": asset.runtime,
			"approved_path": asset.approved,
			"size": [image.get_width(), image.get_height()],
			"sha256": runtime_sha,
			"byte_identical_to_approved": runtime_sha == approved_sha,
			"alpha": alpha,
			"vanilla_reference": vanilla_reference,
		}
		report.assets.append(item)
		loaded.append({"asset": asset, "image": image})
		max_width = maxi(max_width, image.get_width())
		sheet_height += image.get_height() + ROW_GAP + CELL_PADDING * 2

	var cell_width := max_width + CELL_PADDING * 2
	var sheet_width := (
		ROW_GAP * 2
		+ cell_width * BACKGROUNDS.size()
		+ COLUMN_GAP * (BACKGROUNDS.size() - 1)
	)
	var viewport := SubViewport.new()
	viewport.size = Vector2i(sheet_width, sheet_height)
	viewport.transparent_bg = false
	viewport.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	viewport.render_target_clear_mode = SubViewport.CLEAR_MODE_ALWAYS
	root.add_child(viewport)
	var canvas := Control.new()
	canvas.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	viewport.add_child(canvas)

	var y_cursor := ROW_GAP
	for loaded_item: Dictionary in loaded:
		var asset: Dictionary = loaded_item.asset
		var image: Image = loaded_item.image
		var row_height := image.get_height() + CELL_PADDING * 2
		for column in range(BACKGROUNDS.size()):
			var background: Dictionary = BACKGROUNDS[column]
			var x_cursor := ROW_GAP + column * (cell_width + COLUMN_GAP)
			var panel := ColorRect.new()
			panel.position = Vector2(x_cursor, y_cursor)
			panel.size = Vector2(cell_width, row_height)
			panel.color = background.color
			canvas.add_child(panel)
			var rect := TextureRect.new()
			rect.position = Vector2(
				x_cursor + CELL_PADDING + (max_width - image.get_width()) * 0.5,
				y_cursor + CELL_PADDING,
			)
			rect.size = Vector2(image.get_width(), image.get_height())
			rect.texture = ImageTexture.create_from_image(image)
			rect.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
			rect.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_CENTERED
			rect.texture_filter = CanvasItem.TEXTURE_FILTER_LINEAR
			canvas.add_child(rect)
			report.backgrounds.append({
				"asset": asset.id,
				"background": background.name,
				"texture_rect": [rect.position.x, rect.position.y, rect.size.x, rect.size.y],
				"native_one_to_one": rect.size == Vector2(image.get_width(), image.get_height()),
			})
		y_cursor += row_height + ROW_GAP

	await process_frame
	await process_frame
	await RenderingServer.frame_post_draw
	var sheet := viewport.get_texture().get_image()
	if sheet == null or sheet.is_empty():
		_fail("Vulkan produced no UI contact sheet.")
	else:
		if sheet.get_format() != Image.FORMAT_RGBA8:
			sheet.convert(Image.FORMAT_RGBA8)
		DirAccess.make_dir_recursive_absolute(_output_root)
		var save_error := sheet.save_png(_output_root.path_join(str(report.contact_sheet)))
		if save_error != OK:
			_fail("Could not save UI contact sheet: %s" % error_string(save_error))
		report["contact_sheet_size"] = [sheet.get_width(), sheet.get_height()]

	report.errors = _errors.duplicate()
	report.warnings = _warnings.duplicate()
	report.success = _errors.is_empty() and report.assets.size() == ASSETS.size()
	_write_report(report)
	quit(0 if report.success else 1)
