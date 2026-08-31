extends SceneTree

const TARGET_SIZE := Vector2i(1024, 1024)


func _init() -> void:
	var args := OS.get_cmdline_user_args()
	if args.size() != 2:
		printerr("usage: prepare_square_source.gd <native-source-path> <prepared-source-path>")
		quit(2)
		return

	var source := Image.load_from_file(args[0])
	if source == null or source.is_empty():
		printerr("failed to decode native source")
		quit(3)
		return
	if source.is_compressed():
		var decompress_error: Error = source.decompress()
		if decompress_error != OK:
			printerr("failed to decompress native source: %s" % error_string(decompress_error))
			quit(3)
			return
	if source.get_width() != source.get_height():
		printerr("native source is not square: %s" % source.get_size())
		quit(4)
		return
	if not _is_fully_opaque(source):
		printerr("native source contains alpha below 255")
		quit(4)
		return
	if FileAccess.file_exists(args[1]):
		printerr("refusing to overwrite prepared source: %s" % args[1])
		quit(5)
		return

	var prepared := source.duplicate()
	prepared.resize(TARGET_SIZE.x, TARGET_SIZE.y, Image.INTERPOLATE_LANCZOS)
	prepared.convert(Image.FORMAT_RGB8)
	var save_error: Error = prepared.save_png(args[1])
	if save_error != OK:
		printerr("failed to save prepared source: %s" % error_string(save_error))
		quit(6)
		return
	print(
		"native=%dx%d fully_opaque=true -> prepared=1024x1024 format=RGB8 interpolation=Lanczos"
		% [source.get_width(), source.get_height()]
	)
	quit(0)


func _is_fully_opaque(image: Image) -> bool:
	var rgba := image.duplicate()
	if rgba.get_format() != Image.FORMAT_RGBA8:
		rgba.convert(Image.FORMAT_RGBA8)
	var bytes: PackedByteArray = rgba.get_data()
	for index in range(3, bytes.size(), 4):
		if bytes[index] != 255:
			return false
	return true
