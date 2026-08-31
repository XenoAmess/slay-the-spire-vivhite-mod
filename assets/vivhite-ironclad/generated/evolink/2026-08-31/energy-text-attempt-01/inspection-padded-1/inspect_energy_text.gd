extends SceneTree


const BACKGROUNDS := {
	"black": Color(0, 0, 0, 1),
	"white": Color(1, 1, 1, 1),
	"game-indigo": Color("182139")
}
const TARGET_SIZES := [24, 16, 12]
const ALPHA_THRESHOLDS := [1, 16, 64, 127, 240]


func _init() -> void:
	var args := OS.get_cmdline_user_args()
	if args.size() < 2:
		printerr("usage: <source.png> <inspection-dir> [padding]")
		quit(2)
		return
	var source_path := args[0]
	var inspection_dir := args[1]
	var padding: int = int(args[2]) if args.size() >= 3 else 0
	if padding < 0 or padding * 2 >= TARGET_SIZES.min():
		printerr("invalid padding")
		quit(2)
		return
	var mkdir_error := DirAccess.make_dir_recursive_absolute(inspection_dir)
	if mkdir_error != OK:
		printerr("mkdir failed: %s" % error_string(mkdir_error))
		quit(3)
		return
	var source := Image.load_from_file(source_path)
	if source == null or source.is_empty():
		printerr("could not decode source")
		quit(4)
		return
	if source.is_compressed():
		var decompress_error := source.decompress()
		if decompress_error != OK:
			printerr("decompress failed: %s" % error_string(decompress_error))
			quit(4)
			return
	var report := {
		"source": source_path,
		"source_size": [source.get_width(), source.get_height()],
		"source_format_id": int(source.get_format()),
		"source_format": "RGBA8" if source.get_format() == Image.FORMAT_RGBA8 else "unexpected",
		"source_metrics": _metrics(source),
		"operation": "full-canvas uniform RGBA Lanczos inspection resize plus centered transparent padding; no crop, mask, threshold, color key, or Alpha edit",
		"padding": padding,
		"sizes": []
	}
	for target_size in TARGET_SIZES:
		var resized := source.duplicate()
		var inner_size: int = target_size - padding * 2
		resized.resize(inner_size, inner_size, Image.INTERPOLATE_LANCZOS)
		var runtime := Image.create(target_size, target_size, false, Image.FORMAT_RGBA8)
		runtime.fill(Color(0, 0, 0, 0))
		runtime.blit_rect(
			resized,
			Rect2i(Vector2i.ZERO, Vector2i(inner_size, inner_size)),
			Vector2i(padding, padding)
		)
		var rgba_path := inspection_dir.path_join("runtime-%d.png" % target_size)
		var rgba_error: Error = runtime.save_png(rgba_path)
		if rgba_error != OK:
			printerr("could not save %s: %s" % [rgba_path, error_string(rgba_error)])
			quit(5)
			return
		var size_record := {
			"size": target_size,
			"rgba": rgba_path,
			"metrics": _metrics(runtime),
			"sourceover": {}
		}
		for background_name in BACKGROUNDS:
			var composite := Image.create(target_size, target_size, false, Image.FORMAT_RGBA8)
			composite.fill(BACKGROUNDS[background_name])
			composite.blend_rect(
				runtime,
				Rect2i(Vector2i.ZERO, Vector2i(target_size, target_size)),
				Vector2i.ZERO
			)
			var composite_path := inspection_dir.path_join(
				"sourceover-%s-%d.png" % [background_name, target_size]
			)
			var composite_error: Error = composite.save_png(composite_path)
			if composite_error != OK:
				printerr("could not save %s: %s" % [composite_path, error_string(composite_error)])
				quit(5)
				return
			size_record.sourceover[background_name] = composite_path
		report.sizes.append(size_record)
	var report_file := FileAccess.open(inspection_dir.path_join("report.json"), FileAccess.WRITE)
	if report_file == null:
		printerr("could not create report")
		quit(6)
		return
	report_file.store_string(JSON.stringify(report, "  ") + "\n")
	report_file.close()
	print("inspected %s" % source_path)
	quit(0)


func _metrics(image: Image) -> Dictionary:
	var corners := [
		image.get_pixel(0, 0).a8,
		image.get_pixel(image.get_width() - 1, 0).a8,
		image.get_pixel(0, image.get_height() - 1).a8,
		image.get_pixel(image.get_width() - 1, image.get_height() - 1).a8
	]
	var threshold_records := {}
	for threshold in ALPHA_THRESHOLDS:
		var min_x := image.get_width()
		var min_y := image.get_height()
		var max_x := -1
		var max_y := -1
		var count := 0
		var edge_count := 0
		var edge_max := 0
		for y in image.get_height():
			for x in image.get_width():
				var alpha := image.get_pixel(x, y).a8
				if x == 0 or y == 0 or x == image.get_width() - 1 or y == image.get_height() - 1:
					edge_max = maxi(edge_max, alpha)
					if alpha >= threshold:
						edge_count += 1
				if alpha < threshold:
					continue
				count += 1
				min_x = mini(min_x, x)
				min_y = mini(min_y, y)
				max_x = maxi(max_x, x)
				max_y = maxi(max_y, y)
		var bbox := [0, 0, 0, 0]
		if max_x >= min_x and max_y >= min_y:
			bbox = [min_x, min_y, max_x - min_x + 1, max_y - min_y + 1]
		threshold_records[str(threshold)] = {
			"bbox": bbox,
			"count": count,
			"edge_count": edge_count,
			"edge_max_alpha": edge_max
		}
	return {
		"corners_alpha": corners,
		"thresholds": threshold_records
	}
