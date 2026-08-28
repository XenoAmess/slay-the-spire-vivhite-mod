extends SceneTree

## Hidden Vulkan renderer for the isolated torso/skirt graybox. Rendered files
## are acceptance evidence only and are written below .work by the wrapper.
## Source textures and Alpha are never modified.

const DATA_PATH := "res://tools/candidates/semantic_torso_skirt/vivhite_semantic_torso_skirt_skeleton_data.tres"
const POSES := ["setup", "max_twist_clockwise", "max_twist_counter_clockwise"]
const ACTUAL_SCALE := 0.28
const INSPECTION_SCALE := 0.70
const ACTUAL_SIZE := Vector2i(480, 420)
const INSPECTION_SIZE := Vector2i(700, 720)
const GAME_BLUE_GRAY := Color8(31, 48, 62, 255)

var _output_root := ""
var _errors: Array[String] = []


func _initialize() -> void:
	var args := OS.get_cmdline_user_args()
	_output_root = _parse_output_root(args)
	if _output_root.is_empty():
		quit(2)
		return
	var error := DirAccess.make_dir_recursive_absolute(_output_root)
	if error != OK and error != ERR_ALREADY_EXISTS:
		push_error("Could not create render output: %s" % _output_root)
		quit(2)
		return
	call_deferred("_run")


func _run() -> void:
	var data: Resource = ResourceLoader.load(DATA_PATH)
	if data == null or not data.is_class("SpineSkeletonDataResource"):
		push_error("Could not load torso/skirt graybox Spine resource")
		quit(2)
		return
	var summary := {
		"schema": 1,
		"candidate": DATA_PATH,
		"renderer": RenderingServer.get_current_rendering_driver_name(),
		"poses": [],
		"actual_scene_scale": ACTUAL_SCALE,
		"inspection_scale": INSPECTION_SCALE,
		"background": [GAME_BLUE_GRAY.r8, GAME_BLUE_GRAY.g8, GAME_BLUE_GRAY.b8, GAME_BLUE_GRAY.a8],
	}
	var actual_composites: Array[Image] = []
	var inspection_composites: Array[Image] = []
	for pose_name: String in POSES:
		var actual := await _capture(data, pose_name, ACTUAL_SCALE, ACTUAL_SIZE, Vector2(240, 365))
		var inspection := await _capture(data, pose_name, INSPECTION_SCALE, INSPECTION_SIZE, Vector2(350, 790))
		if actual.is_empty() or inspection.is_empty():
			continue
		var actual_image: Image = actual["image"]
		var inspection_image: Image = inspection["image"]
		var actual_path := _output_root.path_join("%s-actual-transparent.png" % pose_name)
		var inspection_path := _output_root.path_join("%s-inspection-transparent.png" % pose_name)
		if actual_image.save_png(actual_path) != OK or inspection_image.save_png(inspection_path) != OK:
			_errors.append("Could not save transparent pose frame: %s" % pose_name)
		var actual_composite := _source_over(actual_image, GAME_BLUE_GRAY)
		var inspection_composite := _source_over(inspection_image, GAME_BLUE_GRAY)
		actual_composites.append(actual_composite)
		inspection_composites.append(inspection_composite)
		actual_composite.save_png(_output_root.path_join("%s-actual-blue-gray.png" % pose_name))
		inspection_composite.save_png(_output_root.path_join("%s-inspection-blue-gray.png" % pose_name))
		summary["poses"].append({
			"name": pose_name,
			"actual": actual["metrics"],
			"inspection": inspection["metrics"],
		})

	if actual_composites.size() == POSES.size():
		_write_sheet(actual_composites, ACTUAL_SIZE, _output_root.path_join("contact-sheet-actual-0.28.png"))
	if inspection_composites.size() == POSES.size():
		_write_sheet(inspection_composites, INSPECTION_SIZE, _output_root.path_join("contact-sheet-inspection-0.70.png"))
	if not _write_json(_output_root.path_join("summary.json"), summary):
		_errors.append("Could not save render summary")
	if not _errors.is_empty():
		for message: String in _errors:
			push_error(message)
		quit(2)
		return
	print("Rendered torso/skirt setup and +/-46 degree graybox:")
	print("  actual:     %s" % _output_root.path_join("contact-sheet-actual-0.28.png"))
	print("  inspection: %s" % _output_root.path_join("contact-sheet-inspection-0.70.png"))
	quit(0)


func _capture(
	data: Resource,
	pose_name: String,
	scale_value: float,
	size: Vector2i,
	origin: Vector2,
) -> Dictionary:
	var viewport := SubViewport.new()
	viewport.size = size
	viewport.transparent_bg = true
	viewport.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	root.add_child(viewport)
	var sprite := SpineSprite.new()
	sprite.set("skeleton_data_res", data)
	sprite.position = origin
	sprite.scale = Vector2(scale_value, scale_value)
	viewport.add_child(sprite)
	var state: Object = sprite.call("get_animation_state")
	if state == null:
		_errors.append("No Spine animation state for %s" % pose_name)
		viewport.queue_free()
		return {}
	state.call("set_animation", pose_name, false, 0)
	sprite.call("update_skeleton", 1.0)
	await process_frame
	await process_frame
	RenderingServer.force_draw(false)
	await process_frame
	var image := viewport.get_texture().get_image()
	viewport.queue_free()
	if image == null or image.is_empty():
		_errors.append("Empty viewport capture for %s at %.2f" % [pose_name, scale_value])
		return {}
	var bounds := _alpha_bounds(image)
	var touched := (
		bounds.position.x <= 0 or bounds.position.y <= 0
		or bounds.end.x >= size.x or bounds.end.y >= size.y
	)
	if bounds.size.x <= 0 or bounds.size.y <= 0:
		_errors.append("Transparent pose frame for %s at %.2f" % [pose_name, scale_value])
	if touched:
		_errors.append("Pose frame touches canvas for %s at %.2f: %s" % [pose_name, scale_value, bounds])
	return {
		"image": image,
		"metrics": {
			"canvas": [size.x, size.y],
			"alpha_bbox": [bounds.position.x, bounds.position.y, bounds.size.x, bounds.size.y],
			"touches_canvas": touched,
			"sha256": _sha256_bytes(image.save_png_to_buffer()),
		},
	}


func _source_over(foreground: Image, background: Color) -> Image:
	var composite := Image.create(foreground.get_width(), foreground.get_height(), false, Image.FORMAT_RGBA8)
	composite.fill(background)
	composite.blend_rect(foreground, Rect2i(Vector2i.ZERO, foreground.get_size()), Vector2i.ZERO)
	return composite


func _write_sheet(images: Array[Image], cell_size: Vector2i, path: String) -> void:
	var sheet := Image.create(cell_size.x * images.size(), cell_size.y, false, Image.FORMAT_RGBA8)
	sheet.fill(Color(0, 0, 0, 0))
	for index in images.size():
		sheet.blend_rect(images[index], Rect2i(Vector2i.ZERO, cell_size), Vector2i(index * cell_size.x, 0))
	if sheet.save_png(path) != OK:
		_errors.append("Could not save contact sheet: %s" % path)


func _alpha_bounds(image: Image) -> Rect2i:
	var width := image.get_width()
	var height := image.get_height()
	var bytes := image.get_data()
	var min_x := width
	var min_y := height
	var max_x := -1
	var max_y := -1
	for y in height:
		var row := y * width * 4
		for x in width:
			if int(bytes[row + x * 4 + 3]) == 0:
				continue
			min_x = mini(min_x, x)
			min_y = mini(min_y, y)
			max_x = maxi(max_x, x)
			max_y = maxi(max_y, y)
	if max_x < min_x:
		return Rect2i()
	return Rect2i(min_x, min_y, max_x - min_x + 1, max_y - min_y + 1)


func _parse_output_root(args: PackedStringArray) -> String:
	for index in args.size():
		if args[index] == "--output-root" and index + 1 < args.size():
			return args[index + 1].simplify_path()
	push_error("Missing --output-root PATH")
	return ""


func _write_json(path: String, value: Dictionary) -> bool:
	var file := FileAccess.open(path, FileAccess.WRITE)
	if file == null:
		return false
	file.store_string(JSON.stringify(value, "  ", false) + "\n")
	file.close()
	return true


func _sha256_bytes(bytes: PackedByteArray) -> String:
	var hashing := HashingContext.new()
	hashing.start(HashingContext.HASH_SHA256)
	hashing.update(bytes)
	return hashing.finish().hex_encode()
