extends SceneTree

# Converts the flat green technical background requested from ImageGen into
# real RGBA transparency. This is deliberately color-dominance based instead
# of matching one RGB value because generated backgrounds contain mild
# gradients and compression noise.

const FULLY_FOREGROUND_DOMINANCE := 0.07
const FULLY_BACKGROUND_DOMINANCE := 0.32
const MIN_GREEN := 0.34


func _initialize() -> void:
	var args := OS.get_cmdline_user_args()
	if args.size() != 2:
		push_error("usage: remove_chroma.gd -- <input.png> <output.png>")
		quit(2)
		return

	var input_path := args[0]
	var output_path := args[1]
	var image := Image.new()
	var load_error := image.load(input_path)
	if load_error != OK:
		push_error("unable to load image %s: %s" % [input_path, error_string(load_error)])
		quit(3)
		return

	image.convert(Image.FORMAT_RGBA8)
	var background := _estimate_background(image)
	var transparent_pixels := 0
	var partial_pixels := 0
	var opaque_pixels := 0

	for y in image.get_height():
		for x in image.get_width():
			var source := image.get_pixel(x, y)
			var dominance := source.g - maxf(source.r, source.b)
			var background_amount := 0.0
			if source.g >= MIN_GREEN:
				background_amount = smoothstep(
					FULLY_FOREGROUND_DOMINANCE,
					FULLY_BACKGROUND_DOMINANCE,
					dominance
				)

			var alpha := source.a * (1.0 - background_amount)
			if alpha <= 0.003:
				image.set_pixel(x, y, Color(0.0, 0.0, 0.0, 0.0))
				transparent_pixels += 1
			elif alpha >= 0.997:
				image.set_pixel(x, y, Color(source.r, source.g, source.b, 1.0))
				opaque_pixels += 1
			else:
				# Remove the estimated green matte from antialiased boundary pixels.
				var red := clampf((source.r - (1.0 - alpha) * background.r) / alpha, 0.0, 1.0)
				var green := clampf((source.g - (1.0 - alpha) * background.g) / alpha, 0.0, 1.0)
				var blue := clampf((source.b - (1.0 - alpha) * background.b) / alpha, 0.0, 1.0)
				image.set_pixel(x, y, Color(red, green, blue, alpha))
				partial_pixels += 1

	var output_directory := output_path.get_base_dir()
	if not output_directory.is_empty():
		DirAccess.make_dir_recursive_absolute(output_directory)
	var save_error := image.save_png(output_path)
	if save_error != OK:
		push_error("unable to save image %s: %s" % [output_path, error_string(save_error)])
		quit(4)
		return

	print(JSON.stringify({
		"input": input_path,
		"output": output_path,
		"width": image.get_width(),
		"height": image.get_height(),
		"estimated_background": background.to_html(false),
		"transparent_pixels": transparent_pixels,
		"partial_pixels": partial_pixels,
		"opaque_pixels": opaque_pixels,
	}))
	quit(0)


func _estimate_background(image: Image) -> Color:
	var x_max := image.get_width() - 1
	var y_max := image.get_height() - 1
	var samples := [
		image.get_pixel(0, 0),
		image.get_pixel(x_max, 0),
		image.get_pixel(0, y_max),
		image.get_pixel(x_max, y_max),
		image.get_pixel(int(image.get_width() / 2), 0),
		image.get_pixel(int(image.get_width() / 2), y_max),
	]
	var result := Color(0.0, 0.0, 0.0, 1.0)
	for sample in samples:
		result.r += sample.r
		result.g += sample.g
		result.b += sample.b
	result.r /= samples.size()
	result.g /= samples.size()
	result.b /= samples.size()
	return result
