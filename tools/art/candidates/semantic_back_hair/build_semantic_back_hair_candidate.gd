extends "res://build_vivhite_combat_split_mesh_candidate.gd"

## Offline-only integration study for the accepted 0031 rear-hair drawing.
##
## The source PNG is never cropped, masked, thresholded, or alpha-cleaned. It is
## copied byte-for-byte into its own atlas page, then driven as one weighted
## mesh whose crown stays attached to the head while three lower influence
## zones provide restrained inertia. Adjacent head layers are included only to
## test the real draw-order/overlap contract; this candidate never writes to the
## live Ironclad skin.

const COMMAND_SEMANTIC := "build-semantic-back-hair-candidate"
const OUTPUT_ROOT := "Vivhite/tools/candidates/semantic_back_hair"
const MOUNT_ROOT := "res://tools/candidates/semantic_back_hair"

const SEMANTIC_OUTPUT_JSON := "semantic_back_hair.spjson"
const SEMANTIC_OUTPUT_ATLAS := "semantic_back_hair.spatlas"
const SEMANTIC_OUTPUT_DATA := "semantic_back_hair_skeleton_data.tres"
const SEMANTIC_OUTPUT_MANIFEST := "candidate.json"
const SEMANTIC_OUTPUT_ALPHA_CONTACT := "semantic_back_hair_alpha_contact.png"
const SEMANTIC_OUTPUT_SETUP_CONTACT := "semantic_back_hair_setup_contact.png"

const BASE_PAGE := "vivhite_combat_split_mesh.png"
const BASE_DEATH_PAGE := "vivhite_combat_split_mesh_death.png"
const BACK_HAIR_PAGE := "semantic_back_hair.png"
const HEAD_FACE_PAGE := "semantic_head_face_neighbor.png"
const FRONT_HAIR_PAGE := "semantic_front_hair_neighbor.png"
const BUTTERFLY_PAGE := "semantic_butterfly_neighbor.png"

const BACK_HAIR_REGION := "vivhite_semantic_back_hair"
const HEAD_FACE_REGION := "vivhite_semantic_head_face_neighbor"
const FRONT_HAIR_REGION := "vivhite_semantic_front_hair_neighbor"
const BUTTERFLY_REGION := "vivhite_semantic_butterfly_neighbor"

const SLOT_BACK_HAIR := "semantic_back_hair"
const SLOT_HEAD_FACE := "semantic_head_face_neighbor"
const SLOT_FRONT_HAIR := "semantic_front_hair_neighbor"
const SLOT_BUTTERFLY := "semantic_butterfly_neighbor"
const OLD_HEAD_SLOT := "part_head_front_hair_butterfly"

const BONE_HAIR_ROOT := "vivhite_hair_back"
const BONE_HAIR_LEFT := "vivhite_hair_left"
const BONE_HAIR_CENTER := "vivhite_hair_center"
const BONE_HAIR_RIGHT := "vivhite_hair_right"

const BACK_HAIR_SOURCE := (
	"assets/vivhite-ironclad/custom/combat/parts/normal/"
	+ "vivhite-back-hair-v1.png"
)
const BACK_HAIR_ARCHIVE := (
	"assets/vivhite-ironclad/generated/evolink-paid/2026-08-28/"
	+ "0031-split-back-hair-attachment-attempt-01/output.png"
)
const HEAD_FACE_SOURCE := (
	"assets/vivhite-ironclad/generated/evolink-paid/2026-08-28/"
	+ "0044-split-head-face-attachment-attempt-05/output.png"
)
const FRONT_HAIR_SOURCE := (
	"assets/vivhite-ironclad/generated/evolink-paid/2026-08-28/"
	+ "0033-split-front-hair-attachment-attempt-02/output.png"
)
const BUTTERFLY_SOURCE := (
	"assets/vivhite-ironclad/custom/combat/parts/normal/"
	+ "vivhite-butterfly-v1.png"
)
const BASE_ROOT := "assets/vivhite-ironclad/candidates/split_mesh/combat"

const EXPECTED_BACK_HAIR_SHA256 := "9fd66b599eb4128ba9c3b4c2bd815aadb0613e064aca2f697307997048c01782"
const SOURCE_CANVAS := Vector2i(1024, 1024)

# All three head layers keep their complete 1024-square canvas and share one
# deterministic 360x360 authored-world transform. This preserves the natural
# alignment demonstrated by 0031 + 0044 + 0033 instead of independently
# normalizing each Alpha bbox.
const HEAD_CANVAS_SIZE := 360.0
const HEAD_CANVAS_CENTER := Vector2(-23.0, 1106.0)
const HEAD_CANVAS_RECT := Rect2(
	HEAD_CANVAS_CENTER - Vector2(HEAD_CANVAS_SIZE, HEAD_CANVAS_SIZE) * 0.5,
	Vector2(HEAD_CANVAS_SIZE, HEAD_CANVAS_SIZE)
)
# 0033's full-canvas top is 126 source pixels lower than 0031's solid crown.
# Moving it up by 118 source pixels aligns the two physical crown arcs while
# preserving a small rear-hair reveal; this is an attachment transform, not a
# crop or Alpha edit.
const FRONT_HAIR_OFFSET_SOURCE_PX := Vector2(0.0, -118.0)
const FRONT_HAIR_OFFSET_WORLD := Vector2(
	FRONT_HAIR_OFFSET_SOURCE_PX.x * HEAD_CANVAS_SIZE / 1024.0,
	-FRONT_HAIR_OFFSET_SOURCE_PX.y * HEAD_CANVAS_SIZE / 1024.0
)
const BUTTERFLY_WORLD_SIZE := 120.0

# Seven by seven is enough to expose whether a single connected bob can accept
# useful tip inertia without turning its crown into rubber cloth. This is a
# research mesh, not a claim that 49 vertices are the final production density.
const HAIR_GRID_COLUMNS := 7
const HAIR_GRID_ROWS := 7


func _initialize() -> void:
	var args := OS.get_cmdline_user_args()
	if args.is_empty():
		args = PackedStringArray([COMMAND_SEMANTIC])
	if args[0] in ["-h", "--help", "help"]:
		print("Usage: godot --headless --path tools/art --script res://candidates/semantic_back_hair/build_semantic_back_hair_candidate.gd -- build-semantic-back-hair-candidate [--output-root PATH]")
		quit(0)
		return
	if args[0] != COMMAND_SEMANTIC:
		quit(_fail("Unknown command: %s" % args[0]))
		return
	var options := _parse_options(args)
	if options.is_empty() and args.size() > 1:
		quit(2)
		return
	var output_root := _absolute_path(str(options.get("output-root", OUTPUT_ROOT)))
	if not _build_semantic_candidate(output_root):
		quit(_fail(_last_error))
		return
	quit(0)


func _build_semantic_candidate(output_root: String) -> bool:
	_last_error = ""
	if output_root.replace("\\", "/").contains("/Vivhite/Vivhite/skins/ironclad"):
		return _set_error("Semantic candidate may not target the live runtime skin: %s" % output_root)

	var paths := {
		"back_hair": _absolute_path(BACK_HAIR_SOURCE),
		"back_hair_archive": _absolute_path(BACK_HAIR_ARCHIVE),
		"head_face": _absolute_path(HEAD_FACE_SOURCE),
		"front_hair": _absolute_path(FRONT_HAIR_SOURCE),
		"butterfly": _absolute_path(BUTTERFLY_SOURCE),
		"base_page": _absolute_path(BASE_ROOT.path_join(SPLIT_PAGE)),
		"base_death_page": _absolute_path(BASE_ROOT.path_join(SPLIT_DEATH_PAGE)),
	}
	for label: String in paths:
		if not FileAccess.file_exists(str(paths[label])):
			return _set_error("Missing %s input: %s" % [label, paths[label]])

	var back_hair := _load_semantic_rgba(str(paths.back_hair), "0031 rear hair")
	var head_face := _load_semantic_rgba(str(paths.head_face), "0044 head/face neighbor")
	var front_hair := _load_semantic_rgba(str(paths.front_hair), "0033 front-hair neighbor")
	var butterfly := _load_semantic_rgba(str(paths.butterfly), "0030 butterfly neighbor")
	if back_hair.is_empty() or head_face.is_empty() or front_hair.is_empty() or butterfly.is_empty():
		return false

	var source_hash := FileAccess.get_sha256(str(paths.back_hair)).to_lower()
	var archive_hash := FileAccess.get_sha256(str(paths.back_hair_archive)).to_lower()
	if source_hash != EXPECTED_BACK_HAIR_SHA256:
		return _set_error("0031 source hash changed: %s" % source_hash)
	if archive_hash != source_hash:
		return _set_error("Promoted back-hair source is not byte-identical to archived 0031")

	var skeleton := _build_semantic_skeleton()
	var atlas_data := _build_semantic_atlas_data()
	if not _validate_semantic_in_memory(skeleton, atlas_data, back_hair):
		return false
	if not _make_dir(output_root):
		return false

	var raw_copies := {
		str(paths.base_page): output_root.path_join(BASE_PAGE),
		str(paths.base_death_page): output_root.path_join(BASE_DEATH_PAGE),
		str(paths.back_hair): output_root.path_join(BACK_HAIR_PAGE),
		str(paths.head_face): output_root.path_join(HEAD_FACE_PAGE),
		str(paths.front_hair): output_root.path_join(FRONT_HAIR_PAGE),
		str(paths.butterfly): output_root.path_join(BUTTERFLY_PAGE),
	}
	for source_path: String in raw_copies:
		if not _copy_bytes(source_path, str(raw_copies[source_path])):
			return false

	if not _write_text(output_root.path_join(SEMANTIC_OUTPUT_JSON), JSON.stringify(skeleton, "  ", false) + "\n"):
		return false
	var atlas_wrapper := {
		"atlas_data": atlas_data,
		"normal_texture_prefix": "n",
		"source_path": "%s/%s" % [MOUNT_ROOT, SEMANTIC_OUTPUT_ATLAS.replace(".spatlas", ".atlas")],
		"specular_texture_prefix": "s",
	}
	if not _write_text(output_root.path_join(SEMANTIC_OUTPUT_ATLAS), JSON.stringify(atlas_wrapper, "", false) + "\n"):
		return false
	if not _write_text(output_root.path_join(SEMANTIC_OUTPUT_DATA), _build_semantic_tres()):
		return false
	if not _write_text(
		output_root.path_join(SEMANTIC_OUTPUT_MANIFEST),
		JSON.stringify(_build_semantic_manifest(paths, back_hair, skeleton), "  ", false) + "\n"
	):
		return false
	if not _write_alpha_contact(back_hair, output_root.path_join(SEMANTIC_OUTPUT_ALPHA_CONTACT)):
		return false
	if not _write_setup_contact(
		back_hair, head_face, front_hair, butterfly,
		output_root.path_join(SEMANTIC_OUTPUT_SETUP_CONTACT)
	):
		return false

	print("Built isolated semantic back-hair candidate:")
	print("  output: %s" % output_root)
	print("  source: archived 0031, byte-identical promoted copy")
	print("  mesh:   %d weighted vertices, %d triangles" % [
		HAIR_GRID_COLUMNS * HAIR_GRID_ROWS,
		(HAIR_GRID_COLUMNS - 1) * (HAIR_GRID_ROWS - 1) * 2,
	])
	print("  layers: rear hair < torso/neck < head-face < front hair < butterfly")
	print("  runtime skin modified: false")
	return true


func _load_semantic_rgba(path: String, label: String) -> Image:
	var image := Image.load_from_file(path)
	if image == null or image.is_empty():
		_set_error("Could not decode %s: %s" % [label, path])
		return Image.new()
	if image.get_format() != Image.FORMAT_RGBA8:
		_set_error("%s must be native RGBA8: %s" % [label, path])
		return Image.new()
	if image.get_size() != SOURCE_CANVAS:
		_set_error("%s must retain its complete 1024x1024 canvas: %s" % [label, image.get_size()])
		return Image.new()
	for corner: Vector2i in [Vector2i.ZERO, Vector2i(1023, 0), Vector2i(0, 1023), Vector2i(1023, 1023)]:
		if image.get_pixelv(corner).a > 0.0:
			_set_error("%s has a non-transparent corner at %s" % [label, corner])
			return Image.new()
	return image


func _build_semantic_skeleton() -> Dictionary:
	var skeleton: Dictionary = _build_split_skeleton()
	skeleton["skeleton"]["hash"] = "vivhite-semantic-back-hair-study-v1"
	var bones: Array = skeleton["bones"]
	var world := _bone_world_positions()
	var hair_root_world: Vector2 = world[BONE_HAIR_ROOT]
	var center_world := Vector2(HEAD_CANVAS_CENTER.x, HEAD_CANVAS_CENTER.y - 82.0)
	bones.append({
		"name": BONE_HAIR_CENTER,
		"parent": BONE_HAIR_ROOT,
		"x": center_world.x - hair_root_world.x,
		"y": center_world.y - hair_root_world.y,
		"length": 82.0,
	})
	world[BONE_HAIR_CENTER] = center_world

	var slots: Array = skeleton["slots"]
	var rebuilt_slots := []
	for slot: Dictionary in slots:
		var name := str(slot["name"])
		if name == OLD_HEAD_SLOT:
			rebuilt_slots.append({"name": SLOT_HEAD_FACE, "bone": SPLIT_BONE_HEAD, "attachment": HEAD_FACE_REGION})
			rebuilt_slots.append({"name": SLOT_FRONT_HAIR, "bone": SPLIT_BONE_HEAD, "attachment": FRONT_HAIR_REGION})
			rebuilt_slots.append({"name": SLOT_BUTTERFLY, "bone": "vivhite_butterfly", "attachment": BUTTERFLY_REGION})
			continue
		if name == "part_torso":
			rebuilt_slots.append({"name": SLOT_BACK_HAIR, "bone": BONE_HAIR_ROOT, "attachment": BACK_HAIR_REGION})
		rebuilt_slots.append(slot)
	skeleton["slots"] = rebuilt_slots

	var attachments: Dictionary = skeleton["skins"][0]["attachments"]
	attachments.erase(OLD_HEAD_SLOT)
	var indices := _bone_indices(bones)
	attachments[SLOT_BACK_HAIR] = {
		BACK_HAIR_REGION: _build_back_hair_weighted_mesh(indices, world),
	}
	var head_world: Vector2 = world[SPLIT_BONE_HEAD]
	var head_local := HEAD_CANVAS_CENTER - head_world
	attachments[SLOT_HEAD_FACE] = {
		HEAD_FACE_REGION: _positioned_region_attachment(
			HEAD_FACE_REGION, HEAD_CANVAS_SIZE, HEAD_CANVAS_SIZE, head_local
		),
	}
	attachments[SLOT_FRONT_HAIR] = {
		FRONT_HAIR_REGION: _positioned_region_attachment(
			FRONT_HAIR_REGION,
			HEAD_CANVAS_SIZE,
			HEAD_CANVAS_SIZE,
			head_local + FRONT_HAIR_OFFSET_WORLD
		),
	}
	attachments[SLOT_BUTTERFLY] = {
		BUTTERFLY_REGION: _positioned_region_attachment(
			BUTTERFLY_REGION, BUTTERFLY_WORLD_SIZE, BUTTERFLY_WORLD_SIZE, Vector2.ZERO
		),
	}

	var animations: Dictionary = skeleton["animations"]
	_apply_back_hair_motion(animations)
	_apply_layer_visibility(animations)
	return skeleton


func _bone_indices(bones: Array) -> Dictionary:
	var result := {}
	for index in bones.size():
		result[str(bones[index]["name"])] = index
	return result


func _positioned_region_attachment(path: String, width: float, height: float, offset: Vector2) -> Dictionary:
	return {
		"path": path,
		"x": offset.x,
		"y": offset.y,
		"width": width,
		"height": height,
	}


func _build_back_hair_weighted_mesh(indices: Dictionary, world: Dictionary) -> Dictionary:
	var points := _ordered_hair_grid_points()
	var uvs := []
	var vertices := []
	for point: Vector2i in points:
		var normalized := Vector2(
			float(point.x) / float(HAIR_GRID_COLUMNS - 1),
			float(point.y) / float(HAIR_GRID_ROWS - 1)
		)
		var vertex_world := Vector2(
			HEAD_CANVAS_RECT.position.x + HEAD_CANVAS_RECT.size.x * normalized.x,
			HEAD_CANVAS_RECT.position.y + HEAD_CANVAS_RECT.size.y * (1.0 - normalized.y)
		)
		uvs.append_array([normalized.x, normalized.y])
		var influences := _hair_influences(normalized)
		vertices.append(influences.size())
		for influence: Dictionary in influences:
			var bone_name := str(influence.bone)
			var local: Vector2 = vertex_world - (world[bone_name] as Vector2)
			vertices.append_array([
				int(indices[bone_name]), local.x, local.y, float(influence.weight),
			])
	return {
		"type": "mesh",
		"path": BACK_HAIR_REGION,
		"uvs": uvs,
		"triangles": _build_hair_triangles(points),
		"vertices": vertices,
		"hull": HAIR_GRID_COLUMNS * 2 + HAIR_GRID_ROWS * 2 - 4,
		"width": HEAD_CANVAS_SIZE,
		"height": HEAD_CANVAS_SIZE,
	}


func _hair_influences(point: Vector2) -> Array:
	var tail_strength := smoothstep(0.36, 0.98, point.y) * 0.72
	if tail_strength <= 0.00001:
		return [{"bone": BONE_HAIR_ROOT, "weight": 1.0}]
	var raw_left := maxf(0.0, 1.0 - absf(point.x - 0.18) / 0.50)
	var raw_center := maxf(0.0, 1.0 - absf(point.x - 0.50) / 0.42)
	var raw_right := maxf(0.0, 1.0 - absf(point.x - 0.82) / 0.50)
	var raw_sum := raw_left + raw_center + raw_right
	var result := [{"bone": BONE_HAIR_ROOT, "weight": 1.0 - tail_strength}]
	for spec: Dictionary in [
		{"bone": BONE_HAIR_LEFT, "raw": raw_left},
		{"bone": BONE_HAIR_CENTER, "raw": raw_center},
		{"bone": BONE_HAIR_RIGHT, "raw": raw_right},
	]:
		if float(spec.raw) > 0.00001:
			result.append({
				"bone": spec.bone,
				"weight": tail_strength * float(spec.raw) / raw_sum,
			})
	return result


func _ordered_hair_grid_points() -> Array:
	var result := []
	for x in HAIR_GRID_COLUMNS:
		result.append(Vector2i(x, 0))
	for y in range(1, HAIR_GRID_ROWS):
		result.append(Vector2i(HAIR_GRID_COLUMNS - 1, y))
	for x in range(HAIR_GRID_COLUMNS - 2, -1, -1):
		result.append(Vector2i(x, HAIR_GRID_ROWS - 1))
	for y in range(HAIR_GRID_ROWS - 2, 0, -1):
		result.append(Vector2i(0, y))
	for y in range(1, HAIR_GRID_ROWS - 1):
		for x in range(1, HAIR_GRID_COLUMNS - 1):
			result.append(Vector2i(x, y))
	return result


func _build_hair_triangles(points: Array) -> Array:
	var lookup := {}
	for index in points.size():
		var point: Vector2i = points[index]
		lookup["%d,%d" % [point.x, point.y]] = index
	var result := []
	for y in range(HAIR_GRID_ROWS - 1):
		for x in range(HAIR_GRID_COLUMNS - 1):
			var tl: int = lookup["%d,%d" % [x, y]]
			var tr: int = lookup["%d,%d" % [x + 1, y]]
			var bl: int = lookup["%d,%d" % [x, y + 1]]
			var br: int = lookup["%d,%d" % [x + 1, y + 1]]
			result.append_array([tl, bl, tr, tr, bl, br])
	return result


func _apply_layer_visibility(animations: Dictionary) -> void:
	var relaxed: Dictionary = animations["relaxed_loop"]
	var relaxed_slots: Dictionary = relaxed.get_or_add("slots", {})
	for spec: Dictionary in [
		{"slot": SLOT_BACK_HAIR, "attachment": BACK_HAIR_REGION},
		{"slot": SLOT_HEAD_FACE, "attachment": HEAD_FACE_REGION},
		{"slot": SLOT_FRONT_HAIR, "attachment": FRONT_HAIR_REGION},
		{"slot": SLOT_BUTTERFLY, "attachment": BUTTERFLY_REGION},
	]:
		relaxed_slots[spec.slot] = {"attachment": [
			{"time": 0.0, "name": spec.attachment},
			{"time": 12.000001, "name": spec.attachment},
		]}
	var die_slots: Dictionary = animations["die"].get_or_add("slots", {})
	die_slots.erase(OLD_HEAD_SLOT)
	for slot_name: String in [SLOT_BACK_HAIR, SLOT_HEAD_FACE, SLOT_FRONT_HAIR, SLOT_BUTTERFLY]:
		die_slots[slot_name] = {"attachment": [{"time": 0.0, "name": null}]}


func _apply_back_hair_motion(animations: Dictionary) -> void:
	_add_loop_hair_motion(animations["idle_loop"], 2.0, 1.0)
	_add_loop_hair_motion(animations["relaxed_loop"], 12.000001, 0.72)
	_add_loop_hair_motion(animations["low_health_loop"], 1.4666667, 1.35)
	_add_action_hair_motion(animations["attack"], 0.08, 0.84, 8.0, 13.0)
	_add_action_hair_motion(animations["attack_heavy"], 0.12, 1.10, 13.0, 20.0)
	_add_action_hair_motion(animations["cast"], 0.25, 1.22, 7.0, 12.0)
	_add_action_hair_motion(animations["hurt"], 0.14, 0.72, -12.0, -19.0)


func _add_loop_hair_motion(animation: Dictionary, duration: float, strength: float) -> void:
	var bones: Dictionary = animation.get_or_add("bones", {})
	bones[BONE_HAIR_ROOT] = {"rotate": _rotate_loop(duration, 0.0, 0.7 * strength, 0.0, -0.5 * strength)}
	bones[BONE_HAIR_CENTER] = {"rotate": _rotate_loop(duration, 0.0, -1.8 * strength, 0.0, 1.3 * strength)}
	# The base candidate already animates left/right in idle and relaxed. Replace
	# those timelines with a coordinated phase so all three weighted zones close
	# exactly at the loop boundary, including the merchant's random seek path.
	bones[BONE_HAIR_LEFT] = {"rotate": _rotate_loop(duration, 0.0, 3.2 * strength, 0.0, -2.4 * strength)}
	bones[BONE_HAIR_RIGHT] = {"rotate": _rotate_loop(duration, 0.0, -2.8 * strength, 0.0, 2.0 * strength)}


func _add_action_hair_motion(
	animation: Dictionary,
	peak_time: float,
	recover_time: float,
	root_peak: float,
	tip_peak: float,
) -> void:
	var duration := _max_timeline_time(animation)
	var bones: Dictionary = animation.get_or_add("bones", {})
	bones[BONE_HAIR_ROOT] = {"rotate": [
		{"time": 0.0, "value": 0.0},
		{"time": peak_time, "value": root_peak},
		{"time": minf(duration, peak_time + 0.16), "value": -root_peak * 0.35},
		{"time": recover_time, "value": root_peak * 0.12},
		{"time": duration, "value": 0.0},
	]}
	for spec: Dictionary in [
		{"bone": BONE_HAIR_LEFT, "sign": 1.0},
		{"bone": BONE_HAIR_CENTER, "sign": -0.72},
		{"bone": BONE_HAIR_RIGHT, "sign": -0.88},
	]:
		var signed_peak := tip_peak * float(spec.sign)
		bones[spec.bone] = {"rotate": [
			{"time": 0.0, "value": 0.0},
			{"time": minf(duration, peak_time + 0.06), "value": signed_peak},
			{"time": minf(duration, peak_time + 0.24), "value": -signed_peak * 0.42},
			{"time": recover_time, "value": signed_peak * 0.16},
			{"time": duration, "value": 0.0},
		]}


func _build_semantic_atlas_data() -> String:
	var data := _build_split_atlas_data()
	for spec: Dictionary in [
		{"page": BACK_HAIR_PAGE, "region": BACK_HAIR_REGION},
		{"page": HEAD_FACE_PAGE, "region": HEAD_FACE_REGION},
		{"page": FRONT_HAIR_PAGE, "region": FRONT_HAIR_REGION},
		{"page": BUTTERFLY_PAGE, "region": BUTTERFLY_REGION},
	]:
		data += "\n%s\nsize:1024,1024\nfilter:Linear,Linear\npma:false\nrepeat:none\n%s\nbounds:0,0,1024,1024\n" % [
			spec.page, spec.region,
		]
	return data


func _build_semantic_tres() -> String:
	var text := _build_split_tres()
	text = text.replace(SPLIT_MOUNT_ROOT, MOUNT_ROOT)
	text = text.replace(SPLIT_JSON, SEMANTIC_OUTPUT_JSON)
	text = text.replace(SPLIT_ATLAS, SEMANTIC_OUTPUT_ATLAS)
	return text


func _build_semantic_manifest(paths: Dictionary, back_hair: Image, skeleton: Dictionary) -> Dictionary:
	var metrics := _alpha_metrics(back_hair)
	return {
		"schema": 1,
		"name": "semantic_back_hair",
		"status": "offline_vulkan_passed_research_candidate",
		"classification": "one complete single-frame rear-hair attachment; not a spritesheet or atlas",
		"source": BACK_HAIR_SOURCE,
		"source_sha256": FileAccess.get_sha256(str(paths.back_hair)).to_lower(),
		"archive": BACK_HAIR_ARCHIVE,
		"archive_sha256": FileAccess.get_sha256(str(paths.back_hair_archive)).to_lower(),
		"alpha_metrics": metrics,
		"consumer_contract": {
			"combat_scene_scale": 0.28,
			"authored_character_scale": 0.70,
			"merchant_animation": "relaxed_loop",
			"merchant_random_seek": true,
			"merchant_duration": 12.000001,
			"merchant_visibility_reasserted_at": [0.0, 12.000001],
			"draw_order": [
				"semantic_back_hair",
				"part_torso",
				"semantic_head_face_neighbor",
				"semantic_front_hair_neighbor",
				"semantic_butterfly_neighbor",
			],
		},
		"mesh_contract": {
			"type": "weighted_mesh",
			"vertices": HAIR_GRID_COLUMNS * HAIR_GRID_ROWS,
			"triangles": (HAIR_GRID_COLUMNS - 1) * (HAIR_GRID_ROWS - 1) * 2,
			"bones": [BONE_HAIR_ROOT, BONE_HAIR_LEFT, BONE_HAIR_CENTER, BONE_HAIR_RIGHT],
			"crown_max_tail_weight": 0.0,
			"lower_tip_max_tail_weight": 0.72,
		},
		"neighbor_sources_are_validation_only": [HEAD_FACE_SOURCE, FRONT_HAIR_SOURCE, BUTTERFLY_SOURCE],
		"files": [
			SEMANTIC_OUTPUT_JSON, SEMANTIC_OUTPUT_ATLAS, SEMANTIC_OUTPUT_DATA,
			BASE_PAGE, BASE_DEATH_PAGE,
			BACK_HAIR_PAGE, HEAD_FACE_PAGE, FRONT_HAIR_PAGE, BUTTERFLY_PAGE,
			SEMANTIC_OUTPUT_ALPHA_CONTACT, SEMANTIC_OUTPUT_SETUP_CONTACT,
		],
		"bone_count": skeleton["bones"].size(),
		"runtime_skin_modified": false,
		"evolink_paid_calls": 0,
		"alpha_modified": false,
		"offline_vulkan_evidence": {
			"report": ".work/combat-rig-compare-preview/semantic-back-hair-v1/summary.json",
			"driver": "vulkan",
			"candidates": 2,
			"animations_per_candidate": 8,
			"samples_per_animation": 21,
			"semantic_frames": 168,
			"errors": 0,
			"empty_frames": 0,
			"edge_touch_frames": 0,
			"setup_bbox": [220, 326, 220, 367],
			"split_base_setup_bbox": [220, 336, 220, 357],
			"relaxed_loop_closed": true,
			"relaxed_unique_frames": 11,
			"relaxed_max_centroid_px": 4.191,
			"manual_actual_size_review": "No visible crown detachment, head double-image, neck penetration, or triangular mesh fold in setup, relaxed, +20 degree heavy stress, and -19 degree hurt stress samples.",
		},
		"known_limitations": [
			"0044 head-face, 0033 front hair and 0030 butterfly are validation neighbors, not production approvals owned by this component.",
			"The die animation intentionally switches to the existing death-preview head and does not validate this rear-hair mesh during collapse.",
			"Final acceptance still requires the combined semantic head/torso candidate and user game-size review.",
		],
		"next_gate": "Cross-component semantic head/torso integration, then user game-size review; no additional rear-hair generation is justified by current evidence",
	}


func _validate_semantic_in_memory(skeleton: Dictionary, atlas_data: String, back_hair: Image) -> bool:
	if str(skeleton["skeleton"].get("spine", "")) != SPINE_VERSION:
		return _set_error("Semantic candidate must retain Spine %s" % SPINE_VERSION)
	var slots := []
	for slot: Dictionary in skeleton["slots"]:
		slots.append(str(slot.name))
	for name: String in [SLOT_BACK_HAIR, SLOT_HEAD_FACE, SLOT_FRONT_HAIR, SLOT_BUTTERFLY]:
		if name not in slots:
			return _set_error("Missing semantic slot: %s" % name)
	if OLD_HEAD_SLOT in slots:
		return _set_error("Flattened legacy head slot remains in normal setup")
	if not (
		slots.find(SLOT_BACK_HAIR) < slots.find("part_torso")
		and slots.find("part_torso") < slots.find(SLOT_HEAD_FACE)
		and slots.find(SLOT_HEAD_FACE) < slots.find(SLOT_FRONT_HAIR)
		and slots.find(SLOT_FRONT_HAIR) < slots.find(SLOT_BUTTERFLY)
	):
		return _set_error("Semantic head draw order does not match the audited contract")
	var attachments: Dictionary = skeleton["skins"][0]["attachments"]
	var mesh: Dictionary = attachments[SLOT_BACK_HAIR][BACK_HAIR_REGION]
	if str(mesh.get("type", "")) != "mesh":
		return _set_error("Rear hair must be a weighted mesh")
	if mesh["uvs"].size() != HAIR_GRID_COLUMNS * HAIR_GRID_ROWS * 2:
		return _set_error("Rear-hair mesh UV count changed")
	if mesh["triangles"].size() != (HAIR_GRID_COLUMNS - 1) * (HAIR_GRID_ROWS - 1) * 6:
		return _set_error("Rear-hair mesh triangle count changed")
	if FileAccess.get_sha256(_absolute_path(BACK_HAIR_SOURCE)).to_lower() != EXPECTED_BACK_HAIR_SHA256:
		return _set_error("Rear-hair source hash changed during build")
	for region_name: String in [BACK_HAIR_REGION, HEAD_FACE_REGION, FRONT_HAIR_REGION, BUTTERFLY_REGION]:
		if atlas_data.count("%s\n" % region_name) != 1:
			return _set_error("Atlas must declare one %s region" % region_name)
	var metrics := _alpha_metrics(back_hair)
	if int(metrics.edge_max_alpha) != 0:
		return _set_error("0031 has non-zero Alpha on a canvas edge")
	var solid: Array = metrics.bbox_a128
	var visible: Array = metrics.bbox_a16
	if _bbox_expansion(visible, solid) > 4:
		return _set_error("0031 visible Alpha fringe expands more than four pixels beyond its solid core")
	return true


func _alpha_metrics(image: Image) -> Dictionary:
	var thresholds := [1, 16, 64, 128]
	var bounds := {}
	var counts := {}
	for threshold: int in thresholds:
		bounds[threshold] = Rect2i()
		counts[threshold] = 0
	var mins := {}
	var maxs := {}
	for threshold: int in thresholds:
		mins[threshold] = Vector2i(image.get_width(), image.get_height())
		maxs[threshold] = Vector2i(-1, -1)
	var edge_max := 0
	for y in image.get_height():
		for x in image.get_width():
			var alpha := int(round(image.get_pixel(x, y).a * 255.0))
			if x == 0 or y == 0 or x == image.get_width() - 1 or y == image.get_height() - 1:
				edge_max = maxi(edge_max, alpha)
			for threshold: int in thresholds:
				if alpha >= threshold:
					counts[threshold] = int(counts[threshold]) + 1
					mins[threshold] = Vector2i(
						mini((mins[threshold] as Vector2i).x, x),
						mini((mins[threshold] as Vector2i).y, y)
					)
					maxs[threshold] = Vector2i(
						maxi((maxs[threshold] as Vector2i).x, x),
						maxi((maxs[threshold] as Vector2i).y, y)
					)
	var result := {"edge_max_alpha": edge_max}
	for threshold: int in thresholds:
		var minimum: Vector2i = mins[threshold]
		var maximum: Vector2i = maxs[threshold]
		var rect := []
		if maximum.x >= minimum.x:
			rect = [minimum.x, minimum.y, maximum.x - minimum.x + 1, maximum.y - minimum.y + 1]
		result["bbox_a%d" % threshold] = rect
		result["pixels_a%d" % threshold] = counts[threshold]
	return result


func _bbox_expansion(outer: Array, inner: Array) -> int:
	if outer.size() != 4 or inner.size() != 4:
		return 1_000_000
	var outer_right := int(outer[0]) + int(outer[2])
	var inner_right := int(inner[0]) + int(inner[2])
	var outer_bottom := int(outer[1]) + int(outer[3])
	var inner_bottom := int(inner[1]) + int(inner[3])
	return maxi(
		maxi(int(inner[0]) - int(outer[0]), int(inner[1]) - int(outer[1])),
		maxi(outer_right - inner_right, outer_bottom - inner_bottom)
	)


func _copy_bytes(source: String, destination: String) -> bool:
	var input := FileAccess.open(source, FileAccess.READ)
	if input == null:
		return _set_error("Could not read raw page: %s" % source)
	var bytes := input.get_buffer(input.get_length())
	input.close()
	var output := FileAccess.open(destination, FileAccess.WRITE)
	if output == null:
		return _set_error("Could not write raw page: %s" % destination)
	output.store_buffer(bytes)
	output.close()
	if FileAccess.get_sha256(source) != FileAccess.get_sha256(destination):
		return _set_error("Byte-for-byte page copy changed: %s" % destination)
	return true


func _solid_image(size: Vector2i, color: Color) -> Image:
	var image := Image.create(size.x, size.y, false, Image.FORMAT_RGBA8)
	image.fill(color)
	return image


func _source_over(background: Color, layers: Array) -> Image:
	var result := _solid_image(SOURCE_CANVAS, background)
	for layer: Image in layers:
		result.blend_rect(layer, Rect2i(Vector2i.ZERO, layer.get_size()), Vector2i.ZERO)
	return result


func _write_alpha_contact(back_hair: Image, destination: String) -> bool:
	var sheet := Image.create(1536, 512, false, Image.FORMAT_RGBA8)
	for index in 3:
		var background: Color = [Color.BLACK, Color.WHITE, Color("#263849")][index]
		var panel := _source_over(background, [back_hair])
		panel.resize(512, 512, Image.INTERPOLATE_LANCZOS)
		sheet.blit_rect(panel, Rect2i(Vector2i.ZERO, panel.get_size()), Vector2i(index * 512, 0))
	var error := sheet.save_png(destination)
	if error != OK:
		return _set_error("Could not write Alpha contact sheet: %s" % error_string(error))
	return true


func _write_setup_contact(
	back_hair: Image,
	head_face: Image,
	front_hair: Image,
	butterfly: Image,
	destination: String,
) -> bool:
	var butterfly_scaled := butterfly.duplicate()
	var butterfly_size := int(round(1024.0 * BUTTERFLY_WORLD_SIZE / HEAD_CANVAS_SIZE))
	butterfly_scaled.resize(butterfly_size, butterfly_size, Image.INTERPOLATE_LANCZOS)
	var butterfly_world: Vector2 = _bone_world_positions()["vivhite_butterfly"]
	var offset_world := butterfly_world - HEAD_CANVAS_CENTER
	var butterfly_center_px := Vector2(512.0, 512.0) + Vector2(
		offset_world.x * 1024.0 / HEAD_CANVAS_SIZE,
		-offset_world.y * 1024.0 / HEAD_CANVAS_SIZE
	)
	var butterfly_top_left := Vector2i(
		int(round(butterfly_center_px.x - butterfly_size * 0.5)),
		int(round(butterfly_center_px.y - butterfly_size * 0.5))
	)
	var sheet := Image.create(1536, 512, false, Image.FORMAT_RGBA8)
	for index in 3:
		var background: Color = [Color.BLACK, Color.WHITE, Color("#263849")][index]
		var panel := _source_over(background, [back_hair, head_face])
		panel.blend_rect(
			front_hair,
			Rect2i(Vector2i.ZERO, front_hair.get_size()),
			Vector2i(
				int(round(FRONT_HAIR_OFFSET_SOURCE_PX.x)),
				int(round(FRONT_HAIR_OFFSET_SOURCE_PX.y))
			)
		)
		panel.blend_rect(
			butterfly_scaled,
			Rect2i(Vector2i.ZERO, butterfly_scaled.get_size()),
			butterfly_top_left
		)
		panel.resize(512, 512, Image.INTERPOLATE_LANCZOS)
		sheet.blit_rect(panel, Rect2i(Vector2i.ZERO, panel.get_size()), Vector2i(index * 512, 0))
	var error := sheet.save_png(destination)
	if error != OK:
		return _set_error("Could not write setup contact sheet: %s" % error_string(error))
	return true
