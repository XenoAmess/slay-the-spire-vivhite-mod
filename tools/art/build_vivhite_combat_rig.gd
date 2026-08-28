extends SceneTree

## Builds Vivhite's private Spine 4.2 combat rig and the merchant wrapper that
## deliberately reuses it. The model-produced RGBA sources are read-only. This
## tool only validates, uniformly resizes and packs complete RGBA images; it
## never creates, extracts, thresholds, masks or repairs Alpha.

const COMMAND := "build-combat"
const SPINE_VERSION := "4.2.43"
const DEFAULT_BODY_SOURCE := (
	"assets/vivhite-ironclad/custom/combat/sources/"
	+ "vivhite-combat-body-master-v1.png"
)
const DEFAULT_ARC_SOURCE := (
	"assets/vivhite-ironclad/custom/combat/sources/"
	+ "vivhite-combat-magic-arc-v1.png"
)
const DEFAULT_SIGIL_SOURCE := (
	"assets/vivhite-ironclad/custom/character_select/sources/"
	+ "vivhite-character-select-magic-sigil-v1.png"
)
const DEFAULT_OUTPUT_ROOT := "Vivhite/Vivhite/skins/ironclad/spine/combat"

const OUTPUT_JSON := "vivhite_combat.spjson"
const OUTPUT_ATLAS := "vivhite_combat.spatlas"
const OUTPUT_PAGE := "vivhite_combat.png"
const OUTPUT_DATA := "vivhite_combat_skeleton_data.tres"

const ATLAS_SIZE := Vector2i(3072, 2304)
const BODY_REGION_NAME := "vivhite_combat_body"
const BODY_REGION_POS := Vector2i(16, 16)
const BODY_REGION_SIZE := Vector2i(1536, 2272)
const ARC_REGION_NAME := "vivhite_combat_magic_arc"
const ARC_REGION_POS := Vector2i(1568, 16)
const ARC_REGION_SIZE := Vector2i(1488, 1104)
const SIGIL_REGION_NAME := "vivhite_combat_magic_sigil"
const SIGIL_REGION_POS := Vector2i(1808, 1152)
const SIGIL_REGION_SIZE := Vector2i(1248, 1136)
const SOURCE_MARGIN := 8
const REGION_MARGIN := 18

# 15x23 provides 345 continuously connected vertices and 616 triangles. This
# is a real weighted Spine mesh, not a four-corner image card or a vanilla mesh.
const GRID_COLUMNS := 15
const GRID_ROWS := 23
# The private combat scene intentionally retains the vanilla 0.28 SpineSprite
# scale. Normalize only Vivhite's authored character space so the shared scene
# Bounds/UI/VFX coordinate system remains unchanged. The floor offset aligns
# her feet with the vanilla gameplay capture independently of character scale.
const CHARACTER_WORLD_SCALE := 0.70
const CHARACTER_FLOOR_OFFSET := -61.0
const BODY_WORLD_RECT := Rect2(
	-620.0 * CHARACTER_WORLD_SCALE,
	CHARACTER_FLOOR_OFFSET,
	1240.0 * CHARACTER_WORLD_SCALE,
	1860.0 * CHARACTER_WORLD_SCALE
)
# The wide right side includes the hand-origin magic arc and the horizontal
# death pose. Gameplay placement still uses the unchanged scene anchors.
const SKELETON_BOUNDS := Rect2(-900.0, -220.0, 3260.0, 2220.0)

const BONE_ROOT := "root"
const BONE_RIG := "vivhite_rig"
const BONE_SIGIL := "vivhite_magic_sigil"
const BONE_ARC := "vivhite_magic_arc"
const BONE_EYES := "vivhite_eye_anchor"

# Independent Vivhite deformation controls. All positions are normalized in
# the body master, so they do not inherit the Ironclad's proportions or pose.
const DEFORM_BONES := [
	{"name": "vivhite_hair_crown", "p": Vector2(0.50, 0.055)},
	{"name": "vivhite_hair_left", "p": Vector2(0.38, 0.12)},
	{"name": "vivhite_hair_right", "p": Vector2(0.62, 0.12)},
	{"name": "vivhite_butterfly", "p": Vector2(0.67, 0.10)},
	{"name": "vivhite_head", "p": Vector2(0.51, 0.16)},
	{"name": "vivhite_neck", "p": Vector2(0.50, 0.245)},
	{"name": "vivhite_shoulder_left", "p": Vector2(0.35, 0.28)},
	{"name": "vivhite_upper_arm_left", "p": Vector2(0.24, 0.35)},
	{"name": "vivhite_forearm_left", "p": Vector2(0.14, 0.43)},
	{"name": "vivhite_hand_left", "p": Vector2(0.06, 0.49)},
	{"name": "vivhite_shoulder_right", "p": Vector2(0.65, 0.28)},
	{"name": "vivhite_upper_arm_right", "p": Vector2(0.76, 0.31)},
	{"name": "vivhite_forearm_right", "p": Vector2(0.87, 0.27)},
	{"name": "vivhite_hand_right", "p": Vector2(0.96, 0.22)},
	{"name": "vivhite_torso_upper", "p": Vector2(0.50, 0.32)},
	{"name": "vivhite_torso_lower", "p": Vector2(0.50, 0.43)},
	{"name": "vivhite_skirt_left", "p": Vector2(0.39, 0.54)},
	{"name": "vivhite_skirt_center", "p": Vector2(0.50, 0.55)},
	{"name": "vivhite_skirt_right", "p": Vector2(0.61, 0.54)},
	{"name": "vivhite_thigh_left", "p": Vector2(0.43, 0.64)},
	{"name": "vivhite_knee_left", "p": Vector2(0.41, 0.75)},
	{"name": "vivhite_ankle_left", "p": Vector2(0.39, 0.91)},
	{"name": "vivhite_thigh_right", "p": Vector2(0.57, 0.64)},
	{"name": "vivhite_knee_right", "p": Vector2(0.62, 0.75)},
	{"name": "vivhite_ankle_right", "p": Vector2(0.69, 0.91)},
]

const ANIMATION_DURATIONS := {
	"attack": 1.1666667,
	"attack_heavy": 1.5333334,
	"cast": 1.5666667,
	"die": 2.3333335,
	"hurt": 1.0,
	"idle_loop": 2.0,
	"low_health_loop": 1.4666667,
	"relaxed_loop": 12.000001,
}
const EVENT_TIMES := {
	# The event, hand impulse, and private arc become active together. The
	# runtime shader keeps the ordinary arc fully visible for its built-in
	# 0.15 s hold and then fades it; heavy fades continuously for 0.35 s.
	"attack_slash_start": 0.08,
	"heavy_slash_start": 0.12,
	"cast_eyes_start": 0.25,
}
const REQUIRED_EVENTS := [
	"attack_slash_start", "heavy_slash_start", "cast_eyes_start", "clear_vfx",
]
const REQUIRED_SLOTS := ["slash_mesh", "eye_attach_slot"]

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
	var body_path := _absolute_path(str(options.get("body-source", DEFAULT_BODY_SOURCE)))
	var arc_path := _absolute_path(str(options.get("arc-source", DEFAULT_ARC_SOURCE)))
	var sigil_path := _absolute_path(str(options.get("sigil-source", DEFAULT_SIGIL_SOURCE)))
	var output_root := _absolute_path(str(options.get("output-root", DEFAULT_OUTPUT_ROOT)))
	if not _build(body_path, arc_path, sigil_path, output_root):
		quit(_fail(_last_error))
		return
	quit(0)


func _print_help() -> void:
	print("Usage:")
	print("  godot --headless --path tools/art --script res://build_vivhite_combat_rig.gd -- build-combat")
	print("    [--body-source PATH] [--arc-source PATH] [--sigil-source PATH]")
	print("    [--output-root PATH]")


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
	var root := ProjectSettings.globalize_path("res://").path_join("../..").simplify_path()
	return root.path_join(path).simplify_path()


func _build(body_path: String, arc_path: String, sigil_path: String, output_root: String) -> bool:
	_last_error = ""
	var inputs := [
		{"label": "combat body master", "path": body_path, "size": BODY_REGION_SIZE},
		{"label": "combat magic arc", "path": arc_path, "size": ARC_REGION_SIZE},
		{"label": "shared magic sigil", "path": sigil_path, "size": SIGIL_REGION_SIZE},
	]
	var prepared := []
	for input: Dictionary in inputs:
		var path := str(input["path"])
		if not FileAccess.file_exists(path):
			return _set_error("Required %s does not exist: %s" % [input["label"], path])
		var image := Image.load_from_file(path)
		if image == null or image.is_empty():
			return _set_error("Could not decode %s: %s" % [input["label"], path])
		if image.get_format() != Image.FORMAT_RGBA8:
			return _set_error("%s must decode directly as RGBA8: %s" % [input["label"], path])
		if not _validate_native_alpha(image, path, str(input["label"])):
			return false
		var region := _prepare_region(image, input["size"], str(input["label"]))
		if region.is_empty():
			return false
		prepared.append(region)

	var page := _transparent_image(ATLAS_SIZE)
	page.blend_rect(prepared[0]["image"], Rect2i(Vector2i.ZERO, BODY_REGION_SIZE), BODY_REGION_POS)
	page.blend_rect(prepared[1]["image"], Rect2i(Vector2i.ZERO, ARC_REGION_SIZE), ARC_REGION_POS)
	page.blend_rect(prepared[2]["image"], Rect2i(Vector2i.ZERO, SIGIL_REGION_SIZE), SIGIL_REGION_POS)
	var skeleton := _build_skeleton_json()
	var atlas_data := _build_atlas_data()
	if not _validate_rig(skeleton, atlas_data):
		return false
	if not _make_dir(output_root):
		return false
	var page_path := output_root.path_join(OUTPUT_PAGE)
	var save_error := page.save_png(page_path)
	if save_error != OK:
		return _set_error("Could not save combat atlas (%s): %s" % [error_string(save_error), page_path])
	var skeleton_path := output_root.path_join(OUTPUT_JSON)
	if not _write_text(skeleton_path, JSON.stringify(skeleton, "  ", false) + "\n"):
		return false
	var atlas_wrapper := {
		"atlas_data": atlas_data,
		"normal_texture_prefix": "n",
		"source_path": "res://Vivhite/skins/ironclad/spine/combat/vivhite_combat.atlas",
		"specular_texture_prefix": "s",
	}
	if not _write_text(output_root.path_join(OUTPUT_ATLAS), JSON.stringify(atlas_wrapper, "", false) + "\n"):
		return false
	if not _write_text(output_root.path_join(OUTPUT_DATA), _build_skeleton_data_tres()):
		return false
	if not _validate_written(output_root):
		return false
	print("Built independent Vivhite combat rig:")
	print("  body:     %s (read-only)" % body_path)
	print("  arc:      %s (read-only)" % arc_path)
	print("  sigil:    %s (read-only)" % sigil_path)
	print("  skeleton: %s" % skeleton_path)
	print("  page:     %s (%dx%d RGBA8)" % [page_path, ATLAS_SIZE.x, ATLAS_SIZE.y])
	print("  mesh:     %d weighted vertices, %d triangles, hull=%d" % [
		GRID_COLUMNS * GRID_ROWS,
		(GRID_COLUMNS - 1) * (GRID_ROWS - 1) * 2,
		_hull_vertex_count(),
	])
	print("  bones:    %d; exact animations: %s" % [skeleton["bones"].size(), ANIMATION_DURATIONS])
	return true


func _validate_native_alpha(image: Image, path: String, label: String) -> bool:
	var bytes := image.get_data()
	var width := image.get_width()
	var height := image.get_height()
	for pixel in PackedInt32Array([0, width - 1, (height - 1) * width, width * height - 1]):
		if bytes[pixel * 4 + 3] != 0:
			return _set_error("%s corner Alpha must be exactly zero; this tool never repairs Alpha: %s" % [label, path])
	var transparent := 0
	var visible := 0
	for index in range(3, bytes.size(), 4):
		if bytes[index] == 0:
			transparent += 1
		else:
			visible += 1
	if visible == 0:
		return _set_error("%s is fully transparent: %s" % [label, path])
	if transparent < int(width * height * 0.02):
		return _set_error("%s lacks a meaningful native-transparent background: %s" % [label, path])
	return true


func _prepare_region(source: Image, region_size: Vector2i, label: String) -> Dictionary:
	var bounds := _alpha_bounds(source)
	if bounds.size.x <= 0 or bounds.size.y <= 0:
		return _error_dictionary("%s contains no non-zero Alpha pixels" % label)
	var padded := bounds.grow(SOURCE_MARGIN).intersection(Rect2i(Vector2i.ZERO, source.get_size()))
	var cropped := source.get_region(padded)
	var available := region_size - Vector2i(REGION_MARGIN * 2, REGION_MARGIN * 2)
	var factor := minf(1.0, minf(
		float(available.x) / float(cropped.get_width()),
		float(available.y) / float(cropped.get_height())
	))
	var packed_size := Vector2i(
		maxi(1, int(round(cropped.get_width() * factor))),
		maxi(1, int(round(cropped.get_height() * factor)))
	)
	if cropped.get_size() != packed_size:
		cropped.resize(packed_size.x, packed_size.y, Image.INTERPOLATE_LANCZOS)
	var destination := Vector2i(
		(region_size.x - packed_size.x) / 2,
		region_size.y - REGION_MARGIN - packed_size.y
	)
	var region := _transparent_image(region_size)
	region.blend_rect(cropped, Rect2i(Vector2i.ZERO, packed_size), destination)
	var packed_bounds := _alpha_bounds(region)
	if (
		packed_bounds.position.x < 1 or packed_bounds.position.y < 1
		or packed_bounds.end.x >= region_size.x - 1
		or packed_bounds.end.y >= region_size.y - 1
	):
		return _error_dictionary("Prepared %s touches its atlas-region edge: %s" % [label, packed_bounds])
	return {"image": region, "source_bounds": bounds, "packed_size": packed_size}


func _alpha_bounds(image: Image) -> Rect2i:
	var width := image.get_width()
	var height := image.get_height()
	var bytes := image.get_data()
	var min_x := width
	var min_y := height
	var max_x := -1
	var max_y := -1
	for y in height:
		var row := y * width * 4
		for x in width:
			if bytes[row + x * 4 + 3] == 0:
				continue
			min_x = mini(min_x, x)
			min_y = mini(min_y, y)
			max_x = maxi(max_x, x)
			max_y = maxi(max_y, y)
	if max_x < min_x:
		return Rect2i()
	return Rect2i(min_x, min_y, max_x - min_x + 1, max_y - min_y + 1)


func _build_skeleton_json() -> Dictionary:
	var bones := _build_bones()
	var indices := {}
	var positions := {}
	for index in bones.size():
		var bone: Dictionary = bones[index]
		var name := str(bone["name"])
		indices[name] = index
		positions[name] = Vector2(float(bone.get("x", 0.0)), float(bone.get("y", 0.0)))
	var events := {}
	for event_name: String in REQUIRED_EVENTS:
		events[event_name] = {}
	return {
		"skeleton": {
			"hash": "vivhite-private-combat-rig-v2",
			"spine": SPINE_VERSION,
			"x": SKELETON_BOUNDS.position.x,
			"y": SKELETON_BOUNDS.position.y,
			"width": SKELETON_BOUNDS.size.x,
			"height": SKELETON_BOUNDS.size.y,
			"images": "./",
		},
		"bones": bones,
		"slots": [
			{"name": "vivhite_magic_sigil", "bone": BONE_SIGIL},
			{"name": "vivhite_body", "bone": BONE_RIG, "attachment": BODY_REGION_NAME},
			# The private magic ribbon is the required slash_mesh attachment itself.
			# SlashVfxSlot therefore consumes the same geometry at the same hand
			# anchor instead of drawing a second detached weapon-like slash.
			{"name": "slash_mesh", "bone": BONE_ARC},
			{"name": "eye_attach_slot", "bone": BONE_EYES},
		],
		"skins": [{
			"name": "default",
			"attachments": {
				"vivhite_magic_sigil": {SIGIL_REGION_NAME: _region_attachment(SIGIL_REGION_NAME, 1420.0, 1420.0)},
				"vivhite_body": {BODY_REGION_NAME: _build_weighted_mesh(indices, positions)},
				"slash_mesh": {ARC_REGION_NAME: _region_attachment(ARC_REGION_NAME, 1340.0, 900.0)},
			},
		}],
		"events": events,
		"animations": _build_animations(),
	}


func _build_bones() -> Array:
	var sigil_anchor := _scaled_character_anchor(Vector2(80.0, 960.0))
	var arc_anchor := _scaled_character_anchor(Vector2(840.0, 1750.0))
	var eye_anchor := _scaled_character_anchor(Vector2(20.0, 1555.0))
	var result := [
		{"name": BONE_ROOT},
		{"name": BONE_SIGIL, "parent": BONE_ROOT, "x": sigil_anchor.x, "y": sigil_anchor.y},
		{"name": BONE_RIG, "parent": BONE_ROOT},
	]
	for spec: Dictionary in DEFORM_BONES:
		var world := _normalized_world_position(spec["p"])
		result.append({"name": spec["name"], "parent": BONE_RIG, "x": world.x, "y": world.y})
	# The model's arc blooms at its left end. These anchors put that bloom at
	# Vivhite's outstretched right hand and send the magic to the enemy side.
	result.append({"name": BONE_ARC, "parent": BONE_ROOT, "x": arc_anchor.x, "y": arc_anchor.y, "rotation": -5.0})
	result.append({"name": BONE_EYES, "parent": BONE_ROOT, "x": eye_anchor.x, "y": eye_anchor.y})
	return result


func _scaled_character_anchor(original: Vector2) -> Vector2:
	return Vector2(
		original.x * CHARACTER_WORLD_SCALE,
		original.y * CHARACTER_WORLD_SCALE + CHARACTER_FLOOR_OFFSET
	)


func _region_attachment(path: String, width: float, height: float) -> Dictionary:
	return {"path": path, "width": width, "height": height}


func _normalized_world_position(p: Vector2) -> Vector2:
	return Vector2(
		BODY_WORLD_RECT.position.x + BODY_WORLD_RECT.size.x * p.x,
		BODY_WORLD_RECT.position.y + BODY_WORLD_RECT.size.y * (1.0 - p.y)
	)


func _build_weighted_mesh(indices: Dictionary, positions: Dictionary) -> Dictionary:
	var points := _ordered_grid_points()
	var uvs := []
	var vertices := []
	for point: Vector2i in points:
		var normalized := Vector2(
			float(point.x) / float(GRID_COLUMNS - 1),
			float(point.y) / float(GRID_ROWS - 1)
		)
		var world := _normalized_world_position(normalized)
		uvs.append_array([normalized.x, normalized.y])
		var influences := _nearest_influences(normalized)
		vertices.append(influences.size())
		for influence: Dictionary in influences:
			var name := str(influence["bone"])
			var local := world - (positions[name] as Vector2)
			vertices.append_array([
				int(indices[name]), local.x, local.y, float(influence["weight"]),
			])
	return {
		"type": "mesh",
		"path": BODY_REGION_NAME,
		"uvs": uvs,
		"triangles": _build_triangles(points),
		"vertices": vertices,
		"hull": _hull_vertex_count(),
		"width": BODY_WORLD_RECT.size.x,
		"height": BODY_WORLD_RECT.size.y,
	}


func _nearest_influences(point: Vector2) -> Array:
	var candidates := []
	for spec: Dictionary in DEFORM_BONES:
		var delta: Vector2 = point - (spec["p"] as Vector2)
		candidates.append({"bone": spec["name"], "distance": delta.length_squared()})
	candidates.sort_custom(func(a: Dictionary, b: Dictionary) -> bool: return a["distance"] < b["distance"])
	var raw := []
	var total := 0.0
	for index in 3:
		var value := 1.0 / maxf(0.0005, float(candidates[index]["distance"]))
		raw.append(value)
		total += value
	var result := []
	for index in 3:
		result.append({"bone": candidates[index]["bone"], "weight": raw[index] / total})
	return result


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
	return result


func _hull_vertex_count() -> int:
	return GRID_COLUMNS * 2 + GRID_ROWS * 2 - 4


func _build_triangles(points: Array) -> Array:
	var indices := {}
	for index in points.size():
		var point: Vector2i = points[index]
		indices["%d,%d" % [point.x, point.y]] = index
	var result := []
	for y in range(GRID_ROWS - 1):
		for x in range(GRID_COLUMNS - 1):
			var tl: int = indices["%d,%d" % [x, y]]
			var tr: int = indices["%d,%d" % [x + 1, y]]
			var bl: int = indices["%d,%d" % [x, y + 1]]
			var br: int = indices["%d,%d" % [x + 1, y + 1]]
			result.append_array([tl, bl, tr, tr, bl, br])
	return result


func _build_animations() -> Dictionary:
	return {
		"idle_loop": _loop_animation("idle_loop", 1.0, 2.0),
		"low_health_loop": _low_health_animation(),
		"relaxed_loop": _loop_animation("relaxed_loop", 0.72, 12.000001),
		"attack": _attack_animation(false),
		"attack_heavy": _attack_animation(true),
		"cast": _cast_animation(),
		"hurt": _hurt_animation(),
		"die": _die_animation(),
	}


func _loop_animation(_name: String, strength: float, duration: float) -> Dictionary:
	var q := duration * 0.25
	var h := duration * 0.5
	var tq := duration * 0.75
	var bones := {
		BONE_RIG: {"translate": _translate_loop(duration, Vector2(0, 0), Vector2(-2, 5 * strength), Vector2(0, 0), Vector2(2, -3 * strength))},
		"vivhite_torso_upper": {"rotate": _rotate_loop(duration, 0, 0.8 * strength, 0, -0.6 * strength)},
		"vivhite_head": {"rotate": _rotate_loop(duration, 0, -0.7 * strength, 0, 0.5 * strength)},
		"vivhite_hair_left": {"rotate": _rotate_loop(duration, 0, 1.6 * strength, 0, -1.2 * strength)},
		"vivhite_hair_right": {"rotate": _rotate_loop(duration, 0, -1.4 * strength, 0, 1.0 * strength)},
		"vivhite_butterfly": {"rotate": _rotate_loop(duration, 0, -2.0 * strength, 0, 1.4 * strength)},
		"vivhite_skirt_left": {"rotate": _rotate_loop(duration, 0, -0.8 * strength, 0, 0.6 * strength)},
		"vivhite_skirt_right": {"rotate": _rotate_loop(duration, 0, 0.8 * strength, 0, -0.6 * strength)},
	}
	# These explicit keys document that relaxed_loop is phase-safe at all loop
	# boundaries, including the merchant's arbitrary starting preview_time.
	assert(q > 0.0 and h > q and tq > h)
	return {"bones": bones}


func _low_health_animation() -> Dictionary:
	var duration := float(ANIMATION_DURATIONS["low_health_loop"])
	return {"bones": {
		BONE_RIG: {"translate": _translate_loop(duration, Vector2(0, -12), Vector2(-3, -18), Vector2(0, -12), Vector2(2, -16))},
		"vivhite_torso_upper": {"rotate": _rotate_loop(duration, -4, -5.2, -4, -4.8)},
		"vivhite_head": {"rotate": _rotate_loop(duration, 3, 4.2, 3, 3.6)},
		"vivhite_hair_left": {"rotate": _rotate_loop(duration, 0, 1.2, 0, -0.8)},
		"vivhite_hair_right": {"rotate": _rotate_loop(duration, 0, -1.1, 0, 0.8)},
	}}


func _attack_animation(heavy: bool) -> Dictionary:
	var name := "attack_heavy" if heavy else "attack"
	var duration := float(ANIMATION_DURATIONS[name])
	var event_time := float(EVENT_TIMES["heavy_slash_start" if heavy else "attack_slash_start"])
	var strike_time := event_time
	var recover := duration * 0.72
	var power := 1.75 if heavy else 1.0
	return {
		"slots": {
			"slash_mesh": {"attachment": [
				{"time": 0.0, "name": null},
				{"time": strike_time, "name": ARC_REGION_NAME},
				{"time": recover, "name": null},
			]},
		},
		"bones": {
			BONE_RIG: {"translate": [
				{"time": 0.0, "x": -12.0 * power, "y": 0.0},
				{"time": strike_time, "x": 30.0 * power, "y": 14.0 * power},
				{"time": recover, "x": 8.0, "y": 3.0},
				{"time": duration, "x": 0.0, "y": 0.0},
			]},
			"vivhite_torso_upper": {"rotate": _action_rotate(duration, -5 * power, 8 * power, strike_time, recover)},
			"vivhite_upper_arm_right": {"rotate": _action_rotate(duration, -9 * power, 17 * power, strike_time, recover)},
			"vivhite_forearm_right": {"rotate": _action_rotate(duration, -13 * power, 22 * power, strike_time, recover)},
			"vivhite_hand_right": {"rotate": _action_rotate(duration, -8 * power, 16 * power, strike_time, recover)},
			"vivhite_skirt_left": {"rotate": _action_rotate(duration, 2, -3 * power, strike_time, recover)},
			BONE_ARC: {"rotate": _action_rotate(duration, -22 * power, 34 * power, strike_time, recover)},
		},
		"events": [
			{"time": event_time, "name": "heavy_slash_start" if heavy else "attack_slash_start"},
			{"time": recover, "name": "clear_vfx"},
		],
	}


func _cast_animation() -> Dictionary:
	var duration := float(ANIMATION_DURATIONS["cast"])
	var start := float(EVENT_TIMES["cast_eyes_start"])
	var clear := duration * 0.78
	return {
		"slots": {"vivhite_magic_sigil": {"attachment": [
			{"time": 0.0, "name": null},
			{"time": 0.10, "name": SIGIL_REGION_NAME},
			{"time": clear, "name": null},
		]}},
		"bones": {
			BONE_RIG: {"translate": [
				{"time": 0.0, "x": 0.0, "y": 0.0},
				{"time": start, "x": 0.0, "y": 16.0},
				{"time": clear, "x": 0.0, "y": 8.0},
				{"time": duration, "x": 0.0, "y": 0.0},
			]},
			"vivhite_upper_arm_left": {"rotate": _action_rotate(duration, 0, -13, start, clear)},
			"vivhite_forearm_left": {"rotate": _action_rotate(duration, 0, -19, start, clear)},
			"vivhite_upper_arm_right": {"rotate": _action_rotate(duration, 0, 11, start, clear)},
			"vivhite_forearm_right": {"rotate": _action_rotate(duration, 0, 16, start, clear)},
			"vivhite_hair_left": {"rotate": _action_rotate(duration, 0, 3, start, clear)},
			"vivhite_hair_right": {"rotate": _action_rotate(duration, 0, -3, start, clear)},
			BONE_SIGIL: {"rotate": [
				{"time": 0.0, "value": -10.0},
				{"time": clear, "value": 18.0},
				{"time": duration, "value": -10.0},
			]},
		},
		"events": [
			{"time": start, "name": "cast_eyes_start"},
			{"time": clear, "name": "clear_vfx"},
		],
	}


func _hurt_animation() -> Dictionary:
	var duration := float(ANIMATION_DURATIONS["hurt"])
	return {"bones": {
		BONE_RIG: {"translate": [
			{"time": 0.0, "x": 0.0, "y": 0.0},
			{"time": 0.14, "x": -38.0, "y": -8.0},
			{"time": 0.52, "x": 12.0, "y": 2.0},
			{"time": duration, "x": 0.0, "y": 0.0},
		]},
		"vivhite_torso_upper": {"rotate": _action_rotate(duration, 0, -8, 0.14, 0.52)},
		"vivhite_head": {"rotate": _action_rotate(duration, 0, 6, 0.14, 0.52)},
		"vivhite_hair_left": {"rotate": _action_rotate(duration, 0, 5, 0.14, 0.52)},
		"vivhite_hair_right": {"rotate": _action_rotate(duration, 0, 6, 0.14, 0.52)},
	}, "events": [{"time": 0.72, "name": "clear_vfx"}]}


func _die_animation() -> Dictionary:
	var duration := float(ANIMATION_DURATIONS["die"])
	return {"bones": {
		BONE_RIG: {
			"translate": [
				{"time": 0.0, "x": 0.0, "y": 0.0},
				{"time": 0.45, "x": -18.0, "y": -26.0},
				{"time": 1.20, "x": 18.0, "y": -95.0},
				{"time": duration, "x": 120.0, "y": -145.0},
			],
			"rotate": _terminal_rotate(duration, -7.0, -43.0, -76.0),
		},
		"vivhite_torso_upper": {"rotate": _terminal_rotate(duration, -5, -24, -47)},
		"vivhite_head": {"rotate": _terminal_rotate(duration, 4, 17, 31)},
		"vivhite_upper_arm_left": {"rotate": _terminal_rotate(duration, 3, 18, 31)},
		"vivhite_forearm_left": {"rotate": _terminal_rotate(duration, 2, 24, 43)},
		"vivhite_upper_arm_right": {"rotate": _terminal_rotate(duration, -3, -16, -28)},
		"vivhite_forearm_right": {"rotate": _terminal_rotate(duration, -2, -22, -38)},
		"vivhite_skirt_left": {"rotate": _terminal_rotate(duration, 0, 6, 12)},
		"vivhite_skirt_right": {"rotate": _terminal_rotate(duration, 0, 7, 14)},
		"vivhite_thigh_left": {"rotate": _terminal_rotate(duration, 0, -10, -19)},
		"vivhite_thigh_right": {"rotate": _terminal_rotate(duration, 0, 9, 17)},
	}, "events": [{"time": 0.10, "name": "clear_vfx"}]}


func _rotate_loop(duration: float, start: float, quarter: float, half: float, three_quarters: float) -> Array:
	return [
		{"time": 0.0, "value": start},
		{"time": duration * 0.25, "value": quarter},
		{"time": duration * 0.50, "value": half},
		{"time": duration * 0.75, "value": three_quarters},
		{"time": duration, "value": start},
	]


func _translate_loop(duration: float, start: Vector2, quarter: Vector2, half: Vector2, three_quarters: Vector2) -> Array:
	return [
		{"time": 0.0, "x": start.x, "y": start.y},
		{"time": duration * 0.25, "x": quarter.x, "y": quarter.y},
		{"time": duration * 0.50, "x": half.x, "y": half.y},
		{"time": duration * 0.75, "x": three_quarters.x, "y": three_quarters.y},
		{"time": duration, "x": start.x, "y": start.y},
	]


func _action_rotate(duration: float, anticipation: float, strike: float, strike_time: float, recover: float) -> Array:
	return [
		{"time": 0.0, "value": 0.0},
		{"time": strike_time * 0.55, "value": anticipation},
		{"time": strike_time, "value": strike},
		{"time": recover, "value": strike * 0.22},
		{"time": duration, "value": 0.0},
	]


func _terminal_rotate(duration: float, early: float, middle: float, end: float) -> Array:
	return [
		{"time": 0.0, "value": 0.0},
		{"time": duration * 0.22, "value": early},
		{"time": duration * 0.54, "value": middle},
		{"time": duration, "value": end},
	]


func _build_atlas_data() -> String:
	return "\n".join(PackedStringArray([
		OUTPUT_PAGE,
		"size:%d,%d" % [ATLAS_SIZE.x, ATLAS_SIZE.y],
		"filter:Linear,Linear",
		"pma:false",
		"repeat:none",
		BODY_REGION_NAME,
		"bounds:%d,%d,%d,%d" % [BODY_REGION_POS.x, BODY_REGION_POS.y, BODY_REGION_SIZE.x, BODY_REGION_SIZE.y],
		ARC_REGION_NAME,
		"bounds:%d,%d,%d,%d" % [ARC_REGION_POS.x, ARC_REGION_POS.y, ARC_REGION_SIZE.x, ARC_REGION_SIZE.y],
		SIGIL_REGION_NAME,
		"bounds:%d,%d,%d,%d" % [SIGIL_REGION_POS.x, SIGIL_REGION_POS.y, SIGIL_REGION_SIZE.x, SIGIL_REGION_SIZE.y],
	])) + "\n"


func _build_skeleton_data_tres() -> String:
	return """[gd_resource type="SpineSkeletonDataResource" load_steps=13 format=3]

[ext_resource type="SpineAtlasResource" path="res://Vivhite/skins/ironclad/spine/combat/vivhite_combat.spatlas" id="1_atlas"]
[ext_resource type="SpineSkeletonFileResource" path="res://Vivhite/skins/ironclad/spine/combat/vivhite_combat.spjson" id="2_skeleton"]

[sub_resource type="SpineAnimationMix" id="Mix_idle_attack"]
from = "idle_loop"
to = "attack"
mix = 0.1

[sub_resource type="SpineAnimationMix" id="Mix_attack_attack"]
from = "attack"
to = "attack"

[sub_resource type="SpineAnimationMix" id="Mix_hurt_hurt"]
from = "hurt"
to = "hurt"

[sub_resource type="SpineAnimationMix" id="Mix_hurt_die"]
from = "hurt"
to = "die"

[sub_resource type="SpineAnimationMix" id="Mix_idle_hurt"]
from = "idle_loop"
to = "hurt"
mix = 0.03

[sub_resource type="SpineAnimationMix" id="Mix_hurt_idle"]
from = "hurt"
to = "idle_loop"
mix = 0.1

[sub_resource type="SpineAnimationMix" id="Mix_idle_heavy"]
from = "idle_loop"
to = "attack_heavy"
mix = 0.02

[sub_resource type="SpineAnimationMix" id="Mix_heavy_heavy"]
from = "attack_heavy"
to = "attack_heavy"

[sub_resource type="SpineAnimationMix" id="Mix_attack_heavy"]
from = "attack"
to = "attack_heavy"

[sub_resource type="SpineAnimationMix" id="Mix_heavy_attack"]
from = "attack_heavy"
to = "attack"

[resource]
atlas_res = ExtResource("1_atlas")
skeleton_file_res = ExtResource("2_skeleton")
default_mix = 0.05
animation_mixes = [SubResource("Mix_idle_attack"), SubResource("Mix_attack_attack"), SubResource("Mix_hurt_hurt"), SubResource("Mix_hurt_die"), SubResource("Mix_idle_hurt"), SubResource("Mix_hurt_idle"), SubResource("Mix_idle_heavy"), SubResource("Mix_heavy_heavy"), SubResource("Mix_attack_heavy"), SubResource("Mix_heavy_attack")]
"""


func _validate_rig(skeleton: Dictionary, atlas_data: String) -> bool:
	if str(skeleton["skeleton"].get("spine", "")) != SPINE_VERSION:
		return _set_error("Generated skeleton is not Spine %s" % SPINE_VERSION)
	if skeleton["bones"].size() < 20:
		return _set_error("Combat rig must contain at least 20 independent Vivhite bones")
	if skeleton["skins"].size() != 1 or skeleton["skins"][0]["name"] != "default":
		return _set_error("Combat rig must contain exactly one default skin")
	var slots := {}
	for slot: Dictionary in skeleton["slots"]:
		slots[str(slot["name"])] = true
	for required: String in REQUIRED_SLOTS:
		if not slots.has(required):
			return _set_error("Combat rig is missing required slot: %s" % required)
	if slots.has("vivhite_magic_arc"):
		return _set_error("Magic arc must share slash_mesh instead of using a detached duplicate slot")
	var default_attachments: Dictionary = skeleton["skins"][0]["attachments"]
	if (
		not default_attachments.has("slash_mesh")
		or not default_attachments["slash_mesh"].has(ARC_REGION_NAME)
	):
		return _set_error("Required slash_mesh slot does not own the private magic-ribbon attachment")
	for required: String in REQUIRED_EVENTS:
		if not skeleton["events"].has(required):
			return _set_error("Combat rig is missing required event: %s" % required)
	if skeleton["animations"].size() != ANIMATION_DURATIONS.size():
		return _set_error("Combat rig must contain exactly eight animations")
	for animation_name: String in ANIMATION_DURATIONS:
		if not skeleton["animations"].has(animation_name):
			return _set_error("Combat rig is missing animation: %s" % animation_name)
		var duration := _max_timeline_time(skeleton["animations"][animation_name])
		if absf(duration - float(ANIMATION_DURATIONS[animation_name])) > 0.00001:
			return _set_error("Animation %s duration must be %.7f, got %.7f" % [animation_name, ANIMATION_DURATIONS[animation_name], duration])
	for region_name: String in [BODY_REGION_NAME, ARC_REGION_NAME, SIGIL_REGION_NAME]:
		if atlas_data.count("%s\n" % region_name) != 1:
			return _set_error("Atlas must declare exactly one region: %s" % region_name)
	var attachment: Dictionary = skeleton["skins"][0]["attachments"]["vivhite_body"][BODY_REGION_NAME]
	if str(attachment.get("type", "")) != "mesh":
		return _set_error("Vivhite body is not a Spine mesh")
	var vertex_count := GRID_COLUMNS * GRID_ROWS
	if attachment["uvs"].size() != vertex_count * 2:
		return _set_error("Combat mesh UV count changed")
	if attachment["triangles"].size() != (GRID_COLUMNS - 1) * (GRID_ROWS - 1) * 6:
		return _set_error("Combat mesh triangle count changed")
	if attachment["vertices"].size() <= attachment["uvs"].size():
		return _set_error("Combat mesh is not encoded as a weighted vertex stream")
	if not _validate_weight_stream(attachment["vertices"], vertex_count, skeleton["bones"].size()):
		return false
	if not _validate_event_time(skeleton["animations"]["attack"], "attack_slash_start", EVENT_TIMES["attack_slash_start"]):
		return false
	if not _validate_event_time(skeleton["animations"]["attack_heavy"], "heavy_slash_start", EVENT_TIMES["heavy_slash_start"]):
		return false
	if not _validate_event_time(skeleton["animations"]["cast"], "cast_eyes_start", EVENT_TIMES["cast_eyes_start"]):
		return false
	for attack_name: String in ["attack", "attack_heavy"]:
		var attack_slots: Dictionary = skeleton["animations"][attack_name].get("slots", {})
		if not attack_slots.has("slash_mesh"):
			return _set_error("Animation %s does not drive the shared slash_mesh magic ribbon" % attack_name)
	return true


func _validate_weight_stream(stream: Array, expected_vertices: int, bone_count: int) -> bool:
	var cursor := 0
	var decoded := 0
	while cursor < stream.size():
		var count := int(stream[cursor])
		cursor += 1
		if count < 1 or count > 4:
			return _set_error("Every mesh vertex must have 1-4 bone influences")
		var sum := 0.0
		for _index in count:
			if cursor + 3 >= stream.size():
				return _set_error("Weighted vertex stream ended mid-influence")
			var bone_index := int(stream[cursor])
			if bone_index < 0 or bone_index >= bone_count:
				return _set_error("Weighted vertex references invalid bone %d" % bone_index)
			sum += float(stream[cursor + 3])
			cursor += 4
		if absf(sum - 1.0) > 0.00001:
			return _set_error("Weighted vertex influence sum is %.8f, not 1" % sum)
		decoded += 1
	if decoded != expected_vertices:
		return _set_error("Expected %d weighted vertices, decoded %d" % [expected_vertices, decoded])
	return true


func _validate_event_time(animation: Dictionary, event_name: String, expected: float) -> bool:
	for event: Dictionary in animation.get("events", []):
		if str(event.get("name", "")) == event_name:
			if absf(float(event.get("time", -1.0)) - expected) > 0.00001:
				return _set_error("Event %s must occur at %.7f" % [event_name, expected])
			return true
	return _set_error("Animation is missing event %s" % event_name)


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


func _validate_written(output_root: String) -> bool:
	var page := Image.load_from_file(output_root.path_join(OUTPUT_PAGE))
	if page == null or page.is_empty() or page.get_size() != ATLAS_SIZE or page.get_format() != Image.FORMAT_RGBA8:
		return _set_error("Written combat atlas is not 3072x2304 RGBA8")
	var decoded = JSON.parse_string(FileAccess.get_file_as_string(output_root.path_join(OUTPUT_JSON)))
	if not decoded is Dictionary:
		return _set_error("Written combat Spine JSON could not be parsed")
	var atlas_decoded = JSON.parse_string(FileAccess.get_file_as_string(output_root.path_join(OUTPUT_ATLAS)))
	if not atlas_decoded is Dictionary:
		return _set_error("Written combat atlas wrapper could not be parsed")
	if not _validate_rig(decoded, str(atlas_decoded.get("atlas_data", ""))):
		return false
	var tres := FileAccess.get_file_as_string(output_root.path_join(OUTPUT_DATA))
	for required: String in [
		"res://Vivhite/skins/ironclad/spine/combat/vivhite_combat.spatlas",
		"res://Vivhite/skins/ironclad/spine/combat/vivhite_combat.spjson",
	]:
		if not tres.contains(required):
			return _set_error("Written skeleton-data wrapper is missing %s" % required)
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
	printerr("Vivhite combat rig build failed: %s" % message)
	return 1
