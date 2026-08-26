extends SceneTree

# Converts the high-resolution, chroma-keyed Vivhite UI source art into the
# exact image sizes and anchor boxes expected by the Ironclad replacement.
# icon_outline and select_locked are deliberately derived from their matching
# normal images so changing UI state never changes the character's framing.

const ALPHA_CROP_THRESHOLD := 16.0 / 255.0

const ICON_SIZE := Vector2i(85, 85)
const ICON_RECT := Rect2i(4, 12, 76, 62)
const SELECT_SIZE := Vector2i(132, 195)
const MAP_SIZE := Vector2i(49, 64)
const MAP_RECT := Rect2i(0, 7, 49, 52)
const HAND_SIZE := Vector2i(422, 1200)

const SOURCE_NAMES := [
	"icon",
	"select",
	"map-marker",
	"point",
	"rock",
	"paper",
	"scissors",
]

const OUTPUT_PATHS := [
	"icon.png",
	"icon_outline.png",
	"select.png",
	"select_locked.png",
	"map_marker.png",
	"multiplayer/point.png",
	"multiplayer/rock.png",
	"multiplayer/paper.png",
	"multiplayer/scissors.png",
]

const HAND_RECTS := {
	"point": Rect2i(43, 18, 324, 1182),
	"rock": Rect2i(43, 143, 324, 1057),
	"paper": Rect2i(23, 14, 344, 1186),
	"scissors": Rect2i(43, 18, 324, 1182),
}

var _failure_code := 0


func _initialize() -> void:
	var args := OS.get_cmdline_user_args()
	if args.size() != 2:
		_fail("usage: process_vivhite_ui.gd -- <alpha-source-dir> <output-dir>", 2)
		_quit_with_failure()
		return

	var source_dir := _absolute_path(args[0])
	var output_dir := _absolute_path(args[1])
	if _failure_code != 0:
		_quit_with_failure()
		return
	var sources := {}
	for source_name: String in SOURCE_NAMES:
		var source_image := _load_rgba(
			source_dir.path_join("%s-alpha.png" % source_name)
		)
		if source_image == null:
			_quit_with_failure()
			return
		sources[source_name] = source_image

	# Build every output in memory before opening the destination. This keeps a
	# bad source or processing failure from leaving a partially refreshed set.
	var outputs := {}

	var icon := _fit_source(
		sources["icon"], ICON_SIZE, ICON_RECT
	)
	if icon == null:
		_quit_with_failure()
		return
	outputs["icon.png"] = icon
	outputs["icon_outline.png"] = _make_white_outline(icon, 4)

	var select_subject := _fit_source(
		sources["select"],
		SELECT_SIZE,
		Rect2i(Vector2i.ZERO, SELECT_SIZE)
	)
	if select_subject == null:
		_quit_with_failure()
		return
	var select := _make_select_background()
	select.blend_rect(
		select_subject,
		Rect2i(Vector2i.ZERO, SELECT_SIZE),
		Vector2i.ZERO
	)
	outputs["select.png"] = select
	outputs["select_locked.png"] = _make_locked_select(select, select_subject)

	var map_marker := _fit_source(
		sources["map-marker"], MAP_SIZE, MAP_RECT
	)
	if map_marker == null:
		_quit_with_failure()
		return
	outputs["map_marker.png"] = map_marker

	for gesture: String in HAND_RECTS:
		var hand := _fit_source(
			sources[gesture],
			HAND_SIZE,
			HAND_RECTS[gesture]
		)
		if hand == null:
			_quit_with_failure()
			return
		_apply_hand_bottom_fade(hand)
		outputs["multiplayer/%s.png" % gesture] = hand

	if not _write_outputs(outputs, output_dir):
		_quit_with_failure()
		return
	if _failure_code != 0:
		_quit_with_failure()
		return

	print(JSON.stringify({
		"source_dir": source_dir,
		"output_dir": output_dir,
		"files": OUTPUT_PATHS,
	}))
	quit(0)


func _load_rgba(path: String) -> Image:
	var image := Image.new()
	var error := image.load(path)
	if error != OK:
		_fail("unable to load %s: %s" % [path, error_string(error)], 3)
		return null
	image.convert(Image.FORMAT_RGBA8)
	return image


func _fit_source(source: Image, canvas_size: Vector2i, target: Rect2i) -> Image:
	var bounds := _alpha_bounds(source, ALPHA_CROP_THRESHOLD)
	if bounds.size == Vector2i.ZERO:
		_fail("source contains no usable alpha", 4)
		return null

	var cropped := source.get_region(bounds)
	_clear_low_alpha(cropped, ALPHA_CROP_THRESHOLD)
	cropped.resize(target.size.x, target.size.y, Image.INTERPOLATE_LANCZOS)

	var canvas := Image.create(
		canvas_size.x, canvas_size.y, false, Image.FORMAT_RGBA8
	)
	canvas.fill(Color(0.0, 0.0, 0.0, 0.0))
	canvas.blit_rect(
		cropped,
		Rect2i(Vector2i.ZERO, cropped.get_size()),
		target.position
	)
	_remove_green_residue(canvas)
	return canvas


func _alpha_bounds(image: Image, threshold: float) -> Rect2i:
	var min_x := image.get_width()
	var min_y := image.get_height()
	var max_x := -1
	var max_y := -1
	for y in image.get_height():
		for x in image.get_width():
			if image.get_pixel(x, y).a <= threshold:
				continue
			min_x = mini(min_x, x)
			min_y = mini(min_y, y)
			max_x = maxi(max_x, x)
			max_y = maxi(max_y, y)
	if max_x < min_x or max_y < min_y:
		return Rect2i()
	return Rect2i(min_x, min_y, max_x - min_x + 1, max_y - min_y + 1)


func _clear_low_alpha(image: Image, threshold: float) -> void:
	for y in image.get_height():
		for x in image.get_width():
			var color := image.get_pixel(x, y)
			if color.a <= threshold:
				image.set_pixel(x, y, Color(0.0, 0.0, 0.0, 0.0))


func _remove_green_residue(image: Image) -> void:
	for y in image.get_height():
		for x in image.get_width():
			var color := image.get_pixel(x, y)
			var dominance := color.g - maxf(color.r, color.b)
			if color.a > 0.0 and color.g > 0.20 and dominance > 0.12:
				image.set_pixel(x, y, Color(0.0, 0.0, 0.0, 0.0))


func _make_white_outline(icon: Image, radius: int) -> Image:
	var outline := Image.create(
		icon.get_width(), icon.get_height(), false, Image.FORMAT_RGBA8
	)
	outline.fill(Color(0.0, 0.0, 0.0, 0.0))
	var radius_squared := radius * radius
	for y in icon.get_height():
		for x in icon.get_width():
			var alpha := 0.0
			for offset_y in range(-radius, radius + 1):
				for offset_x in range(-radius, radius + 1):
					if offset_x * offset_x + offset_y * offset_y > radius_squared:
						continue
					var source_x := x + offset_x
					var source_y := y + offset_y
					if (
						source_x < 0
						or source_y < 0
						or source_x >= icon.get_width()
						or source_y >= icon.get_height()
					):
						continue
					alpha = maxf(alpha, icon.get_pixel(source_x, source_y).a)
			if alpha > 0.0:
				outline.set_pixel(x, y, Color(1.0, 1.0, 1.0, alpha))
	return outline


func _make_select_background() -> Image:
	var background := Image.create(
		SELECT_SIZE.x, SELECT_SIZE.y, false, Image.FORMAT_RGBA8
	)
	var top := Color("17142f")
	var bottom := Color("54245e")
	var cyan := Color("285a83")
	for y in SELECT_SIZE.y:
		var vertical := float(y) / float(SELECT_SIZE.y - 1)
		for x in SELECT_SIZE.x:
			var horizontal := float(x) / float(SELECT_SIZE.x - 1)
			var color := top.lerp(bottom, vertical)
			var cyan_distance := Vector2(horizontal - 0.82, vertical - 0.18).length()
			var cyan_amount := clampf(1.0 - cyan_distance / 0.72, 0.0, 1.0) * 0.34
			color = color.lerp(cyan, cyan_amount)
			var texture := sin(float(x) * 0.31 + float(y) * 0.17) * 0.012
			color.r = clampf(color.r + texture, 0.0, 1.0)
			color.g = clampf(color.g + texture, 0.0, 1.0)
			color.b = clampf(color.b + texture, 0.0, 1.0)
			color.a = 1.0
			background.set_pixel(x, y, color)
	return background


func _make_locked_select(normal: Image, subject: Image) -> Image:
	var locked := Image.create(
		SELECT_SIZE.x, SELECT_SIZE.y, false, Image.FORMAT_RGBA8
	)
	for y in SELECT_SIZE.y:
		for x in SELECT_SIZE.x:
			var source := normal.get_pixel(x, y)
			var luminance := (
				source.r * 0.2126 + source.g * 0.7152 + source.b * 0.0722
			)
			var silhouette := pow(subject.get_pixel(x, y).a, 0.58)
			var value := lerpf(luminance * 0.78, 0.0, silhouette * 0.98)
			locked.set_pixel(x, y, Color(value, value, value, 1.0))
	return locked


func _apply_hand_bottom_fade(image: Image) -> void:
	for y in range(1037, image.get_height()):
		var opacity := 1.0
		if y <= 1108:
			opacity = lerpf(0.49, 0.064, float(y - 1037) / 71.0)
		else:
			opacity = lerpf(0.058, 0.004, float(y - 1109) / 90.0)
		for x in image.get_width():
			var color := image.get_pixel(x, y)
			if color.a <= 0.0:
				continue
			color.a *= opacity
			image.set_pixel(x, y, color)


func _save(image: Image, path: String) -> bool:
	var error := image.save_png(path)
	if error != OK:
		_fail("unable to save %s: %s" % [path, error_string(error)], 5)
		return false
	return true


func _write_outputs(outputs: Dictionary, output_dir: String) -> bool:
	var parent_dir := output_dir.get_base_dir()
	var parent_error := DirAccess.make_dir_recursive_absolute(parent_dir)
	if parent_error != OK:
		_fail(
			"unable to create output parent %s: %s"
			% [parent_dir, error_string(parent_error)],
			5
		)
		return false

	# PID keeps concurrent tool processes distinct; ticks keep sequential runs
	# in the same process distinct without introducing nondeterminism in images.
	var transaction_id := "%s-%s" % [OS.get_process_id(), Time.get_ticks_usec()]
	var staging_dir := "%s.tmp-%s" % [output_dir, transaction_id]
	var backup_dir := "%s.backup-%s" % [output_dir, transaction_id]
	var staging_error := DirAccess.make_dir_recursive_absolute(
		staging_dir.path_join("multiplayer")
	)
	if staging_error != OK:
		_fail(
			"unable to create staging directory %s: %s"
			% [staging_dir, error_string(staging_error)],
			5
		)
		return false

	for relative_path: String in OUTPUT_PATHS:
		var image: Image = outputs.get(relative_path)
		if image == null:
			_fail("missing processed output: %s" % relative_path, 4)
			_remove_tree(staging_dir)
			return false
		if not _save(image, staging_dir.path_join(relative_path)):
			_remove_tree(staging_dir)
			return false

	var had_previous_output := DirAccess.dir_exists_absolute(output_dir)
	if not had_previous_output and FileAccess.file_exists(output_dir):
		_fail("output path is a file, not a directory: %s" % output_dir, 5)
		_remove_tree(staging_dir)
		return false

	if had_previous_output:
		var backup_error := DirAccess.rename_absolute(output_dir, backup_dir)
		if backup_error != OK:
			_fail(
				"unable to stage existing output %s: %s"
				% [output_dir, error_string(backup_error)],
				5
			)
			_remove_tree(staging_dir)
			return false

	var publish_error := DirAccess.rename_absolute(staging_dir, output_dir)
	if publish_error != OK:
		_fail(
			"unable to publish output %s: %s"
			% [output_dir, error_string(publish_error)],
			5
		)
		if had_previous_output:
			var restore_error := DirAccess.rename_absolute(backup_dir, output_dir)
			if restore_error != OK:
				push_error(
					"unable to restore previous output %s: %s"
					% [output_dir, error_string(restore_error)]
				)
		_remove_tree(staging_dir)
		return false

	if had_previous_output:
		var cleanup_error := _remove_tree(backup_dir)
		if cleanup_error != OK:
			_fail(
				"published output but could not remove backup %s: %s"
				% [backup_dir, error_string(cleanup_error)],
				5
			)
			return false
	return true


func _remove_tree(path: String) -> Error:
	# Treat links as leaves. In particular, never recurse through a polluted
	# output directory's symlink/junction while cleaning a transaction backup.
	if _is_link(path):
		return DirAccess.remove_absolute(path)
	if not DirAccess.dir_exists_absolute(path):
		return OK
	for file_name: String in DirAccess.get_files_at(path):
		var file_error := DirAccess.remove_absolute(path.path_join(file_name))
		if file_error != OK:
			return file_error
	for directory_name: String in DirAccess.get_directories_at(path):
		var directory_error := _remove_tree(path.path_join(directory_name))
		if directory_error != OK:
			return directory_error
	return DirAccess.remove_absolute(path)


func _is_link(path: String) -> bool:
	var parent := DirAccess.open(path.get_base_dir())
	return parent != null and parent.is_link(path.get_file())


func _absolute_path(path: String) -> String:
	var simplified := path.simplify_path()
	if simplified.is_absolute_path():
		return simplified
	# Godot changes its process directory to the --path project. The art tools
	# live two levels below the repository, while their documented relative
	# arguments are repository-relative.
	var repository_root := ProjectSettings.globalize_path("res://").path_join("../..").simplify_path()
	return repository_root.path_join(simplified).simplify_path()


func _fail(message: String, code: int) -> void:
	push_error(message)
	if _failure_code == 0:
		_failure_code = code


func _quit_with_failure() -> void:
	quit(_failure_code if _failure_code != 0 else 1)
