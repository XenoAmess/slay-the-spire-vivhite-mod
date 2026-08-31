extends SceneTree

const SOURCE_SIZE := Vector2i(1024, 1024)
const RUNTIME_SIZE := Vector2i(1000, 760)


func _init() -> void:
	var args := OS.get_cmdline_user_args()
	if args.size() != 4:
		printerr("usage: inspect_candidate.gd <native-path> <prepared-source-path> <runtime-path> <inspection-output-dir>")
		quit(2)
		return

	var native_path := args[0]
	var source_path := args[1]
	var runtime_path := args[2]
	var output_dir := args[3]
	var native := _load_image(native_path, "native source")
	var source := _load_image(source_path, "prepared source")
	var runtime := _load_image(runtime_path, "runtime")
	if native == null or source == null or runtime == null:
		quit(3)
		return
	if native.get_size() != Vector2i(1254, 1254):
		printerr("native source does not match verified built-in output size: %s" % native.get_size())
		quit(4)
		return
	if not _is_fully_opaque(native):
		printerr("native source contains alpha below 255")
		quit(4)
		return
	if source.get_size() != SOURCE_SIZE:
		printerr("source is not 1024x1024: %s" % source.get_size())
		quit(4)
		return
	if not _is_fully_opaque(source):
		printerr("source contains alpha below 255")
		quit(4)
		return
	if runtime.get_size() != RUNTIME_SIZE:
		printerr("runtime candidate is not 1000x760: %s" % runtime.get_size())
		quit(4)
		return
	if runtime.get_format() != Image.FORMAT_RGB8:
		printerr("runtime candidate is not RGB8: %s" % runtime.get_format())
		quit(4)
		return

	_save(runtime, output_dir.path_join("centered-25x19-1000x760-rgb8.png"))
	var gray := runtime.duplicate()
	gray.convert(Image.FORMAT_L8)
	_save(gray, output_dir.path_join("centered-25x19-1000x760-gray.png"))
	_save_scaled(runtime, output_dir.path_join("thumbnail-250x190-color.png"), 250, 190)
	_save_scaled(gray, output_dir.path_join("thumbnail-250x190-gray.png"), 250, 190)
	_save_scaled(runtime, output_dir.path_join("thumbnail-100x76-color.png"), 100, 76)
	_save_scaled(gray, output_dir.path_join("thumbnail-100x76-gray.png"), 100, 76)
	print(
		"native=1254x1254 fully_opaque=true prepared=1024x1024 RGB8 "
		+ "crop=12,132,1000,760 "
		+ "runtime=1000x760 format=RGB8 thumbnails=250x190,100x76"
	)
	quit(0)


func _load_image(path: String, label: String) -> Image:
	var image := Image.load_from_file(path)
	if image == null or image.is_empty():
		printerr("failed to decode %s image" % label)
		return null
	if image.is_compressed():
		var error := image.decompress()
		if error != OK:
			printerr("failed to decompress %s image: %s" % [label, error_string(error)])
			return null
	return image


func _is_fully_opaque(image: Image) -> bool:
	var rgba := image.duplicate()
	if rgba.get_format() != Image.FORMAT_RGBA8:
		rgba.convert(Image.FORMAT_RGBA8)
	var bytes: PackedByteArray = rgba.get_data()
	for index in range(3, bytes.size(), 4):
		if bytes[index] != 255:
			return false
	return true


func _save(source: Image, path: String) -> void:
	var error := source.save_png(path)
	if error != OK:
		push_error("failed to save %s: %s" % [path, error_string(error)])


func _save_scaled(source: Image, path: String, width: int, height: int) -> void:
	var scaled := source.duplicate()
	scaled.resize(width, height, Image.INTERPOLATE_LANCZOS)
	_save(scaled, path)
