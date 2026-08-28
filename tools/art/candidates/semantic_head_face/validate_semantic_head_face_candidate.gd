extends SceneTree

## Static, no-network validator for the isolated semantic head candidates.
## It verifies bloodline, exact atlas packing, draw order, mesh contracts,
## eye-anchor ownership, relaxed-loop phase safety and the death hand-off.

const ROOT := "Vivhite/tools/candidates/semantic_head_face"
const SOURCE_ROOT := "assets/vivhite-ironclad/generated/evolink-paid/2026-08-28"
const VARIANTS := {
	"head0044_rigid": {"head_dir": "0044-split-head-face-attachment-attempt-05", "weighted": false},
	"head0045_rigid": {"head_dir": "0045-split-head-face-attachment-attempt-06", "weighted": false},
	"head0045_weighted": {"head_dir": "0045-split-head-face-attachment-attempt-06", "weighted": true},
}
const SOURCE_DIRS := {
	"back": "0031-split-back-hair-attachment-attempt-01",
	"front": "0033-split-front-hair-attachment-attempt-02",
	"butterfly": "0030-split-butterfly-attachment-attempt-01",
}
const SLOT_ORDER := [
	"semantic_back_hair",
	"part_torso",
	"semantic_head_face",
	"semantic_front_hair",
	"semantic_butterfly",
	"part_arm_right_upper",
]
const HEAD_SLOTS := [
	"semantic_back_hair",
	"semantic_head_face",
	"semantic_front_hair",
	"semantic_butterfly",
]
const HEAD_REGIONS := [
	"semantic_back_hair",
	"semantic_head_face",
	"semantic_front_hair",
	"semantic_butterfly",
]
const OLD_HEAD_SLOTS := ["part_head_front_hair_butterfly", "death_head_front_hair_butterfly"]
const RELAXED_END := 12.000001
const DEATH_SWAP := 1.05
const CONSUMER_CONTRACT := "Vivhite/tools/candidates/semantic_head_face/consumer-contract.json"

var _errors: Array[String] = []


func _initialize() -> void:
	var repo_root := ProjectSettings.globalize_path("res://").path_join("../..").simplify_path()
	var candidate_root := repo_root.path_join(ROOT).simplify_path()
	var source_root := repo_root.path_join(SOURCE_ROOT).simplify_path()
	_validate_consumer_contract(repo_root.path_join(CONSUMER_CONTRACT).simplify_path())
	for slug: String in VARIANTS:
		_validate_variant(candidate_root.path_join(slug), source_root, slug, VARIANTS[slug])
	if not _errors.is_empty():
		for issue: String in _errors:
			push_error(issue)
		quit(1)
		return
	print("Semantic head-face static validation passed:")
	print("  variants: 3")
	print("  source quadrants: 12 byte-exact RGBA copies")
	print("  rendered candidate: back hair -> torso -> head/face -> front hair -> butterfly -> foreground arm")
	print("  integration correction: back hair -> torso -> head/face -> butterfly -> front hair -> foreground arm")
	print("  eye_attach_slot: head-local anchor in all variants")
	print("  relaxed_loop: four head layers explicit at 0 and 12.000001")
	print("  promotion: blocked until full-rig and EyeSlot/EyeFire scene integration")
	quit(0)


func _validate_consumer_contract(path: String) -> void:
	if not FileAccess.file_exists(path):
		_errors.append("Missing semantic head-face consumer contract")
		return
	var contract = JSON.parse_string(FileAccess.get_file_as_string(path))
	if not contract is Dictionary:
		_errors.append("Semantic head-face consumer contract is not valid JSON")
		return
	if str(contract.get("status", "")) != "research_only_blocked_from_runtime":
		_errors.append("Semantic head-face consumer contract lost its runtime block")
	if str(contract.get("preferred_next_gate", "")) != "head0045_weighted":
		_errors.append("Semantic head-face preferred next gate changed without review")
	var distinction: Dictionary = contract.get("evidence_distinction", {})
	if bool(distinction.get("historical_0045_combination_proven", true)):
		_errors.append("Consumer contract falsely treats the old contact image as 0045 evidence")
	var consumer: Dictionary = contract.get("consumer_contract", {})
	var rendered_layer_order: Array = consumer.get("candidate_rendered_layer_order", [])
	if rendered_layer_order != SLOT_ORDER:
		_errors.append("Consumer contract rendered layer order diverges from the candidate skeleton gate")
	var integration_layer_order: Array = consumer.get("integration_layer_order", [])
	var corrected_order := [
		"semantic_back_hair",
		"part_torso",
		"semantic_head_face",
		"semantic_butterfly",
		"semantic_front_hair",
		"part_arm_right_upper",
	]
	if integration_layer_order != corrected_order:
		_errors.append("Consumer contract lost the dedicated butterfly/front-hair integration correction")
	var eye: Dictionary = contract.get("eye_vfx_contract", {})
	if str(eye.get("scene_slot_name", "")) != "eye_attach_slot":
		_errors.append("Consumer contract lost the actual EyeSlot binding")
	if str(eye.get("slot_bone", "")) != "vivhite_eye_anchor" or str(eye.get("anchor_parent", "")) != "vivhite_head":
		_errors.append("Consumer contract lost the head-local eye anchor chain")
	if absf(float(eye.get("cast_event_time", -1.0)) - 0.25) > 0.00001:
		_errors.append("Consumer contract changed cast_eyes_start timing")
	if bool(eye.get("full_scene_eye_fire_composite_tested", true)):
		_errors.append("Consumer contract may not claim an unperformed EyeFire scene composite")
	var vulkan: Dictionary = contract.get("offline_vulkan_evidence", {})
	if str(vulkan.get("rendering_driver", "")).to_lower() != "vulkan":
		_errors.append("Consumer contract lost Vulkan evidence")
	for key: String in ["empty_frames", "edge_touch_frames", "failed_frames"]:
		if int(vulkan.get(key, -1)) != 0:
			_errors.append("Consumer contract records non-zero %s" % key)
	if int(vulkan.get("candidate_count", 0)) != 3 or int(vulkan.get("animations_per_candidate", 0)) != 8 or int(vulkan.get("frames_per_candidate", 0)) != 40:
		_errors.append("Consumer contract Vulkan coverage is incomplete")
	if bool(contract.get("safety", {}).get("deployable", true)):
		_errors.append("Semantic head-face research contract may not be deployable")


func _validate_variant(root: String, source_root: String, slug: String, contract: Dictionary) -> void:
	var required := [
		"semantic_head_face.spjson",
		"semantic_head_face.spatlas",
		"semantic_head_face.png",
		"semantic_head_face_skeleton_data.tres",
		"candidate.json",
		"vivhite_combat_split_mesh.png",
		"vivhite_combat_split_mesh_death.png",
	]
	for file_name: String in required:
		if not FileAccess.file_exists(root.path_join(file_name)):
			_errors.append("%s is missing %s" % [slug, file_name])
	var skeleton = JSON.parse_string(FileAccess.get_file_as_string(root.path_join("semantic_head_face.spjson")))
	var atlas = JSON.parse_string(FileAccess.get_file_as_string(root.path_join("semantic_head_face.spatlas")))
	var manifest = JSON.parse_string(FileAccess.get_file_as_string(root.path_join("candidate.json")))
	if not skeleton is Dictionary or not atlas is Dictionary or not manifest is Dictionary:
		_errors.append("%s has unparsable JSON resources" % slug)
		return
	if str(manifest.get("status", "")) != "research_only_not_publishable":
		_errors.append("%s must remain research-only" % slug)
	if bool(manifest.get("weighted_hair", false)) != bool(contract["weighted"]):
		_errors.append("%s manifest weighted flag does not match its branch" % slug)
	_validate_source_pack(root, source_root, str(contract["head_dir"]), slug)
	_validate_atlas(atlas, slug)
	_validate_skeleton(skeleton, slug, bool(contract["weighted"]))


func _validate_source_pack(root: String, source_root: String, head_dir: String, slug: String) -> void:
	var page := Image.load_from_file(root.path_join("semantic_head_face.png"))
	if page == null or page.is_empty() or page.get_format() != Image.FORMAT_RGBA8 or page.get_size() != Vector2i(2048, 2048):
		_errors.append("%s semantic page must be 2048x2048 native RGBA8" % slug)
		return
	var source_paths := [
		source_root.path_join(str(SOURCE_DIRS["back"])).path_join("output.png"),
		source_root.path_join(head_dir).path_join("output.png"),
		source_root.path_join(str(SOURCE_DIRS["front"])).path_join("output.png"),
		source_root.path_join(str(SOURCE_DIRS["butterfly"])).path_join("output.png"),
	]
	var positions := [Vector2i(0, 0), Vector2i(1024, 0), Vector2i(0, 1024), Vector2i(1024, 1024)]
	for index in source_paths.size():
		var source := Image.load_from_file(source_paths[index])
		if source == null or source.is_empty() or source.get_format() != Image.FORMAT_RGBA8:
			_errors.append("%s source %d is not native RGBA8" % [slug, index])
			continue
		if source.get_size() != Vector2i(1024, 1024):
			_errors.append("%s source %d does not retain 1024x1024 canvas" % [slug, index])
			continue
		for corner: Vector2i in [Vector2i(0, 0), Vector2i(1023, 0), Vector2i(0, 1023), Vector2i(1023, 1023)]:
			if source.get_pixelv(corner).a != 0.0:
				_errors.append("%s source %d has a nontransparent corner" % [slug, index])
		var packed := page.get_region(Rect2i(positions[index], Vector2i(1024, 1024)))
		if packed.get_data() != source.get_data():
			_errors.append("%s packed quadrant %d is not pixel-exact" % [slug, index])


func _validate_atlas(atlas: Dictionary, slug: String) -> void:
	var data := str(atlas.get("atlas_data", ""))
	for page_name: String in ["vivhite_combat_split_mesh.png", "vivhite_combat_split_mesh_death.png", "semantic_head_face.png"]:
		if data.count("%s\n" % page_name) != 1:
			_errors.append("%s atlas must declare page %s once" % [slug, page_name])
	for region_name: String in HEAD_REGIONS:
		if data.count("%s\n" % region_name) != 1:
			_errors.append("%s atlas must declare region %s once" % [slug, region_name])
	if not str(atlas.get("source_path", "")).contains("/%s/semantic_head_face.atlas" % slug):
		_errors.append("%s atlas source_path is not branch-local" % slug)


func _validate_skeleton(skeleton: Dictionary, slug: String, weighted: bool) -> void:
	if str(skeleton.get("skeleton", {}).get("spine", "")) != "4.2.43":
		_errors.append("%s does not retain Spine 4.2.43" % slug)
	var slots: Array = skeleton.get("slots", [])
	var slot_indices := {}
	var slot_bones := {}
	for index in slots.size():
		var slot: Dictionary = slots[index]
		slot_indices[str(slot["name"])] = index
		slot_bones[str(slot["name"])] = str(slot.get("bone", ""))
	for old_slot: String in OLD_HEAD_SLOTS:
		if slot_indices.has(old_slot):
			_errors.append("%s retains legacy combined slot %s" % [slug, old_slot])
	var previous := -1
	for slot_name: String in SLOT_ORDER:
		if not slot_indices.has(slot_name):
			_errors.append("%s is missing ordered slot %s" % [slug, slot_name])
			continue
		if int(slot_indices[slot_name]) <= previous:
			_errors.append("%s draw order breaks at %s" % [slug, slot_name])
		previous = int(slot_indices[slot_name])
	if str(slot_bones.get("eye_attach_slot", "")) != "vivhite_eye_anchor":
		_errors.append("%s eye_attach_slot does not bind vivhite_eye_anchor" % slug)

	var eye_parent := ""
	for bone: Dictionary in skeleton.get("bones", []):
		if str(bone["name"]) == "vivhite_eye_anchor":
			eye_parent = str(bone.get("parent", ""))
	if eye_parent != "vivhite_head":
		_errors.append("%s eye anchor is not head-local" % slug)

	var attachments: Dictionary = skeleton.get("skins", [])[0].get("attachments", {})
	for slot_name: String in HEAD_SLOTS:
		if not attachments.has(slot_name) or not attachments[slot_name].has(slot_name):
			_errors.append("%s has no attachment for %s" % [slug, slot_name])
	var back: Dictionary = attachments.get("semantic_back_hair", {}).get("semantic_back_hair", {})
	var front: Dictionary = attachments.get("semantic_front_hair", {}).get("semantic_front_hair", {})
	if weighted:
		for item: Dictionary in [back, front]:
			if str(item.get("type", "region")) != "mesh":
				_errors.append("%s weighted branch contains a rigid hair layer" % slug)
			elif not _valid_weight_stream(item.get("vertices", []), 25, skeleton.get("bones", []).size()):
				_errors.append("%s has an invalid weighted hair stream" % slug)
	else:
		if str(back.get("type", "region")) != "region" or str(front.get("type", "region")) != "region":
			_errors.append("%s rigid branch contains a mesh hair layer" % slug)
	if str(attachments.get("semantic_head_face", {}).get("semantic_head_face", {}).get("type", "region")) != "region":
		_errors.append("%s head/face is not rigid" % slug)

	var animations: Dictionary = skeleton.get("animations", {})
	for animation_name: String in ["idle_loop", "low_health_loop", "relaxed_loop", "attack", "attack_heavy", "cast", "hurt", "die"]:
		if not animations.has(animation_name):
			_errors.append("%s is missing animation %s" % [slug, animation_name])
	var relaxed_slots: Dictionary = animations.get("relaxed_loop", {}).get("slots", {})
	var die_slots: Dictionary = animations.get("die", {}).get("slots", {})
	for slot_name: String in HEAD_SLOTS:
		var relaxed: Array = relaxed_slots.get(slot_name, {}).get("attachment", [])
		if relaxed.size() != 2 or absf(float(relaxed[0].get("time", -1.0))) > 0.00001 or absf(float(relaxed[1].get("time", -1.0)) - RELAXED_END) > 0.00001:
			_errors.append("%s relaxed_loop is not phase-safe for %s" % [slug, slot_name])
		var die: Array = die_slots.get(slot_name, {}).get("attachment", [])
		if die.size() != 2 or absf(float(die[1].get("time", -1.0)) - DEATH_SWAP) > 0.00001 or die[1].get("name", "sentinel") != null:
			_errors.append("%s die does not atomically detach %s" % [slug, slot_name])
	var relaxed_bones: Dictionary = animations.get("relaxed_loop", {}).get("bones", {})
	for bone_name: String in ["vivhite_hair_left", "vivhite_hair_right", "vivhite_butterfly"]:
		var keys: Array = relaxed_bones.get(bone_name, {}).get("rotate", [])
		if keys.size() < 2 or absf(float(keys[0].get("time", -1.0))) > 0.00001 or absf(float(keys[-1].get("time", -1.0)) - RELAXED_END) > 0.00001:
			_errors.append("%s relaxed_loop does not close %s" % [slug, bone_name])


func _valid_weight_stream(stream: Array, expected_vertices: int, bone_count: int) -> bool:
	var cursor := 0
	var vertices := 0
	while cursor < stream.size():
		var influence_count := int(stream[cursor])
		cursor += 1
		if influence_count <= 0 or cursor + influence_count * 4 > stream.size():
			return false
		var total := 0.0
		for influence_index in influence_count:
			var bone_index := int(stream[cursor])
			var weight := float(stream[cursor + 3])
			if bone_index < 0 or bone_index >= bone_count or weight <= 0.0:
				return false
			total += weight
			cursor += 4
		if absf(total - 1.0) > 0.0001:
			return false
		vertices += 1
	return cursor == stream.size() and vertices == expected_vertices
