extends SceneTree

const TARGET_WIDTH := 2560
const TARGET_HEIGHT := 1200
const PREVIEW_WIDTH := 640
const PREVIEW_HEIGHT := 300
const PREVIEW_THRESHOLDS := [0.20, 0.35, 0.50, 0.65, 0.80, 0.90]


func _initialize() -> void:
	var args := OS.get_cmdline_user_args()
	if args.size() != 3:
		printerr("usage: prepare_runtime_transition.gd <source-png> <runtime-png> <inspection-directory>")
		quit(2)
		return

	var source_path := args[0]
	var runtime_path := args[1]
	var inspection_dir := args[2]
	var source := Image.load_from_file(source_path)
	if source == null or source.is_empty():
		_fail("could not load source image", 3)
		return
	if source.is_compressed() and source.decompress() != OK:
		_fail("could not decompress source image", 4)
		return

	var source_width := source.get_width()
	var source_height := source.get_height()
	var exact_scale := mini(source_width / 32, source_height / 15)
	var crop_width := exact_scale * 32
	var crop_height := exact_scale * 15
	if crop_width <= 0 or crop_height <= 0:
		_fail("source is too small for a 32:15 crop", 5)
		return
	var crop_x := (source_width - crop_width) / 2
	var crop_y := (source_height - crop_height) / 2
	var crop_rect := Rect2i(crop_x, crop_y, crop_width, crop_height)
	var runtime := source.get_region(crop_rect)
	runtime.convert(Image.FORMAT_RGB8)
	runtime.resize(TARGET_WIDTH, TARGET_HEIGHT, Image.INTERPOLATE_LANCZOS)

	DirAccess.make_dir_recursive_absolute(runtime_path.get_base_dir())
	DirAccess.make_dir_recursive_absolute(inspection_dir)
	if runtime.save_png(runtime_path) != OK:
		_fail("could not save runtime image", 6)
		return

	var preview_mask := runtime.duplicate()
	preview_mask.resize(PREVIEW_WIDTH, PREVIEW_HEIGHT, Image.INTERPOLATE_LANCZOS)
	var sheet := Image.create(
		PREVIEW_WIDTH * 3,
		PREVIEW_HEIGHT * 2,
		false,
		Image.FORMAT_RGB8
	)
	var preview_paths: Array[String] = []
	for index in PREVIEW_THRESHOLDS.size():
		var threshold: float = PREVIEW_THRESHOLDS[index]
		var frame := _render_preview(preview_mask, threshold)
		var stem := "threshold-%03d" % int(round(threshold * 100.0))
		var frame_path := inspection_dir.path_join(stem + ".png")
		if frame.save_png(frame_path) != OK:
			_fail("could not save preview frame: %s" % frame_path, 7)
			return
		preview_paths.append(frame_path)
		var destination := Vector2i((index % 3) * PREVIEW_WIDTH, (index / 3) * PREVIEW_HEIGHT)
		sheet.blit_rect(frame, Rect2i(Vector2i.ZERO, frame.get_size()), destination)
	var sheet_path := inspection_dir.path_join("threshold-contact-sheet.png")
	if sheet.save_png(sheet_path) != OK:
		_fail("could not save threshold contact sheet", 8)
		return

	var report := {
		"schema": "vivhite-transition-runtime-adaptation/v1",
		"source": {
			"path": source_path.replace("\\", "/"),
			"sha256": FileAccess.get_sha256(source_path),
			"width": source_width,
			"height": source_height,
			"format_enum": int(source.get_format()),
		},
		"crop": {
			"x": crop_x,
			"y": crop_y,
			"width": crop_width,
			"height": crop_height,
			"aspect": "32:15",
		},
		"runtime": {
			"path": runtime_path.replace("\\", "/"),
			"sha256": FileAccess.get_sha256(runtime_path),
			"width": TARGET_WIDTH,
			"height": TARGET_HEIGHT,
			"format_enum": int(runtime.get_format()),
			"interpolation": "Image.INTERPOLATE_LANCZOS",
		},
		"previews": {
			"thresholds": PREVIEW_THRESHOLDS,
			"paths": preview_paths,
			"contact_sheet": sheet_path,
			"note": "Inspection-only black shader mask composited over a deterministic blue-violet gradient; not a runtime creative asset.",
		},
	}
	var report_path := inspection_dir.path_join("runtime-adaptation.json")
	var file := FileAccess.open(report_path, FileAccess.WRITE)
	if file == null:
		_fail("could not write adaptation report", 9)
		return
	file.store_string(JSON.stringify(report, "  ") + "\n")
	print("[PASS] runtime transition prepared: %s" % runtime_path)
	quit(0)


func _render_preview(mask: Image, threshold: float) -> Image:
	var output := Image.create(PREVIEW_WIDTH, PREVIEW_HEIGHT, false, Image.FORMAT_RGB8)
	var remap := lerpf(-0.1, 1.1, threshold)
	for y in PREVIEW_HEIGHT:
		for x in PREVIEW_WIDTH:
			var u := x / float(PREVIEW_WIDTH - 1)
			var v := y / float(PREVIEW_HEIGHT - 1)
			var background := Color(
				lerpf(0.16, 0.40, u),
				lerpf(0.20, 0.32, v),
				lerpf(0.36, 0.58, 1.0 - u * 0.4),
				1.0
			)
			var red := mask.get_pixel(x, y).r
			var covered := remap >= 1.0 - red
			output.set_pixel(x, y, Color.BLACK if covered else background)
	return output


func _fail(message: String, code: int) -> void:
	printerr("[FAIL] %s" % message)
	quit(code)
