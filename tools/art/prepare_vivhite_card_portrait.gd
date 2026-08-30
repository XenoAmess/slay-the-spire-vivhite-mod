extends SceneTree

## Deterministically prepares one accepted, fully opaque card illustration for runtime.
##
## The source is never modified. The largest centered rectangle with an exact 25:19
## integer ratio is cropped, resized to 1000x760 with Lanczos, and saved as RGB8.
## Any source pixel with alpha below 255 is a hard failure; this tool never hides
## transparency by flattening, masking, thresholding, or painting a background.

const TARGET_WIDTH := 1000
const TARGET_HEIGHT := 760
const RATIO_WIDTH := 25
const RATIO_HEIGHT := 19


func _initialize() -> void:
	var options := _parse_options(OS.get_cmdline_user_args())
	var source_path: String = options.get("source", "")
	var output_path: String = options.get("output", "")
	if source_path.is_empty() or output_path.is_empty():
		printerr("Usage: --source <opaque-source.png> --output <runtime.png>")
		quit(2)
		return

	var status := _prepare(source_path, output_path)
	quit(status)


func _parse_options(args: PackedStringArray) -> Dictionary:
	var parsed := {}
	var index := 0
	while index < args.size():
		var option := args[index]
		if option in ["--source", "--output"] and index + 1 < args.size():
			parsed[option.trim_prefix("--")] = args[index + 1]
			index += 2
		else:
			index += 1
	return parsed


func _prepare(source_path: String, output_path: String) -> int:
	if not FileAccess.file_exists(source_path):
		printerr("Source card illustration does not exist: %s" % source_path)
		return 2
	if FileAccess.file_exists(output_path):
		printerr("Refusing to overwrite an existing runtime portrait: %s" % output_path)
		return 2

	var source := Image.load_from_file(source_path)
	if source == null or source.is_empty():
		printerr("Could not decode source card illustration: %s" % source_path)
		return 2
	if source.is_compressed():
		var decompress_error := source.decompress()
		if decompress_error != OK:
			printerr("Image.decompress failed: %s" % error_string(decompress_error))
			return 2

	if not _is_fully_opaque(source):
		printerr(
			"Source contains alpha below 255. Full card illustrations must be "
			+ "generated as opaque scenes; this tool will not flatten them."
		)
		return 3

	var source_width := source.get_width()
	var source_height := source.get_height()
	var integer_scale: int = mini(
		floori(float(source_width) / float(RATIO_WIDTH)),
		floori(float(source_height) / float(RATIO_HEIGHT))
	)
	if integer_scale <= 0:
		printerr("Source is too small for a 25:19 crop: %dx%d" % [source_width, source_height])
		return 2

	var crop_width := RATIO_WIDTH * integer_scale
	var crop_height := RATIO_HEIGHT * integer_scale
	var crop_x := floori(float(source_width - crop_width) / 2.0)
	var crop_y := floori(float(source_height - crop_height) / 2.0)
	var prepared := source.get_region(
		Rect2i(crop_x, crop_y, crop_width, crop_height)
	)
	if prepared == null or prepared.is_empty():
		printerr("Image.get_region returned no pixels.")
		return 2

	prepared.resize(TARGET_WIDTH, TARGET_HEIGHT, Image.INTERPOLATE_LANCZOS)
	prepared.convert(Image.FORMAT_RGB8)
	if prepared.get_width() != TARGET_WIDTH or prepared.get_height() != TARGET_HEIGHT:
		printerr("Lanczos resize did not produce 1000x760.")
		return 2
	if prepared.get_format() != Image.FORMAT_RGB8:
		printerr("Prepared image did not convert to RGB8.")
		return 2

	var output_directory := output_path.get_base_dir()
	var mkdir_error := DirAccess.make_dir_recursive_absolute(output_directory)
	if mkdir_error != OK:
		printerr("Could not create output directory: %s" % error_string(mkdir_error))
		return 2
	var save_error := prepared.save_png(output_path)
	if save_error != OK:
		printerr("Image.save_png failed: %s" % error_string(save_error))
		return 2

	print(
		(
			"Prepared opaque Vivhite card portrait: %s -> %s "
			+ "(crop x=%d y=%d w=%d h=%d; RGB8 1000x760)"
		)
		% [source_path, output_path, crop_x, crop_y, crop_width, crop_height]
	)
	return 0


func _is_fully_opaque(image: Image) -> bool:
	var rgba := image.duplicate()
	if rgba.get_format() != Image.FORMAT_RGBA8:
		rgba.convert(Image.FORMAT_RGBA8)
	var bytes: PackedByteArray = rgba.get_data()
	for index in range(3, bytes.size(), 4):
		if bytes[index] != 255:
			return false
	return true
