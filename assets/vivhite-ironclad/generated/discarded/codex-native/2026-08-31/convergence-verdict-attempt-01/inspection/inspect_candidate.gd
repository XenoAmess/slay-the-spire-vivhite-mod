extends SceneTree

const ARCHIVE := "res://../../assets/vivhite-ironclad/generated/codex-native/2026-08-31/convergence-verdict-attempt-01/inspection"
const SOURCE := ARCHIVE + "/centered-25x19-1000x760-rgb8.png"


func _initialize() -> void:
	var image := Image.load_from_file(SOURCE)
	if image == null or image.is_empty():
		printerr("Could not load prepared candidate: %s" % SOURCE)
		quit(2)
		return
	if image.get_width() != 1000 or image.get_height() != 760 or image.get_format() != Image.FORMAT_RGB8:
		printerr("Prepared candidate contract mismatch: %dx%d format=%s" % [image.get_width(), image.get_height(), image.get_format()])
		quit(3)
		return

	var gray := _grayscale(image)
	_save(gray, ARCHIVE + "/centered-25x19-1000x760-gray.png")
	_save_resized(image, ARCHIVE + "/thumbnail-250x190-color.png", 250, 190)
	_save_resized(gray, ARCHIVE + "/thumbnail-250x190-gray.png", 250, 190)
	_save_resized(image, ARCHIVE + "/thumbnail-100x76-color.png", 100, 76)
	_save_resized(gray, ARCHIVE + "/thumbnail-100x76-gray.png", 100, 76)
	print("Prepared ConvergenceVerdict color, grayscale, and thumbnail inspections.")
	quit(0)


func _grayscale(source: Image) -> Image:
	var result := source.duplicate()
	result.convert(Image.FORMAT_RGBA8)
	for y in range(result.get_height()):
		for x in range(result.get_width()):
			var color: Color = result.get_pixel(x, y)
			var luminance: float = color.r * 0.2126 + color.g * 0.7152 + color.b * 0.0722
			result.set_pixel(x, y, Color(luminance, luminance, luminance, 1.0))
	result.convert(Image.FORMAT_RGB8)
	return result


func _save_resized(source: Image, path: String, width: int, height: int) -> void:
	var resized := source.duplicate()
	resized.resize(width, height, Image.INTERPOLATE_LANCZOS)
	_save(resized, path)


func _save(image: Image, path: String) -> void:
	var error := image.save_png(path)
	if error != OK:
		printerr("Could not save %s: %s" % [path, error_string(error)])
		quit(4)
