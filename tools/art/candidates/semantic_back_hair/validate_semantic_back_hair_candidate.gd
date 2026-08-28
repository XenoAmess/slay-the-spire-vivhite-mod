extends "res://candidates/semantic_back_hair/build_semantic_back_hair_candidate.gd"

## Static, offline gate for the semantic rear-hair research candidate. It reads
## source/candidate bytes only and never writes, deploys, launches the game, or
## calls a model service.

const VALIDATE_COMMAND := "validate-semantic-back-hair-candidate"
const EXPECTED_FILES := [
	"candidate.json",
	"semantic_back_hair.png",
	"semantic_back_hair.spatlas",
	"semantic_back_hair.spjson",
	"semantic_back_hair_alpha_contact.png",
	"semantic_back_hair_setup_contact.png",
	"semantic_back_hair_skeleton_data.tres",
	"semantic_butterfly_neighbor.png",
	"semantic_front_hair_neighbor.png",
	"semantic_head_face_neighbor.png",
	"vivhite_combat_split_mesh.png",
	"vivhite_combat_split_mesh_death.png",
]

var _validation_errors: Array[String] = []


func _initialize() -> void:
	var args := OS.get_cmdline_user_args()
	if args.is_empty():
		args = PackedStringArray([VALIDATE_COMMAND])
	if args[0] in ["-h", "--help", "help"]:
		print("Usage: godot --headless --path tools/art --script res://candidates/semantic_back_hair/validate_semantic_back_hair_candidate.gd -- validate-semantic-back-hair-candidate [--candidate-root PATH]")
		quit(0)
		return
	if args[0] != VALIDATE_COMMAND:
		_validation_errors.append("Unknown command: %s" % args[0])
		_finish()
		return
	var options := _parse_options(args)
	if options.is_empty() and args.size() > 1:
		_validation_errors.append("Invalid command-line options")
		_finish()
		return
	var root := _absolute_path(str(options.get("candidate-root", OUTPUT_ROOT)))
	_validate_written_candidate(root)
	_finish()


func _finish() -> void:
	if not _validation_errors.is_empty():
		printerr("Semantic back-hair validation FAILED (%d issues):" % _validation_errors.size())
		for issue: String in _validation_errors:
			printerr("  - %s" % issue)
		quit(2)
		return
	print("Semantic back-hair validation passed:")
	print("  files: 12 exact authored candidate files")
	print("  source: archived/promoted 0031 byte identity and native RGBA")
	print("  alpha: edge=0; A>=16 fringe <= 1 px from A>=128 core")
	print("  rig: 49 weighted vertices; crown fixed; lower tail weight <= 0.72")
	print("  draw: back hair < torso < face < front hair < butterfly")
	print("  merchant: relaxed_loop 12.000001 s, both boundaries explicit")
	print("  runtime skin modified: false")
	quit(0)


func _validate_written_candidate(root: String) -> void:
	if not DirAccess.dir_exists_absolute(root):
		_validation_errors.append("Candidate root does not exist: %s" % root)
		return
	var actual_files := []
	for name: String in DirAccess.get_files_at(root):
		# Godot editor/import metadata is cache, not an authored candidate file.
		if name.ends_with(".import") or name.ends_with(".uid"):
			continue
		actual_files.append(name)
	actual_files.sort()
	var expected := EXPECTED_FILES.duplicate()
	expected.sort()
	if actual_files != expected:
		_validation_errors.append("Candidate file set changed: expected %s, got %s" % [expected, actual_files])

	var required := {}
	for file_name: String in EXPECTED_FILES:
		var path := root.path_join(file_name)
		required[file_name] = path
		if not FileAccess.file_exists(path):
			_validation_errors.append("Missing candidate file: %s" % path)
	if not _validation_errors.is_empty():
		return

	_validate_byte_copy(BACK_HAIR_SOURCE, str(required[BACK_HAIR_PAGE]), "0031 rear hair")
	_validate_byte_copy(HEAD_FACE_SOURCE, str(required[HEAD_FACE_PAGE]), "0044 head/face neighbor")
	_validate_byte_copy(FRONT_HAIR_SOURCE, str(required[FRONT_HAIR_PAGE]), "0033 front-hair neighbor")
	_validate_byte_copy(BUTTERFLY_SOURCE, str(required[BUTTERFLY_PAGE]), "0030 butterfly neighbor")
	_validate_byte_copy(
		BASE_ROOT.path_join(SPLIT_PAGE),
		str(required[BASE_PAGE]),
		"split base page"
	)
	_validate_byte_copy(
		BASE_ROOT.path_join(SPLIT_DEATH_PAGE),
		str(required[BASE_DEATH_PAGE]),
		"split death page"
	)

	var source_path := _absolute_path(BACK_HAIR_SOURCE)
	var archive_path := _absolute_path(BACK_HAIR_ARCHIVE)
	if FileAccess.get_sha256(source_path).to_lower() != EXPECTED_BACK_HAIR_SHA256:
		_validation_errors.append("Promoted 0031 source hash changed")
	if FileAccess.get_sha256(source_path) != FileAccess.get_sha256(archive_path):
		_validation_errors.append("Promoted 0031 source no longer matches paid archive")

	var skeleton := _read_json(str(required[SEMANTIC_OUTPUT_JSON]), "skeleton")
	var atlas_wrapper := _read_json(str(required[SEMANTIC_OUTPUT_ATLAS]), "atlas wrapper")
	var manifest := _read_json(str(required[SEMANTIC_OUTPUT_MANIFEST]), "candidate manifest")
	if skeleton.is_empty() or atlas_wrapper.is_empty() or manifest.is_empty():
		return
	var atlas_data := str(atlas_wrapper.get("atlas_data", ""))
	var back_hair := Image.load_from_file(str(required[BACK_HAIR_PAGE]))
	if back_hair == null or back_hair.is_empty():
		_validation_errors.append("Could not decode candidate rear-hair page")
		return

	_last_error = ""
	if not _validate_semantic_in_memory(skeleton, atlas_data, back_hair):
		_validation_errors.append(_last_error)
	_validate_manifest(manifest)
	_validate_alpha(back_hair, manifest)
	_validate_mesh(skeleton)
	_validate_animations(skeleton)
	_validate_tres(str(required[SEMANTIC_OUTPUT_DATA]))
	_validate_contact(str(required[SEMANTIC_OUTPUT_ALPHA_CONTACT]), Vector2i(1536, 512), "Alpha contact")
	_validate_contact(str(required[SEMANTIC_OUTPUT_SETUP_CONTACT]), Vector2i(1536, 512), "setup contact")
	_validate_merchant_consumer()


func _validate_byte_copy(source_relative: String, candidate: String, label: String) -> void:
	var source := _absolute_path(source_relative)
	if not FileAccess.file_exists(source):
		_validation_errors.append("Missing %s source: %s" % [label, source])
		return
	if FileAccess.get_sha256(source) != FileAccess.get_sha256(candidate):
		_validation_errors.append("%s candidate page is not a byte-for-byte copy" % label)


func _read_json(path: String, label: String) -> Dictionary:
	var text := FileAccess.get_file_as_string(path)
	var parsed = JSON.parse_string(text)
	if not parsed is Dictionary:
		_validation_errors.append("Invalid %s JSON: %s" % [label, path])
		return {}
	return parsed


func _validate_manifest(manifest: Dictionary) -> void:
	if str(manifest.get("status", "")) != "offline_vulkan_passed_research_candidate":
		_validation_errors.append("Manifest must not claim production/runtime status")
	if bool(manifest.get("runtime_skin_modified", true)):
		_validation_errors.append("Manifest incorrectly claims runtime skin mutation")
	if int(manifest.get("evolink_paid_calls", -1)) != 0:
		_validation_errors.append("This offline study must make zero paid calls")
	if bool(manifest.get("alpha_modified", true)):
		_validation_errors.append("Rear-hair Alpha must remain model-authored")
	if str(manifest.get("source_sha256", "")) != EXPECTED_BACK_HAIR_SHA256:
		_validation_errors.append("Manifest source hash does not match archived 0031")
	var contract: Dictionary = manifest.get("consumer_contract", {})
	if absf(float(contract.get("combat_scene_scale", 0.0)) - 0.28) > 0.00001:
		_validation_errors.append("Scene scale contract changed")
	if not bool(contract.get("merchant_random_seek", false)):
		_validation_errors.append("Manifest lost merchant random-seek consumer fact")
	var vulkan: Dictionary = manifest.get("offline_vulkan_evidence", {})
	for key: String in ["errors", "empty_frames", "edge_touch_frames"]:
		if int(vulkan.get(key, -1)) != 0:
			_validation_errors.append("Vulkan evidence has a non-zero %s count" % key)
	if int(vulkan.get("semantic_frames", 0)) != 168:
		_validation_errors.append("Vulkan evidence must cover 8 animations x 21 frames")
	if not bool(vulkan.get("relaxed_loop_closed", false)):
		_validation_errors.append("Vulkan evidence lost the closed merchant loop result")


func _validate_alpha(image: Image, manifest: Dictionary) -> void:
	if image.get_format() != Image.FORMAT_RGBA8 or image.get_size() != SOURCE_CANVAS:
		_validation_errors.append("0031 candidate page must remain 1024x1024 RGBA8")
		return
	var metrics := _alpha_metrics(image)
	if int(metrics.edge_max_alpha) != 0:
		_validation_errors.append("0031 has non-zero edge Alpha")
	if metrics.bbox_a1 != [113, 3, 827, 965]:
		_validation_errors.append("0031 A>=1 bbox changed: %s" % [metrics.bbox_a1])
	if metrics.bbox_a16 != [127, 50, 761, 798]:
		_validation_errors.append("0031 A>=16 bbox changed: %s" % [metrics.bbox_a16])
	if metrics.bbox_a128 != [127, 51, 761, 796]:
		_validation_errors.append("0031 A>=128 bbox changed: %s" % [metrics.bbox_a128])
	if _bbox_expansion(metrics.bbox_a16, metrics.bbox_a128) > 1:
		_validation_errors.append("0031 visible fringe exceeds one pixel around solid core")
	var recorded: Dictionary = manifest.get("alpha_metrics", {})
	for key: String in [
		"edge_max_alpha",
		"bbox_a1", "pixels_a1",
		"bbox_a16", "pixels_a16",
		"bbox_a64", "pixels_a64",
		"bbox_a128", "pixels_a128",
	]:
		if not _metric_equal(recorded.get(key), metrics.get(key)):
			_validation_errors.append("Manifest Alpha metric is stale: %s" % key)


func _metric_equal(left: Variant, right: Variant) -> bool:
	if left is Array and right is Array:
		if left.size() != right.size():
			return false
		for index in left.size():
			if int(left[index]) != int(right[index]):
				return false
		return true
	if (left is int or left is float) and (right is int or right is float):
		return int(left) == int(right)
	return left == right


func _validate_mesh(skeleton: Dictionary) -> void:
	var bones: Array = skeleton.get("bones", [])
	var indices := _bone_indices(bones)
	for bone_name: String in [BONE_HAIR_ROOT, BONE_HAIR_LEFT, BONE_HAIR_CENTER, BONE_HAIR_RIGHT]:
		if not indices.has(bone_name):
			_validation_errors.append("Missing hair influence bone: %s" % bone_name)
	var attachments: Dictionary = skeleton["skins"][0]["attachments"]
	var mesh: Dictionary = attachments[SLOT_BACK_HAIR][BACK_HAIR_REGION]
	var stream: Array = mesh.get("vertices", [])
	var expected_vertices := HAIR_GRID_COLUMNS * HAIR_GRID_ROWS
	var cursor := 0
	var decoded := 0
	var root_index := int(indices.get(BONE_HAIR_ROOT, -1))
	var allowed_indices := {}
	for bone_name: String in [BONE_HAIR_ROOT, BONE_HAIR_LEFT, BONE_HAIR_CENTER, BONE_HAIR_RIGHT]:
		allowed_indices[int(indices.get(bone_name, -1))] = true
	while cursor < stream.size():
		var influence_count := int(stream[cursor])
		cursor += 1
		if influence_count < 1 or influence_count > 4:
			_validation_errors.append("Hair vertex has %d influences" % influence_count)
			return
		var weight_sum := 0.0
		var root_weight := 0.0
		for _influence in influence_count:
			if cursor + 3 >= stream.size():
				_validation_errors.append("Weighted stream ended mid-vertex")
				return
			var bone_index := int(stream[cursor])
			var weight := float(stream[cursor + 3])
			if not allowed_indices.has(bone_index):
				_validation_errors.append("Hair mesh references a non-hair bone index: %d" % bone_index)
			if bone_index == root_index:
				root_weight = weight
			weight_sum += weight
			cursor += 4
		if absf(weight_sum - 1.0) > 0.00001:
			_validation_errors.append("Hair vertex weights sum to %.7f" % weight_sum)
		if decoded < HAIR_GRID_COLUMNS and absf(root_weight - 1.0) > 0.00001:
			_validation_errors.append("Crown hull vertex %d is not fixed to the hair root" % decoded)
		if root_weight < 0.27999:
			_validation_errors.append("Lower hair tail weight exceeds 0.72 at vertex %d" % decoded)
		decoded += 1
	if decoded != expected_vertices:
		_validation_errors.append("Expected %d hair vertices, decoded %d" % [expected_vertices, decoded])


func _validate_animations(skeleton: Dictionary) -> void:
	var animations: Dictionary = skeleton.get("animations", {})
	if animations.size() != ANIMATION_DURATIONS.size():
		_validation_errors.append("Candidate must retain exactly eight gameplay animations")
	for animation_name: String in ANIMATION_DURATIONS:
		if not animations.has(animation_name):
			_validation_errors.append("Missing animation: %s" % animation_name)
			continue
		var duration := _max_timeline_time(animations[animation_name])
		if absf(duration - float(ANIMATION_DURATIONS[animation_name])) > 0.00001:
			_validation_errors.append("Animation %s duration changed to %.7f" % [animation_name, duration])

	var relaxed: Dictionary = animations.get("relaxed_loop", {})
	var relaxed_slots: Dictionary = relaxed.get("slots", {})
	for spec: Dictionary in [
		{"slot": SLOT_BACK_HAIR, "attachment": BACK_HAIR_REGION},
		{"slot": SLOT_HEAD_FACE, "attachment": HEAD_FACE_REGION},
		{"slot": SLOT_FRONT_HAIR, "attachment": FRONT_HAIR_REGION},
		{"slot": SLOT_BUTTERFLY, "attachment": BUTTERFLY_REGION},
	]:
		var keys: Array = relaxed_slots.get(str(spec.slot), {}).get("attachment", [])
		if keys.size() != 2:
			_validation_errors.append("relaxed_loop must reassert %s twice" % spec.slot)
			continue
		for index in 2:
			var expected_time := 0.0 if index == 0 else 12.000001
			if absf(float(keys[index].get("time", -1.0)) - expected_time) > 0.00001:
				_validation_errors.append("relaxed_loop %s boundary time changed" % spec.slot)
			if str(keys[index].get("name", "")) != str(spec.attachment):
				_validation_errors.append("relaxed_loop %s boundary attachment changed" % spec.slot)

	var heavy_rotations := _rotation_values(animations.get("attack_heavy", {}), BONE_HAIR_LEFT)
	var hurt_rotations := _rotation_values(animations.get("hurt", {}), BONE_HAIR_LEFT)
	if heavy_rotations.is_empty() or heavy_rotations.max() < 19.99:
		_validation_errors.append("Heavy attack no longer reaches the +20 degree rear-hair stress pose")
	if hurt_rotations.is_empty() or hurt_rotations.min() > -18.99:
		_validation_errors.append("Hurt no longer reaches the -19 degree rear-hair stress pose")


func _rotation_values(animation: Dictionary, bone_name: String) -> Array:
	var result := []
	for key: Dictionary in animation.get("bones", {}).get(bone_name, {}).get("rotate", []):
		result.append(float(key.get("value", 0.0)))
	return result


func _validate_tres(path: String) -> void:
	var text := FileAccess.get_file_as_string(path)
	for required: String in [
		"res://tools/candidates/semantic_back_hair/semantic_back_hair.spjson",
		"res://tools/candidates/semantic_back_hair/semantic_back_hair.spatlas",
		"default_mix = 0.05",
	]:
		if not text.contains(required):
			_validation_errors.append("Skeleton data resource is missing: %s" % required)
	if text.contains("res://Vivhite/skins/ironclad"):
		_validation_errors.append("Candidate skeleton data references live runtime paths")


func _validate_contact(path: String, expected_size: Vector2i, label: String) -> void:
	var image := Image.load_from_file(path)
	if image == null or image.is_empty():
		_validation_errors.append("Could not decode %s" % label)
		return
	if image.get_format() != Image.FORMAT_RGBA8 or image.get_size() != expected_size:
		_validation_errors.append("%s must be %s RGBA8" % [label, expected_size])


func _validate_merchant_consumer() -> void:
	var scene_path := _absolute_path("Vivhite/Vivhite/skins/ironclad/scenes/merchant.tscn")
	var data_path := _absolute_path("Vivhite/Vivhite/skins/ironclad/spine/merchant/merchant_skeleton_data.tres")
	var scene := FileAccess.get_file_as_string(scene_path)
	var data := FileAccess.get_file_as_string(data_path)
	for required: String in [
		"preview_animation = \"relaxed_loop\"",
		"preview_time = 5.4",
		"scale = Vector2(0.28, 0.28)",
	]:
		if not scene.contains(required):
			_validation_errors.append("Merchant scene lost audited contract: %s" % required)
	for required: String in [
		"res://Vivhite/skins/ironclad/spine/combat/vivhite_combat.spjson",
		"res://Vivhite/skins/ironclad/spine/combat/vivhite_combat.spatlas",
	]:
		if not data.contains(required):
			_validation_errors.append("Merchant no longer reuses combat %s" % required)
