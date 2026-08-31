extends SceneTree

const TEXTURES := [
	{
		"id": "outer_ribbon",
		"path": "res://images/packed/vfx/trail.png",
	},
	{
		"id": "inner_ribbon",
		"path": "res://images/packed/vfx/trail2.png",
	},
	{
		"id": "big_spark",
		"path": "res://images/vfx/brush_particle_2.png",
	},
	{
		"id": "card_silhouette",
		"path": "res://images/packed/vfx/small_card_silhouette.png",
	},
	{
		"id": "little_spark",
		"path": "res://images/vfx/vfx_ghostly_power_up/sparkle.png",
	},
]

const BACKGROUNDS := {
	"black": Color8(0, 0, 0, 255),
	"white": Color8(255, 255, 255, 255),
	"game_indigo": Color8(26, 25, 49, 255),
}


func _initialize() -> void:
	var options := _parse_options(OS.get_cmdline_user_args())
	var pck_path := str(options.get("pck", ""))
	var output_dir := str(options.get("out", ""))
	if pck_path.is_empty() or output_dir.is_empty():
		printerr("usage: --pck <SlayTheSpire2.pck> --out <evidence-directory>")
		quit(2)
		return

	if not ProjectSettings.load_resource_pack(pck_path, false):
		printerr("failed to mount base-game PCK: %s" % pck_path)
		quit(3)
		return

	var mkdir_error := DirAccess.make_dir_recursive_absolute(output_dir)
	if mkdir_error != OK:
		printerr("failed to create evidence directory: %s" % error_string(mkdir_error))
		quit(4)
		return

	var report := {
		"schema": "vivhite.card-trail-base-texture-audit/v1",
		"base_pck": pck_path,
		"textures": [],
	}
	var failed := false
	for spec in TEXTURES:
		var result := _inspect_texture(spec, output_dir)
		report["textures"].append(result)
		if not bool(result.get("accepted", false)):
			failed = true

	var report_path := output_dir.path_join("base-texture-report.json")
	var report_file := FileAccess.open(report_path, FileAccess.WRITE)
	if report_file == null:
		printerr("failed to open report for writing: %s" % report_path)
		quit(5)
		return
	report_file.store_string(JSON.stringify(report, "\t") + "\n")
	report_file.close()

	if failed:
		printerr("base texture audit failed; see %s" % report_path)
		quit(6)
		return

	print("[PASS] five shared card-trail textures decoded with valid Alpha contracts")
	print("[PASS] SourceOver previews written for black, white, and game_indigo")
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


func _inspect_texture(spec: Dictionary, output_dir: String) -> Dictionary:
	var resource_path := str(spec["path"])
	var resource := ResourceLoader.load(resource_path, "Texture2D", ResourceLoader.CACHE_MODE_IGNORE)
	if resource == null or not (resource is Texture2D):
		return {
			"id": spec["id"],
			"path": resource_path,
			"accepted": false,
			"error": "texture did not resolve",
		}

	var image := (resource as Texture2D).get_image()
	if image == null or image.is_empty():
		return {
			"id": spec["id"],
			"path": resource_path,
			"accepted": false,
			"error": "texture image is empty",
		}
	if image.is_compressed():
		var decompress_error := image.decompress()
		if decompress_error != OK:
			return {
				"id": spec["id"],
				"path": resource_path,
				"accepted": false,
				"error": "decompression failed: %s" % error_string(decompress_error),
			}
	image.convert(Image.FORMAT_RGBA8)

	var width := image.get_width()
	var height := image.get_height()
	var counts := {
		"a0": 0,
		"a1_15": 0,
		"a16_63": 0,
		"a64_127": 0,
		"a128_254": 0,
		"a255": 0,
	}
	var edge_nonzero := 0
	var edge_alpha_max := 0
	var bbox_a1 := Rect2i()
	var bbox_a16 := Rect2i()
	var bbox_a128 := Rect2i()
	var bbox_a240 := Rect2i()
	var has_a1 := false
	var has_a16 := false
	var has_a128 := false
	var has_a240 := false

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
			elif alpha < 255:
				counts["a128_254"] += 1
			else:
				counts["a255"] += 1

			if x == 0 or y == 0 or x == width - 1 or y == height - 1:
				if alpha > 0:
					edge_nonzero += 1
				edge_alpha_max = maxi(edge_alpha_max, alpha)

			if alpha > 0:
				bbox_a1 = _include_point(bbox_a1, Vector2i(x, y), has_a1)
				has_a1 = true
			if alpha >= 16:
				bbox_a16 = _include_point(bbox_a16, Vector2i(x, y), has_a16)
				has_a16 = true
			if alpha >= 128:
				bbox_a128 = _include_point(bbox_a128, Vector2i(x, y), has_a128)
				has_a128 = true
			if alpha >= 240:
				bbox_a240 = _include_point(bbox_a240, Vector2i(x, y), has_a240)
				has_a240 = true

	for background_id in BACKGROUNDS:
		var preview := Image.create(width, height, false, Image.FORMAT_RGBA8)
		preview.fill(BACKGROUNDS[background_id])
		preview.blend_rect(image, Rect2i(0, 0, width, height), Vector2i.ZERO)
		var preview_path := output_dir.path_join(
			"%s-sourceover-%s.png" % [spec["id"], background_id]
		)
		var save_error := preview.save_png(preview_path)
		if save_error != OK:
			return {
				"id": spec["id"],
				"path": resource_path,
				"accepted": false,
				"error": "failed to save %s: %s" % [preview_path, error_string(save_error)],
			}

	var corners := [
		image.get_pixel(0, 0).a8,
		image.get_pixel(width - 1, 0).a8,
		image.get_pixel(0, height - 1).a8,
		image.get_pixel(width - 1, height - 1).a8,
	]
	return {
		"id": spec["id"],
		"path": resource_path,
		"width": width,
		"height": height,
		"format": "RGBA8",
		"corner_alpha": corners,
		"edge_nonzero": edge_nonzero,
		"edge_alpha_max": edge_alpha_max,
		"alpha_counts": counts,
		"bbox_a_gt_0": _rect_to_array(bbox_a1, has_a1),
		"bbox_a_ge_16": _rect_to_array(bbox_a16, has_a16),
		"bbox_a_ge_128": _rect_to_array(bbox_a128, has_a128),
		"bbox_a_ge_240": _rect_to_array(bbox_a240, has_a240),
		"accepted": corners.all(func(alpha: int) -> bool: return alpha == 0),
	}


func _include_point(rect: Rect2i, point: Vector2i, has_rect: bool) -> Rect2i:
	if not has_rect:
		return Rect2i(point, Vector2i.ONE)
	return rect.expand(point).expand(point + Vector2i.ONE)


func _rect_to_array(rect: Rect2i, has_rect: bool) -> Variant:
	if not has_rect:
		return null
	return [rect.position.x, rect.position.y, rect.size.x, rect.size.y]
