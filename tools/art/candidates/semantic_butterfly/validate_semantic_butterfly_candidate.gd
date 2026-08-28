extends SceneTree

## Headless contract validator for the isolated 0030 butterfly probe. It reads
## pixels and contracts only; it never edits an image or touches the live skin.

const ROOT := "res://tools/candidates/semantic_butterfly"
const JSON_PATH := ROOT + "/semantic_butterfly.spjson"
const ATLAS_PATH := ROOT + "/semantic_butterfly.spatlas"
const DATA_PATH := ROOT + "/semantic_butterfly_skeleton_data.tres"
const ANALYSIS_PATH := ROOT + "/semantic_butterfly_analysis.json"
const BUTTERFLY_PATH := ROOT + "/semantic_butterfly.png"
const ARCHIVE_PATH := "../assets/vivhite-ironclad/generated/evolink-paid/2026-08-28/0030-split-butterfly-attachment-attempt-01/output.png"
const REQUIRED_ANIMATIONS := {
	"idle_loop": 2.0,
	"low_health_loop": 1.4666667,
	"relaxed_loop": 12.000001,
	"attack": 1.1666667,
	"attack_heavy": 1.5333334,
	"cast": 1.5666667,
	"hurt": 1.0,
	"die": 2.3333335,
}
const EXPECTED_SLOT_ORDER := [
	"semantic_back_hair",
	"semantic_head_face",
	"semantic_butterfly_under_front_hair_probe",
	"semantic_front_hair",
	"semantic_butterfly_front",
]

var _errors: Array[String] = []


func _initialize() -> void:
	call_deferred("_run")


func _run() -> void:
	var skeleton = JSON.parse_string(FileAccess.get_file_as_string(JSON_PATH))
	var atlas = JSON.parse_string(FileAccess.get_file_as_string(ATLAS_PATH))
	var analysis = JSON.parse_string(FileAccess.get_file_as_string(ANALYSIS_PATH))
	if not skeleton is Dictionary:
		_errors.append("Spine JSON is unreadable.")
	if not atlas is Dictionary:
		_errors.append("Atlas wrapper is unreadable.")
	if not analysis is Dictionary:
		_errors.append("Analysis manifest is unreadable.")
	if _errors.is_empty():
		_validate_skeleton(skeleton)
		_validate_atlas(atlas)
		_validate_analysis(analysis)
	_validate_files()
	if _errors.is_empty():
		print("[semantic-butterfly] Static contract passed: byte-identical 0030, RGBA/Alpha, pivot, layers, eight consumers, shop random-seek resets, and death detach.")
		quit(0)
		return
	for error: String in _errors:
		push_error(error)
	quit(1)


func _validate_skeleton(skeleton: Dictionary) -> void:
	var header: Dictionary = skeleton.get("skeleton", {})
	if str(header.get("spine", "")) != "4.2.43":
		_errors.append("Spine version is not 4.2.43.")
	var parents := {}
	for bone: Dictionary in skeleton.get("bones", []):
		parents[str(bone.get("name", ""))] = str(bone.get("parent", ""))
	if str(parents.get("vivhite_butterfly", "<missing>")) != "vivhite_head":
		_errors.append("Butterfly bone must be a direct head child.")
	var slot_order := []
	var slot_defaults := {}
	for slot: Dictionary in skeleton.get("slots", []):
		slot_order.append(str(slot.get("name", "")))
		slot_defaults[str(slot.get("name", ""))] = slot.get("attachment", null)
	if slot_order != EXPECTED_SLOT_ORDER:
		_errors.append("Head draw order does not preserve the under/front A/B probe contract: %s" % slot_order)
	if str(slot_defaults.get("semantic_butterfly_under_front_hair_probe", "")) != "semantic_butterfly":
		_errors.append("Preferred under-hair butterfly slot must be visible by default.")
	if slot_defaults.get("semantic_butterfly_front", "sentinel") != null:
		_errors.append("Front-most A/B probe slot must be empty by default.")
	var animations: Dictionary = skeleton.get("animations", {})
	for name: String in REQUIRED_ANIMATIONS:
		if not animations.has(name):
			_errors.append("Missing consumer animation %s." % name)
			continue
		var duration := _animation_duration(animations[name])
		if absf(duration - float(REQUIRED_ANIMATIONS[name])) > 0.00001:
			_errors.append("Animation %s duration %.7f does not match %.7f." % [name, duration, REQUIRED_ANIMATIONS[name]])
	_validate_relaxed(animations.get("relaxed_loop", {}))
	_validate_die(animations.get("die", {}))
	_validate_under_extreme(animations.get("max_negative", {}), "max_negative")
	_validate_under_extreme(animations.get("max_positive", {}), "max_positive")
	_validate_front_extreme(animations.get("max_negative_front", {}), "max_negative_front")
	_validate_front_extreme(animations.get("max_positive_front", {}), "max_positive_front")


func _validate_relaxed(animation: Dictionary) -> void:
	var slots: Dictionary = animation.get("slots", {})
	for name: String in ["semantic_butterfly_under_front_hair_probe", "semantic_butterfly_front"]:
		var keys: Array = slots.get(name, {}).get("attachment", [])
		if keys.size() != 2:
			_errors.append("relaxed_loop must reset %s at both boundaries." % name)
			continue
		if absf(float(keys[0].get("time", -1.0))) > 0.00001 or absf(float(keys[1].get("time", -1.0)) - 12.000001) > 0.00001:
			_errors.append("relaxed_loop reset times are invalid for %s." % name)
	if str(slots.get("semantic_butterfly_under_front_hair_probe", {}).get("attachment", [])[0].get("name", "")) != "semantic_butterfly":
		_errors.append("relaxed_loop must keep the preferred under-hair butterfly visible for arbitrary merchant seeks.")
	if slots.get("semantic_butterfly_front", {}).get("attachment", [])[0].get("name", "sentinel") != null:
		_errors.append("relaxed_loop may never expose the front-most A/B probe slot.")


func _validate_die(animation: Dictionary) -> void:
	var slots: Dictionary = animation.get("slots", {})
	var keys: Array = slots.get("semantic_butterfly_under_front_hair_probe", {}).get("attachment", [])
	if keys.size() != 2:
		_errors.append("die must contain exactly one visible key and one detach key.")
		return
	if str(keys[0].get("name", "")) != "semantic_butterfly" or absf(float(keys[1].get("time", -1.0)) - 1.05) > 0.00001 or keys[1].get("name", "sentinel") != null:
		_errors.append("Butterfly must detach atomically with the side-collapse body at 1.05s.")
	var front_keys: Array = slots.get("semantic_butterfly_front", {}).get("attachment", [])
	if front_keys.size() != 1 or front_keys[0].get("name", "sentinel") != null:
		_errors.append("die may never expose the front-most A/B probe slot.")


func _validate_under_extreme(animation: Dictionary, animation_name: String) -> void:
	var slots: Dictionary = animation.get("slots", {})
	var under_keys: Array = slots.get("semantic_butterfly_under_front_hair_probe", {}).get("attachment", [])
	var front_keys: Array = slots.get("semantic_butterfly_front", {}).get("attachment", [])
	if under_keys.size() != 2 or front_keys.size() != 2:
		_errors.append("%s must reset both A/B slots at both boundaries." % animation_name)
		return
	if str(under_keys[0].get("name", "")) != "semantic_butterfly" or under_keys[1].get("name", null) != "semantic_butterfly":
		_errors.append("%s must keep exactly the under-hair butterfly visible." % animation_name)
	if front_keys[0].get("name", "sentinel") != null or front_keys[1].get("name", "sentinel") != null:
		_errors.append("%s must keep the front-most butterfly hidden." % animation_name)


func _validate_front_extreme(animation: Dictionary, animation_name: String) -> void:
	var slots: Dictionary = animation.get("slots", {})
	var under_keys: Array = slots.get("semantic_butterfly_under_front_hair_probe", {}).get("attachment", [])
	var front_keys: Array = slots.get("semantic_butterfly_front", {}).get("attachment", [])
	if under_keys.size() != 2 or front_keys.size() != 2:
		_errors.append("%s must reset both A/B slots at both boundaries." % animation_name)
		return
	if under_keys[0].get("name", "sentinel") != null or under_keys[1].get("name", "sentinel") != null:
		_errors.append("%s must hide the preferred under-hair butterfly." % animation_name)
	if str(front_keys[0].get("name", "")) != "semantic_butterfly" or front_keys[1].get("name", null) != "semantic_butterfly":
		_errors.append("%s must keep exactly the front-most A/B butterfly visible." % animation_name)


func _validate_atlas(wrapper: Dictionary) -> void:
	var data := str(wrapper.get("atlas_data", ""))
	for page: String in ["semantic_back_hair.png", "semantic_head_face.png", "semantic_front_hair.png", "semantic_butterfly.png"]:
		if data.count(page + "\n") != 1:
			_errors.append("Atlas must declare exactly one %s page." % page)
	for region: String in ["semantic_back_hair", "semantic_head_face", "semantic_front_hair", "semantic_butterfly"]:
		if data.count(region + "\n") != 1:
			_errors.append("Atlas must declare exactly one %s region." % region)


func _validate_analysis(analysis: Dictionary) -> void:
	if str(analysis.get("status", "")) != "isolated_graybox_not_runtime" or bool(analysis.get("deployable", true)):
		_errors.append("Probe status must remain isolated and non-deployable.")
	if bool(analysis.get("alpha_modified", true)) or int(analysis.get("evolink_paid_calls", -1)) != 0:
		_errors.append("Probe must report zero paid calls and no Alpha modification.")
	var alpha: Dictionary = analysis.get("alpha", {})
	var corners: Array = alpha.get("corner_alpha", [])
	var transparent_corners := corners.size() == 4
	for value: Variant in corners:
		transparent_corners = transparent_corners and int(value) == 0
	if not transparent_corners or int(alpha.get("edge_nonzero_count", -1)) != 0:
		_errors.append("0030 Alpha must have four transparent corners and no edge contact.")
	if int(alpha.get("pivot_alpha", 0)) < 128:
		_errors.append("Butterfly pivot is outside the solid connector core.")
	if int(alpha.get("connected_components_a_ge_16", 0)) != 1:
		_errors.append("Butterfly must be one connected A>=16 object.")


func _validate_files() -> void:
	for path: String in [JSON_PATH, ATLAS_PATH, DATA_PATH, ANALYSIS_PATH, BUTTERFLY_PATH, ROOT + "/semantic_butterfly_sourceover_triptych.png", ROOT + "/semantic_butterfly_setup_layer_probe.png"]:
		if not FileAccess.file_exists(path):
			_errors.append("Missing candidate file %s." % path)
	var archive_absolute := ProjectSettings.globalize_path("res://").path_join(ARCHIVE_PATH).simplify_path()
	if FileAccess.file_exists(BUTTERFLY_PATH) and FileAccess.file_exists(archive_absolute):
		if FileAccess.get_sha256(BUTTERFLY_PATH) != FileAccess.get_sha256(archive_absolute):
			_errors.append("Candidate butterfly page is not byte-identical to archived 0030.")
	else:
		_errors.append("Could not locate both candidate and archived 0030 pages.")


func _animation_duration(animation: Dictionary) -> float:
	var maximum := 0.0
	for section_name: String in ["bones", "slots"]:
		for target: Dictionary in animation.get(section_name, {}).values():
			for timeline: Array in target.values():
				for key: Dictionary in timeline:
					maximum = maxf(maximum, float(key.get("time", 0.0)))
	return maximum
