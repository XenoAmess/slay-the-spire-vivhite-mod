extends SceneTree

func _initialize() -> void:
	var args := OS.get_cmdline_user_args()
	if args.size() != 2:
		printerr("usage: inspect_candidate.gd <runtime-rgb8-path> <inspection-output-dir>")
		quit(2)
		return

	var runtime_path := args[0]
	var output_dir := args[1]
	var image := Image.load_from_file(runtime_path)
	if image == null or image.is_empty():
		printerr("failed to decode runtime candidate")
		quit(3)
		return
	if image.is_compressed():
		var error := image.decompress()
		if error != OK:
			printerr("failed to decompress runtime candidate: %s" % error_string(error))
			quit(3)
			return
	if image.get_size() != Vector2i(1000, 760):
		printerr("runtime candidate is not 1000x760")
		quit(4)
		return
	if image.get_format() != Image.FORMAT_RGB8:
		printerr("runtime candidate is not RGB8: %s" % image.get_format())
		quit(4)
		return

	var gray := image.duplicate()
	gray.convert(Image.FORMAT_L8)
	_save(gray, output_dir.path_join("centered-25x19-1000x760-gray.png"))
	_save_scaled(image, output_dir.path_join("thumbnail-250x190-color.png"), 250, 190)
	_save_scaled(gray, output_dir.path_join("thumbnail-250x190-gray.png"), 250, 190)
	_save_scaled(image, output_dir.path_join("thumbnail-100x76-color.png"), 100, 76)
	_save_scaled(gray, output_dir.path_join("thumbnail-100x76-gray.png"), 100, 76)
	print("inspection outputs saved for 1000x760 RGB8 runtime candidate")
	quit(0)


func _save(source: Image, path: String) -> void:
	var error := source.save_png(path)
	if error != OK:
		push_error("failed to save %s: %s" % [path, error_string(error)])


func _save_scaled(source: Image, path: String, width: int, height: int) -> void:
	var scaled := source.duplicate()
	scaled.resize(width, height, Image.INTERPOLATE_LANCZOS)
	_save(scaled, path)

