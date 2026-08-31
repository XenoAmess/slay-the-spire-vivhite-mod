extends SceneTree


func _initialize() -> void:
	var args := OS.get_cmdline_user_args()
	if args.size() != 3:
		printerr("usage: normalize_red_channel.gd <source-png> <output-png> <report-json>")
		quit(2)
		return

	var source_path := args[0]
	var output_path := args[1]
	var report_path := args[2]
	var image := Image.load_from_file(source_path)
	if image == null or image.is_empty():
		printerr("could not load image: %s" % source_path)
		quit(3)
		return
	image.convert(Image.FORMAT_RGB8)

	var changed_pixels := 0
	var max_source_channel_delta := 0
	for y in image.get_height():
		for x in image.get_width():
			var pixel := image.get_pixel(x, y)
			var red := clampi(int(round(pixel.r * 255.0)), 0, 255)
			var green := clampi(int(round(pixel.g * 255.0)), 0, 255)
			var blue := clampi(int(round(pixel.b * 255.0)), 0, 255)
			var delta := maxi(abs(red - green), maxi(abs(red - blue), abs(green - blue)))
			max_source_channel_delta = maxi(max_source_channel_delta, delta)
			if delta != 0:
				changed_pixels += 1
			var scalar := red / 255.0
			image.set_pixel(x, y, Color(scalar, scalar, scalar, 1.0))

	DirAccess.make_dir_recursive_absolute(output_path.get_base_dir())
	if image.save_png(output_path) != OK:
		printerr("could not save image: %s" % output_path)
		quit(4)
		return

	var report := {
		"schema": "vivhite-transition-red-channel-normalization/v1",
		"operation": "R_out=R_in; G_out=R_in; B_out=R_in; fully opaque RGB8",
		"consumer_equivalence": "The verified transition shader samples only transitionTex.r, so this operation preserves every sampled scalar exactly.",
		"source": {
			"path": source_path.replace("\\", "/"),
			"sha256": FileAccess.get_sha256(source_path),
			"width": image.get_width(),
			"height": image.get_height(),
			"changed_pixels": changed_pixels,
			"max_source_channel_delta_8bit": max_source_channel_delta,
		},
		"output": {
			"path": output_path.replace("\\", "/"),
			"sha256": FileAccess.get_sha256(output_path),
			"width": image.get_width(),
			"height": image.get_height(),
			"format_enum": int(image.get_format()),
		},
	}
	var report_file := FileAccess.open(report_path, FileAccess.WRITE)
	if report_file == null:
		printerr("could not write report: %s" % report_path)
		quit(5)
		return
	report_file.store_string(JSON.stringify(report, "  ") + "\n")
	print("[PASS] red-channel-normalized runtime mask written: %s" % output_path)
	quit(0)
