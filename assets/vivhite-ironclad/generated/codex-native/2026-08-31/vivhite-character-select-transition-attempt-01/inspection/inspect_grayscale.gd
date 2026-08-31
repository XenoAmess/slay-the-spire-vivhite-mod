extends SceneTree


func _initialize() -> void:
	var args := OS.get_cmdline_user_args()
	if args.size() != 2:
		printerr("usage: inspect_grayscale.gd <png-path> <report-path>")
		quit(2)
		return

	var image := Image.load_from_file(args[0])
	if image == null or image.is_empty():
		printerr("could not load image: %s" % args[0])
		quit(3)
		return

	var total := image.get_width() * image.get_height()
	var non_grayscale_pixels := 0
	var max_channel_delta := 0
	for y in image.get_height():
		for x in image.get_width():
			var pixel := image.get_pixel(x, y)
			var red := clampi(int(round(pixel.r * 255.0)), 0, 255)
			var green := clampi(int(round(pixel.g * 255.0)), 0, 255)
			var blue := clampi(int(round(pixel.b * 255.0)), 0, 255)
			var delta := maxi(abs(red - green), maxi(abs(red - blue), abs(green - blue)))
			max_channel_delta = maxi(max_channel_delta, delta)
			if delta != 0:
				non_grayscale_pixels += 1

	var report := {
		"schema": "vivhite-transition-grayscale-inspection/v1",
		"path": args[0].replace("\\", "/"),
		"sha256": FileAccess.get_sha256(args[0]),
		"width": image.get_width(),
		"height": image.get_height(),
		"format_enum": int(image.get_format()),
		"total_pixels": total,
		"non_grayscale_pixels": non_grayscale_pixels,
		"max_channel_delta_8bit": max_channel_delta,
		"strict_grayscale": non_grayscale_pixels == 0,
	}

	var output_path := args[1]
	var file := FileAccess.open(output_path, FileAccess.WRITE)
	if file == null:
		printerr("could not write report: %s" % output_path)
		quit(4)
		return
	file.store_string(JSON.stringify(report, "  ") + "\n")
	print("[PASS] grayscale inspection written: %s" % output_path)
	quit(0)
