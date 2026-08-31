extends SceneTree

const BACKGROUNDS := {
	"black": Color8(0, 0, 0, 255),
	"white": Color8(255, 255, 255, 255),
	"game_indigo": Color8(26, 25, 49, 255),
}
const SMALL_SIZES := [48, 24, 16]


func _initialize() -> void:
	var options := _parse_options(OS.get_cmdline_user_args())
	var input_path := str(options.get("input", ""))
	var output_dir := str(options.get("out", ""))
	var runtime_output := str(options.get("runtime-out", ""))
	var attempt := str(options.get("attempt", "unknown"))
	if input_path.is_empty() or output_dir.is_empty():
		printerr("usage: --input <raw-png> --out <evidence-dir> [--runtime-out <png>]")
		quit(2)
		return

	var source := Image.load_from_file(input_path)
	if source == null or source.is_empty():
		printerr("failed to load input PNG: %s" % input_path)
		quit(3)
		return
	if source.is_compressed():
		var decompress_error := source.decompress()
		if decompress_error != OK:
			printerr("failed to decompress input: %s" % error_string(decompress_error))
			quit(4)
			return
	source.convert(Image.FORMAT_RGBA8)

	var mkdir_error := DirAccess.make_dir_recursive_absolute(output_dir)
	if mkdir_error != OK:
		printerr("failed to create evidence directory: %s" % error_string(mkdir_error))
		quit(5)
		return

	var metrics := _measure_alpha(source)
	var previews := []
	for background_id in BACKGROUNDS:
		var full_path := output_dir.path_join(
			"sourceover-%s.png" % background_id
		)
		var full_preview := _source_over(source, BACKGROUNDS[background_id])
		var full_error := full_preview.save_png(full_path)
		if full_error != OK:
			printerr("failed to save %s: %s" % [full_path, error_string(full_error)])
			quit(6)
			return

		var small_path := output_dir.path_join(
			"small-sizes-sourceover-%s.png" % background_id
		)
		var small_preview := _small_size_sheet(source, BACKGROUNDS[background_id])
		var small_error := small_preview.save_png(small_path)
		if small_error != OK:
			printerr("failed to save %s: %s" % [small_path, error_string(small_error)])
			quit(7)
			return
		previews.append({
			"background": background_id,
			"full": full_path,
			"small_sizes": small_path,
		})

	var runtime_record = null
	if not runtime_output.is_empty():
		var runtime_dir := runtime_output.get_base_dir()
		var runtime_mkdir_error := DirAccess.make_dir_recursive_absolute(runtime_dir)
		if runtime_mkdir_error != OK:
			printerr("failed to create runtime directory: %s" % error_string(runtime_mkdir_error))
			quit(8)
			return
		var runtime := source.duplicate()
		runtime.resize(256, 256, Image.INTERPOLATE_LANCZOS)
		runtime.convert(Image.FORMAT_RGBA8)
		var runtime_error: Error = runtime.save_png(runtime_output)
		if runtime_error != OK:
			printerr("failed to save runtime PNG: %s" % error_string(runtime_error))
			quit(9)
			return
		runtime_record = {
			"path": runtime_output,
			"width": runtime.get_width(),
			"height": runtime.get_height(),
			"format": "RGBA8",
			"sha256": FileAccess.get_sha256(runtime_output),
			"alpha": _measure_alpha(runtime),
			"adaptation": "uniform 1024x1024 to 256x256 Lanczos resize; no crop, mask, threshold, color key, or Alpha cleanup",
		}

	var edge_trace_only: bool = (
		int(metrics["edge_nonzero"]) == 0
		or int(metrics["edge_alpha_max"]) <= 1
	)
	var accepted_technical: bool = (
		metrics["corner_alpha"].all(func(alpha: int) -> bool: return alpha == 0)
		and edge_trace_only
		and metrics["bbox_a_ge_16"] != null
		and float(metrics["visible_margin_min_ratio_a_ge_16"]) >= 0.10
	)
	var report := {
		"schema": "vivhite.card-trail-generated-texture-audit/v1",
		"semantic_asset": "card-trail-mathematical-star",
		"attempt": attempt,
		"input": input_path,
		"input_sha256": FileAccess.get_sha256(input_path),
		"width": source.get_width(),
		"height": source.get_height(),
		"format": "RGBA8",
		"alpha": metrics,
		"edge_trace_warning": int(metrics["edge_nonzero"]) > 0,
		"edge_trace_policy": "Nonzero edge pixels are accepted only when all are A=1 or lower and all corners are A=0; this remains a trim-risk warning and requires SourceOver visual review.",
		"previews": previews,
		"runtime": runtime_record,
		"accepted_technical": accepted_technical,
		"visual_review_required": true,
		"notes": "Independent transparent VFX particle; SourceOver previews, actual-size legibility, palette, prohibited elements, and scene integration remain visual gates.",
	}
	var report_path := output_dir.path_join("report.json")
	var report_file := FileAccess.open(report_path, FileAccess.WRITE)
	if report_file == null:
		printerr("failed to open report for writing: %s" % report_path)
		quit(10)
		return
	report_file.store_string(JSON.stringify(report, "\t") + "\n")
	report_file.close()

	if not accepted_technical:
		printerr("generated texture failed technical Alpha gate; see %s" % report_path)
		quit(11)
		return
	print("[PASS] generated texture has RGBA8, transparent corners/edges, and bounded A>=16 content")
	print("[PASS] SourceOver and 48/24/16px previews written for three backgrounds")
	if runtime_record != null:
		print("[PASS] deterministic 256x256 runtime adaptation written")
	quit(0)


func _parse_options(args: PackedStringArray) -> Dictionary:
	var options := {}
	var index := 0
	while index < args.size():
		var key := args[index]
		if key.begins_with("--") and index + 1 < args.size():
			options[key.trim_prefix("--")] = args[index + 1]
			index += 2
		else:
			index += 1
	return options


func _measure_alpha(image: Image) -> Dictionary:
	var width := image.get_width()
	var height := image.get_height()
	var counts := {
		"a0": 0,
		"a1_15": 0,
		"a16_63": 0,
		"a64_127": 0,
		"a128_239": 0,
		"a240_254": 0,
		"a255": 0,
	}
	var edge_nonzero := 0
	var edge_alpha_max := 0
	var rects := {
		1: Rect2i(),
		16: Rect2i(),
		64: Rect2i(),
		128: Rect2i(),
		240: Rect2i(),
	}
	var seen := {1: false, 16: false, 64: false, 128: false, 240: false}

	for y in range(height):
		for x in range(width):
			var alpha := image.get_pixel(x, y).a8
			if alpha == 0:
				counts["a0"] += 1
			elif alpha < 16:
				counts["a1_15"] += 1
			elif alpha < 64:
				counts["a16_63"] += 1
			elif alpha < 128:
				counts["a64_127"] += 1
			elif alpha < 240:
				counts["a128_239"] += 1
			elif alpha < 255:
				counts["a240_254"] += 1
			else:
				counts["a255"] += 1

			if x == 0 or y == 0 or x == width - 1 or y == height - 1:
				if alpha > 0:
					edge_nonzero += 1
				edge_alpha_max = maxi(edge_alpha_max, alpha)

			for threshold in rects:
				if alpha >= int(threshold):
					rects[threshold] = _include_point(
						rects[threshold], Vector2i(x, y), bool(seen[threshold])
					)
					seen[threshold] = true

	var bbox_a16 = _rect_to_array(rects[16], bool(seen[16]))
	var margin_ratio := 0.0
	if bbox_a16 != null:
		var rect: Rect2i = rects[16]
		var minimum_margin := mini(
			mini(rect.position.x, rect.position.y),
			mini(width - rect.end.x, height - rect.end.y)
		)
		margin_ratio = float(minimum_margin) / float(mini(width, height))

	return {
		"corner_alpha": [
			image.get_pixel(0, 0).a8,
			image.get_pixel(width - 1, 0).a8,
			image.get_pixel(0, height - 1).a8,
			image.get_pixel(width - 1, height - 1).a8,
		],
		"edge_nonzero": edge_nonzero,
		"edge_alpha_max": edge_alpha_max,
		"alpha_counts": counts,
		"bbox_a_gt_0": _rect_to_array(rects[1], bool(seen[1])),
		"bbox_a_ge_16": bbox_a16,
		"bbox_a_ge_64": _rect_to_array(rects[64], bool(seen[64])),
		"bbox_a_ge_128": _rect_to_array(rects[128], bool(seen[128])),
		"bbox_a_ge_240": _rect_to_array(rects[240], bool(seen[240])),
		"visible_margin_min_ratio_a_ge_16": margin_ratio,
	}


func _source_over(source: Image, background: Color) -> Image:
	var preview := Image.create(
		source.get_width(), source.get_height(), false, Image.FORMAT_RGBA8
	)
	preview.fill(background)
	preview.blend_rect(
		source,
		Rect2i(0, 0, source.get_width(), source.get_height()),
		Vector2i.ZERO
	)
	return preview


func _small_size_sheet(source: Image, background: Color) -> Image:
	var sheet := Image.create(320, 96, false, Image.FORMAT_RGBA8)
	sheet.fill(background)
	var x_positions := [28, 144, 244]
	for index in range(SMALL_SIZES.size()):
		var size: int = SMALL_SIZES[index]
		var sample := source.duplicate()
		sample.resize(size, size, Image.INTERPOLATE_LANCZOS)
		sample.convert(Image.FORMAT_RGBA8)
		var target := Vector2i(
			x_positions[index] + int((48 - size) / 2.0),
			24 + int((48 - size) / 2.0)
		)
		sheet.blend_rect(sample, Rect2i(0, 0, size, size), target)
	return sheet


func _include_point(rect: Rect2i, point: Vector2i, has_rect: bool) -> Rect2i:
	if not has_rect:
		return Rect2i(point, Vector2i.ONE)
	return rect.expand(point).expand(point + Vector2i.ONE)


func _rect_to_array(rect: Rect2i, has_rect: bool) -> Variant:
	if not has_rect:
		return null
	return [rect.position.x, rect.position.y, rect.size.x, rect.size.y]
