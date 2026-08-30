extends SceneTree

var _png_signature := PackedByteArray([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])
const TARGET_SIZE := Vector2i(1000, 760)
const TARGET_RATIO := Vector2i(25, 19)
const THRESHOLDS := [1, 16, 64, 128, 240]


func _initialize() -> void:
	_run()


func _run() -> void:
	var args := OS.get_cmdline_user_args()
	if args.size() != 2:
		_fail("Expected source PNG and evaluation directory arguments.")
		return

	var source_path: String = args[0]
	var evaluation_dir: String = args[1]
	var file := FileAccess.open(source_path, FileAccess.READ)
	if file == null:
		_fail("Could not open source PNG: %s" % source_path)
		return
	var signature := file.get_buffer(8)
	file.close()
	if signature != _png_signature:
		_fail("Source does not have a PNG signature.")
		return

	var source := Image.load_from_file(source_path)
	if source == null or source.is_empty():
		_fail("Could not decode source PNG: %s" % source_path)
		return
	var source_size := source.get_size()
	var report := {
		"source_path": source_path,
		"png_signature_valid": true,
		"width": source_size.x,
		"height": source_size.y,
		"format": _format_name(source.get_format()),
		"format_value": source.get_format(),
		"has_alpha": source.detect_alpha() != Image.ALPHA_NONE,
		"corners_alpha_8bit": {
			"top_left": _alpha8(source, 0, 0),
			"top_right": _alpha8(source, source_size.x - 1, 0),
			"bottom_left": _alpha8(source, 0, source_size.y - 1),
			"bottom_right": _alpha8(source, source_size.x - 1, source_size.y - 1),
		},
		"alpha_bands": {
			"0": 0,
			"1_15": 0,
			"16_63": 0,
			"64_127": 0,
			"128_239": 0,
			"240_255": 0,
		},
		"alpha_bbox_by_threshold": {},
		"edge_alpha": {},
		"diagnostic_only": true,
		"diagnostic_note": "The resized crop and SourceOver files are inspection copies and must never replace or modify output.png.",
	}

	var boxes := {}
	for threshold: int in THRESHOLDS:
		boxes[str(threshold)] = [source_size.x, source_size.y, -1, -1]

	for y in source_size.y:
		for x in source_size.x:
			var alpha := _alpha8(source, x, y)
			_increment_alpha_band(report["alpha_bands"], alpha)
			for threshold: int in THRESHOLDS:
				if alpha >= threshold:
					var key := str(threshold)
					var box: Array = boxes[key]
					box[0] = mini(box[0], x)
					box[1] = mini(box[1], y)
					box[2] = maxi(box[2], x)
					box[3] = maxi(box[3], y)
					boxes[key] = box

	for threshold: int in THRESHOLDS:
		var key := str(threshold)
		var box: Array = boxes[key]
		if box[2] < box[0] or box[3] < box[1]:
			report["alpha_bbox_by_threshold"][key] = null
		else:
			report["alpha_bbox_by_threshold"][key] = [
				box[0],
				box[1],
				box[2] - box[0] + 1,
				box[3] - box[1] + 1,
			]

	report["edge_alpha"] = {
		"top": _horizontal_edge_stats(source, 0),
		"bottom": _horizontal_edge_stats(source, source_size.y - 1),
		"left": _vertical_edge_stats(source, 0),
		"right": _vertical_edge_stats(source, source_size.x - 1),
	}

	var crop_unit := mini(
		int(floor(float(source_size.x) / float(TARGET_RATIO.x))),
		int(floor(float(source_size.y) / float(TARGET_RATIO.y))))
	var crop_size := TARGET_RATIO * crop_unit
	var crop_origin := Vector2i(
		(source_size.x - crop_size.x) / 2,
		(source_size.y - crop_size.y) / 2)
	var crop := source.get_region(Rect2i(crop_origin, crop_size))
	crop.resize(TARGET_SIZE.x, TARGET_SIZE.y, Image.INTERPOLATE_LANCZOS)
	report["center_crop"] = {
		"source_rect": [crop_origin.x, crop_origin.y, crop_size.x, crop_size.y],
		"target_size": [TARGET_SIZE.x, TARGET_SIZE.y],
		"interpolation": "Image.INTERPOLATE_LANCZOS",
	}

	var mkdir_error := DirAccess.make_dir_recursive_absolute(evaluation_dir)
	if mkdir_error != OK:
		_fail("Could not create evaluation directory: %s" % error_string(mkdir_error))
		return
	if crop.save_png(evaluation_dir.path_join("center-crop-1000x760.png")) != OK:
		_fail("Could not save centered crop.")
		return

	var backgrounds := {
		"black": Color("000000"),
		"white": Color("ffffff"),
		"deep-blue-gray": Color("182533"),
	}
	for name: String in backgrounds:
		var composite := Image.create(TARGET_SIZE.x, TARGET_SIZE.y, false, Image.FORMAT_RGBA8)
		composite.fill(backgrounds[name])
		composite.blend_rect(crop, Rect2i(Vector2i.ZERO, TARGET_SIZE), Vector2i.ZERO)
		var composite_path := evaluation_dir.path_join("sourceover-%s-1000x760.png" % name)
		if composite.save_png(composite_path) != OK:
			_fail("Could not save SourceOver composite: %s" % composite_path)
			return

	var report_path := evaluation_dir.path_join("inspection.json")
	var report_file := FileAccess.open(report_path, FileAccess.WRITE)
	if report_file == null:
		_fail("Could not write inspection report: %s" % report_path)
		return
	report_file.store_string(JSON.stringify(report, "  ") + "\n")
	report_file.close()
	print(JSON.stringify(report))
	quit(0)


func _increment_alpha_band(bands: Dictionary, alpha: int) -> void:
	var key := "0"
	if alpha >= 240:
		key = "240_255"
	elif alpha >= 128:
		key = "128_239"
	elif alpha >= 64:
		key = "64_127"
	elif alpha >= 16:
		key = "16_63"
	elif alpha >= 1:
		key = "1_15"
	bands[key] = int(bands[key]) + 1


func _horizontal_edge_stats(image: Image, y: int) -> Dictionary:
	var values: Array[int] = []
	for x in image.get_width():
		values.append(_alpha8(image, x, y))
	return _summarize_alpha(values)


func _vertical_edge_stats(image: Image, x: int) -> Dictionary:
	var values: Array[int] = []
	for y in image.get_height():
		values.append(_alpha8(image, x, y))
	return _summarize_alpha(values)


func _summarize_alpha(values: Array[int]) -> Dictionary:
	var nonzero := 0
	var opaque := 0
	var maximum := 0
	var total := 0
	for value: int in values:
		if value > 0:
			nonzero += 1
		if value == 255:
			opaque += 1
		maximum = maxi(maximum, value)
		total += value
	return {
		"pixels": values.size(),
		"nonzero": nonzero,
		"opaque": opaque,
		"max": maximum,
		"mean": float(total) / float(values.size()),
	}


func _alpha8(image: Image, x: int, y: int) -> int:
	return clampi(int(round(image.get_pixel(x, y).a * 255.0)), 0, 255)


func _format_name(format: Image.Format) -> String:
	match format:
		Image.FORMAT_RGBA8:
			return "RGBA8"
		Image.FORMAT_RGBAF:
			return "RGBAF"
		Image.FORMAT_RGBAH:
			return "RGBAH"
		_:
			return "Image.Format(%d)" % int(format)


func _fail(message: String) -> void:
	push_error(message)
	quit(1)
