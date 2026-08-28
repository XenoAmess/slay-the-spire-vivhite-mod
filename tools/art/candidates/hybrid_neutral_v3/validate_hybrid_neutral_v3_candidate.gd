extends SceneTree

## Read-only static + Spine-runtime contract gate for V3 neutral. It proves the
## selected master remains the untouched EvoLink 0018 PNG, the Hybrid atlas
## uses the complete source-canvas transform, the hierarchical weighted mesh
## is intact, and all three neutral loops recover from dirty person/VFX slots.

const ROOT := "res://tools/candidates/hybrid_neutral_v3"
const UPSTREAM_ROOT := "res://tools/candidates/hybrid_action_set"
const DATA_PATH := ROOT + "/vivhite_combat_skeleton_data.tres"
const JSON_PATH := ROOT + "/vivhite_combat.spjson"
const ATLAS_PATH := ROOT + "/vivhite_combat.spatlas"
const SOURCE_REL := "assets/vivhite-ironclad/custom/combat/sources/vivhite-combat-body-master-v1.png"
const ARCHIVE_REL := "assets/vivhite-ironclad/generated/evolink-paid/2026-08-28/0018-combat-body-master-attempt-01/output.png"
const REQUEST_REL := "assets/vivhite-ironclad/generated/evolink-paid/2026-08-28/0018-combat-body-master-attempt-01/output.request.json"
const EXPECTED_SOURCE_SHA256 := "86ffd64a637d170e213879e72d986b707ee181d4812c8e3fb1eda4abfab98bd1"

const EXPECTED_FILES := [
	"vivhite_combat.png",
	"vivhite_combat.spatlas",
	"vivhite_combat.spjson",
	"vivhite_combat_attack.png",
	"vivhite_combat_attack_heavy.png",
	"vivhite_combat_death.png",
	"vivhite_combat_skeleton_data.tres",
]
const PAGE_SIZES := {
	"vivhite_combat.png": Vector2i(3072, 2304),
	"vivhite_combat_attack.png": Vector2i(2048, 2304),
	"vivhite_combat_attack_heavy.png": Vector2i(2048, 2304),
	"vivhite_combat_death.png": Vector2i(2048, 1536),
}
const BODY_PAGE := ROOT + "/vivhite_combat.png"
const BODY_REGION_RECT := Rect2i(16, 16, 1536, 2272)
const SOURCE_CANVAS := Vector2i(1680, 2512)
const REGION_MARGIN := 18
const BODY_WORLD_SIZE := Vector2(868.0, 1302.0)
const SCENE_SCALE := 0.28
const GRID_COLUMNS := 15
const GRID_ROWS := 23
const BODY_SLOT := "vivhite_body"
const BODY_REGION := "vivhite_combat_body"
const ACTION_SLOT := "vivhite_action_pose"
const ATTACK_REGION := "vivhite_combat_attack_peak"
const DEATH_SLOT := "vivhite_death_body"
const DEATH_REGION := "vivhite_combat_death_side"
const SLASH_SLOT := "slash_mesh"
const SLASH_REGION := "vivhite_combat_magic_arc"
const SIGIL_SLOT := "vivhite_magic_sigil"
const SIGIL_REGION := "vivhite_combat_magic_sigil"
const EYE_SLOT := "eye_attach_slot"
const LOOP_DURATIONS := {
	"idle_loop": 2.0,
	"low_health_loop": 1.4666667,
	"relaxed_loop": 12.000001,
}
const LOOP_RESET_SLOTS := {
	BODY_SLOT: BODY_REGION,
	ACTION_SLOT: null,
	DEATH_SLOT: null,
	SLASH_SLOT: null,
	SIGIL_SLOT: null,
	EYE_SLOT: null,
}
const EXPECTED_PARENT_LINKS := {
	"vivhite_pelvis": "vivhite_rig",
	"vivhite_torso_lower": "vivhite_pelvis",
	"vivhite_torso_upper": "vivhite_torso_lower",
	"vivhite_neck": "vivhite_torso_upper",
	"vivhite_head": "vivhite_neck",
	"vivhite_hair_crown": "vivhite_head",
	"vivhite_hair_left": "vivhite_head",
	"vivhite_hair_right": "vivhite_head",
	"vivhite_butterfly": "vivhite_head",
	"vivhite_shoulder_left": "vivhite_torso_upper",
	"vivhite_upper_arm_left": "vivhite_shoulder_left",
	"vivhite_forearm_left": "vivhite_upper_arm_left",
	"vivhite_hand_left": "vivhite_forearm_left",
	"vivhite_shoulder_right": "vivhite_torso_upper",
	"vivhite_upper_arm_right": "vivhite_shoulder_right",
	"vivhite_forearm_right": "vivhite_upper_arm_right",
	"vivhite_hand_right": "vivhite_forearm_right",
	"vivhite_skirt_left": "vivhite_pelvis",
	"vivhite_skirt_center": "vivhite_pelvis",
	"vivhite_skirt_right": "vivhite_pelvis",
	"vivhite_hip_left": "vivhite_pelvis",
	"vivhite_thigh_left": "vivhite_hip_left",
	"vivhite_shin_left": "vivhite_thigh_left",
	"vivhite_foot_left": "vivhite_shin_left",
	"vivhite_hip_right": "vivhite_pelvis",
	"vivhite_thigh_right": "vivhite_hip_right",
	"vivhite_shin_right": "vivhite_thigh_right",
	"vivhite_foot_right": "vivhite_shin_right",
	"vivhite_action_pose_root": "vivhite_rig",
}
const EPSILON := 0.00002

var _errors: Array[String] = []
var _metrics := {}
var _runtime_samples := 0


func _initialize() -> void:
	_validate_file_set()
	var source_path := _repo_path(SOURCE_REL)
	var archive_path := _repo_path(ARCHIVE_REL)
	var request_path := _repo_path(REQUEST_REL)
	_validate_source_lineage(source_path, archive_path, request_path)
	var skeleton := _load_dictionary(JSON_PATH, "neutral Spine JSON")
	var upstream := _load_dictionary(UPSTREAM_ROOT + "/vivhite_combat.spjson", "frozen Hybrid action-set JSON")
	var atlas := _load_dictionary(ATLAS_PATH, "neutral atlas wrapper")
	if not skeleton.is_empty() and not upstream.is_empty():
		_validate_only_reset_delta(skeleton, upstream)
		_validate_mesh_and_bones(skeleton)
		_validate_loops(skeleton)
	if not atlas.is_empty():
		_validate_atlas(atlas, source_path)
	_validate_runtime()
	_finish()


func _validate_file_set() -> void:
	var files: Array[String] = []
	for file_name: String in DirAccess.get_files_at(ROOT):
		if file_name.ends_with(".uid") or file_name.ends_with(".import"):
			continue
		files.append(file_name)
	files.sort()
	var expected: Array[String] = []
	for file_name: String in EXPECTED_FILES:
		expected.append(file_name)
	expected.sort()
	if files != expected:
		_errors.append("Expected exactly seven authored neutral candidate files, got %s" % files)
	for page_name: String in PAGE_SIZES:
		var path := ROOT + "/" + page_name
		var image := Image.load_from_file(path)
		if image == null or image.is_empty() or image.get_format() != Image.FORMAT_RGBA8:
			_errors.append("Atlas page is not native RGBA8: %s" % page_name)
			continue
		if image.get_size() != PAGE_SIZES[page_name]:
			_errors.append("Atlas page size changed for %s: %s" % [page_name, image.get_size()])
		for corner: Vector2i in [
			Vector2i(0, 0), Vector2i(image.get_width() - 1, 0),
			Vector2i(0, image.get_height() - 1), Vector2i(image.get_width() - 1, image.get_height() - 1),
		]:
			if image.get_pixelv(corner).a8 != 0:
				_errors.append("Atlas page corner is not Alpha 0: %s %s" % [page_name, corner])
		var upstream_path := UPSTREAM_ROOT + "/" + page_name
		if FileAccess.file_exists(upstream_path) and FileAccess.get_sha256(path) != FileAccess.get_sha256(upstream_path):
			_errors.append("Neutral candidate changed inherited atlas pixels: %s" % page_name)


func _validate_source_lineage(source_path: String, archive_path: String, request_path: String) -> void:
	for path: String in [source_path, archive_path, request_path]:
		if not FileAccess.file_exists(path):
			_errors.append("Required neutral lineage file is missing: %s" % path)
	if not _errors.filter(func(message: String) -> bool: return message.contains("lineage file")).is_empty():
		return
	var source_hash := FileAccess.get_sha256(source_path).to_lower()
	var archive_hash := FileAccess.get_sha256(archive_path).to_lower()
	if source_hash != EXPECTED_SOURCE_SHA256 or archive_hash != EXPECTED_SOURCE_SHA256:
		_errors.append("Neutral master is not byte-identical to EvoLink 0018")
	var request := _load_absolute_dictionary(request_path, "0018 sanitized request")
	if (
		str(request.get("endpoint", "")) != "https://api.evolink.ai/v1/images/generations"
		or str(request.get("model", "")) != "gpt-image-2"
		or str(request.get("background", "")) != "transparent"
		or int(request.get("n", 0)) != 1
	):
		_errors.append("0018 request lost the repository-native EvoLink transparent contract")
	var image := Image.load_from_file(source_path)
	if image == null or image.is_empty() or image.get_format() != Image.FORMAT_RGBA8:
		_errors.append("Neutral master must decode directly as RGBA8")
		return
	if image.get_size() != SOURCE_CANVAS:
		_errors.append("Neutral master canvas must remain %s, got %s" % [SOURCE_CANVAS, image.get_size()])
	var alpha := _alpha_metrics(image)
	_metrics["source"] = {
		"archive_byte_identical": source_hash == archive_hash,
		"canvas": [image.get_width(), image.get_height()],
		"corner_alpha": alpha.corner_alpha,
		"edge_alpha_pixels": alpha.edge_alpha_pixels,
		"edge_max_alpha": alpha.edge_max_alpha,
		"sha256": source_hash,
		"thresholds": alpha.thresholds,
	}
	if alpha.corner_alpha != [0, 0, 0, 0]:
		_errors.append("Neutral source corners must all remain Alpha 0")
	# Seven isolated A=1 edge pixels are present in the untouched paid return.
	# Repository policy treats this as a trim/cropping warning, not an automatic
	# visual failure; fail only if a materially visible edge reaches A>=16.
	if int(alpha.edge_max_alpha) >= 16:
		_errors.append("Neutral source has materially visible Alpha on its canvas edge")


func _validate_only_reset_delta(candidate: Dictionary, upstream: Dictionary) -> void:
	var stripped := candidate.duplicate(true)
	stripped["skeleton"]["hash"] = upstream.get("skeleton", {}).get("hash", "")
	for animation_name: String in LOOP_DURATIONS:
		stripped["animations"][animation_name]["slots"] = upstream.get("animations", {}).get(animation_name, {}).get("slots", {}).duplicate(true)
	if not _same_variant(stripped, upstream):
		_errors.append("Neutral candidate changed more than the loop reset delta")


func _validate_mesh_and_bones(skeleton: Dictionary) -> void:
	if str(skeleton.get("skeleton", {}).get("spine", "")) != "4.2.43":
		_errors.append("Neutral candidate must remain Spine 4.2.43")
	var bones: Array = skeleton.get("bones", [])
	if bones.size() != 35:
		_errors.append("Hybrid neutral must retain exactly 35 bones, got %d" % bones.size())
	var bone_names: Array[String] = []
	var named := {}
	for bone: Dictionary in bones:
		var name := str(bone.get("name", ""))
		bone_names.append(name)
		named[name] = bone
	for child: String in EXPECTED_PARENT_LINKS:
		if not named.has(child):
			_errors.append("Neutral hierarchy is missing bone %s" % child)
		elif str(named[child].get("parent", "")) != str(EXPECTED_PARENT_LINKS[child]):
			_errors.append("Neutral hierarchy parent changed for %s" % child)

	var skins: Array = skeleton.get("skins", [])
	if skins.size() != 1 or str(skins[0].get("name", "")) != "default":
		_errors.append("Neutral candidate must expose exactly the default skin")
		return
	var mesh: Dictionary = skins[0].get("attachments", {}).get(BODY_SLOT, {}).get(BODY_REGION, {})
	if str(mesh.get("type", "")) != "mesh" or str(mesh.get("path", "")) != BODY_REGION:
		_errors.append("Neutral body must remain a weighted mesh attachment")
		return
	if not _near(float(mesh.get("width", NAN)), BODY_WORLD_SIZE.x) or not _near(float(mesh.get("height", NAN)), BODY_WORLD_SIZE.y):
		_errors.append("Neutral mesh lost the 70 percent authored world size")
	var vertex_count := GRID_COLUMNS * GRID_ROWS
	if mesh.get("uvs", []).size() != vertex_count * 2:
		_errors.append("Neutral mesh must retain 345 UV vertices")
	if mesh.get("triangles", []).size() != (GRID_COLUMNS - 1) * (GRID_ROWS - 1) * 6:
		_errors.append("Neutral mesh must retain 616 triangles")
	var weight_report := _decode_weights(mesh.get("vertices", []), bones.size(), bone_names)
	_metrics["mesh"] = {
		"authored_world_size": [BODY_WORLD_SIZE.x, BODY_WORLD_SIZE.y],
		"bone_count": bones.size(),
		"scene_scale": SCENE_SCALE,
		"triangle_count": int(mesh.get("triangles", []).size() / 3),
		"vertex_count": vertex_count,
		"weight_report": weight_report,
	}
	if not bool(weight_report.get("passed", false)):
		_errors.append("Neutral weighted vertex stream is invalid: %s" % weight_report)


func _decode_weights(stream: Array, bone_count: int, bone_names: Array[String]) -> Dictionary:
	var cursor := 0
	var decoded := 0
	var min_influences := 99
	var max_influences := 0
	var max_sum_error := 0.0
	var referenced := {}
	var passed := true
	while cursor < stream.size():
		var count := int(stream[cursor])
		cursor += 1
		min_influences = mini(min_influences, count)
		max_influences = maxi(max_influences, count)
		if count < 1 or count > 4:
			passed = false
			break
		var sum := 0.0
		for _index in count:
			if cursor + 3 >= stream.size():
				passed = false
				break
			var bone_index := int(stream[cursor])
			if bone_index < 0 or bone_index >= bone_count:
				passed = false
			else:
				referenced[bone_names[bone_index]] = true
			sum += float(stream[cursor + 3])
			cursor += 4
		if not passed:
			break
		max_sum_error = maxf(max_sum_error, absf(sum - 1.0))
		if absf(sum - 1.0) > 0.00001:
			passed = false
		decoded += 1
	if decoded != GRID_COLUMNS * GRID_ROWS or cursor != stream.size():
		passed = false
	return {
		"decoded_vertices": decoded,
		"max_influences": max_influences,
		"max_weight_sum_error": max_sum_error,
		"min_influences": min_influences,
		"passed": passed,
		"referenced_bone_count": referenced.size(),
	}


func _validate_loops(skeleton: Dictionary) -> void:
	var animations: Dictionary = skeleton.get("animations", {})
	for animation_name: String in LOOP_DURATIONS:
		var animation: Dictionary = animations.get(animation_name, {})
		if animation.is_empty():
			_errors.append("Missing neutral animation %s" % animation_name)
			continue
		var duration := float(LOOP_DURATIONS[animation_name])
		for slot_name: String in LOOP_RESET_SLOTS:
			var keys: Array = animation.get("slots", {}).get(slot_name, {}).get("attachment", [])
			if keys.size() != 2:
				_errors.append("%s must reset %s at both boundaries" % [animation_name, slot_name])
				continue
			var expected_name: Variant = LOOP_RESET_SLOTS[slot_name]
			for index in 2:
				var expected_time := 0.0 if index == 0 else duration
				if not _near(float(keys[index].get("time", -1.0)), expected_time) or keys[index].get("name", "sentinel") != expected_name:
					_errors.append("%s has invalid %s reset at %.7f" % [animation_name, slot_name, expected_time])
		for slot_name: String in [BODY_SLOT, ACTION_SLOT, DEATH_SLOT]:
			var timelines: Dictionary = animation.get("slots", {}).get(slot_name, {})
			for forbidden: String in ["rgba", "rgb", "alpha", "color", "twoColor"]:
				if timelines.has(forbidden):
					_errors.append("%s/%s uses a forbidden full-person crossfade" % [animation_name, slot_name])


func _validate_atlas(wrapper: Dictionary, source_path: String) -> void:
	if str(wrapper.get("source_path", "")) != ROOT + "/vivhite_combat.atlas":
		_errors.append("Neutral atlas wrapper is not candidate-local")
	var atlas_data := str(wrapper.get("atlas_data", ""))
	for required: String in [
		"vivhite_combat.png\n", BODY_REGION + "\n", "bounds:16,16,1536,2272",
	]:
		if not atlas_data.contains(required):
			_errors.append("Neutral atlas lost required declaration: %s" % required.strip_edges())
	var tres := FileAccess.get_file_as_string(DATA_PATH)
	for required_path: String in [ATLAS_PATH, JSON_PATH]:
		if not tres.contains(required_path):
			_errors.append("Neutral skeleton-data wrapper is missing %s" % required_path)

	var source := Image.load_from_file(source_path)
	var page := Image.load_from_file(BODY_PAGE)
	if source == null or page == null or source.is_empty() or page.is_empty():
		return
	var expected := _prepare_fixed_canvas(source)
	var actual := page.get_region(BODY_REGION_RECT)
	var packed_delta := _image_delta(expected, actual)
	if int(packed_delta.alpha_mismatch_pixels) != 0 or int(packed_delta.visible_rgba_mismatch_pixels) != 0:
		_errors.append("Packed neutral region is not the deterministic full-canvas transform of 0018")
	_metrics["packing"] = {
		"contract_rect": [0, 0, SOURCE_CANVAS.x, SOURCE_CANVAS.y],
		"packed_region": [BODY_REGION_RECT.position.x, BODY_REGION_RECT.position.y, BODY_REGION_RECT.size.x, BODY_REGION_RECT.size.y],
		"byte_identical_to_expected": expected.get_data() == actual.get_data(),
		"delta": packed_delta,
	}


func _prepare_fixed_canvas(source: Image) -> Image:
	var result := Image.create(BODY_REGION_RECT.size.x, BODY_REGION_RECT.size.y, false, Image.FORMAT_RGBA8)
	result.fill(Color(0, 0, 0, 0))
	var prepared := source.duplicate()
	var available := BODY_REGION_RECT.size - Vector2i(REGION_MARGIN * 2, REGION_MARGIN * 2)
	var factor := minf(1.0, minf(
		float(available.x) / float(source.get_width()),
		float(available.y) / float(source.get_height())
	))
	var packed_size := Vector2i(
		maxi(1, int(round(source.get_width() * factor))),
		maxi(1, int(round(source.get_height() * factor)))
	)
	if prepared.get_size() != packed_size:
		prepared.resize(packed_size.x, packed_size.y, Image.INTERPOLATE_LANCZOS)
	var destination := Vector2i(
		(BODY_REGION_RECT.size.x - packed_size.x) / 2,
		BODY_REGION_RECT.size.y - REGION_MARGIN - packed_size.y
	)
	result.blend_rect(prepared, Rect2i(Vector2i.ZERO, packed_size), destination)
	# The production builder first composes the registered source into its
	# logical region and then composes that region into the atlas page. Reproduce
	# both deterministic SourceOver steps; the second changes only a few hundred
	# anti-aliased RGB samples while preserving the authored Alpha byte-for-byte.
	var atlas_region := Image.create(BODY_REGION_RECT.size.x, BODY_REGION_RECT.size.y, false, Image.FORMAT_RGBA8)
	atlas_region.fill(Color(0, 0, 0, 0))
	atlas_region.blend_rect(result, Rect2i(Vector2i.ZERO, result.get_size()), Vector2i.ZERO)
	_metrics["packing_transform"] = {
		"destination": [destination.x, destination.y],
		"factor": factor,
		"packed_size": [packed_size.x, packed_size.y],
	}
	return atlas_region


func _image_delta(expected: Image, actual: Image) -> Dictionary:
	if expected.get_size() != actual.get_size():
		return {
			"alpha_mismatch_pixels": -1,
			"transparent_rgb_only_mismatch_pixels": -1,
			"visible_rgba_mismatch_pixels": -1,
		}
	var left := expected.get_data()
	var right := actual.get_data()
	var alpha_mismatch := 0
	var transparent_rgb_only := 0
	var visible_rgba_mismatch := 0
	for pixel_index in expected.get_width() * expected.get_height():
		var offset := pixel_index * 4
		var left_alpha := int(left[offset + 3])
		var right_alpha := int(right[offset + 3])
		if left_alpha != right_alpha:
			alpha_mismatch += 1
		var rgb_differs := (
			left[offset] != right[offset]
			or left[offset + 1] != right[offset + 1]
			or left[offset + 2] != right[offset + 2]
		)
		if rgb_differs:
			if left_alpha == 0 and right_alpha == 0:
				transparent_rgb_only += 1
			else:
				visible_rgba_mismatch += 1
	return {
		"alpha_mismatch_pixels": alpha_mismatch,
		"transparent_rgb_only_mismatch_pixels": transparent_rgb_only,
		"visible_rgba_mismatch_pixels": visible_rgba_mismatch,
	}


func _validate_runtime() -> void:
	for type_name: String in ["SpineSprite", "SpineSkeletonDataResource"]:
		if not ClassDB.class_exists(type_name):
			_errors.append("Game-compatible Spine class is unavailable: %s" % type_name)
	if not _errors.filter(func(message: String) -> bool: return message.contains("Spine class")).is_empty():
		return
	var data: Resource = ResourceLoader.load(DATA_PATH)
	if data == null or not data.is_class("SpineSkeletonDataResource"):
		_errors.append("Spine runtime could not load neutral candidate")
		return
	if str(data.call("get_version")) != "4.2.43":
		_errors.append("Runtime Spine version changed")
	for animation_name: String in LOOP_DURATIONS:
		var duration := float(LOOP_DURATIONS[animation_name])
		for sample_time: float in [0.0, duration * 0.5, duration]:
			_sample_dirty_loop(data, animation_name, sample_time)


func _sample_dirty_loop(data: Resource, animation_name: String, sample_time: float) -> void:
	var sprite: Node2D = ClassDB.instantiate("SpineSprite") as Node2D
	if sprite == null:
		_errors.append("Could not instantiate SpineSprite for %s" % animation_name)
		return
	root.add_child(sprite)
	sprite.set("skeleton_data_res", data)
	var state: Object = sprite.call("get_animation_state")
	var skeleton: Object = sprite.call("get_skeleton")
	if state == null or skeleton == null:
		_errors.append("SpineSprite did not initialize for %s" % animation_name)
		sprite.queue_free()
		return
	_set_slot_attachment(skeleton, BODY_SLOT, null)
	_set_slot_attachment(skeleton, ACTION_SLOT, ATTACK_REGION)
	_set_slot_attachment(skeleton, DEATH_SLOT, DEATH_REGION)
	_set_slot_attachment(skeleton, SLASH_SLOT, SLASH_REGION)
	_set_slot_attachment(skeleton, SIGIL_SLOT, SIGIL_REGION)
	var entry: Object = state.call("set_animation", animation_name, true, 0)
	entry.call("set_track_time", sample_time)
	state.call("update", 0.0)
	state.call("apply", skeleton)
	sprite.call("update_skeleton", 0.0)
	for slot_name: String in LOOP_RESET_SLOTS:
		var actual: Variant = _runtime_attachment_name(skeleton, slot_name)
		if actual != LOOP_RESET_SLOTS[slot_name]:
			_errors.append("Dirty seek %s@%.7f left %s=%s" % [animation_name, sample_time, slot_name, actual])
	_runtime_samples += 1
	sprite.queue_free()


func _set_slot_attachment(skeleton: Object, slot_name: String, attachment_name: Variant) -> void:
	var slot: Variant = skeleton.call("find_slot", slot_name)
	if slot == null:
		_errors.append("Runtime is missing slot %s" % slot_name)
		return
	if attachment_name == null:
		(slot as Object).call("set_attachment", null)
		return
	var attachment: Variant = skeleton.call("get_attachment_by_slot_name", slot_name, attachment_name)
	if attachment == null:
		_errors.append("Runtime cannot resolve %s/%s" % [slot_name, attachment_name])
		return
	(slot as Object).call("set_attachment", attachment)


func _runtime_attachment_name(skeleton: Object, slot_name: String) -> Variant:
	var slot: Variant = skeleton.call("find_slot", slot_name)
	if slot == null:
		return "<missing>"
	var attachment: Variant = (slot as Object).call("get_attachment")
	if attachment == null:
		return null
	return str((attachment as Object).call("get_attachment_name"))


func _alpha_metrics(image: Image) -> Dictionary:
	var width := image.get_width()
	var height := image.get_height()
	var bytes := image.get_data()
	var thresholds := [1, 16, 128, 240]
	var mins := {}
	var maxs := {}
	var counts := {}
	for threshold: int in thresholds:
		mins[threshold] = Vector2i(width, height)
		maxs[threshold] = Vector2i(-1, -1)
		counts[threshold] = 0
	var edge_alpha_pixels := 0
	var edge_max_alpha := 0
	for y in height:
		var row := y * width * 4
		for x in width:
			var alpha := int(bytes[row + x * 4 + 3])
			if alpha > 0 and (x == 0 or y == 0 or x == width - 1 or y == height - 1):
				edge_alpha_pixels += 1
				edge_max_alpha = maxi(edge_max_alpha, alpha)
			for threshold: int in thresholds:
				if alpha < threshold:
					continue
				counts[threshold] = int(counts[threshold]) + 1
				var min_point: Vector2i = mins[threshold]
				var max_point: Vector2i = maxs[threshold]
				mins[threshold] = Vector2i(mini(min_point.x, x), mini(min_point.y, y))
				maxs[threshold] = Vector2i(maxi(max_point.x, x), maxi(max_point.y, y))
	var threshold_report := {}
	for threshold: int in thresholds:
		var min_point: Vector2i = mins[threshold]
		var max_point: Vector2i = maxs[threshold]
		var bbox := []
		if max_point.x >= min_point.x:
			bbox = [min_point.x, min_point.y, max_point.x - min_point.x + 1, max_point.y - min_point.y + 1]
		threshold_report[str(threshold)] = {"bbox": bbox, "pixel_count": counts[threshold]}
	return {
		"corner_alpha": [
			image.get_pixel(0, 0).a8,
			image.get_pixel(width - 1, 0).a8,
			image.get_pixel(0, height - 1).a8,
			image.get_pixel(width - 1, height - 1).a8,
		],
		"edge_alpha_pixels": edge_alpha_pixels,
		"edge_max_alpha": edge_max_alpha,
		"thresholds": threshold_report,
	}


func _repo_path(relative: String) -> String:
	return ProjectSettings.globalize_path("res://").path_join("..").path_join(relative).simplify_path()


func _load_dictionary(path: String, label: String) -> Dictionary:
	if not FileAccess.file_exists(path):
		_errors.append("%s is missing: %s" % [label, path])
		return {}
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(path))
	if not parsed is Dictionary:
		_errors.append("%s is invalid JSON: %s" % [label, path])
		return {}
	return parsed


func _load_absolute_dictionary(path: String, label: String) -> Dictionary:
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(path))
	if not parsed is Dictionary:
		_errors.append("%s is invalid JSON: %s" % [label, path])
		return {}
	return parsed


func _same_variant(left: Variant, right: Variant) -> bool:
	if (left is int or left is float) and (right is int or right is float):
		return _near(float(left), float(right))
	if typeof(left) != typeof(right):
		return false
	if left is Dictionary:
		if left.size() != right.size():
			return false
		for key: Variant in left:
			if not right.has(key) or not _same_variant(left[key], right[key]):
				return false
		return true
	if left is Array:
		if left.size() != right.size():
			return false
		for index in left.size():
			if not _same_variant(left[index], right[index]):
				return false
		return true
	return left == right


func _near(left: float, right: float) -> bool:
	return absf(left - right) <= EPSILON


func _finish() -> void:
	_metrics["runtime_dirty_seek_samples"] = _runtime_samples
	if _errors.is_empty():
		print("[hybrid-neutral-v3] Static, lineage, fixed-canvas, mesh and dirty-seek runtime validation passed")
		print(JSON.stringify(_metrics, "  ", false))
		quit(0)
		return
	for message: String in _errors:
		push_error("[hybrid-neutral-v3] %s" % message)
	print(JSON.stringify(_metrics, "  ", false))
	quit(1)
