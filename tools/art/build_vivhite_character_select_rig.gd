extends SceneTree

## Builds the private Spine 4.2 character-select rig for Vivhite.
##
## The input is a paid, model-produced RGBA master and is always read-only.
## This tool may crop transparent padding, uniformly resize the complete RGBA
## image, and place it on a transparent atlas page. Normal resizing resamples
## every RGBA channel together; the tool never creates, extracts, thresholds,
## masks, shrinks, or repairs Alpha independently.

const COMMAND := "build-character-select"
const SPINE_VERSION := "4.2.43"
const ANIMATION_NAME := "animation"
const ANIMATION_DURATION := 5.3333335

const DEFAULT_SOURCE := (
	"assets/vivhite-ironclad/custom/character_select/sources/"
	+ "vivhite-character-select-hero-master-v1.png"
)
const DEFAULT_MAGIC_SOURCE := (
	"assets/vivhite-ironclad/custom/character_select/sources/"
	+ "vivhite-character-select-magic-sigil-v1.png"
)
const DEFAULT_OUTPUT_ROOT := "Vivhite/Vivhite/skins/ironclad/spine/character_select"

const OUTPUT_JSON := "vivhite_character_select.spjson"
const OUTPUT_ATLAS := "characterselect_ironclad.spatlas"
const OUTPUT_PAGE := "characterselect_ironclad.png"
const OUTPUT_DATA := "character_select_skeleton_data.tres"

# Keep the decoded page contract identical to the original scene resource. The
# private atlas has its own region name and layout; no vanilla atlas region is
# copied or referenced.
const ATLAS_PAGE_SIZE := Vector2i(3713, 2427)
const ATLAS_REGION_POSITION := Vector2i(12, 12)
const ATLAS_REGION_SIZE := Vector2i(2286, 2400)
const ATLAS_REGION_NAME := "vivhite_character_select_hero"
const MAGIC_ATLAS_REGION_POSITION := Vector2i(2310, 12)
const MAGIC_ATLAS_REGION_SIZE := Vector2i(1380, 1380)
const MAGIC_ATLAS_REGION_NAME := "vivhite_character_select_magic_sigil"
const SOURCE_CONTENT_MARGIN := 8
const REGION_CONTENT_MARGIN := 20

# The unchanged character-select scene places its SpineSprite at (-185, -20)
# with scale 0.46. These setup coordinates retain the researched right-side,
# near-full-height composition on the 2560x1200 character-select canvas.
const SKELETON_BOUNDS := Rect2(-1.0, -2401.0, 5122.0, 2402.0)
# Five percent smaller than the original attachment union and vertically
# bottom-aligned. With the unchanged scene transform this leaves about 30px of
# top safety for the butterfly/hair instead of clipping them at y=0.
const HERO_WORLD_RECT := Rect2(2213.0, -2401.0, 2172.0, 2280.0)
const MAGIC_WORLD_CENTER := Vector2(3326.0, -1159.0)
const MAGIC_WORLD_SIZE := Vector2(2300.0, 2300.0)

# Boundary vertices are emitted first (clockwise in texture space), followed by
# interior vertices. This satisfies Spine's hull contract while retaining a
# dense, truly weighted deformation mesh rather than a four-vertex quad.
const GRID_COLUMNS := 9
const GRID_ROWS := 13

const BONE_ROOT := "root"
const BONE_MAGIC := "vivhite_magic_backdrop"
const BONE_RIG := "vivhite_rig"
const BONE_TORSO := "vivhite_torso"
const BONE_HEAD := "vivhite_head"
const BONE_HAIR_LEFT := "vivhite_hair_left"
const BONE_HAIR_RIGHT := "vivhite_hair_right"
const BONE_BUTTERFLY := "vivhite_butterfly"
const BONE_CAST_ARM := "vivhite_cast_arm"
const BONE_FAR_ARM := "vivhite_far_arm"
const BONE_SKIRT := "vivhite_skirt"
const BONE_LEFT_LEG := "vivhite_left_leg"
const BONE_RIGHT_LEG := "vivhite_right_leg"

const REQUIRED_WEIGHT_BONES := [
	BONE_TORSO,
	BONE_HEAD,
	BONE_HAIR_LEFT,
	BONE_HAIR_RIGHT,
	BONE_CAST_ARM,
	BONE_FAR_ARM,
	BONE_SKIRT,
	BONE_LEFT_LEG,
	BONE_RIGHT_LEG,
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
	var magic_source_path := _absolute_path(
		str(options.get("magic-source", DEFAULT_MAGIC_SOURCE))
	)
	var output_root := _absolute_path(str(options.get("output-root", DEFAULT_OUTPUT_ROOT)))
	if not _build(source_path, magic_source_path, output_root):
		quit(_fail(_last_error))
		return
	quit(0)


func _print_help() -> void:
	print("Usage:")
	print(
		"  godot --headless --path tools/art --script "
		+ "res://build_vivhite_character_select_rig.gd -- build-character-select"
	)
	print("    [--source PATH] [--magic-source PATH] [--output-root PATH]")


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


func _build(source_path: String, magic_source_path: String, output_root: String) -> bool:
	_last_error = ""
	if not FileAccess.file_exists(source_path):
		return _set_error("Character-select hero master does not exist: %s" % source_path)
	if not FileAccess.file_exists(magic_source_path):
		return _set_error(
			"Character-select magic-sigil master does not exist: %s" % magic_source_path
		)

	var source := Image.load_from_file(source_path)
	if source == null or source.is_empty():
		return _set_error("Could not decode character-select hero master: %s" % source_path)
	if source.get_format() != Image.FORMAT_RGBA8:
		return _set_error(
			"Character-select hero master must decode directly as RGBA8; got format %s: %s"
			% [source.get_format(), source_path]
		)
	if not _validate_source_alpha(source, source_path, "Hero"):
		return false
	var magic_source := Image.load_from_file(magic_source_path)
	if magic_source == null or magic_source.is_empty():
		return _set_error(
			"Could not decode character-select magic-sigil master: %s" % magic_source_path
		)
	if magic_source.get_format() != Image.FORMAT_RGBA8:
		return _set_error(
			"Character-select magic-sigil master must decode directly as RGBA8; got "
			+ "format %s: %s" % [magic_source.get_format(), magic_source_path]
		)
	if not _validate_source_alpha(magic_source, magic_source_path, "Magic-sigil"):
		return false

	var prepared := _prepare_region(
		source,
		ATLAS_REGION_SIZE,
		true,
		"Hero",
	)
	if prepared.is_empty():
		return false
	var prepared_magic := _prepare_region(
		magic_source,
		MAGIC_ATLAS_REGION_SIZE,
		false,
		"Magic-sigil",
	)
	if prepared_magic.is_empty():
		return false
	var region: Image = prepared["image"]
	var magic_region: Image = prepared_magic["image"]
	var atlas_page := _transparent_image(ATLAS_PAGE_SIZE)
	atlas_page.blend_rect(
		region,
		Rect2i(Vector2i.ZERO, ATLAS_REGION_SIZE),
		ATLAS_REGION_POSITION
	)
	atlas_page.blend_rect(
		magic_region,
		Rect2i(Vector2i.ZERO, MAGIC_ATLAS_REGION_SIZE),
		MAGIC_ATLAS_REGION_POSITION
	)

	var skeleton := _build_skeleton_json()
	var atlas_data := _build_atlas_data()
	if not _validate_in_memory_rig(skeleton, atlas_data):
		return false
	if not _make_dir(output_root):
		return false

	var page_path := output_root.path_join(OUTPUT_PAGE)
	var save_error := atlas_page.save_png(page_path)
	if save_error != OK:
		return _set_error(
			"Could not save character-select atlas page (%s): %s"
			% [error_string(save_error), page_path]
		)
	var skeleton_path := output_root.path_join(OUTPUT_JSON)
	if not _write_text(skeleton_path, JSON.stringify(skeleton, "  ", false) + "\n"):
		return false
	var atlas_wrapper := {
		"atlas_data": atlas_data,
		"normal_texture_prefix": "n",
		"source_path": (
			"res://Vivhite/skins/ironclad/spine/character_select/"
			+ "characterselect_ironclad.atlas"
		),
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

	print("Built independent Vivhite character-select rig:")
	print("  source:   %s (read-only)" % source_path)
	print("  magic:    %s (read-only)" % magic_source_path)
	print("  skeleton: %s" % skeleton_path)
	print("  atlas:    %s" % atlas_path)
	print("  page:     %s (%dx%d RGBA8)" % [
		page_path,
		ATLAS_PAGE_SIZE.x,
		ATLAS_PAGE_SIZE.y,
	])
	print("  data:     %s" % data_path)
	print("  source alpha bounds: %s" % prepared["source_alpha_bounds"])
	print("  packed content size: %s at %s" % [
		prepared["packed_content_size"],
		prepared["packed_content_position"],
	])
	print("  magic alpha bounds: %s" % prepared_magic["source_alpha_bounds"])
	print("  magic packed size: %s at %s" % [
		prepared_magic["packed_content_size"],
		prepared_magic["packed_content_position"],
	])
	print("  mesh: %d weighted vertices, %d triangles, hull=%d" % [
		GRID_COLUMNS * GRID_ROWS,
		(GRID_COLUMNS - 1) * (GRID_ROWS - 1) * 2,
		_hull_vertex_count(),
	])
	print("  bones: %d total; animation: %s (%.7fs)" % [
		skeleton["bones"].size(),
		ANIMATION_NAME,
		ANIMATION_DURATION,
	])
	return true


func _validate_source_alpha(image: Image, source_path: String, label: String) -> bool:
	var width := image.get_width()
	var height := image.get_height()
	var bytes := image.get_data()
	var corner_indices := PackedInt32Array([
		0,
		width - 1,
		(height - 1) * width,
		height * width - 1,
	])
	for pixel_index in corner_indices:
		if bytes[pixel_index * 4 + 3] != 0:
			return _set_error(
				"%s master corner Alpha must be exactly zero; Alpha is never repaired by this "
				+ "tool: %s" % [label, source_path]
			)
	var transparent_count := 0
	var visible_count := 0
	for index in range(3, bytes.size(), 4):
		if bytes[index] == 0:
			transparent_count += 1
		else:
			visible_count += 1
	if visible_count == 0:
		return _set_error("%s master is fully transparent: %s" % [label, source_path])
	if transparent_count < int(width * height * 0.02):
		return _set_error(
			"%s master lacks a meaningful native-transparent background: %s"
			% [label, source_path]
		)
	return true


func _prepare_region(
	source: Image,
	region_size: Vector2i,
	align_bottom: bool,
	label: String,
) -> Dictionary:
	var source_bounds := _alpha_bounds(source)
	if source_bounds.size.x <= 0 or source_bounds.size.y <= 0:
		return _error_dictionary("%s master contains no non-zero Alpha pixels" % label)
	var padded_bounds := source_bounds.grow(SOURCE_CONTENT_MARGIN)
	padded_bounds = padded_bounds.intersection(Rect2i(Vector2i.ZERO, source.get_size()))
	var cropped := source.get_region(padded_bounds)
	var available := region_size - Vector2i(
		REGION_CONTENT_MARGIN * 2,
		REGION_CONTENT_MARGIN * 2
	)
	var scale_factor := minf(
		float(available.x) / float(cropped.get_width()),
		float(available.y) / float(cropped.get_height())
	)
	# Never enlarge a paid original. Downsampling is deterministic and preserves
	# the model-provided Alpha as image content; no Alpha-specific operation is run.
	scale_factor = minf(scale_factor, 1.0)
	var packed_size := Vector2i(
		maxi(1, int(round(cropped.get_width() * scale_factor))),
		maxi(1, int(round(cropped.get_height() * scale_factor)))
	)
	if packed_size != cropped.get_size():
		cropped.resize(packed_size.x, packed_size.y, Image.INTERPOLATE_LANCZOS)

	var destination := Vector2i(
		int(round(region_size.x * 0.50 - packed_size.x * 0.50)),
		(
			region_size.y - REGION_CONTENT_MARGIN - packed_size.y
			if align_bottom
			else int(round(region_size.y * 0.50 - packed_size.y * 0.50))
		)
	)
	destination.x = clampi(
		destination.x,
		REGION_CONTENT_MARGIN,
		region_size.x - REGION_CONTENT_MARGIN - packed_size.x
	)
	destination.y = clampi(
		destination.y,
		REGION_CONTENT_MARGIN,
		region_size.y - REGION_CONTENT_MARGIN - packed_size.y
	)
	var region := _transparent_image(region_size)
	region.blend_rect(cropped, Rect2i(Vector2i.ZERO, packed_size), destination)
	var packed_bounds := _alpha_bounds(region)
	if packed_bounds.size.x <= 0 or packed_bounds.size.y <= 0:
		return _error_dictionary("Prepared character-select %s region is transparent" % label)
	if (
		packed_bounds.position.x < 1
		or packed_bounds.position.y < 1
		or packed_bounds.end.x >= region_size.x - 1
		or packed_bounds.end.y >= region_size.y - 1
	):
		return _error_dictionary(
			"Prepared character-select %s art touches the atlas region edge: %s"
			% [label, packed_bounds]
		)
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
		var bone_name := str(bone["name"])
		bone_indices[bone_name] = index
		bone_positions[bone_name] = Vector2(
			float(bone.get("x", 0.0)),
			float(bone.get("y", 0.0))
		)

	var mesh := _build_weighted_mesh(bone_indices, bone_positions)
	var magic_attachment := _build_magic_attachment()
	return {
		"skeleton": {
			"hash": "vivhite-private-character-select-rig-v2",
			"spine": SPINE_VERSION,
			"x": SKELETON_BOUNDS.position.x,
			"y": SKELETON_BOUNDS.position.y,
			"width": SKELETON_BOUNDS.size.x,
			"height": SKELETON_BOUNDS.size.y,
			"images": "./",
		},
		"bones": bones,
		"slots": [
			{
				"name": "vivhite_magic_backdrop",
				"bone": BONE_MAGIC,
				"attachment": MAGIC_ATLAS_REGION_NAME,
			},
			{
				"name": "vivhite_hero",
				"bone": BONE_RIG,
				"attachment": ATLAS_REGION_NAME,
			},
		],
		"skins": [{
			"name": "default",
			"attachments": {
				"vivhite_magic_backdrop": {
					MAGIC_ATLAS_REGION_NAME: magic_attachment,
				},
				"vivhite_hero": {
					ATLAS_REGION_NAME: mesh,
				},
			},
		}],
		"animations": {
			ANIMATION_NAME: _build_animation(),
		},
	}


func _build_bones() -> Array:
	return [
		{"name": BONE_ROOT},
		{
			"name": BONE_MAGIC,
			"parent": BONE_ROOT,
			"x": MAGIC_WORLD_CENTER.x,
			"y": MAGIC_WORLD_CENTER.y,
		},
		{"name": BONE_RIG, "parent": BONE_ROOT},
		_bone_at(BONE_TORSO, Vector2(0.52, 0.36)),
		_bone_at(BONE_HEAD, Vector2(0.49, 0.14)),
		_bone_at(BONE_HAIR_LEFT, Vector2(0.41, 0.12)),
		_bone_at(BONE_HAIR_RIGHT, Vector2(0.58, 0.12)),
		_bone_at(BONE_BUTTERFLY, Vector2(0.62, 0.08)),
		_bone_at(BONE_CAST_ARM, Vector2(0.27, 0.27)),
		_bone_at(BONE_FAR_ARM, Vector2(0.70, 0.36)),
		_bone_at(BONE_SKIRT, Vector2(0.52, 0.51)),
		_bone_at(BONE_LEFT_LEG, Vector2(0.46, 0.75)),
		_bone_at(BONE_RIGHT_LEG, Vector2(0.57, 0.75)),
	]


func _build_magic_attachment() -> Dictionary:
	# A rigid region attachment is intentional here: the sigil rotates as one
	# coherent magical motif while only Vivhite herself uses a deforming mesh.
	return {
		"path": MAGIC_ATLAS_REGION_NAME,
		"width": MAGIC_WORLD_SIZE.x,
		"height": MAGIC_WORLD_SIZE.y,
	}


func _bone_at(name: String, normalized_position: Vector2) -> Dictionary:
	var world := _normalized_world_position(normalized_position)
	return {
		"name": name,
		"parent": BONE_RIG,
		"x": world.x,
		"y": world.y,
	}


func _normalized_world_position(normalized: Vector2) -> Vector2:
	return Vector2(
		HERO_WORLD_RECT.position.x + HERO_WORLD_RECT.size.x * normalized.x,
		HERO_WORLD_RECT.position.y + HERO_WORLD_RECT.size.y * (1.0 - normalized.y)
	)


func _build_weighted_mesh(bone_indices: Dictionary, bone_positions: Dictionary) -> Dictionary:
	var ordered_grid_points := _ordered_grid_points()
	var uvs := []
	var weighted_vertices := []
	for grid_point: Vector2i in ordered_grid_points:
		var normalized := Vector2(
			float(grid_point.x) / float(GRID_COLUMNS - 1),
			float(grid_point.y) / float(GRID_ROWS - 1)
		)
		var world := _normalized_world_position(normalized)
		uvs.append(normalized.x)
		uvs.append(normalized.y)
		var influences := _weights_for(normalized)
		weighted_vertices.append(influences.size())
		for influence: Dictionary in influences:
			var bone_name := str(influence["bone"])
			var bone_position: Vector2 = bone_positions[bone_name]
			var local := world - bone_position
			weighted_vertices.append(int(bone_indices[bone_name]))
			weighted_vertices.append(local.x)
			weighted_vertices.append(local.y)
			weighted_vertices.append(float(influence["weight"]))

	return {
		"type": "mesh",
		"path": ATLAS_REGION_NAME,
		"uvs": uvs,
		"triangles": _build_triangles(ordered_grid_points),
		"vertices": weighted_vertices,
		"hull": _hull_vertex_count(),
		"width": HERO_WORLD_RECT.size.x,
		"height": HERO_WORLD_RECT.size.y,
	}


func _ordered_grid_points() -> Array:
	var result := []
	# Hull, clockwise in image coordinates.
	for x in GRID_COLUMNS:
		result.append(Vector2i(x, 0))
	for y in range(1, GRID_ROWS):
		result.append(Vector2i(GRID_COLUMNS - 1, y))
	for x in range(GRID_COLUMNS - 2, -1, -1):
		result.append(Vector2i(x, GRID_ROWS - 1))
	for y in range(GRID_ROWS - 2, 0, -1):
		result.append(Vector2i(0, y))
	# Interior, row-major for deterministic JSON output.
	for y in range(1, GRID_ROWS - 1):
		for x in range(1, GRID_COLUMNS - 1):
			result.append(Vector2i(x, y))
	assert(result.size() == GRID_COLUMNS * GRID_ROWS)
	return result


func _hull_vertex_count() -> int:
	return GRID_COLUMNS * 2 + GRID_ROWS * 2 - 4


func _build_triangles(ordered_grid_points: Array) -> Array:
	var point_indices := {}
	for index in ordered_grid_points.size():
		var point: Vector2i = ordered_grid_points[index]
		point_indices["%d,%d" % [point.x, point.y]] = index
	var triangles := []
	for y in range(GRID_ROWS - 1):
		for x in range(GRID_COLUMNS - 1):
			var top_left: int = point_indices["%d,%d" % [x, y]]
			var top_right: int = point_indices["%d,%d" % [x + 1, y]]
			var bottom_left: int = point_indices["%d,%d" % [x, y + 1]]
			var bottom_right: int = point_indices["%d,%d" % [x + 1, y + 1]]
			triangles.append_array([
				top_left, bottom_left, top_right,
				top_right, bottom_left, bottom_right,
			])
	return triangles


func _weights_for(normalized: Vector2) -> Array:
	var x := normalized.x
	var y := normalized.y
	if y < 0.23:
		if x < 0.49:
			return _weights(BONE_HEAD, 0.68, BONE_HAIR_LEFT, 0.32)
		if x > 0.62:
			return _weights(BONE_HEAD, 0.55, BONE_BUTTERFLY, 0.25, BONE_HAIR_RIGHT, 0.20)
		return _weights(BONE_HEAD, 0.70, BONE_HAIR_RIGHT, 0.30)
	if y < 0.45 and x < 0.42:
		return _weights(BONE_CAST_ARM, 0.78, BONE_TORSO, 0.22)
	if y < 0.49 and x > 0.62:
		return _weights(BONE_FAR_ARM, 0.78, BONE_TORSO, 0.22)
	if y < 0.46:
		return _weights(BONE_TORSO, 0.76, BONE_HEAD, 0.24)
	if y < 0.64:
		return _weights(BONE_SKIRT, 0.76, BONE_TORSO, 0.24)
	if x < 0.515:
		return _weights(BONE_LEFT_LEG, 0.84, BONE_SKIRT, 0.16)
	return _weights(BONE_RIGHT_LEG, 0.84, BONE_SKIRT, 0.16)


func _weights(
	bone_a: String,
	weight_a: float,
	bone_b: String,
	weight_b: float,
	bone_c: String = "",
	weight_c: float = 0.0
) -> Array:
	var result := [
		{"bone": bone_a, "weight": weight_a},
		{"bone": bone_b, "weight": weight_b},
	]
	if not bone_c.is_empty():
		result.append({"bone": bone_c, "weight": weight_c})
	return result


func _build_animation() -> Dictionary:
	var quarter := ANIMATION_DURATION * 0.25
	var half := ANIMATION_DURATION * 0.50
	var three_quarters := ANIMATION_DURATION * 0.75
	return {
		"bones": {
			BONE_MAGIC: {
				"rotate": _rotation_loop(-5.0, 0.0, 5.0, 0.0),
			},
			BONE_RIG: {
				"translate": [
					{"time": 0.0, "x": 0.0, "y": 0.0},
					{"time": quarter, "x": -2.0, "y": 5.0},
					{"time": half, "x": 0.0, "y": 0.0},
					{"time": three_quarters, "x": 2.0, "y": -3.0},
					{"time": ANIMATION_DURATION, "x": 0.0, "y": 0.0},
				],
			},
			BONE_TORSO: {"rotate": _rotation_loop(0.0, 0.35, 0.0, -0.25)},
			BONE_HEAD: {"rotate": _rotation_loop(0.0, -0.55, 0.0, 0.40)},
			BONE_HAIR_LEFT: {"rotate": _rotation_loop(0.0, 0.85, 0.0, -0.65)},
			BONE_HAIR_RIGHT: {"rotate": _rotation_loop(0.0, -0.75, 0.0, 0.55)},
			BONE_BUTTERFLY: {"rotate": _rotation_loop(0.0, -1.10, 0.0, 0.80)},
			BONE_CAST_ARM: {"rotate": _rotation_loop(0.0, -0.65, 0.0, 0.45)},
			BONE_FAR_ARM: {"rotate": _rotation_loop(0.0, 0.45, 0.0, -0.35)},
			BONE_SKIRT: {"rotate": _rotation_loop(0.0, 0.30, 0.0, -0.25)},
			BONE_LEFT_LEG: {"rotate": _rotation_loop(0.0, -0.12, 0.0, 0.10)},
			BONE_RIGHT_LEG: {"rotate": _rotation_loop(0.0, 0.12, 0.0, -0.10)},
		},
	}


func _rotation_loop(start: float, quarter: float, half: float, three_quarters: float) -> Array:
	return [
		{"time": 0.0, "value": start},
		{"time": ANIMATION_DURATION * 0.25, "value": quarter},
		{"time": ANIMATION_DURATION * 0.50, "value": half},
		{"time": ANIMATION_DURATION * 0.75, "value": three_quarters},
		{"time": ANIMATION_DURATION, "value": start},
	]


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
		MAGIC_ATLAS_REGION_NAME,
		"bounds:%d,%d,%d,%d" % [
			MAGIC_ATLAS_REGION_POSITION.x,
			MAGIC_ATLAS_REGION_POSITION.y,
			MAGIC_ATLAS_REGION_SIZE.x,
			MAGIC_ATLAS_REGION_SIZE.y,
		],
	])) + "\n"


func _build_skeleton_data_tres() -> String:
	return """[gd_resource type="SpineSkeletonDataResource" load_steps=3 format=3]

[ext_resource type="SpineAtlasResource" path="res://Vivhite/skins/ironclad/spine/character_select/characterselect_ironclad.spatlas" id="1_atlas"]
[ext_resource type="SpineSkeletonFileResource" path="res://Vivhite/skins/ironclad/spine/character_select/vivhite_character_select.spjson" id="2_skeleton"]

[resource]
atlas_res = ExtResource("1_atlas")
skeleton_file_res = ExtResource("2_skeleton")
default_mix = 0.05
"""


func _validate_in_memory_rig(skeleton: Dictionary, atlas_data: String) -> bool:
	if str(skeleton["skeleton"].get("spine", "")) != SPINE_VERSION:
		return _set_error("Generated skeleton version is not %s" % SPINE_VERSION)
	var animation_names: Array = skeleton["animations"].keys()
	if animation_names.size() != 1 or str(animation_names[0]) != ANIMATION_NAME:
		return _set_error(
			"Character-select rig must contain exactly ['%s']; got %s"
			% [ANIMATION_NAME, animation_names]
		)
	if skeleton["skins"].size() != 1 or skeleton["skins"][0]["name"] != "default":
		return _set_error("Character-select rig must contain exactly one default skin")
	if atlas_data.count("%s\n" % ATLAS_REGION_NAME) != 1:
		return _set_error("Private atlas must declare exactly one hero region")
	if atlas_data.count("%s\n" % MAGIC_ATLAS_REGION_NAME) != 1:
		return _set_error("Private atlas must declare exactly one magic-sigil region")

	var bones: Array = skeleton["bones"]
	var bone_names := {}
	for index in bones.size():
		bone_names[str(bones[index]["name"])] = index
	for required_bone: String in REQUIRED_WEIGHT_BONES:
		if not bone_names.has(required_bone):
			return _set_error("Generated rig is missing Vivhite bone: %s" % required_bone)
	if not bone_names.has(BONE_MAGIC):
		return _set_error("Generated rig is missing its independent magic-sigil bone")

	var slots: Array = skeleton["slots"]
	if slots.size() != 2:
		return _set_error("Character-select rig must contain exactly magic and hero slots")
	if str(slots[0].get("name", "")) != "vivhite_magic_backdrop":
		return _set_error("Magic-sigil slot must draw behind the Vivhite hero slot")
	var magic_attachment: Dictionary = (
		skeleton["skins"][0]["attachments"]["vivhite_magic_backdrop"]
		[MAGIC_ATLAS_REGION_NAME]
	)
	if magic_attachment.has("type"):
		return _set_error("Character-select magic sigil must remain a rigid region attachment")
	if (
		str(magic_attachment.get("path", "")) != MAGIC_ATLAS_REGION_NAME
		or float(magic_attachment.get("width", 0.0)) != MAGIC_WORLD_SIZE.x
		or float(magic_attachment.get("height", 0.0)) != MAGIC_WORLD_SIZE.y
	):
		return _set_error("Character-select magic-sigil region contract changed unexpectedly")

	var attachment: Dictionary = (
		skeleton["skins"][0]["attachments"]["vivhite_hero"][ATLAS_REGION_NAME]
	)
	if str(attachment.get("type", "")) != "mesh":
		return _set_error("Character-select hero attachment is not a mesh")
	var vertex_count := GRID_COLUMNS * GRID_ROWS
	if attachment["uvs"].size() != vertex_count * 2:
		return _set_error("Weighted mesh UV count changed unexpectedly")
	if attachment["triangles"].size() != (GRID_COLUMNS - 1) * (GRID_ROWS - 1) * 6:
		return _set_error("Weighted mesh triangle index count changed unexpectedly")
	if int(attachment["hull"]) != _hull_vertex_count():
		return _set_error("Weighted mesh hull count changed unexpectedly")
	if not _validate_weighted_vertices(attachment["vertices"], vertex_count, bones.size(), bone_names):
		return false

	var duration := _max_timeline_time(skeleton["animations"][ANIMATION_NAME])
	if absf(duration - ANIMATION_DURATION) > 0.00001:
		return _set_error(
			"Character-select animation duration must be %.7f, got %.7f"
			% [ANIMATION_DURATION, duration]
		)
	return true


func _validate_weighted_vertices(
	stream: Array,
	expected_vertices: int,
	bone_count: int,
	bone_names: Dictionary
) -> bool:
	var cursor := 0
	var decoded_vertices := 0
	var influence_counts := {}
	while cursor < stream.size():
		var influence_count := int(stream[cursor])
		cursor += 1
		if influence_count < 2:
			return _set_error("Every character-select mesh vertex must be truly weighted")
		var weight_sum := 0.0
		for _influence in influence_count:
			if cursor + 3 >= stream.size():
				return _set_error("Weighted vertex stream ended mid-influence")
			var bone_index := int(stream[cursor])
			if bone_index < 0 or bone_index >= bone_count:
				return _set_error("Weighted vertex references invalid bone index %d" % bone_index)
			weight_sum += float(stream[cursor + 3])
			influence_counts[bone_index] = int(influence_counts.get(bone_index, 0)) + 1
			cursor += 4
		if absf(weight_sum - 1.0) > 0.00001:
			return _set_error("Weighted vertex influence sum is %.8f instead of 1" % weight_sum)
		decoded_vertices += 1
	if cursor != stream.size() or decoded_vertices != expected_vertices:
		return _set_error(
			"Expected %d weighted vertices, decoded %d" % [expected_vertices, decoded_vertices]
		)
	for required_bone: String in REQUIRED_WEIGHT_BONES:
		var required_index := int(bone_names[required_bone])
		if int(influence_counts.get(required_index, 0)) == 0:
			return _set_error("No mesh vertex is influenced by required bone: %s" % required_bone)
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
		return _set_error("Written character-select atlas page cannot be decoded")
	if page.get_size() != ATLAS_PAGE_SIZE or page.get_format() != Image.FORMAT_RGBA8:
		return _set_error("Written character-select atlas page is not 3713x2427 RGBA8")
	var page_bytes := page.get_data()
	var page_corner_pixels := PackedInt32Array([
		0,
		ATLAS_PAGE_SIZE.x - 1,
		(ATLAS_PAGE_SIZE.y - 1) * ATLAS_PAGE_SIZE.x,
		ATLAS_PAGE_SIZE.x * ATLAS_PAGE_SIZE.y - 1,
	])
	for pixel_index in page_corner_pixels:
		if page_bytes[pixel_index * 4 + 3] != 0:
			return _set_error("Written atlas page does not retain transparent corners")

	var encoded := FileAccess.get_file_as_string(output_root.path_join(OUTPUT_JSON))
	var decoded = JSON.parse_string(encoded)
	if not decoded is Dictionary:
		return _set_error("Written Spine JSON could not be parsed")
	var atlas_encoded := FileAccess.get_file_as_string(output_root.path_join(OUTPUT_ATLAS))
	var atlas_decoded = JSON.parse_string(atlas_encoded)
	if not atlas_decoded is Dictionary:
		return _set_error("Written Spine atlas wrapper could not be parsed")
	if not _validate_in_memory_rig(decoded, str(atlas_decoded.get("atlas_data", ""))):
		return false
	var tres := FileAccess.get_file_as_string(output_root.path_join(OUTPUT_DATA))
	for required_text: String in [
		"res://Vivhite/skins/ironclad/spine/character_select/characterselect_ironclad.spatlas",
		"res://Vivhite/skins/ironclad/spine/character_select/vivhite_character_select.spjson",
	]:
		if not tres.contains(required_text):
			return _set_error("Written skeleton-data wrapper is missing %s" % required_text)
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
	printerr("Vivhite character-select rig build failed: %s" % message)
	return 1
