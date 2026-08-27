extends SceneTree

## Builds the private Spine 4.2 rest-site rig for the Ironclad -> Vivhite skin.
##
## The paid RGBA source is read-only. This tool may crop native-transparent
## padding, uniformly resize all RGBA channels together, and pack the result.
## It never creates, extracts, thresholds, masks, shrinks, or repairs Alpha.

const COMMAND := "build-rest-site"
const SPINE_VERSION := "4.2.43"
const DEFAULT_SOURCE := (
	"assets/vivhite-ironclad/custom/rest_site/sources/"
	+ "vivhite-rest-site-seated-master-v1.png"
)
const DEFAULT_OUTPUT_ROOT := "Vivhite/Vivhite/skins/ironclad/spine/rest_site"

const OUTPUT_JSON := "vivhite_rest_site.spjson"
const OUTPUT_ATLAS := "restsite_ironclad.spatlas"
const OUTPUT_PAGE := "restsite_ironclad.png"
const OUTPUT_DATA := "rest_site_skeleton_data.tres"

const ATLAS_PAGE_SIZE := Vector2i(2048, 2048)
const ATLAS_REGION_POSITION := Vector2i(24, 24)
const ATLAS_REGION_SIZE := Vector2i(2000, 2000)
const ATLAS_REGION_NAME := "vivhite_rest_site_seated"
const SOURCE_CONTENT_MARGIN := 8
const REGION_CONTENT_MARGIN := 28

# The existing rest-site scene remains at position (-2, 42), scale 0.760006.
# This setup rectangle fits its unchanged hitbox/reticle while retaining a
# generous transparent margin around the seated magical-girl silhouette.
const HERO_WORLD_RECT := Rect2(-210.0, -350.0, 500.0, 650.0)
const SKELETON_BOUNDS := Rect2(-230.0, -370.0, 540.0, 690.0)
const GRID_COLUMNS := 11
const GRID_ROWS := 15

const ANIMATION_DURATIONS := {
	"overgrowth_loop": 5.0,
	"hive_loop": 3.6,
	"glory_loop": 4.4,
	"_tracks/light_off": 0.5,
	"_tracks/light_on": 0.5,
}

const BONE_ROOT := "root"
const BONE_RIG := "vivhite_rest_rig"
const BONE_PELVIS := "vivhite_pelvis"
const BONE_TORSO_LOWER := "vivhite_torso_lower"
const BONE_TORSO_UPPER := "vivhite_torso_upper"
const BONE_NECK := "vivhite_neck"
const BONE_HEAD := "vivhite_head"
const BONE_GLASSES := "vivhite_glasses"
const BONE_HAIR_CENTER := "vivhite_hair_center"
const BONE_HAIR_LEFT := "vivhite_hair_left"
const BONE_HAIR_RIGHT := "vivhite_hair_right"
const BONE_BUTTERFLY := "vivhite_butterfly"
const BONE_SHOULDER_LEFT := "vivhite_shoulder_left"
const BONE_ARM_LEFT := "vivhite_arm_left"
const BONE_HAND_LEFT := "vivhite_hand_left"
const BONE_SHOULDER_RIGHT := "vivhite_shoulder_right"
const BONE_ARM_RIGHT := "vivhite_arm_right"
const BONE_HAND_RIGHT := "vivhite_hand_right"
const BONE_SKIRT_CENTER := "vivhite_skirt_center"
const BONE_SKIRT_LEFT := "vivhite_skirt_left"
const BONE_SKIRT_RIGHT := "vivhite_skirt_right"
const BONE_THIGH_LEFT := "vivhite_thigh_left"
const BONE_SHIN_LEFT := "vivhite_shin_left"
const BONE_FOOT_LEFT := "vivhite_foot_left"
const BONE_THIGH_RIGHT := "vivhite_thigh_right"
const BONE_SHIN_RIGHT := "vivhite_shin_right"
const BONE_FOOT_RIGHT := "vivhite_foot_right"

const REQUIRED_WEIGHT_BONES := [
	BONE_PELVIS,
	BONE_TORSO_LOWER,
	BONE_TORSO_UPPER,
	BONE_HEAD,
	BONE_HAIR_CENTER,
	BONE_HAIR_LEFT,
	BONE_HAIR_RIGHT,
	BONE_BUTTERFLY,
	BONE_ARM_LEFT,
	BONE_HAND_LEFT,
	BONE_ARM_RIGHT,
	BONE_HAND_RIGHT,
	BONE_SKIRT_CENTER,
	BONE_SKIRT_LEFT,
	BONE_SKIRT_RIGHT,
	BONE_THIGH_LEFT,
	BONE_SHIN_LEFT,
	BONE_THIGH_RIGHT,
	BONE_SHIN_RIGHT,
]

var _last_error := ""


func _initialize() -> void:
	var args := OS.get_cmdline_user_args()
	if args.is_empty():
		args = PackedStringArray([COMMAND])
	if args[0] in ["-h", "--help", "help"]:
		_print_help()
		quit(0)
		return
	if args[0] != COMMAND:
		quit(_fail("Unknown command: %s" % args[0]))
		return

	var options := _parse_options(args)
	if options.is_empty() and args.size() > 1:
		quit(2)
		return
	var source_path := _absolute_path(str(options.get("source", DEFAULT_SOURCE)))
	var output_root := _absolute_path(str(options.get("output-root", DEFAULT_OUTPUT_ROOT)))
	if not _build(source_path, output_root):
		quit(_fail(_last_error))
		return
	quit(0)


func _print_help() -> void:
	print("Usage:")
	print(
		"  godot --headless --path tools/art --script "
		+ "res://build_vivhite_rest_site_rig.gd -- build-rest-site"
	)
	print("    [--source PATH] [--output-root PATH]")


func _parse_options(args: PackedStringArray) -> Dictionary:
	var result := {}
	var index := 1
	while index < args.size():
		var token := args[index]
		if not token.begins_with("--") or index + 1 >= args.size():
			printerr("Expected --name value, got: %s" % token)
			return {}
		result[token.trim_prefix("--")] = args[index + 1]
		index += 2
	return result


func _absolute_path(path: String) -> String:
	if path.is_absolute_path():
		return path.simplify_path()
	var repository_root := ProjectSettings.globalize_path("res://").path_join("../..").simplify_path()
	return repository_root.path_join(path).simplify_path()


func _build(source_path: String, output_root: String) -> bool:
	_last_error = ""
	if not FileAccess.file_exists(source_path):
		return _set_error(
			"Rest-site seated master does not exist; generate and approve the clean EvoLink "
			+ "RGBA source first: %s" % source_path
		)
	var source := Image.load_from_file(source_path)
	if source == null or source.is_empty():
		return _set_error("Could not decode rest-site seated master: %s" % source_path)
	if source.get_format() != Image.FORMAT_RGBA8:
		return _set_error(
			"Rest-site seated master must decode directly as RGBA8; got format %s: %s"
			% [source.get_format(), source_path]
		)
	if not _validate_source_alpha(source, source_path):
		return false

	var prepared := _prepare_region(source)
	if prepared.is_empty():
		return false
	var region: Image = prepared["image"]
	var page := _transparent_image(ATLAS_PAGE_SIZE)
	page.blend_rect(region, Rect2i(Vector2i.ZERO, ATLAS_REGION_SIZE), ATLAS_REGION_POSITION)

	var skeleton := _build_skeleton_json()
	var atlas_data := _build_atlas_data()
	if not _validate_rig(skeleton, atlas_data):
		return false
	if not _make_dir(output_root):
		return false

	var page_path := output_root.path_join(OUTPUT_PAGE)
	var save_error := page.save_png(page_path)
	if save_error != OK:
		return _set_error("Could not save rest-site page (%s): %s" % [error_string(save_error), page_path])
	var skeleton_path := output_root.path_join(OUTPUT_JSON)
	if not _write_text(skeleton_path, JSON.stringify(skeleton, "  ", false) + "\n"):
		return false
	var atlas_wrapper := {
		"atlas_data": atlas_data,
		"normal_texture_prefix": "n",
		"source_path": "res://Vivhite/skins/ironclad/spine/rest_site/restsite_ironclad.atlas",
		"specular_texture_prefix": "s",
	}
	var atlas_path := output_root.path_join(OUTPUT_ATLAS)
	if not _write_text(atlas_path, JSON.stringify(atlas_wrapper, "", false) + "\n"):
		return false
	var data_path := output_root.path_join(OUTPUT_DATA)
	if not _write_text(data_path, _build_skeleton_data_tres()):
		return false
	if not _validate_written_outputs(output_root):
		return false

	print("Built independent Vivhite rest-site rig:")
	print("  source:   %s (read-only)" % source_path)
	print("  skeleton: %s" % skeleton_path)
	print("  atlas:    %s" % atlas_path)
	print("  page:     %s (%dx%d RGBA8)" % [page_path, ATLAS_PAGE_SIZE.x, ATLAS_PAGE_SIZE.y])
	print("  data:     %s" % data_path)
	print("  source alpha bounds: %s" % prepared["source_alpha_bounds"])
	print("  packed content size: %s at %s" % [
		prepared["packed_content_size"],
		prepared["packed_content_position"],
	])
	print("  mesh: %d weighted vertices, %d triangles, hull=%d" % [
		GRID_COLUMNS * GRID_ROWS,
		(GRID_COLUMNS - 1) * (GRID_ROWS - 1) * 2,
		_hull_vertex_count(),
	])
	print("  bones: %d; animations: %s" % [skeleton["bones"].size(), skeleton["animations"].keys()])
	return true


func _validate_source_alpha(image: Image, source_path: String) -> bool:
	var width := image.get_width()
	var height := image.get_height()
	var bytes := image.get_data()
	for pixel_index in PackedInt32Array([
		0,
		width - 1,
		(height - 1) * width,
		height * width - 1,
	]):
		if bytes[pixel_index * 4 + 3] != 0:
			return _set_error(
				"Rest-site source corner Alpha must be exactly zero; this tool never repairs Alpha: %s"
				% source_path
			)
	var transparent_count := 0
	var visible_count := 0
	for index in range(3, bytes.size(), 4):
		if bytes[index] == 0:
			transparent_count += 1
		else:
			visible_count += 1
	if visible_count == 0:
		return _set_error("Rest-site source is fully transparent: %s" % source_path)
	if transparent_count < int(width * height * 0.02):
		return _set_error("Rest-site source lacks meaningful native transparency: %s" % source_path)
	return true


func _prepare_region(source: Image) -> Dictionary:
	var source_bounds := _alpha_bounds(source)
	if source_bounds.size.x <= 0 or source_bounds.size.y <= 0:
		return _error_dictionary("Rest-site source contains no non-zero Alpha pixels")
	var padded_bounds := source_bounds.grow(SOURCE_CONTENT_MARGIN)
	padded_bounds = padded_bounds.intersection(Rect2i(Vector2i.ZERO, source.get_size()))
	var cropped := source.get_region(padded_bounds)
	var available := ATLAS_REGION_SIZE - Vector2i(REGION_CONTENT_MARGIN * 2, REGION_CONTENT_MARGIN * 2)
	var scale_factor := minf(
		float(available.x) / float(cropped.get_width()),
		float(available.y) / float(cropped.get_height())
	)
	# Never enlarge a paid original. Resizing resamples every RGBA channel together.
	scale_factor = minf(scale_factor, 1.0)
	var packed_size := Vector2i(
		maxi(1, int(round(cropped.get_width() * scale_factor))),
		maxi(1, int(round(cropped.get_height() * scale_factor)))
	)
	if packed_size != cropped.get_size():
		cropped.resize(packed_size.x, packed_size.y, Image.INTERPOLATE_LANCZOS)
	var destination := Vector2i(
		int(round(ATLAS_REGION_SIZE.x * 0.5 - packed_size.x * 0.5)),
		ATLAS_REGION_SIZE.y - REGION_CONTENT_MARGIN - packed_size.y
	)
	var region := _transparent_image(ATLAS_REGION_SIZE)
	region.blend_rect(cropped, Rect2i(Vector2i.ZERO, packed_size), destination)
	var packed_bounds := _alpha_bounds(region)
	if (
		packed_bounds.position.x < 1
		or packed_bounds.position.y < 1
		or packed_bounds.end.x >= ATLAS_REGION_SIZE.x - 1
		or packed_bounds.end.y >= ATLAS_REGION_SIZE.y - 1
	):
		return _error_dictionary("Prepared rest-site art touches its atlas region edge: %s" % packed_bounds)
	return {
		"image": region,
		"source_alpha_bounds": source_bounds,
		"packed_content_size": packed_size,
		"packed_content_position": destination,
	}


func _alpha_bounds(image: Image) -> Rect2i:
	var width := image.get_width()
	var height := image.get_height()
	var bytes := image.get_data()
	var min_x := width
	var min_y := height
	var max_x := -1
	var max_y := -1
	for y in height:
		var row_offset := y * width * 4
		for x in width:
			if bytes[row_offset + x * 4 + 3] == 0:
				continue
			min_x = mini(min_x, x)
			min_y = mini(min_y, y)
			max_x = maxi(max_x, x)
			max_y = maxi(max_y, y)
	if max_x < min_x or max_y < min_y:
		return Rect2i()
	return Rect2i(min_x, min_y, max_x - min_x + 1, max_y - min_y + 1)


func _build_skeleton_json() -> Dictionary:
	var bones := _build_bones()
	var bone_indices := {}
	var bone_positions := {}
	for index in bones.size():
		var bone: Dictionary = bones[index]
		var name := str(bone["name"])
		bone_indices[name] = index
		bone_positions[name] = Vector2(float(bone.get("x", 0.0)), float(bone.get("y", 0.0)))
	return {
		"skeleton": {
			"hash": "vivhite-private-rest-site-rig-v1",
			"spine": SPINE_VERSION,
			"x": SKELETON_BOUNDS.position.x,
			"y": SKELETON_BOUNDS.position.y,
			"width": SKELETON_BOUNDS.size.x,
			"height": SKELETON_BOUNDS.size.y,
			"images": "./",
		},
		"bones": bones,
		"slots": [{
			"name": "vivhite_rest_hero",
			"bone": BONE_RIG,
			"attachment": ATLAS_REGION_NAME,
		}],
		"skins": [{
			"name": "default",
			"attachments": {
				"vivhite_rest_hero": {
					ATLAS_REGION_NAME: _build_weighted_mesh(bone_indices, bone_positions),
				},
			},
		}],
		"animations": _build_animations(),
	}


func _build_bones() -> Array:
	return [
		{"name": BONE_ROOT},
		{"name": BONE_RIG, "parent": BONE_ROOT},
		_bone_at(BONE_PELVIS, Vector2(0.50, 0.57)),
		_bone_at(BONE_TORSO_LOWER, Vector2(0.50, 0.44)),
		_bone_at(BONE_TORSO_UPPER, Vector2(0.50, 0.32)),
		_bone_at(BONE_NECK, Vector2(0.50, 0.23)),
		_bone_at(BONE_HEAD, Vector2(0.50, 0.15)),
		_bone_at(BONE_GLASSES, Vector2(0.50, 0.15)),
		_bone_at(BONE_HAIR_CENTER, Vector2(0.50, 0.12)),
		_bone_at(BONE_HAIR_LEFT, Vector2(0.37, 0.17)),
		_bone_at(BONE_HAIR_RIGHT, Vector2(0.63, 0.17)),
		_bone_at(BONE_BUTTERFLY, Vector2(0.66, 0.08)),
		_bone_at(BONE_SHOULDER_LEFT, Vector2(0.36, 0.31)),
		_bone_at(BONE_ARM_LEFT, Vector2(0.29, 0.42)),
		_bone_at(BONE_HAND_LEFT, Vector2(0.39, 0.54)),
		_bone_at(BONE_SHOULDER_RIGHT, Vector2(0.64, 0.31)),
		_bone_at(BONE_ARM_RIGHT, Vector2(0.71, 0.42)),
		_bone_at(BONE_HAND_RIGHT, Vector2(0.61, 0.54)),
		_bone_at(BONE_SKIRT_CENTER, Vector2(0.50, 0.58)),
		_bone_at(BONE_SKIRT_LEFT, Vector2(0.36, 0.62)),
		_bone_at(BONE_SKIRT_RIGHT, Vector2(0.64, 0.62)),
		_bone_at(BONE_THIGH_LEFT, Vector2(0.39, 0.68)),
		_bone_at(BONE_SHIN_LEFT, Vector2(0.28, 0.80)),
		_bone_at(BONE_FOOT_LEFT, Vector2(0.20, 0.91)),
		_bone_at(BONE_THIGH_RIGHT, Vector2(0.61, 0.68)),
		_bone_at(BONE_SHIN_RIGHT, Vector2(0.72, 0.80)),
		_bone_at(BONE_FOOT_RIGHT, Vector2(0.80, 0.91)),
	]


func _bone_at(name: String, normalized: Vector2) -> Dictionary:
	var position := _normalized_world_position(normalized)
	return {"name": name, "parent": BONE_RIG, "x": position.x, "y": position.y}


func _normalized_world_position(normalized: Vector2) -> Vector2:
	return Vector2(
		HERO_WORLD_RECT.position.x + HERO_WORLD_RECT.size.x * normalized.x,
		HERO_WORLD_RECT.position.y + HERO_WORLD_RECT.size.y * (1.0 - normalized.y)
	)


func _build_weighted_mesh(bone_indices: Dictionary, bone_positions: Dictionary) -> Dictionary:
	var ordered_points := _ordered_grid_points()
	var uvs := []
	var vertices := []
	for point: Vector2i in ordered_points:
		var normalized := Vector2(
			float(point.x) / float(GRID_COLUMNS - 1),
			float(point.y) / float(GRID_ROWS - 1)
		)
		var world := _normalized_world_position(normalized)
		uvs.append_array([normalized.x, normalized.y])
		var influences := _weights_for(normalized)
		vertices.append(influences.size())
		for influence: Dictionary in influences:
			var bone_name := str(influence["bone"])
			var local := world - Vector2(bone_positions[bone_name])
			vertices.append_array([
				int(bone_indices[bone_name]),
				local.x,
				local.y,
				float(influence["weight"]),
			])
	return {
		"type": "mesh",
		"path": ATLAS_REGION_NAME,
		"uvs": uvs,
		"triangles": _build_triangles(ordered_points),
		"vertices": vertices,
		"hull": _hull_vertex_count(),
		"width": HERO_WORLD_RECT.size.x,
		"height": HERO_WORLD_RECT.size.y,
	}


func _ordered_grid_points() -> Array:
	var result := []
	for x in GRID_COLUMNS:
		result.append(Vector2i(x, 0))
	for y in range(1, GRID_ROWS):
		result.append(Vector2i(GRID_COLUMNS - 1, y))
	for x in range(GRID_COLUMNS - 2, -1, -1):
		result.append(Vector2i(x, GRID_ROWS - 1))
	for y in range(GRID_ROWS - 2, 0, -1):
		result.append(Vector2i(0, y))
	for y in range(1, GRID_ROWS - 1):
		for x in range(1, GRID_COLUMNS - 1):
			result.append(Vector2i(x, y))
	assert(result.size() == GRID_COLUMNS * GRID_ROWS)
	return result


func _hull_vertex_count() -> int:
	return GRID_COLUMNS * 2 + GRID_ROWS * 2 - 4


func _build_triangles(points: Array) -> Array:
	var indices := {}
	for index in points.size():
		var point: Vector2i = points[index]
		indices["%d,%d" % [point.x, point.y]] = index
	var triangles := []
	for y in range(GRID_ROWS - 1):
		for x in range(GRID_COLUMNS - 1):
			var top_left: int = indices["%d,%d" % [x, y]]
			var top_right: int = indices["%d,%d" % [x + 1, y]]
			var bottom_left: int = indices["%d,%d" % [x, y + 1]]
			var bottom_right: int = indices["%d,%d" % [x + 1, y + 1]]
			triangles.append_array([top_left, bottom_left, top_right, top_right, bottom_left, bottom_right])
	return triangles


func _weights_for(normalized: Vector2) -> Array:
	var x := normalized.x
	var y := normalized.y
	if y < 0.10 and x > 0.57:
		return _weights(BONE_BUTTERFLY, 0.72, BONE_HAIR_RIGHT, 0.28)
	if y < 0.23:
		if x < 0.42:
			return _weights(BONE_HAIR_LEFT, 0.58, BONE_HEAD, 0.42)
		if x > 0.58:
			return _weights(BONE_HAIR_RIGHT, 0.58, BONE_HEAD, 0.42)
		return _weights(BONE_HEAD, 0.62, BONE_HAIR_CENTER, 0.38)
	if y < 0.42 and x < 0.34:
		return _weights(BONE_ARM_LEFT, 0.70, BONE_SHOULDER_LEFT, 0.30)
	if y < 0.42 and x > 0.66:
		return _weights(BONE_ARM_RIGHT, 0.70, BONE_SHOULDER_RIGHT, 0.30)
	if y < 0.58 and x < 0.43:
		return _weights(BONE_HAND_LEFT, 0.64, BONE_TORSO_LOWER, 0.36)
	if y < 0.58 and x > 0.57:
		return _weights(BONE_HAND_RIGHT, 0.64, BONE_TORSO_LOWER, 0.36)
	if y < 0.43:
		return _weights(BONE_TORSO_UPPER, 0.72, BONE_TORSO_LOWER, 0.28)
	if y < 0.66:
		if x < 0.42:
			return _weights(BONE_SKIRT_LEFT, 0.68, BONE_SKIRT_CENTER, 0.32)
		if x > 0.58:
			return _weights(BONE_SKIRT_RIGHT, 0.68, BONE_SKIRT_CENTER, 0.32)
		return _weights(BONE_SKIRT_CENTER, 0.65, BONE_PELVIS, 0.35)
	if x < 0.50:
		if y < 0.80:
			return _weights(BONE_THIGH_LEFT, 0.68, BONE_SKIRT_LEFT, 0.32)
		return _weights(BONE_SHIN_LEFT, 0.72, BONE_THIGH_LEFT, 0.28)
	if y < 0.80:
		return _weights(BONE_THIGH_RIGHT, 0.68, BONE_SKIRT_RIGHT, 0.32)
	return _weights(BONE_SHIN_RIGHT, 0.72, BONE_THIGH_RIGHT, 0.28)


func _weights(bone_a: String, weight_a: float, bone_b: String, weight_b: float) -> Array:
	return [
		{"bone": bone_a, "weight": weight_a},
		{"bone": bone_b, "weight": weight_b},
	]


func _build_animations() -> Dictionary:
	return {
		"overgrowth_loop": _build_loop(5.0, 1.00, 0.70, 0.80),
		"hive_loop": _build_loop(3.6, 1.20, 0.90, 1.05),
		"glory_loop": _build_loop(4.4, 0.82, 0.58, 0.62),
		"_tracks/light_off": _build_light_track(0.5, "b8bed2ff"),
		"_tracks/light_on": _build_light_track(0.5, "ffffffff"),
	}


func _build_loop(duration: float, breathing: float, hair: float, skirt: float) -> Dictionary:
	var quarter := duration * 0.25
	var half := duration * 0.50
	var three_quarters := duration * 0.75
	return {
		"bones": {
			BONE_RIG: {"translate": [
				{"time": 0.0, "x": 0.0, "y": 0.0},
				{"time": quarter, "x": -0.8, "y": 1.5 * breathing},
				{"time": half, "x": 0.0, "y": 0.0},
				{"time": three_quarters, "x": 0.8, "y": -0.8 * breathing},
				{"time": duration, "x": 0.0, "y": 0.0},
			]},
			BONE_TORSO_LOWER: {"rotate": _rotation_loop(duration, 0.0, 0.22 * breathing, 0.0, -0.18 * breathing)},
			BONE_TORSO_UPPER: {"rotate": _rotation_loop(duration, 0.0, -0.34 * breathing, 0.0, 0.26 * breathing)},
			BONE_HEAD: {"rotate": _rotation_loop(duration, 0.0, 0.28, 0.0, -0.22)},
			BONE_HAIR_CENTER: {"rotate": _rotation_loop(duration, 0.0, 0.42 * hair, 0.0, -0.36 * hair)},
			BONE_HAIR_LEFT: {"rotate": _rotation_loop(duration, 0.0, 0.80 * hair, 0.0, -0.66 * hair)},
			BONE_HAIR_RIGHT: {"rotate": _rotation_loop(duration, 0.0, -0.74 * hair, 0.0, 0.62 * hair)},
			BONE_BUTTERFLY: {"rotate": _rotation_loop(duration, 0.0, -0.95 * hair, 0.0, 0.72 * hair)},
			BONE_ARM_LEFT: {"rotate": _rotation_loop(duration, 0.0, -0.25, 0.0, 0.18)},
			BONE_HAND_LEFT: {"rotate": _rotation_loop(duration, 0.0, 0.42, 0.0, -0.30)},
			BONE_ARM_RIGHT: {"rotate": _rotation_loop(duration, 0.0, 0.25, 0.0, -0.18)},
			BONE_HAND_RIGHT: {"rotate": _rotation_loop(duration, 0.0, -0.42, 0.0, 0.30)},
			BONE_SKIRT_CENTER: {"rotate": _rotation_loop(duration, 0.0, 0.22 * skirt, 0.0, -0.18 * skirt)},
			BONE_SKIRT_LEFT: {"rotate": _rotation_loop(duration, 0.0, 0.48 * skirt, 0.0, -0.38 * skirt)},
			BONE_SKIRT_RIGHT: {"rotate": _rotation_loop(duration, 0.0, -0.48 * skirt, 0.0, 0.38 * skirt)},
		},
	}


func _rotation_loop(duration: float, start: float, quarter: float, half: float, three_quarters: float) -> Array:
	return [
		{"time": 0.0, "value": start},
		{"time": duration * 0.25, "value": quarter},
		{"time": duration * 0.50, "value": half},
		{"time": duration * 0.75, "value": three_quarters},
		{"time": duration, "value": start},
	]


func _build_light_track(duration: float, color: String) -> Dictionary:
	# Both keys deliberately carry the same value. NRestSiteCharacter can layer
	# this named track over a chapter loop without a one-frame setup-color flash.
	return {
		"slots": {
			"vivhite_rest_hero": {
				"rgba": [
					{"time": 0.0, "color": color},
					{"time": duration, "color": color},
				],
			},
		},
	}


func _build_atlas_data() -> String:
	return "\n".join(PackedStringArray([
		OUTPUT_PAGE,
		"size:%d,%d" % [ATLAS_PAGE_SIZE.x, ATLAS_PAGE_SIZE.y],
		"filter:Linear,Linear",
		"pma:false",
		"repeat:none",
		"scale:0.5",
		ATLAS_REGION_NAME,
		"bounds:%d,%d,%d,%d" % [
			ATLAS_REGION_POSITION.x,
			ATLAS_REGION_POSITION.y,
			ATLAS_REGION_SIZE.x,
			ATLAS_REGION_SIZE.y,
		],
	])) + "\n"


func _build_skeleton_data_tres() -> String:
	return """[gd_resource type="SpineSkeletonDataResource" load_steps=3 format=3]

[ext_resource type="SpineAtlasResource" path="res://Vivhite/skins/ironclad/spine/rest_site/restsite_ironclad.spatlas" id="1_atlas"]
[ext_resource type="SpineSkeletonFileResource" path="res://Vivhite/skins/ironclad/spine/rest_site/vivhite_rest_site.spjson" id="2_skeleton"]

[resource]
atlas_res = ExtResource("1_atlas")
skeleton_file_res = ExtResource("2_skeleton")
default_mix = 0.2
"""


func _validate_rig(skeleton: Dictionary, atlas_data: String) -> bool:
	if str(skeleton["skeleton"].get("spine", "")) != SPINE_VERSION:
		return _set_error("Generated rest-site skeleton is not Spine %s" % SPINE_VERSION)
	var bones: Array = skeleton["bones"]
	if bones.size() < 20:
		return _set_error("Rest-site rig must contain at least 20 private bones")
	var bone_names := {}
	for index in bones.size():
		bone_names[str(bones[index]["name"])] = index
	for required_bone: String in REQUIRED_WEIGHT_BONES:
		if not bone_names.has(required_bone):
			return _set_error("Rest-site rig is missing weighted bone: %s" % required_bone)
	if skeleton["skins"].size() != 1 or str(skeleton["skins"][0].get("name", "")) != "default":
		return _set_error("Rest-site rig must contain exactly one default skin")
	if atlas_data.count("%s\n" % ATLAS_REGION_NAME) != 1:
		return _set_error("Private rest-site atlas must contain exactly one Vivhite region")
	if atlas_data.contains("arm top") or atlas_data.contains("cast chadow"):
		return _set_error("Private rest-site atlas contains a vanilla Ironclad region")

	var animations: Dictionary = skeleton["animations"]
	var actual_names: Array = animations.keys()
	actual_names.sort()
	var expected_names: Array = ANIMATION_DURATIONS.keys()
	expected_names.sort()
	if actual_names != expected_names:
		return _set_error("Rest-site animations must be exactly %s; got %s" % [expected_names, actual_names])
	for animation_name: String in ANIMATION_DURATIONS:
		var duration := _max_timeline_time(animations[animation_name])
		var expected_duration := float(ANIMATION_DURATIONS[animation_name])
		if absf(duration - expected_duration) > 0.00001:
			return _set_error("Animation %s must last %.3fs; got %.7fs" % [animation_name, expected_duration, duration])
		if animation_name.ends_with("_loop") and not _validate_closed_loop(animations[animation_name]):
			return false
		if animation_name.begins_with("_tracks/") and not _validate_constant_light_track(animations[animation_name]):
			return false

	var attachment: Dictionary = skeleton["skins"][0]["attachments"]["vivhite_rest_hero"][ATLAS_REGION_NAME]
	if str(attachment.get("type", "")) != "mesh":
		return _set_error("Rest-site Vivhite attachment must be a weighted mesh")
	var vertex_count := GRID_COLUMNS * GRID_ROWS
	if attachment["uvs"].size() != vertex_count * 2:
		return _set_error("Rest-site weighted mesh UV count changed unexpectedly")
	if attachment["triangles"].size() != (GRID_COLUMNS - 1) * (GRID_ROWS - 1) * 6:
		return _set_error("Rest-site weighted mesh triangle count changed unexpectedly")
	if int(attachment["hull"]) != _hull_vertex_count():
		return _set_error("Rest-site weighted mesh hull changed unexpectedly")
	return _validate_weighted_vertices(attachment["vertices"], vertex_count, bones.size(), bone_names)


func _validate_closed_loop(animation: Dictionary) -> bool:
	var bone_timelines: Dictionary = animation.get("bones", {})
	for bone_name: String in bone_timelines:
		var timelines: Dictionary = bone_timelines[bone_name]
		for timeline_name: String in timelines:
			var keys: Array = timelines[timeline_name]
			if keys.size() < 2 or keys[0] != keys[keys.size() - 1]:
				# Time intentionally differs; compare animated values only.
				var first: Dictionary = keys[0].duplicate()
				var last: Dictionary = keys[keys.size() - 1].duplicate()
				first.erase("time")
				last.erase("time")
				if first != last:
					return _set_error("Loop %s/%s does not return to its first value" % [bone_name, timeline_name])
	return true


func _validate_constant_light_track(animation: Dictionary) -> bool:
	var slots: Dictionary = animation.get("slots", {})
	if slots.keys() != ["vivhite_rest_hero"]:
		return _set_error("Rest-site light track may only tint the Vivhite hero slot")
	var keys: Array = slots["vivhite_rest_hero"].get("rgba", [])
	if keys.size() != 2:
		return _set_error("Rest-site light track must contain two constant endpoint keys")
	if str(keys[0].get("color", "")) != str(keys[1].get("color", "")):
		return _set_error("Rest-site light track endpoints must be identical")
	return true


func _validate_weighted_vertices(stream: Array, expected_vertices: int, bone_count: int, bone_names: Dictionary) -> bool:
	var cursor := 0
	var decoded_vertices := 0
	var influence_counts := {}
	while cursor < stream.size():
		var influence_count := int(stream[cursor])
		cursor += 1
		if influence_count < 2:
			return _set_error("Every rest-site mesh vertex must be truly weighted")
		var weight_sum := 0.0
		for _influence in influence_count:
			if cursor + 3 >= stream.size():
				return _set_error("Rest-site weighted vertex stream ended mid-influence")
			var bone_index := int(stream[cursor])
			if bone_index < 0 or bone_index >= bone_count:
				return _set_error("Rest-site mesh references invalid bone index %d" % bone_index)
			weight_sum += float(stream[cursor + 3])
			influence_counts[bone_index] = int(influence_counts.get(bone_index, 0)) + 1
			cursor += 4
		if absf(weight_sum - 1.0) > 0.00001:
			return _set_error("Rest-site vertex weight sum is %.8f instead of 1" % weight_sum)
		decoded_vertices += 1
	if cursor != stream.size() or decoded_vertices != expected_vertices:
		return _set_error("Expected %d weighted vertices, decoded %d" % [expected_vertices, decoded_vertices])
	for bone_name: String in REQUIRED_WEIGHT_BONES:
		var bone_index := int(bone_names[bone_name])
		if int(influence_counts.get(bone_index, 0)) == 0:
			return _set_error("No mesh vertex is influenced by required rest-site bone: %s" % bone_name)
	return true


func _max_timeline_time(value: Variant) -> float:
	var result := 0.0
	if value is Dictionary:
		for child in value.values():
			result = maxf(result, _max_timeline_time(child))
	elif value is Array:
		for child in value:
			if child is Dictionary and child.has("time"):
				result = maxf(result, float(child["time"]))
			result = maxf(result, _max_timeline_time(child))
	return result


func _validate_written_outputs(output_root: String) -> bool:
	var page := Image.load_from_file(output_root.path_join(OUTPUT_PAGE))
	if page == null or page.is_empty():
		return _set_error("Written rest-site atlas page cannot be decoded")
	if page.get_size() != ATLAS_PAGE_SIZE or page.get_format() != Image.FORMAT_RGBA8:
		return _set_error("Written rest-site atlas page is not 2048x2048 RGBA8")
	var bytes := page.get_data()
	for pixel_index in PackedInt32Array([0, ATLAS_PAGE_SIZE.x - 1, (ATLAS_PAGE_SIZE.y - 1) * ATLAS_PAGE_SIZE.x, ATLAS_PAGE_SIZE.x * ATLAS_PAGE_SIZE.y - 1]):
		if bytes[pixel_index * 4 + 3] != 0:
			return _set_error("Written rest-site atlas page does not retain transparent corners")
	var decoded = JSON.parse_string(FileAccess.get_file_as_string(output_root.path_join(OUTPUT_JSON)))
	if not decoded is Dictionary:
		return _set_error("Written rest-site Spine JSON could not be parsed")
	var atlas_wrapper = JSON.parse_string(FileAccess.get_file_as_string(output_root.path_join(OUTPUT_ATLAS)))
	if not atlas_wrapper is Dictionary:
		return _set_error("Written rest-site atlas wrapper could not be parsed")
	if not _validate_rig(decoded, str(atlas_wrapper.get("atlas_data", ""))):
		return false
	var tres := FileAccess.get_file_as_string(output_root.path_join(OUTPUT_DATA))
	for required_text: String in [
		"res://Vivhite/skins/ironclad/spine/rest_site/restsite_ironclad.spatlas",
		"res://Vivhite/skins/ironclad/spine/rest_site/vivhite_rest_site.spjson",
	]:
		if not tres.contains(required_text):
			return _set_error("Written rest-site wrapper is missing %s" % required_text)
	return true


func _transparent_image(size: Vector2i) -> Image:
	var image := Image.create(size.x, size.y, false, Image.FORMAT_RGBA8)
	image.fill(Color(0, 0, 0, 0))
	return image


func _make_dir(path: String) -> bool:
	var error := DirAccess.make_dir_recursive_absolute(path)
	if error != OK:
		return _set_error("Could not create directory (%s): %s" % [error_string(error), path])
	return true


func _write_text(path: String, content: String) -> bool:
	if not _make_dir(path.get_base_dir()):
		return false
	var file := FileAccess.open(path, FileAccess.WRITE)
	if file == null:
		return _set_error("Could not write file: %s" % path)
	file.store_string(content)
	file.close()
	return true


func _error_dictionary(message: String) -> Dictionary:
	_set_error(message)
	return {}


func _set_error(message: String) -> bool:
	_last_error = message
	return false


func _fail(message: String) -> int:
	printerr("Vivhite rest-site rig build failed: %s" % message)
	return 1
