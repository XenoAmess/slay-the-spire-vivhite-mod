extends SceneTree

## Validates one model-produced native-transparent PNG, then performs only the
## permitted deterministic size adaptation for a Vivhite UI consumer.
##
## This tool never thresholds, masks, flood-fills, color-keys, erodes, expands,
## repairs, or otherwise invents Alpha. It uniformly resamples every RGBA channel,
## centers the complete result on a transparent target canvas, and emits opaque
## SourceOver inspection images on black, white, and game-like backgrounds.


func _initialize() -> void:
	var options := _parse_options(OS.get_cmdline_user_args())
	var source_path: String = options.get("source", "")
	var output_path: String = options.get("output", "")
	var inspection_dir: String = options.get("inspection-dir", "")
	var target_width := int(options.get("width", "256"))
	var target_height := int(options.get("height", "256"))
	var padding := int(options.get("padding", "12"))
	if source_path.is_empty() or output_path.is_empty() or inspection_dir.is_empty():
		printerr(
			"Usage: --source <native-rgba.png> --output <runtime.png> "
			+ "--inspection-dir <dir> [--width 256 --height 256 --padding 12]"
		)
		quit(2)
		return
	if target_width <= 0 or target_height <= 0 or padding < 0:
		printerr("Target dimensions must be positive and padding cannot be negative.")
		quit(2)
		return
	if padding * 2 >= target_width or padding * 2 >= target_height:
		printerr("Padding leaves no drawable target area.")
		quit(2)
		return

	quit(_prepare(
		source_path,
		output_path,
		inspection_dir,
		Vector2i(target_width, target_height),
		padding
	))


func _parse_options(args: PackedStringArray) -> Dictionary:
	var parsed := {}
	var index := 0
	while index < args.size():
		var option := args[index]
		if option in [
			"--source",
			"--output",
			"--inspection-dir",
			"--width",
			"--height",
			"--padding"
		] and index + 1 < args.size():
			parsed[option.trim_prefix("--")] = args[index + 1]
			index += 2
		else:
			index += 1
	return parsed


func _prepare(
	source_path: String,
	output_path: String,
	inspection_dir: String,
	target_size: Vector2i,
	padding: int
) -> int:
	if not FileAccess.file_exists(source_path):
		printerr("Source PNG does not exist: %s" % source_path)
		return 2
	if FileAccess.file_exists(output_path):
		printerr("Refusing to overwrite runtime output: %s" % output_path)
		return 2

	var source := Image.load_from_file(source_path)
	if source == null or source.is_empty():
		printerr("Could not decode source PNG: %s" % source_path)
		return 2
	if source.is_compressed():
		var decompress_error := source.decompress()
		if decompress_error != OK:
			printerr("Image.decompress failed: %s" % error_string(decompress_error))
			return 2
	if source.get_format() != Image.FORMAT_RGBA8:
		printerr(
			"Source must decode natively as RGBA8; got format %d: %s"
			% [int(source.get_format()), source_path]
		)
		return 3

	var alpha := _inspect_alpha(source)
	if alpha.corners != [0, 0, 0, 0]:
		printerr("All four source corners must have Alpha=0: %s" % [alpha.corners])
		return 3
	if alpha.nonzero_pixels <= 0 or alpha.opaque_pixels <= 0:
		printerr("Source has no visible, substantially opaque subject.")
		return 3
	var source_bbox: Rect2i = alpha.bbox
	if (
		source_bbox.position.x <= 0
		or source_bbox.position.y <= 0
		or source_bbox.end.x >= source.get_width()
		or source_bbox.end.y >= source.get_height()
	):
		printerr("Visible Alpha touches a source edge; reject before runtime packing: %s" % source_bbox)
		return 3

	var source_padding := maxi(
		2,
		ceili(float(maxi(source_bbox.size.x, source_bbox.size.y)) * 0.04)
	)
	var crop_rect := source_bbox.grow(source_padding).intersection(
		Rect2i(Vector2i.ZERO, source.get_size())
	)
	var adapted := source.get_region(crop_rect)
	if adapted == null or adapted.is_empty():
		printerr("Could not crop the validated native-transparent source.")
		return 2

	var drawable_size := target_size - Vector2i(padding * 2, padding * 2)
	var scale_factor := minf(
		float(drawable_size.x) / float(adapted.get_width()),
		float(drawable_size.y) / float(adapted.get_height())
	)
	if scale_factor <= 0.0:
		printerr("Could not calculate a positive uniform scale.")
		return 2

	# The crop removes only fully transparent outer padding after the complete
	# source has passed Alpha validation. All nonzero Alpha and a deterministic
	# transparent safety band remain, and all four channels are resampled together.
	var resized := adapted
	var resized_size := Vector2i(
		maxi(1, roundi(float(adapted.get_width()) * scale_factor)),
		maxi(1, roundi(float(adapted.get_height()) * scale_factor))
	)
	if resized_size.x > target_size.x or resized_size.y > target_size.y:
		var canvas_scale := minf(
			float(target_size.x) / float(resized_size.x),
			float(target_size.y) / float(resized_size.y)
		)
		resized_size = Vector2i(
			maxi(1, floori(float(resized_size.x) * canvas_scale)),
			maxi(1, floori(float(resized_size.y) * canvas_scale))
		)
	resized.resize(resized_size.x, resized_size.y, Image.INTERPOLATE_LANCZOS)
	if resized.get_format() != Image.FORMAT_RGBA8:
		printerr("RGBA resize changed the decoded image format unexpectedly.")
		return 2

	var runtime := Image.create(target_size.x, target_size.y, false, Image.FORMAT_RGBA8)
	runtime.fill(Color(0, 0, 0, 0))
	var destination := Vector2i(
		floori(float(target_size.x - resized_size.x) / 2.0),
		floori(float(target_size.y - resized_size.y) / 2.0)
	)
	runtime.blit_rect(resized, Rect2i(Vector2i.ZERO, resized_size), destination)

	if not _mkdir_for_file(output_path) or not _mkdir(inspection_dir):
		return 2
	var save_error := runtime.save_png(output_path)
	if save_error != OK:
		printerr("Could not save runtime PNG: %s" % error_string(save_error))
		return 2

	var backgrounds := {
		"sourceover-black.png": Color(0, 0, 0, 1),
		"sourceover-white.png": Color(1, 1, 1, 1),
		"sourceover-game-indigo.png": Color("182139")
	}
	for file_name in backgrounds:
		var composite := Image.create(target_size.x, target_size.y, false, Image.FORMAT_RGBA8)
		composite.fill(backgrounds[file_name])
		composite.blend_rect(runtime, Rect2i(Vector2i.ZERO, target_size), Vector2i.ZERO)
		var composite_error := composite.save_png(inspection_dir.path_join(file_name))
		if composite_error != OK:
			printerr("Could not save SourceOver inspection: %s" % error_string(composite_error))
			return 2

	var runtime_alpha := _inspect_alpha(runtime)
	var report := {
		"source": source_path,
		"source_size": [source.get_width(), source.get_height()],
		"source_format": "RGBA8",
		"source_alpha_bbox": _rect_to_array(source_bbox),
		"source_crop_rect": _rect_to_array(crop_rect),
		"source_corner_alpha": alpha.corners,
		"source_nonzero_alpha_pixels": alpha.nonzero_pixels,
		"source_opaque_pixels": alpha.opaque_pixels,
		"operation": "uniform RGBA Lanczos resize plus centered transparent padding; no Alpha repair",
		"runtime": output_path,
		"runtime_size": [target_size.x, target_size.y],
		"runtime_format": "RGBA8",
		"runtime_alpha_bbox": _rect_to_array(runtime_alpha.bbox),
		"runtime_corner_alpha": runtime_alpha.corners,
		"inspection_backgrounds": backgrounds.keys()
	}
	var report_file := FileAccess.open(inspection_dir.path_join("report.json"), FileAccess.WRITE)
	if report_file == null:
		printerr("Could not create inspection report.")
		return 2
	report_file.store_string(JSON.stringify(report, "  ") + "\n")
	report_file.close()

	print(
		"Prepared native-transparent Vivhite UI icon: %s -> %s (%dx%d RGBA8)"
		% [source_path, output_path, target_size.x, target_size.y]
	)
	return 0


func _inspect_alpha(image: Image) -> Dictionary:
	var corners := [
		image.get_pixel(0, 0).a8,
		image.get_pixel(image.get_width() - 1, 0).a8,
		image.get_pixel(0, image.get_height() - 1).a8,
		image.get_pixel(image.get_width() - 1, image.get_height() - 1).a8
	]
	var min_x := image.get_width()
	var min_y := image.get_height()
	var max_x := -1
	var max_y := -1
	var nonzero_pixels := 0
	var opaque_pixels := 0
	for y in image.get_height():
		for x in image.get_width():
			var alpha := image.get_pixel(x, y).a8
			if alpha <= 0:
				continue
			nonzero_pixels += 1
			if alpha >= 250:
				opaque_pixels += 1
			min_x = mini(min_x, x)
			min_y = mini(min_y, y)
			max_x = maxi(max_x, x)
			max_y = maxi(max_y, y)
	var bbox := Rect2i()
	if max_x >= min_x and max_y >= min_y:
		bbox = Rect2i(min_x, min_y, max_x - min_x + 1, max_y - min_y + 1)
	return {
		"corners": corners,
		"bbox": bbox,
		"nonzero_pixels": nonzero_pixels,
		"opaque_pixels": opaque_pixels
	}


func _rect_to_array(rect: Rect2i) -> Array:
	return [rect.position.x, rect.position.y, rect.size.x, rect.size.y]


func _mkdir_for_file(path: String) -> bool:
	return _mkdir(path.get_base_dir())


func _mkdir(path: String) -> bool:
	var error := DirAccess.make_dir_recursive_absolute(path)
	if error != OK:
		printerr("Could not create directory %s: %s" % [path, error_string(error)])
		return false
	return true
