extends SceneTree


func _init() -> void:
	var args := OS.get_cmdline_user_args()
	if args.size() != 1:
		push_error("usage: inspect_candidate.gd <absolute-source-path>")
		quit(2)
		return

	var source := Image.load_from_file(args[0])
	if source.is_empty():
		push_error("failed to decode source image")
		quit(3)
		return

	var scale_units: int = mini(source.get_width() / 25, source.get_height() / 19)
	var crop_width := scale_units * 25
	var crop_height := scale_units * 19
	var crop_x := (source.get_width() - crop_width) / 2
	var crop_y := (source.get_height() - crop_height) / 2
	var runtime := source.get_region(Rect2i(crop_x, crop_y, crop_width, crop_height))
	runtime.resize(1000, 760, Image.INTERPOLATE_LANCZOS)
	if runtime.get_format() != Image.FORMAT_RGB8:
		runtime.convert(Image.FORMAT_RGB8)
	runtime.save_png("res://centered-25x19-1000x760-rgb8.png")

	var gray := runtime.duplicate()
	gray.convert(Image.FORMAT_L8)
	gray.save_png("res://centered-25x19-1000x760-gray.png")

	_save_scaled(runtime, "res://thumbnail-250x190-color.png", 250, 190)
	_save_scaled(gray, "res://thumbnail-250x190-gray.png", 250, 190)
	_save_scaled(runtime, "res://thumbnail-100x76-color.png", 100, 76)
	_save_scaled(gray, "res://thumbnail-100x76-gray.png", 100, 76)

	print("source=%dx%d format=%s crop=%d,%d,%d,%d target=1000x760 RGB8" % [
		source.get_width(), source.get_height(), str(source.get_format()),
		crop_x, crop_y, crop_width, crop_height
	])
	quit(0)


func _save_scaled(source: Image, path: String, width: int, height: int) -> void:
	var scaled := source.duplicate()
	scaled.resize(width, height, Image.INTERPOLATE_LANCZOS)
	scaled.save_png(path)
