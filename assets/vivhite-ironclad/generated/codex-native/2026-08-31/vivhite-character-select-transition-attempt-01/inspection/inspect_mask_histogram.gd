extends SceneTree


func _initialize() -> void:
	var args := OS.get_cmdline_user_args()
	if args.size() != 2:
		printerr("usage: inspect_mask_histogram.gd <png-path> <report-path>")
		quit(2)
		return

	var image := Image.load_from_file(args[0])
	if image == null or image.is_empty():
		printerr("could not load image: %s" % args[0])
		quit(3)
		return
	if image.is_compressed() and image.decompress() != OK:
		printerr("could not decompress image: %s" % args[0])
		quit(4)
		return

	var histogram: Array[int] = []
	histogram.resize(256)
	histogram.fill(0)
	var alpha_histogram: Array[int] = []
	alpha_histogram.resize(256)
	alpha_histogram.fill(0)
	var total := image.get_width() * image.get_height()
	var red_sum := 0
	for y in image.get_height():
		for x in image.get_width():
			var pixel := image.get_pixel(x, y)
			var red := clampi(int(round(pixel.r * 255.0)), 0, 255)
			var alpha := clampi(int(round(pixel.a * 255.0)), 0, 255)
			histogram[red] += 1
			alpha_histogram[alpha] += 1
			red_sum += red

	var reveal_curve: Array[Dictionary] = []
	for index in 11:
		var threshold := index / 10.0
		var remap := lerpf(-0.1, 1.1, threshold)
		var visible := 0
		for red in 256:
			if remap >= 1.0 - red / 255.0:
				visible += histogram[red]
		reveal_curve.append({
			"threshold": threshold,
			"black_coverage": visible / float(total),
		})

	var report := {
		"schema": "vivhite-transition-mask-metrics/v1",
		"path": args[0].replace("\\", "/"),
		"sha256": FileAccess.get_sha256(args[0]),
		"width": image.get_width(),
		"height": image.get_height(),
		"format_enum": int(image.get_format()),
		"red": {
			"minimum": _first_nonzero(histogram),
			"maximum": _last_nonzero(histogram),
			"mean": red_sum / float(total),
			"quantiles": {
				"p01": _quantile(histogram, total, 0.01),
				"p05": _quantile(histogram, total, 0.05),
				"p10": _quantile(histogram, total, 0.10),
				"p25": _quantile(histogram, total, 0.25),
				"p50": _quantile(histogram, total, 0.50),
				"p75": _quantile(histogram, total, 0.75),
				"p90": _quantile(histogram, total, 0.90),
				"p95": _quantile(histogram, total, 0.95),
				"p99": _quantile(histogram, total, 0.99),
			},
			"histogram": histogram,
		},
		"alpha": {
			"minimum": _first_nonzero(alpha_histogram),
			"maximum": _last_nonzero(alpha_histogram),
			"transparent_pixels": alpha_histogram[0],
			"opaque_pixels": alpha_histogram[255],
		},
		"shader_reveal_curve": reveal_curve,
	}

	var output_path := args[1]
	var output_dir := output_path.get_base_dir()
	if not output_dir.is_empty():
		DirAccess.make_dir_recursive_absolute(output_dir)
	var file := FileAccess.open(output_path, FileAccess.WRITE)
	if file == null:
		printerr("could not write report: %s" % output_path)
		quit(5)
		return
	file.store_string(JSON.stringify(report, "  ") + "\n")
	print("[PASS] mask metrics written: %s" % output_path)
	quit(0)


func _first_nonzero(histogram: Array[int]) -> int:
	for index in histogram.size():
		if histogram[index] > 0:
			return index
	return 0


func _last_nonzero(histogram: Array[int]) -> int:
	for index in range(histogram.size() - 1, -1, -1):
		if histogram[index] > 0:
			return index
	return 0


func _quantile(histogram: Array[int], total: int, fraction: float) -> int:
	var target := ceili(total * fraction)
	var cumulative := 0
	for index in histogram.size():
		cumulative += histogram[index]
		if cumulative >= target:
			return index
	return histogram.size() - 1
