extends SceneTree


func _init() -> void:
	var args := OS.get_cmdline_user_args()
	if args.size() != 1:
		push_error("usage: inspect_candidate.gd <absolute-runtime-path>")
		quit(2)
		return

	var runtime := Image.load_from_file(args[0])
	if runtime.is_empty():
		push_error("failed to decode runtime image")
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

	runtime.save_png("res://centered-25x19-1000x760-rgb8.png")

	var gray := runtime.duplicate()
	gray.convert(Image.FORMAT_L8)
	gray.save_png("res://centered-25x19-1000x760-gray.png")

	_save_scaled(runtime, "res://thumbnail-250x190-color.png", 250, 190)
	_save_scaled(gray, "res://thumbnail-250x190-gray.png", 250, 190)
	_save_scaled(runtime, "res://thumbnail-100x76-color.png", 100, 76)
	_save_scaled(gray, "res://thumbnail-100x76-gray.png", 100, 76)

	print("runtime=1000x760 format=RGB8 inspection_thumbnails=250x190,100x76")
	quit(0)


func _save_scaled(source: Image, path: String, width: int, height: int) -> void:
	var scaled := source.duplicate()
	scaled.resize(width, height, Image.INTERPOLATE_LANCZOS)
	scaled.save_png(path)
