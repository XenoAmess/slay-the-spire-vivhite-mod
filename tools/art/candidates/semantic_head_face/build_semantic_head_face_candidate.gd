extends "res://build_vivhite_combat_split_mesh_candidate.gd"

## Builds three isolated head-layer research candidates from the already
## archived native-transparent EvoLink results.  The base split rig is used as
## a motion/consumer graybox only; no live skin or game installation is touched.
## Source pixels are copied into a deterministic atlas without Alpha cleanup.

const SEMANTIC_COMMAND := "build-semantic-head-face"
const BASE_ROOT := "assets/vivhite-ironclad/candidates/split_mesh/combat"
const OUTPUT_ROOT := "Vivhite/tools/candidates/semantic_head_face"
const RESOURCE_ROOT := "res://tools/candidates/semantic_head_face"

const BACK_SOURCE := (
	"assets/vivhite-ironclad/generated/evolink-paid/2026-08-28/"
	+ "0031-split-back-hair-attachment-attempt-01/output.png"
)
const FRONT_SOURCE := (
	"assets/vivhite-ironclad/generated/evolink-paid/2026-08-28/"
	+ "0033-split-front-hair-attachment-attempt-02/output.png"
)
const HEAD_0044_SOURCE := (
	"assets/vivhite-ironclad/generated/evolink-paid/2026-08-28/"
	+ "0044-split-head-face-attachment-attempt-05/output.png"
)
const HEAD_0045_SOURCE := (
	"assets/vivhite-ironclad/generated/evolink-paid/2026-08-28/"
	+ "0045-split-head-face-attachment-attempt-06/output.png"
)
const BUTTERFLY_SOURCE := (
	"assets/vivhite-ironclad/generated/evolink-paid/2026-08-28/"
	+ "0030-split-butterfly-attachment-attempt-01/output.png"
)

const BASE_JSON := "vivhite_combat_split_mesh.spjson"
const BASE_ATLAS := "vivhite_combat_split_mesh.spatlas"
const BASE_PAGE := "vivhite_combat_split_mesh.png"
const BASE_DEATH_PAGE := "vivhite_combat_split_mesh_death.png"

const SEMANTIC_JSON := "semantic_head_face.spjson"
const SEMANTIC_ATLAS := "semantic_head_face.spatlas"
const SEMANTIC_PAGE := "semantic_head_face.png"
const SEMANTIC_DATA := "semantic_head_face_skeleton_data.tres"
const SEMANTIC_MANIFEST := "candidate.json"

const HEAD_CANVAS_SIZE := Vector2(1024.0, 1024.0)
const HEAD_PAGE_SIZE := Vector2i(2048, 2048)
const HEAD_WORLD_SIZE := 360.0
const HEAD_GRID_COLUMNS := 5
const HEAD_GRID_ROWS := 5
const BUTTERFLY_SOURCE_PIVOT := Vector2(0.435, 0.55)

const SLOT_BACK := "semantic_back_hair"
const SLOT_HEAD := "semantic_head_face"
const SLOT_FRONT := "semantic_front_hair"
const SLOT_BUTTERFLY := "semantic_butterfly"
const HEAD_SLOTS := [SLOT_BACK, SLOT_HEAD, SLOT_FRONT, SLOT_BUTTERFLY]
const OLD_HEAD_SLOTS := [
	"part_head_front_hair_butterfly",
	"death_head_front_hair_butterfly",
]

const REGION_BACK := "semantic_back_hair"
const REGION_HEAD := "semantic_head_face"
const REGION_FRONT := "semantic_front_hair"
const REGION_BUTTERFLY := "semantic_butterfly"

# These placements are evidence-bearing consumer transforms, not edits to the
# archived PNGs.  0044 needs the hair canvases reduced to 75%; 0045 consumes
# them at native common-canvas scale.  The front layer is raised so its opaque
# crown covers the bald scalp while keeping the eyes and glasses readable.
const VARIANTS := [
	{
		"slug": "head0044_rigid",
		"head_id": "0044",
		"head_source": HEAD_0044_SOURCE,
		"weighted_hair": false,
		"back_rect": Rect2(128, 15, 768, 768),
		"front_rect": Rect2(128, -5, 768, 768),
		"butterfly_rect": Rect2(595, 30, 245, 245),
		"eye_center_px": Vector2(565, 475),
		"butterfly_mount_px": Vector2(703, 165),
	},
	{
		"slug": "head0045_rigid",
		"head_id": "0045",
		"head_source": HEAD_0045_SOURCE,
		"weighted_hair": false,
		"back_rect": Rect2(0, 0, 1024, 1024),
		"front_rect": Rect2(0, -80, 1024, 1024),
		"butterfly_rect": Rect2(590, 0, 300, 300),
		"eye_center_px": Vector2(592, 474),
		"butterfly_mount_px": Vector2(722, 165),
	},
	{
		"slug": "head0045_weighted",
		"head_id": "0045",
		"head_source": HEAD_0045_SOURCE,
		"weighted_hair": true,
		"back_rect": Rect2(0, 0, 1024, 1024),
		"front_rect": Rect2(0, -80, 1024, 1024),
		"butterfly_rect": Rect2(590, 0, 300, 300),
		"eye_center_px": Vector2(592, 474),
		"butterfly_mount_px": Vector2(722, 165),
	},
]


func _initialize() -> void:
	var args := OS.get_cmdline_user_args()
	if args.is_empty():
		args = PackedStringArray([SEMANTIC_COMMAND])
	if args[0] in ["-h", "--help", "help"]:
		print("Usage: godot --headless --path tools/art --script res://candidates/semantic_head_face/build_semantic_head_face_candidate.gd -- build-semantic-head-face [--output-root PATH]")
		quit(0)
		return
	if args[0] != SEMANTIC_COMMAND:
		quit(_fail("Unknown command: %s" % args[0]))
		return
	var options := _parse_options(args)
	if options.is_empty() and args.size() > 1:
		quit(2)
		return
	var output_root := _absolute_path(str(options.get("output-root", OUTPUT_ROOT)))
	var base_root := _absolute_path(BASE_ROOT)
	var sources := {
		"back": _absolute_path(BACK_SOURCE),
		"front": _absolute_path(FRONT_SOURCE),
		"butterfly": _absolute_path(BUTTERFLY_SOURCE),
		"head0044": _absolute_path(HEAD_0044_SOURCE),
		"head0045": _absolute_path(HEAD_0045_SOURCE),
	}
	if not _build_all(base_root, output_root, sources):
		quit(_fail(_last_error))
		return
	quit(0)


func _build_all(base_root: String, output_root: String, sources: Dictionary) -> bool:
	if output_root.replace("\\", "/").contains("/Vivhite/Vivhite/skins/ironclad"):
		return _set_error("Semantic head research may not target the live runtime skin: %s" % output_root)
	var base_json_path := base_root.path_join(BASE_JSON)
	var base_atlas_path := base_root.path_join(BASE_ATLAS)
	var base_page_path := base_root.path_join(BASE_PAGE)
	var base_death_page_path := base_root.path_join(BASE_DEATH_PAGE)
	for path: String in [base_json_path, base_atlas_path, base_page_path, base_death_page_path]:
		if not FileAccess.file_exists(path):
			return _set_error("Missing base split candidate input: %s" % path)
	var base_skeleton = JSON.parse_string(FileAccess.get_file_as_string(base_json_path))
	var base_atlas = JSON.parse_string(FileAccess.get_file_as_string(base_atlas_path))
	if not base_skeleton is Dictionary or not base_atlas is Dictionary:
		return _set_error("Base split candidate JSON/atlas wrapper could not be parsed")

	var images := {}
	for key: String in sources:
		var image := _load_native_rgba(str(sources[key]), key)
		if image.is_empty():
			return false
		if image.get_size() != Vector2i(1024, 1024):
			return _set_error("%s must retain its native 1024x1024 canvas, got %s" % [key, image.get_size()])
		images[key] = image

	for variant: Dictionary in VARIANTS:
		var slug := str(variant["slug"])
		var branch_root := output_root.path_join(slug)
		if not _make_dir(branch_root):
			return false
		var head_key := "head%s" % str(variant["head_id"])
		var head_page := _pack_head_page(
			images["back"], images[head_key], images["front"], images["butterfly"]
		)
		var skeleton: Dictionary = (base_skeleton as Dictionary).duplicate(true)
		_patch_skeleton(skeleton, variant)
		var atlas_data := str(base_atlas.get("atlas_data", "")) + "\n" + _head_atlas_data()
		var atlas_wrapper := {
			"atlas_data": atlas_data,
			"normal_texture_prefix": "n",
			"source_path": "%s/%s/%s" % [RESOURCE_ROOT, slug, SEMANTIC_ATLAS.replace(".spatlas", ".atlas")],
			"specular_texture_prefix": "s",
		}
		if not _validate_patched_structure(skeleton, atlas_data, variant):
			return false
		if DirAccess.copy_absolute(base_page_path, branch_root.path_join(BASE_PAGE)) != OK:
			return _set_error("Could not copy base split atlas page for %s" % slug)
		if DirAccess.copy_absolute(base_death_page_path, branch_root.path_join(BASE_DEATH_PAGE)) != OK:
			return _set_error("Could not copy base split death page for %s" % slug)
		var save_error := head_page.save_png(branch_root.path_join(SEMANTIC_PAGE))
		if save_error != OK:
			return _set_error("Could not save semantic head page for %s: %s" % [slug, error_string(save_error)])
		if not _write_text(branch_root.path_join(SEMANTIC_JSON), JSON.stringify(skeleton, "  ", false) + "\n"):
			return false
		if not _write_text(branch_root.path_join(SEMANTIC_ATLAS), JSON.stringify(atlas_wrapper, "", false) + "\n"):
			return false
		if not _write_text(branch_root.path_join(SEMANTIC_DATA), _build_tres(slug)):
			return false
		if not _write_text(
			branch_root.path_join(SEMANTIC_MANIFEST),
			JSON.stringify(_build_manifest(variant, sources, images), "  ", false) + "\n"
		):
			return false
		print("Built semantic head candidate: %s" % branch_root)
	return true


func _pack_head_page(back: Image, head: Image, front: Image, butterfly: Image) -> Image:
	var page := Image.create(HEAD_PAGE_SIZE.x, HEAD_PAGE_SIZE.y, false, Image.FORMAT_RGBA8)
	page.fill(Color(0, 0, 0, 0))
	page.blit_rect(back, Rect2i(0, 0, 1024, 1024), Vector2i(0, 0))
	page.blit_rect(head, Rect2i(0, 0, 1024, 1024), Vector2i(1024, 0))
	page.blit_rect(front, Rect2i(0, 0, 1024, 1024), Vector2i(0, 1024))
	page.blit_rect(butterfly, Rect2i(0, 0, 1024, 1024), Vector2i(1024, 1024))
	return page


func _patch_skeleton(skeleton: Dictionary, variant: Dictionary) -> void:
	skeleton["skeleton"]["hash"] = "vivhite-semantic-head-face-v1-%s" % str(variant["slug"])
	var bones: Array = skeleton["bones"]
	var eye_center: Vector2 = _common_px_to_head_local(variant["eye_center_px"])
	var butterfly_mount: Vector2 = _common_px_to_head_local(variant["butterfly_mount_px"])
	for bone: Dictionary in bones:
		match str(bone["name"]):
			"vivhite_eye_anchor":
				bone["parent"] = SPLIT_BONE_HEAD
				bone["x"] = eye_center.x
				bone["y"] = eye_center.y
			"vivhite_butterfly":
				bone["parent"] = SPLIT_BONE_HEAD
				bone["x"] = butterfly_mount.x
				bone["y"] = butterfly_mount.y

	var slots: Array = skeleton["slots"]
	var filtered_slots := []
	for slot: Dictionary in slots:
		if str(slot["name"]) not in OLD_HEAD_SLOTS:
			filtered_slots.append(slot)
	var torso_index := _slot_index(filtered_slots, "part_torso")
	filtered_slots.insert(torso_index, {
		"name": SLOT_BACK,
		"bone": SPLIT_BONE_HEAD,
		"attachment": REGION_BACK,
	})
	var right_arm_index := _slot_index(filtered_slots, "part_arm_right_upper")
	filtered_slots.insert(right_arm_index, {
		"name": SLOT_HEAD,
		"bone": SPLIT_BONE_HEAD,
		"attachment": REGION_HEAD,
	})
	filtered_slots.insert(right_arm_index + 1, {
		"name": SLOT_FRONT,
		"bone": SPLIT_BONE_HEAD,
		"attachment": REGION_FRONT,
	})
	filtered_slots.insert(right_arm_index + 2, {
		"name": SLOT_BUTTERFLY,
		"bone": "vivhite_butterfly",
		"attachment": REGION_BUTTERFLY,
	})
	skeleton["slots"] = filtered_slots

	var attachments: Dictionary = skeleton["skins"][0]["attachments"]
	for old_slot: String in OLD_HEAD_SLOTS:
		attachments.erase(old_slot)
	var bone_indices := _bone_indices(bones)
	var bone_world := _bone_world_positions_from_skeleton(bones)
	var weighted := bool(variant["weighted_hair"])
	attachments[SLOT_BACK] = {REGION_BACK: (
		_build_weighted_hair_mesh(REGION_BACK, variant["back_rect"], "back", bone_indices, bone_world)
		if weighted else _rigid_region_for_common_rect(REGION_BACK, variant["back_rect"])
	)}
	attachments[SLOT_HEAD] = {REGION_HEAD: _rigid_region_for_common_rect(
		REGION_HEAD, Rect2(0, 0, HEAD_CANVAS_SIZE.x, HEAD_CANVAS_SIZE.y)
	)}
	attachments[SLOT_FRONT] = {REGION_FRONT: (
		_build_weighted_hair_mesh(REGION_FRONT, variant["front_rect"], "front", bone_indices, bone_world)
		if weighted else _rigid_region_for_common_rect(REGION_FRONT, variant["front_rect"])
	)}
	attachments[SLOT_BUTTERFLY] = {REGION_BUTTERFLY: _butterfly_region(variant["butterfly_rect"])}

	_patch_slot_timelines(skeleton["animations"])
	_patch_head_dynamics(skeleton["animations"])


func _patch_slot_timelines(animations: Dictionary) -> void:
	for animation_name: String in animations:
		var animation: Dictionary = animations[animation_name]
		var slot_timelines: Dictionary = animation.get("slots", {})
		for old_slot: String in OLD_HEAD_SLOTS:
			slot_timelines.erase(old_slot)
		if animation_name == "die":
			for slot_name: String in HEAD_SLOTS:
				slot_timelines[slot_name] = {"attachment": [
					{"time": 0.0, "name": slot_name},
					{"time": SPLIT_DEATH_SWAP_TIME, "name": null},
				]}
		elif animation_name == "relaxed_loop":
			var duration := float(ANIMATION_DURATIONS[animation_name])
			for slot_name: String in HEAD_SLOTS:
				slot_timelines[slot_name] = {"attachment": [
					{"time": 0.0, "name": slot_name},
					{"time": duration, "name": slot_name},
				]}
		else:
			for slot_name: String in HEAD_SLOTS:
				slot_timelines[slot_name] = {"attachment": [{"time": 0.0, "name": slot_name}]}
		animation["slots"] = slot_timelines


func _patch_head_dynamics(animations: Dictionary) -> void:
	for animation_name: String in animations:
		var animation: Dictionary = animations[animation_name]
		var bones: Dictionary = animation.get("bones", {})
		var duration := float(ANIMATION_DURATIONS[animation_name])
		var left_keys: Array
		var right_keys: Array
		var butterfly_keys: Array
		match animation_name:
			"idle_loop":
				left_keys = _rotate_loop(duration, 0, 2.4, 0, -1.8)
				right_keys = _rotate_loop(duration, 0, -2.1, 0, 1.5)
				butterfly_keys = _rotate_loop(duration, 0, -1.6, 0, 1.1)
			"relaxed_loop":
				left_keys = _rotate_loop(duration, 0, 1.8, 0, -1.35)
				right_keys = _rotate_loop(duration, 0, -1.575, 0, 1.125)
				butterfly_keys = _rotate_loop(duration, 0, -1.2, 0, 0.8)
			"low_health_loop":
				left_keys = _rotate_loop(duration, 4.0, 6.0, 4.0, 5.0)
				right_keys = _rotate_loop(duration, -4.0, -6.0, -4.0, -5.0)
				butterfly_keys = _rotate_loop(duration, -2.0, -3.5, -2.0, -2.8)
			"attack", "attack_heavy":
				var heavy := animation_name == "attack_heavy"
				var strike := float(EVENT_TIMES["heavy_slash_start" if heavy else "attack_slash_start"])
				var recover := duration * 0.72
				left_keys = _action_rotate(duration, -3.0, 10.0 if heavy else 6.0, strike, recover)
				right_keys = _action_rotate(duration, 3.0, -9.0 if heavy else -5.0, strike, recover)
				butterfly_keys = _action_rotate(duration, 2.0, -8.0 if heavy else -5.0, strike, recover)
			"cast":
				var start := float(EVENT_TIMES["cast_eyes_start"])
				var clear := duration * 0.78
				left_keys = _action_rotate(duration, 0.0, 7.0, start, clear)
				right_keys = _action_rotate(duration, 0.0, -7.0, start, clear)
				butterfly_keys = _action_rotate(duration, 0.0, -5.0, start, clear)
			"hurt":
				left_keys = _action_rotate(duration, 0.0, 12.0, 0.14, 0.52)
				right_keys = _action_rotate(duration, 0.0, -10.0, 0.14, 0.52)
				butterfly_keys = _action_rotate(duration, 0.0, -8.0, 0.14, 0.52)
			"die":
				left_keys = bones["vivhite_hair_left"]["rotate"]
				right_keys = bones["vivhite_hair_right"]["rotate"]
				butterfly_keys = _staggered_terminal(duration, 0.46, -7.0, 1.36, -31.0, -25.0)
		bones["vivhite_hair_left"] = {"rotate": left_keys}
		bones["vivhite_hair_right"] = {"rotate": right_keys}
		bones["vivhite_butterfly"] = {"rotate": butterfly_keys}
		for bone_name: String in ["vivhite_hair_left", "vivhite_hair_right", "vivhite_butterfly"]:
			_add_split_timeline_easing(
				bones[bone_name]["rotate"],
				"rotate",
				SPLIT_LOOP_EASING if animation_name.ends_with("_loop") else SPLIT_ACTION_EASING,
			)
		animation["bones"] = bones


func _rigid_region_for_common_rect(region: String, common_rect: Rect2) -> Dictionary:
	var world_width := common_rect.size.x / HEAD_CANVAS_SIZE.x * HEAD_WORLD_SIZE
	var world_height := common_rect.size.y / HEAD_CANVAS_SIZE.y * HEAD_WORLD_SIZE
	var center_px := common_rect.position + common_rect.size * 0.5
	var center := _common_px_to_head_local(center_px)
	return {
		"path": region,
		"x": center.x,
		"y": center.y,
		"width": world_width,
		"height": world_height,
	}


func _butterfly_region(common_rect: Rect2) -> Dictionary:
	var world_width := common_rect.size.x / HEAD_CANVAS_SIZE.x * HEAD_WORLD_SIZE
	var world_height := common_rect.size.y / HEAD_CANVAS_SIZE.y * HEAD_WORLD_SIZE
	# The bone is placed at the hairpin/wing joint.  Offset the region center so
	# rotating the butterfly does not orbit the full 1024 source canvas center.
	return {
		"path": REGION_BUTTERFLY,
		"x": (0.5 - BUTTERFLY_SOURCE_PIVOT.x) * world_width,
		"y": (BUTTERFLY_SOURCE_PIVOT.y - 0.5) * world_height,
		"width": world_width,
		"height": world_height,
	}


func _build_weighted_hair_mesh(
	region: String,
	common_rect: Rect2,
	layer: String,
	bone_indices: Dictionary,
	bone_world: Dictionary,
) -> Dictionary:
	var points := _ordered_grid_points()
	var uvs := []
	var vertices := []
	var head_world: Vector2 = bone_world[SPLIT_BONE_HEAD]
	for point: Vector2i in points:
		var normalized := Vector2(
			float(point.x) / float(HEAD_GRID_COLUMNS - 1),
			float(point.y) / float(HEAD_GRID_ROWS - 1),
		)
		uvs.append_array([normalized.x, normalized.y])
		var common_px := common_rect.position + common_rect.size * normalized
		var world := head_world + _common_px_to_head_local(common_px)
		var influences := _hair_influences(normalized, layer)
		vertices.append(influences.size())
		for influence: Dictionary in influences:
			var bone_name := str(influence["bone"])
			var local: Vector2 = world - (bone_world[bone_name] as Vector2)
			vertices.append_array([
				int(bone_indices[bone_name]),
				local.x,
				local.y,
				float(influence["weight"]),
			])
	return {
		"type": "mesh",
		"path": region,
		"uvs": uvs,
		"triangles": _grid_triangles(points),
		"vertices": vertices,
		"hull": HEAD_GRID_COLUMNS * 2 + HEAD_GRID_ROWS * 2 - 4,
		"width": common_rect.size.x / HEAD_CANVAS_SIZE.x * HEAD_WORLD_SIZE,
		"height": common_rect.size.y / HEAD_CANVAS_SIZE.y * HEAD_WORLD_SIZE,
	}


func _hair_influences(point: Vector2, layer: String) -> Array:
	var vertical := clampf((point.y - 0.18) / 0.82, 0.0, 1.0)
	var lateral := clampf((absf(point.x - 0.5) - 0.10) / 0.40, 0.0, 1.0)
	var maximum := 0.72 if layer == "back" else 0.24
	var side_weight := maximum * vertical * lateral
	if side_weight <= 0.0001:
		return [{"bone": SPLIT_BONE_HEAD, "weight": 1.0}]
	return [
		{"bone": SPLIT_BONE_HEAD, "weight": 1.0 - side_weight},
		{
			"bone": "vivhite_hair_left" if point.x < 0.5 else "vivhite_hair_right",
			"weight": side_weight,
		},
	]


func _ordered_grid_points() -> Array:
	var result := []
	for x in HEAD_GRID_COLUMNS:
		result.append(Vector2i(x, 0))
	for y in range(1, HEAD_GRID_ROWS):
		result.append(Vector2i(HEAD_GRID_COLUMNS - 1, y))
	for x in range(HEAD_GRID_COLUMNS - 2, -1, -1):
		result.append(Vector2i(x, HEAD_GRID_ROWS - 1))
	for y in range(HEAD_GRID_ROWS - 2, 0, -1):
		result.append(Vector2i(0, y))
	for y in range(1, HEAD_GRID_ROWS - 1):
		for x in range(1, HEAD_GRID_COLUMNS - 1):
			result.append(Vector2i(x, y))
	return result


func _grid_triangles(points: Array) -> Array:
	var indices := {}
	for index in points.size():
		indices[points[index]] = index
	var triangles := []
	for y in HEAD_GRID_ROWS - 1:
		for x in HEAD_GRID_COLUMNS - 1:
			var top_left := int(indices[Vector2i(x, y)])
			var top_right := int(indices[Vector2i(x + 1, y)])
			var bottom_left := int(indices[Vector2i(x, y + 1)])
			var bottom_right := int(indices[Vector2i(x + 1, y + 1)])
			triangles.append_array([top_left, bottom_left, top_right, top_right, bottom_left, bottom_right])
	return triangles


func _bone_indices(bones: Array) -> Dictionary:
	var result := {}
	for index in bones.size():
		result[str(bones[index]["name"])] = index
	return result


func _bone_world_positions_from_skeleton(bones: Array) -> Dictionary:
	var result := {}
	for bone: Dictionary in bones:
		var local := Vector2(float(bone.get("x", 0.0)), float(bone.get("y", 0.0)))
		var parent_name := str(bone.get("parent", ""))
		result[str(bone["name"])] = local + (result.get(parent_name, Vector2.ZERO) as Vector2)
	return result


func _common_px_to_head_local(point: Vector2) -> Vector2:
	return Vector2(
		(point.x - HEAD_CANVAS_SIZE.x * 0.5) / HEAD_CANVAS_SIZE.x * HEAD_WORLD_SIZE,
		(HEAD_CANVAS_SIZE.y * 0.5 - point.y) / HEAD_CANVAS_SIZE.y * HEAD_WORLD_SIZE,
	)


func _slot_index(slots: Array, slot_name: String) -> int:
	for index in slots.size():
		if str(slots[index]["name"]) == slot_name:
			return index
	return slots.size()


func _head_atlas_data() -> String:
	return "\n".join(PackedStringArray([
		SEMANTIC_PAGE,
		"size:2048,2048",
		"filter:Linear,Linear",
		"pma:false",
		"repeat:none",
		REGION_BACK,
		"bounds:0,0,1024,1024",
		REGION_HEAD,
		"bounds:1024,0,1024,1024",
		REGION_FRONT,
		"bounds:0,1024,1024,1024",
		REGION_BUTTERFLY,
		"bounds:1024,1024,1024,1024",
		"",
	]))


func _build_tres(slug: String) -> String:
	var base_text := FileAccess.get_file_as_string(_absolute_path(BASE_ROOT).path_join("vivhite_combat_split_mesh_skeleton_data.tres"))
	base_text = base_text.replace(
		"res://candidates/split_mesh/combat/vivhite_combat_split_mesh.spatlas",
		"%s/%s/%s" % [RESOURCE_ROOT, slug, SEMANTIC_ATLAS],
	)
	base_text = base_text.replace(
		"res://candidates/split_mesh/combat/vivhite_combat_split_mesh.spjson",
		"%s/%s/%s" % [RESOURCE_ROOT, slug, SEMANTIC_JSON],
	)
	return base_text


func _build_manifest(
	variant: Dictionary,
	sources: Dictionary,
	images: Dictionary,
) -> Dictionary:
	var records := {}
	for key: String in sources:
		records[key] = {
			"path": _repo_relative(str(sources[key])),
			"sha256": _sha256_file(str(sources[key])),
			"size": [images[key].get_width(), images[key].get_height()],
			"alpha_bbox": _rect_to_array(_alpha_bounds(images[key])),
		}
	return {
		"schema": "vivhite-semantic-head-face-candidate/v1",
		"status": "research_only_not_publishable",
		"variant": str(variant["slug"]),
		"head_id": str(variant["head_id"]),
		"weighted_hair": bool(variant["weighted_hair"]),
		"source_evidence": records,
		"consumer_contract": {
			"layer_order": [SLOT_BACK, "part_torso", SLOT_HEAD, SLOT_FRONT, SLOT_BUTTERFLY, "part_arm_right_upper"],
			"eye_slot": "eye_attach_slot",
			"eye_bone": "vivhite_eye_anchor",
			"eye_center_common_px": _vector_to_array(variant["eye_center_px"]),
			"eye_center_head_local": _vector_to_array(_common_px_to_head_local(variant["eye_center_px"])),
			"butterfly_mount_common_px": _vector_to_array(variant["butterfly_mount_px"]),
			"butterfly_source_pivot": _vector_to_array(BUTTERFLY_SOURCE_PIVOT),
			"relaxed_loop_duration": float(ANIMATION_DURATIONS["relaxed_loop"]),
			"death_detach_time": SPLIT_DEATH_SWAP_TIME,
		},
		"placements": {
			"back_rect": _rect2_to_array(variant["back_rect"]),
			"head_rect": [0.0, 0.0, 1024.0, 1024.0],
			"front_rect": _rect2_to_array(variant["front_rect"]),
			"butterfly_rect": _rect2_to_array(variant["butterfly_rect"]),
			"common_canvas": [1024, 1024],
			"head_world_size": HEAD_WORLD_SIZE,
		},
		"evidence_limits": [
			"The earlier three-layer visual claim used 0044; it is not evidence for 0045.",
			"This build evaluates 0044 and 0045 under separately recorded transforms.",
			"The base body remains temporary split UV art, so this candidate cannot be published.",
		],
		"safety": {
			"evolink_paid_calls": 0,
			"source_alpha_modified": false,
			"game_or_runtime_modified": false,
		},
	}


func _validate_patched_structure(skeleton: Dictionary, atlas_data: String, variant: Dictionary) -> bool:
	if str(skeleton["skeleton"].get("spine", "")) != SPINE_VERSION:
		return _set_error("Semantic head candidate must retain Spine %s" % SPINE_VERSION)
	var slot_indices := {}
	for index in skeleton["slots"].size():
		slot_indices[str(skeleton["slots"][index]["name"])] = index
	for old_slot: String in OLD_HEAD_SLOTS:
		if slot_indices.has(old_slot):
			return _set_error("Legacy combined head slot survived: %s" % old_slot)
	for slot_name: String in HEAD_SLOTS:
		if not slot_indices.has(slot_name):
			return _set_error("Missing semantic head slot: %s" % slot_name)
	if not (
		int(slot_indices[SLOT_BACK]) < int(slot_indices["part_torso"])
		and int(slot_indices["part_torso"]) < int(slot_indices[SLOT_HEAD])
		and int(slot_indices[SLOT_HEAD]) < int(slot_indices[SLOT_FRONT])
		and int(slot_indices[SLOT_FRONT]) < int(slot_indices[SLOT_BUTTERFLY])
		and int(slot_indices[SLOT_BUTTERFLY]) < int(slot_indices["part_arm_right_upper"])
	):
		return _set_error("Semantic head draw order does not satisfy back hair -> torso -> face -> fringe -> butterfly -> foreground arm")
	var attachments: Dictionary = skeleton["skins"][0]["attachments"]
	var weighted := bool(variant["weighted_hair"])
	for slot_name: String in HEAD_SLOTS:
		if not attachments.has(slot_name) or not attachments[slot_name].has(slot_name):
			return _set_error("Missing attachment for %s" % slot_name)
	var back_type := str(attachments[SLOT_BACK][REGION_BACK].get("type", "region"))
	var front_type := str(attachments[SLOT_FRONT][REGION_FRONT].get("type", "region"))
	if weighted != (back_type == "mesh" and front_type == "mesh"):
		return _set_error("Weighted-hair variant/type mismatch for %s" % str(variant["slug"]))
	if not weighted and (back_type != "region" or front_type != "region"):
		return _set_error("Rigid variant must use rigid back/front regions")
	if str(attachments[SLOT_HEAD][REGION_HEAD].get("type", "region")) != "region":
		return _set_error("Head/face must remain a rigid region")
	if str(attachments[SLOT_BUTTERFLY][REGION_BUTTERFLY].get("type", "region")) != "region":
		return _set_error("Butterfly must remain a rigid region")
	for region_name: String in [REGION_BACK, REGION_HEAD, REGION_FRONT, REGION_BUTTERFLY]:
		if atlas_data.count("%s\n" % region_name) != 1:
			return _set_error("Atlas must declare exactly one %s region" % region_name)
	var eye_parent := ""
	var eye_slot_bone := ""
	for bone: Dictionary in skeleton["bones"]:
		if str(bone["name"]) == "vivhite_eye_anchor":
			eye_parent = str(bone.get("parent", ""))
	for slot: Dictionary in skeleton["slots"]:
		if str(slot["name"]) == "eye_attach_slot":
			eye_slot_bone = str(slot.get("bone", ""))
	if eye_parent != SPLIT_BONE_HEAD or eye_slot_bone != "vivhite_eye_anchor":
		return _set_error("eye_attach_slot must follow a head-local vivhite_eye_anchor")
	for animation_name: String in ANIMATION_DURATIONS:
		if not skeleton["animations"].has(animation_name):
			return _set_error("Missing animation %s" % animation_name)
	var relaxed_slots: Dictionary = skeleton["animations"]["relaxed_loop"].get("slots", {})
	for slot_name: String in HEAD_SLOTS:
		var keys: Array = relaxed_slots.get(slot_name, {}).get("attachment", [])
		if keys.size() != 2 or str(keys[0].get("name", "")) != slot_name or str(keys[1].get("name", "")) != slot_name:
			return _set_error("relaxed_loop must keep %s visible at both boundaries" % slot_name)
		if absf(float(keys[1].get("time", -1.0)) - float(ANIMATION_DURATIONS["relaxed_loop"])) > 0.00001:
			return _set_error("relaxed_loop boundary mismatch for %s" % slot_name)
	var die_slots: Dictionary = skeleton["animations"]["die"].get("slots", {})
	for slot_name: String in HEAD_SLOTS:
		var keys: Array = die_slots.get(slot_name, {}).get("attachment", [])
		if keys.size() != 2 or absf(float(keys[1].get("time", -1.0)) - SPLIT_DEATH_SWAP_TIME) > 0.00001 or keys[1].get("name", "sentinel") != null:
			return _set_error("die must detach %s at the side-collapse swap" % slot_name)
	return true


func _rect_to_array(rect: Rect2i) -> Array:
	return [rect.position.x, rect.position.y, rect.size.x, rect.size.y]


func _rect2_to_array(rect: Rect2) -> Array:
	return [rect.position.x, rect.position.y, rect.size.x, rect.size.y]


func _vector_to_array(vector: Vector2) -> Array:
	return [vector.x, vector.y]


func _sha256_file(path: String) -> String:
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null:
		return ""
	var context := HashingContext.new()
	context.start(HashingContext.HASH_SHA256)
	context.update(file.get_buffer(file.get_length()))
	return context.finish().hex_encode()
