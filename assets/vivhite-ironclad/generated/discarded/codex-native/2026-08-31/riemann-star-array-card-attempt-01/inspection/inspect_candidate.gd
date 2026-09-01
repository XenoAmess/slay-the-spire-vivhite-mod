extends SceneTree


func _init() -> void:
	var args := OS.get_cmdline_user_args()
	if args.size() != 2:
		push_error("usage: inspect_candidate.gd <absolute-original-path> <absolute-runtime-path>")
		quit(2)
		return

	var source := Image.load_from_file(args[0])
	var runtime := Image.load_from_file(args[1])
	if source.is_empty() or runtime.is_empty():
		push_error("failed to decode original or runtime image")
		quit(3)
		return
	if runtime.get_width() != 1000 or runtime.get_height() != 760:
		push_error("runtime image is not 1000x760")
		quit(4)
		return
	if runtime.get_format() != Image.FORMAT_RGB8:
		push_error("runtime image is not RGB8")
		quit(5)
		return

	var gray := runtime.duplicate()
	gray.convert(Image.FORMAT_L8)
	gray.save_png("res://centered-25x19-1000x760-gray.png")

	_save_scaled(runtime, "res://thumbnail-250x190-color.png", 250, 190)
	_save_scaled(gray, "res://thumbnail-250x190-gray.png", 250, 190)
	_save_scaled(runtime, "res://thumbnail-100x76-color.png", 100, 76)
	_save_scaled(gray, "res://thumbnail-100x76-gray.png", 100, 76)

	var array_detail := runtime.get_region(Rect2i(230, 190, 470, 390))
	array_detail.resize(940, 780, Image.INTERPOLATE_LANCZOS)
	array_detail.save_png("res://detail-five-term-array.png")
	var impact_detail := runtime.get_region(Rect2i(690, 110, 310, 390))
	impact_detail.resize(620, 780, Image.INTERPOLATE_LANCZOS)
	impact_detail.save_png("res://detail-terminal-impacts.png")

	var scale_units: int = mini(source.get_width() / 25, source.get_height() / 19)
	var crop_width := scale_units * 25
	var crop_height := scale_units * 19
	var crop_x := (source.get_width() - crop_width) / 2
	var crop_y := (source.get_height() - crop_height) / 2
	print("source=%dx%d format=%s crop=%d,%d,%d,%d runtime=%dx%d format=%s" % [
		source.get_width(), source.get_height(), str(source.get_format()),
		crop_x, crop_y, crop_width, crop_height,
		runtime.get_width(), runtime.get_height(), str(runtime.get_format())
	])
	quit(0)


func _save_scaled(source: Image, path: String, width: int, height: int) -> void:
	var scaled := source.duplicate()
	scaled.resize(width, height, Image.INTERPOLATE_LANCZOS)
	scaled.save_png(path)
