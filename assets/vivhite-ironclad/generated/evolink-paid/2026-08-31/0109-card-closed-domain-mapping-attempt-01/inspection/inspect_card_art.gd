extends SceneTree

const RAW_PATH := "D:/workspace/slay-the-spire-vivhite-mod/assets/vivhite-ironclad/generated/evolink-paid/2026-08-31/0109-card-closed-domain-mapping-attempt-01/output.png"
const OUTPUT_DIR := "D:/workspace/slay-the-spire-vivhite-mod/assets/vivhite-ironclad/generated/evolink-paid/2026-08-31/0109-card-closed-domain-mapping-attempt-01/inspection"
const TARGET_WIDTH := 1000
const TARGET_HEIGHT := 760
const TARGET_RATIO_WIDTH := 25
const TARGET_RATIO_HEIGHT := 19


func alpha_at(data: PackedByteArray, width: int, x: int, y: int) -> int:
	return int(data[((y * width + x) * 4) + 3])


func edge_stats(data: PackedByteArray, width: int, height: int, side: String) -> Dictionary:
	var values: Array[int] = []
	if side == "top" or side == "bottom":
		var y := 0 if side == "top" else height - 1
		for x in range(width):
			values.append(alpha_at(data, width, x, y))
	else:
		var x := 0 if side == "left" else width - 1
		for y in range(height):
			values.append(alpha_at(data, width, x, y))

	var zero := 0
	var opaque := 0
	var minimum := 255
	var maximum := 0
	for value in values:
		minimum = mini(minimum, value)
		maximum = maxi(maximum, value)
		if value == 0:
			zero += 1
		if value == 255:
			opaque += 1
	return {
		"pixels": values.size(),
		"minimum": minimum,
		"maximum": maximum,
		"zero": zero,
		"nonzero": values.size() - zero,
		"opaque": opaque,
	}


func save_source_over(source: Image, color: Color, path: String) -> Error:
	var composite := Image.create(source.get_width(), source.get_height(), false, Image.FORMAT_RGBA8)
	composite.fill(color)
	composite.blend_rect(
		source,
		Rect2i(0, 0, source.get_width(), source.get_height()),
		Vector2i.ZERO
	)
	return composite.save_png(path)


func _init() -> void:
	var png := Image.load_from_file(RAW_PATH)
	if png == null or png.is_empty():
		push_error("Unable to load raw PNG: " + RAW_PATH)
		quit(2)
		return

	var original_format := png.get_format()
	var width := png.get_width()
	var height := png.get_height()
	png.convert(Image.FORMAT_RGBA8)
	var data := png.get_data()
	var expected_bytes := width * height * 4
	if data.size() != expected_bytes:
		push_error("Unexpected RGBA byte count")
		quit(3)
		return

	var thresholds := [1, 16, 64, 128, 240]
	var boxes := {}
	for threshold in thresholds:
		boxes[str(threshold)] = {
			"count": 0,
			"min_x": width,
			"min_y": height,
			"max_x": -1,
			"max_y": -1,
		}

	var histogram := {
		"alpha_0": 0,
		"alpha_1_15": 0,
		"alpha_16_63": 0,
		"alpha_64_127": 0,
		"alpha_128_239": 0,
		"alpha_240_254": 0,
		"alpha_255": 0,
	}
	var pixel_count := width * height
	for pixel_index in range(pixel_count):
		var alpha := int(data[(pixel_index * 4) + 3])
		if alpha == 0:
			histogram["alpha_0"] += 1
		elif alpha < 16:
			histogram["alpha_1_15"] += 1
		elif alpha < 64:
			histogram["alpha_16_63"] += 1
		elif alpha < 128:
			histogram["alpha_64_127"] += 1
		elif alpha < 240:
			histogram["alpha_128_239"] += 1
		elif alpha < 255:
			histogram["alpha_240_254"] += 1
		else:
			histogram["alpha_255"] += 1

		var x := pixel_index % width
		var y := int(pixel_index / width)
		for threshold in thresholds:
			if alpha >= threshold:
				var box: Dictionary = boxes[str(threshold)]
				box["count"] += 1
				box["min_x"] = mini(int(box["min_x"]), x)
				box["min_y"] = mini(int(box["min_y"]), y)
				box["max_x"] = maxi(int(box["max_x"]), x)
				box["max_y"] = maxi(int(box["max_y"]), y)

	for threshold in thresholds:
		var box: Dictionary = boxes[str(threshold)]
		if int(box["count"]) == 0:
			boxes[str(threshold)] = {"count": 0, "bbox": null}
		else:
			boxes[str(threshold)] = {
				"count": box["count"],
				"bbox": [
					box["min_x"],
					box["min_y"],
					int(box["max_x"]) + 1,
					int(box["max_y"]) + 1,
				],
			}

	var crop_scale := mini(int(width / TARGET_RATIO_WIDTH), int(height / TARGET_RATIO_HEIGHT))
	var crop_width := crop_scale * TARGET_RATIO_WIDTH
	var crop_height := crop_scale * TARGET_RATIO_HEIGHT
	var crop_x := int((width - crop_width) / 2)
	var crop_y := int((height - crop_height) / 2)
	var card := png.get_region(Rect2i(crop_x, crop_y, crop_width, crop_height))
	card.resize(TARGET_WIDTH, TARGET_HEIGHT, Image.INTERPOLATE_LANCZOS)
	var full_source_preview := png.duplicate()
	var full_source_preview_height := int(round(float(height) * float(TARGET_WIDTH) / float(width)))
	full_source_preview.resize(TARGET_WIDTH, full_source_preview_height, Image.INTERPOLATE_LANCZOS)

	DirAccess.make_dir_recursive_absolute(OUTPUT_DIR)
	var save_errors := {
		"full_source_preview": full_source_preview.save_png(OUTPUT_DIR + "/full-source-1000px-wide-rgba.png"),
		"rgba": card.save_png(OUTPUT_DIR + "/center-crop-1000x760-rgba.png"),
		"black": save_source_over(card, Color8(0, 0, 0, 255), OUTPUT_DIR + "/sourceover-black-1000x760.png"),
		"white": save_source_over(card, Color8(255, 255, 255, 255), OUTPUT_DIR + "/sourceover-white-1000x760.png"),
		"deep_blue_gray": save_source_over(card, Color8(24, 32, 48, 255), OUTPUT_DIR + "/sourceover-deep-blue-gray-1000x760.png"),
	}

	var metrics := {
		"raw_path": RAW_PATH,
		"raw_width": width,
		"raw_height": height,
		"original_godot_format": original_format,
		"analysis_format": "RGBA8",
		"rgba_byte_count": data.size(),
		"pixel_count": pixel_count,
		"corner_alpha": {
			"top_left": alpha_at(data, width, 0, 0),
			"top_right": alpha_at(data, width, width - 1, 0),
			"bottom_left": alpha_at(data, width, 0, height - 1),
			"bottom_right": alpha_at(data, width, width - 1, height - 1),
		},
		"edge_alpha": {
			"top": edge_stats(data, width, height, "top"),
			"right": edge_stats(data, width, height, "right"),
			"bottom": edge_stats(data, width, height, "bottom"),
			"left": edge_stats(data, width, height, "left"),
		},
		"alpha_histogram": histogram,
		"threshold_bboxes_xyxy_exclusive": boxes,
		"deterministic_crop": {
			"x": crop_x,
			"y": crop_y,
			"width": crop_width,
			"height": crop_height,
			"target_width": TARGET_WIDTH,
			"target_height": TARGET_HEIGHT,
			"interpolation": "Godot Image.INTERPOLATE_LANCZOS",
		},
		"full_source_preview": {
			"width": TARGET_WIDTH,
			"height": full_source_preview_height,
			"interpolation": "Godot Image.INTERPOLATE_LANCZOS",
		},
		"sourceover_colors": {
			"black": "#000000",
			"white": "#ffffff",
			"deep_blue_gray": "#182030",
		},
		"save_errors": save_errors,
	}
	var report_path := OUTPUT_DIR + "/inspection-metrics.json"
	var report := FileAccess.open(report_path, FileAccess.WRITE)
	if report == null:
		push_error("Unable to write metrics report")
		quit(4)
		return
	report.store_string(JSON.stringify(metrics, "  ") + "\n")
	report.close()
	print(JSON.stringify(metrics))
	quit(0)
