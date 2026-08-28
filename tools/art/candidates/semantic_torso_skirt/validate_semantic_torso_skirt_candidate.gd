extends SceneTree

## Fail-closed static/runtime-load gate for the torso/skirt consumer graybox.
## It intentionally passes only when the graybox remains marked non-publishable
## and the frozen next-generation contract still records every known blocker.

const ROOT := "res://tools/candidates/semantic_torso_skirt"
const DATA_PATH := ROOT + "/vivhite_semantic_torso_skirt_skeleton_data.tres"
const JSON_PATH := ROOT + "/vivhite_semantic_torso_skirt.spjson"
const ATLAS_PATH := ROOT + "/vivhite_semantic_torso_skirt.spatlas"
const TORSO_PAGE_PATH := ROOT + "/vivhite_semantic_torso_0054.png"
const CONTEXT_PAGE_PATH := ROOT + "/vivhite_semantic_context_0018.png"
const MANIFEST_PATH := ROOT + "/candidate.json"

const TORSO_SOURCE := (
	"../assets/vivhite-ironclad/generated/evolink-paid/2026-08-28/"
	+ "0054-split-torso-attachment-attempt-07/output.png"
)
const CONTEXT_SOURCE := (
	"../assets/vivhite-ironclad/generated/evolink-paid/2026-08-28/"
	+ "0018-combat-body-master-attempt-01/output.png"
)
const REQUIRED_FILES := [
	"vivhite_semantic_torso_skirt.spjson",
	"vivhite_semantic_torso_skirt.spatlas",
	"vivhite_semantic_torso_skirt_skeleton_data.tres",
	"vivhite_semantic_torso_0054.png",
	"vivhite_semantic_context_0018.png",
	"candidate.json",
]
const EXPECTED_SLOTS := [
	"context_far_upper_arm",
	"context_left_thigh",
	"context_right_thigh",
	"semantic_torso",
	"context_skirt",
	"context_near_upper_arm",
]
const EXPECTED_ANIMATIONS := [
	"setup",
	"max_twist_clockwise",
	"max_twist_counter_clockwise",
]
const REQUIRED_BLOCKER_FRAGMENTS := [
	"bakes both white shoulder caps/sleeves",
	"blue/gold shoulder ornament",
	"proportion mismatch",
	"white lower waist/skirt-like layer",
	"skirt after torso",
]
const EPSILON := 0.001

var _errors: Array[String] = []
var _metrics := {}


func _initialize() -> void:
	_validate_files()
	var skeleton := _load_json(JSON_PATH, "Spine JSON")
	var atlas := _load_json(ATLAS_PATH, "atlas wrapper")
	var manifest := _load_json(MANIFEST_PATH, "candidate manifest")
	if not skeleton.is_empty():
		_validate_skeleton(skeleton)
	if not atlas.is_empty():
		_validate_atlas(atlas)
	if not manifest.is_empty():
		_validate_manifest(manifest)
	_validate_exact_source_copies()
	_validate_runtime_load()
	if not _errors.is_empty():
		for message: String in _errors:
			push_error(message)
		quit(2)
		return
	print("Semantic torso/skirt static gate passed (candidate remains intentionally non-publishable).")
	print(JSON.stringify(_metrics, "  ", false))
	quit(0)


func _validate_files() -> void:
	var existing := []
	for file_name: String in REQUIRED_FILES:
		var path := ROOT + "/" + file_name
		if not FileAccess.file_exists(path):
			_errors.append("Missing authored candidate file: %s" % path)
		else:
			existing.append(file_name)
	_metrics["authored_files"] = existing


func _validate_skeleton(document: Dictionary) -> void:
	if str(document.get("skeleton", {}).get("spine", "")) != "4.2.43":
		_errors.append("Semantic graybox must remain Spine 4.2.43")
	var slot_names := []
	for slot: Dictionary in document.get("slots", []):
		slot_names.append(str(slot.get("name", "")))
	if slot_names != EXPECTED_SLOTS:
		_errors.append("Graybox slot order changed: %s" % slot_names)
	_metrics["slot_order"] = slot_names

	var animations: Dictionary = document.get("animations", {})
	var animation_names := animations.keys()
	animation_names.sort()
	var sorted_expected := EXPECTED_ANIMATIONS.duplicate()
	sorted_expected.sort()
	if animation_names != sorted_expected:
		_errors.append("Graybox animation set changed: %s" % animation_names)
	for animation_name: String in animation_names:
		var animation: Dictionary = animations[animation_name]
		if animation.has("drawOrder") or animation.has("draworder"):
			_errors.append("Graybox must expose the fixed slot order, not conceal it with drawOrder: %s" % animation_name)

	_validate_twist(animations, "max_twist_clockwise", 1.0)
	_validate_twist(animations, "max_twist_counter_clockwise", -1.0)
	var setup: Dictionary = animations.get("setup", {})
	for bone_name: String in ["vivhite_torso_lower", "vivhite_torso_upper", "vivhite_skirt_center"]:
		var keys: Array = setup.get("bones", {}).get(bone_name, {}).get("rotate", [])
		if keys.size() != 2 or not _near(float(keys[1].get("value", 999.0)), 0.0):
			_errors.append("Setup pose does not explicitly keep %s neutral" % bone_name)

	var attachments: Dictionary = {}
	var skins: Array = document.get("skins", [])
	if skins.size() != 1 or str(skins[0].get("name", "")) != "default":
		_errors.append("Graybox must contain exactly one default skin")
	else:
		attachments = skins[0].get("attachments", {})
	var torso: Dictionary = attachments.get("semantic_torso", {}).get("vivhite_semantic_torso_0054", {})
	if torso.get("type", "region") != "region" or str(torso.get("path", "")) != "vivhite_semantic_torso_0054":
		_errors.append("0054 must remain one rigid unmodified region attachment")
	for slot_name: String in [
		"context_far_upper_arm", "context_left_thigh", "context_right_thigh",
		"context_skirt", "context_near_upper_arm",
	]:
		var attachment: Dictionary = attachments.get(slot_name, {}).get(slot_name, {})
		if str(attachment.get("type", "")) != "mesh":
			_errors.append("Context slot %s must remain a UV graybox mesh" % slot_name)
		if str(attachment.get("path", "")) != "vivhite_semantic_context_0018":
			_errors.append("Context slot %s no longer samples the exact 0018 page" % slot_name)


func _validate_twist(animations: Dictionary, animation_name: String, direction: float) -> void:
	var animation: Dictionary = animations.get(animation_name, {})
	var bones: Dictionary = animation.get("bones", {})
	var lower := _last_rotation(bones, "vivhite_torso_lower")
	var upper := _last_rotation(bones, "vivhite_torso_upper")
	var skirt := _last_rotation(bones, "vivhite_skirt_center")
	if not _near(lower, direction * 23.0) or not _near(upper, direction * 23.0):
		_errors.append("%s no longer exercises +/-23 degrees on both torso bones" % animation_name)
	if not _near(absf(lower + upper), 46.0):
		_errors.append("%s no longer reaches the 46-degree torso-to-pelvis gate" % animation_name)
	if not _near(skirt, -direction * 8.0):
		_errors.append("%s no longer counter-swings the skirt by 8 degrees" % animation_name)


func _last_rotation(bones: Dictionary, bone_name: String) -> float:
	var keys: Array = bones.get(bone_name, {}).get("rotate", [])
	if keys.size() != 2:
		_errors.append("Missing two-key rotation for %s" % bone_name)
		return NAN
	if not _near(float(keys[0].get("time", -1.0)), 0.0) or not _near(float(keys[1].get("time", -1.0)), 1.0):
		_errors.append("Rotation for %s must span exactly 0..1 seconds" % bone_name)
	return float(keys[1].get("value", NAN))


func _validate_atlas(wrapper: Dictionary) -> void:
	var atlas_data := str(wrapper.get("atlas_data", ""))
	for fragment: String in [
		"vivhite_semantic_torso_0054.png",
		"size:832,1248",
		"vivhite_semantic_torso_0054",
		"bounds:0,0,832,1248",
		"vivhite_semantic_context_0018.png",
		"size:1680,2512",
		"vivhite_semantic_context_0018",
		"bounds:0,0,1680,2512",
		"pma:false",
	]:
		if not fragment in atlas_data:
			_errors.append("Atlas wrapper is missing contract fragment: %s" % fragment)
	if str(wrapper.get("source_path", "")) != ROOT + "/vivhite_semantic_torso_skirt.atlas":
		_errors.append("Atlas source_path escaped the isolated semantic candidate")


func _validate_manifest(manifest: Dictionary) -> void:
	if str(manifest.get("status", "")) != "contract_frozen_existing_art_rejected_not_publishable":
		_errors.append("Candidate must remain rejected/non-publishable until new semantic art passes")
	var safety: Dictionary = manifest.get("safety", {})
	for key: String in ["source_images_modified", "alpha_threshold_mask_or_cleanup", "runtime_skin_modified", "game_or_stream_touched", "deployable"]:
		if bool(safety.get(key, true)):
			_errors.append("Safety flag must remain false: %s" % key)
	if int(safety.get("evolink_paid_calls", -1)) != 0:
		_errors.append("This audit task must perform zero paid EvoLink calls")
	var verdict: Dictionary = manifest.get("audit_verdict", {})
	if bool(verdict.get("0054_production_eligible", true)):
		_errors.append("0054 may not be promoted by this graybox")
	var blockers_text := JSON.stringify(verdict.get("blocking_findings", []))
	for fragment: String in REQUIRED_BLOCKER_FRAGMENTS:
		if not fragment in blockers_text:
			_errors.append("Manifest lost blocker evidence: %s" % fragment)
	var split_audit: Dictionary = manifest.get("consumer_evidence", {}).get("split_slot_audit", {})
	var slot_indices: Dictionary = split_audit.get("slot_indices", {})
	for pair in [["far_arm", 13], ["torso", 19], ["skirt", 21], ["near_arm", 25]]:
		if int(slot_indices.get(str(pair[0]), -1)) != int(pair[1]):
			_errors.append("Split slot index no longer matches %s=%d" % [pair[0], pair[1]])
	if not (split_audit.get("draw_order_animation_names", []) as Array).is_empty():
		_errors.append("Existing split candidate unexpectedly gained draw-order animation")
	var proposed: Array = manifest.get("recommended_draw_order_back_to_front", [])
	var torso_index := proposed.find("torso_core_with_visible_navy_front_hem")
	for skirt_name: String in ["skirt_back", "skirt_side_far", "skirt_center_front", "skirt_side_near"]:
		if proposed.find(skirt_name) < 0 or proposed.find(skirt_name) > torso_index:
			_errors.append("Recommended layer contract must place %s behind torso front hem" % skirt_name)
	var next_contract: Dictionary = manifest.get("next_generation_consumer_contract", {})
	if bool(next_contract.get("paid_call_performed_by_this_task", true)):
		_errors.append("Manifest incorrectly claims a paid call")
	if not "both white upper-arm sleeves/caps" in str(next_contract.get("torso_core", {}).get("excludes", "")):
		_errors.append("Frozen torso contract no longer excludes baked sleeves")
	if not "four" in str(next_contract.get("skirt", {}).get("attachments", "")):
		# The prose uses one + three; check the semantic output count below instead.
		var semantic_outputs: Array = next_contract.get("semantic_group_outputs", [])
		var skirt_outputs := semantic_outputs.filter(func(value: Variant) -> bool: return str(value).begins_with("skirt_"))
		if skirt_outputs.size() != 4:
			_errors.append("Frozen skirt contract must preserve four coordinated panel attachments")
	_metrics["status"] = manifest.get("status", "")
	_metrics["relative_twist_degrees"] = manifest.get("graybox", {}).get("relative_torso_to_skirt_twist_degrees", null)
	_metrics["chest_waist_audit"] = manifest.get("graybox", {}).get("chest_to_waist_width_audit", {})


func _validate_exact_source_copies() -> void:
	var source_torso := ProjectSettings.globalize_path("res://" + TORSO_SOURCE).simplify_path()
	var source_context := ProjectSettings.globalize_path("res://" + CONTEXT_SOURCE).simplify_path()
	for pair in [[source_torso, TORSO_PAGE_PATH], [source_context, CONTEXT_PAGE_PATH]]:
		var source_path := str(pair[0])
		var page_path := str(pair[1])
		if not FileAccess.file_exists(source_path) or not FileAccess.file_exists(page_path):
			_errors.append("Cannot compare exact source/page copy: %s -> %s" % [source_path, page_path])
			continue
		var source_hash := FileAccess.get_sha256(source_path)
		var page_hash := FileAccess.get_sha256(page_path)
		if source_hash != page_hash:
			_errors.append("Candidate page is not a byte-exact source copy: %s" % page_path)
		var image := Image.load_from_file(ProjectSettings.globalize_path(page_path))
		if image == null or image.is_empty() or image.get_format() != Image.FORMAT_RGBA8:
			_errors.append("Candidate page is not native RGBA8: %s" % page_path)
			continue
		var corners := [
			image.get_pixel(0, 0).a8,
			image.get_pixel(image.get_width() - 1, 0).a8,
			image.get_pixel(0, image.get_height() - 1).a8,
			image.get_pixel(image.get_width() - 1, image.get_height() - 1).a8,
		]
		if corners != [0, 0, 0, 0]:
			_errors.append("Candidate page corners are not zero Alpha: %s" % page_path)


func _validate_runtime_load() -> void:
	var data: Resource = ResourceLoader.load(DATA_PATH)
	if data == null or not data.is_class("SpineSkeletonDataResource"):
		_errors.append("Could not load semantic graybox as SpineSkeletonDataResource")
		return
	if str(data.call("get_version")) != "4.2.43":
		_errors.append("Runtime reports wrong Spine version")
	for animation_name: String in EXPECTED_ANIMATIONS:
		if data.call("find_animation", animation_name) == null:
			_errors.append("Runtime missing graybox animation: %s" % animation_name)
	for slot_name: String in EXPECTED_SLOTS:
		if data.call("find_slot", slot_name) == null:
			_errors.append("Runtime missing graybox slot: %s" % slot_name)
	var sprite := SpineSprite.new()
	sprite.set("skeleton_data_res", data)
	root.add_child(sprite)
	var state: Object = sprite.call("get_animation_state")
	if state == null:
		_errors.append("Spine runtime did not create an animation state")
	else:
		for animation_name: String in EXPECTED_ANIMATIONS:
			state.call("set_animation", animation_name, false, 0)
			sprite.call("update_skeleton", 1.0)
	sprite.queue_free()
	_metrics["runtime_spine_version"] = str(data.call("get_version"))
	_metrics["runtime_slot_count"] = data.call("get_slots").size()


func _load_json(path: String, label: String) -> Dictionary:
	if not FileAccess.file_exists(path):
		_errors.append("Missing %s: %s" % [label, path])
		return {}
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(path))
	if not parsed is Dictionary:
		_errors.append("Invalid %s JSON: %s" % [label, path])
		return {}
	return parsed as Dictionary


func _near(a: float, b: float) -> bool:
	return absf(a - b) <= EPSILON
