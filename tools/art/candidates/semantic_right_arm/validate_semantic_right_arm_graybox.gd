extends SceneTree

## Static and kinematic gate for the isolated semantic near-arm consumer.
## It validates hashes, naming, pivots, hierarchy, split granularity, draw order,
## hidden-overlap budgets, and every authored motion extreme without loading or
## changing the game/runtime skin.

const COMMAND := "validate-semantic-right-arm-graybox"
const OUTPUT_ROOT := "Vivhite/tools/candidates/semantic_right_arm"
const CONTRACT_FILE := "consumer-contract.json"
const SKELETON_FILE := "vivhite_semantic_right_arm_graybox.spjson"
const EXPECTED_MASTER_SHA256 := "86ffd64a637d170e213879e72d986b707ee181d4812c8e3fb1eda4abfab98bd1"
const EXPECTED_VISUAL_SHA256 := "488e74758164dab0702ec6f943e02d23d9561caef29320275f698cb0000e232e"

var _errors: Array[String] = []


func _initialize() -> void:
	var args := OS.get_cmdline_user_args()
	if args.is_empty():
		args = PackedStringArray([COMMAND])
	if args[0] in ["-h", "--help", "help"]:
		print("Usage: godot --headless --path tools/art --script res://candidates/semantic_right_arm/validate_semantic_right_arm_graybox.gd -- %s" % COMMAND)
		quit(0)
		return
	if args[0] != COMMAND:
		push_error("Unknown command: %s" % args[0])
		quit(2)
		return

	var repo_root := ProjectSettings.globalize_path("res://").path_join("../..").simplify_path()
	var output_root := repo_root.path_join(OUTPUT_ROOT)
	var contract := _read_json(output_root.path_join(CONTRACT_FILE))
	var skeleton := _read_json(output_root.path_join(SKELETON_FILE))
	if contract.is_empty() or skeleton.is_empty():
		_finish(repo_root, {})
		return

	_validate_contract(repo_root, output_root, contract)
	_validate_skeleton(contract, skeleton)
	var pose_metrics := _validate_pose_geometry(contract)
	_finish(repo_root, pose_metrics)


func _validate_contract(repo_root: String, output_root: String, contract: Dictionary) -> void:
	if int(contract.get("schema_version", 0)) != 1:
		_errors.append("Contract schema_version must be 1")
	if str(contract.get("status", "")) != "executable-graybox-consumer-no-art":
		_errors.append("Contract status must remain no-art graybox")
	var side: Dictionary = contract.get("side_identity", {})
	if str(side.get("screen_side", "")) != "right" or str(side.get("camera_depth", "")) != "near" or str(side.get("anatomical_side", "")) != "left":
		_errors.append("Side mapping drifted: required screen-right / near / anatomical-left")
	if str(side.get("canonical_id", "")) != "near_screen_right_anatomical_left_arm":
		_errors.append("Canonical ambiguity-free side id is missing")

	var sources: Array = contract.get("evidence_sources", [])
	for source_value: Variant in sources:
		var source: Dictionary = source_value
		var path := repo_root.path_join(str(source.get("path", "")))
		if not FileAccess.file_exists(path):
			_errors.append("Missing evidence source: %s" % source.get("path", ""))
			continue
		var actual := FileAccess.get_sha256(path).to_lower()
		if actual != str(source.get("sha256", "")).to_lower():
			_errors.append("Evidence hash drift: %s" % source.get("path", ""))
	if sources.size() >= 3:
		if str((sources[0] as Dictionary).get("sha256", "")) != EXPECTED_MASTER_SHA256:
			_errors.append("0018 is no longer the frozen pivot authority")
		if str((sources[2] as Dictionary).get("sha256", "")) != EXPECTED_VISUAL_SHA256:
			_errors.append("0022 visual comparison source drifted")

	var availability: Dictionary = contract.get("source_availability", {})
	if availability.get("dedicated_production_upper_arm", "sentinel") != null or availability.get("dedicated_production_forearm_hand", "sentinel") != null:
		_errors.append("No dedicated production arm art exists yet; contract must not claim otherwise")
	if not (availability.get("usable_existing_arm_sources", []) as Array).is_empty():
		_errors.append("Flattened whole-body UV crops cannot be declared usable production arm sources")

	for file_name: String in DirAccess.get_files_at(output_root):
		var extension := file_name.get_extension().to_lower()
		if extension in ["png", "webp", "jpg", "jpeg", "atlas", "spatlas"]:
			_errors.append("No-art graybox directory contains forbidden raster/atlas output: %s" % file_name)

	var attachments: Dictionary = contract.get("attachments", {})
	if not attachments.has("upper_arm") or not attachments.has("forearm_hand") or attachments.size() != 3:
		_errors.append("Semantic group must freeze upper_arm + forearm_hand plus shoulder occluder requirement")
	else:
		var upper: Dictionary = attachments["upper_arm"]
		var forearm: Dictionary = attachments["forearm_hand"]
		if str(upper.get("pivot", "")) != "shoulder_pivot" or str(forearm.get("pivot", "")) != "elbow_pivot":
			_errors.append("Attachment pivots drifted")
		if str(forearm.get("wrist_seam", "")) != "none; hand is continuous with forearm":
			_errors.append("Forearm and hand must remain one continuous attachment")
		if float(upper.get("hidden_shoulder_root_overlap_px", 0.0)) <= 0.0 or float(upper.get("hidden_elbow_extension_px", 0.0)) <= 0.0 or float(forearm.get("hidden_elbow_root_overlap_px", 0.0)) <= 0.0:
			_errors.append("Hidden overlap budgets must be positive")
		var occluder: Dictionary = attachments["shoulder_occluder_requirement"]
		var required_radius := float(upper.get("hidden_shoulder_root_overlap_px", 0.0)) + float(upper.get("joint_cap_radius_px", 0.0))
		if float(occluder.get("minimum_coverage_radius_px", 0.0)) < required_radius:
			_errors.append("Torso shoulder occluder cannot fully hide the upper-arm root connector")


func _validate_skeleton(contract: Dictionary, skeleton: Dictionary) -> void:
	if str(skeleton.get("skeleton", {}).get("spine", "")) != "4.2.43":
		_errors.append("Graybox skeleton must target Spine 4.2.43")
	var skins: Array = skeleton.get("skins", [])
	if skins.size() != 1 or str((skins[0] as Dictionary).get("name", "")) != "default":
		_errors.append("Graybox skeleton must contain one default skin")

	var bones := {}
	for bone_value: Variant in skeleton.get("bones", []):
		var bone: Dictionary = bone_value
		bones[str(bone.get("name", ""))] = bone
	var expected_parents := {
		"near_clavicle_bind": "root",
		"near_upper_arm": "near_clavicle_bind",
		"near_forearm_hand": "near_upper_arm",
		"near_palm_deform": "near_forearm_hand",
		"near_magic_arc_anchor": "near_palm_deform",
	}
	for bone_name: String in expected_parents:
		if not bones.has(bone_name) or str((bones[bone_name] as Dictionary).get("parent", "")) != expected_parents[bone_name]:
			_errors.append("Bone hierarchy mismatch: %s" % bone_name)

	var slots: Array = skeleton.get("slots", [])
	var required_order: Array = contract.get("required_slot_order", [])
	if slots.size() != required_order.size():
		_errors.append("Graybox slot count differs from frozen draw order")
	else:
		for index in range(required_order.size()):
			if str((slots[index] as Dictionary).get("name", "")) != str(required_order[index]):
				_errors.append("Draw order mismatch at slot %d" % index)

	var expected_slot_bones := {
		"near_upper_arm_back": "near_upper_arm",
		"near_shoulder_occluder_reference": "near_clavicle_bind",
		"near_forearm_hand_front": "near_forearm_hand",
		"slash_mesh": "near_magic_arc_anchor",
	}
	for slot_value: Variant in slots:
		var slot: Dictionary = slot_value
		var slot_name := str(slot.get("name", ""))
		if str(slot.get("bone", "")) != str(expected_slot_bones.get(slot_name, "<missing>")):
			_errors.append("Slot is bound to the wrong bone: %s" % slot_name)

	var animations: Dictionary = skeleton.get("animations", {})
	var gates: Array = contract.get("extreme_pose_gates", [])
	if animations.size() != gates.size():
		_errors.append("Graybox skeleton does not contain every extreme gate")
	for gate_value: Variant in gates:
		var gate: Dictionary = gate_value
		var pose_name := str(gate.get("name", ""))
		if not animations.has(pose_name):
			_errors.append("Missing extreme animation: %s" % pose_name)
			continue
		var animation: Dictionary = animations[pose_name]
		var timelines: Dictionary = animation.get("bones", {})
		_validate_terminal_rotation(pose_name, timelines, "near_upper_arm", float(gate["upper_arm_rotation_deg"]))
		_validate_terminal_rotation(pose_name, timelines, "near_forearm_hand", float(gate["forearm_hand_rotation_deg"]))
		_validate_terminal_rotation(pose_name, timelines, "near_palm_deform", float(gate["palm_internal_rotation_deg"]))


func _validate_terminal_rotation(pose_name: String, timelines: Dictionary, bone_name: String, expected: float) -> void:
	var keys: Array = timelines.get(bone_name, {}).get("rotate", [])
	if keys.size() != 2 or absf(float((keys[1] as Dictionary).get("time", -1.0)) - 1.0) > 0.00001 or absf(float((keys[1] as Dictionary).get("value", 9999.0)) - expected) > 0.00001:
		_errors.append("%s/%s terminal rotation drifted" % [pose_name, bone_name])


func _validate_pose_geometry(contract: Dictionary) -> Dictionary:
	var landmarks: Dictionary = contract.get("landmarks", {})
	var shoulder := _pair(landmarks["shoulder_pivot"]["world_units"])
	var elbow_setup := _pair(landmarks["elbow_pivot"]["world_units"])
	var palm_setup := _pair(landmarks["palm_deform_pivot"]["world_units"])
	var arc_setup := _pair(landmarks["magic_arc_anchor"]["world_units"])
	var upper_vector := elbow_setup - shoulder
	var forearm_vector := palm_setup - elbow_setup
	var arc_vector := arc_setup - palm_setup
	if arc_vector.x <= 0.0 or arc_vector.y <= 0.0:
		_errors.append("Magic arc anchor must remain screen-right and above the palm in Spine world space")
	var source_to_world := float(contract["consumer"]["world_rect"][2]) / float(contract["consumer"]["source_size_px"][0])
	var upper: Dictionary = contract["attachments"]["upper_arm"]
	var forearm: Dictionary = contract["attachments"]["forearm_hand"]
	var occluder: Dictionary = contract["attachments"]["shoulder_occluder_requirement"]
	var root_overlap_world := float(upper["hidden_shoulder_root_overlap_px"]) * source_to_world
	var shoulder_cap_world := float(upper["joint_cap_radius_px"]) * source_to_world
	var occluder_world := float(occluder["minimum_coverage_radius_px"]) * source_to_world
	if root_overlap_world + shoulder_cap_world > occluder_world + 0.0001:
		_errors.append("Shoulder root connector escapes its torso occluder")
	if float(upper["hidden_elbow_extension_px"]) <= 0.0:
		_errors.append("Upper arm has no distal elbow overlap")
	if float(upper["hidden_elbow_extension_px"]) > float(forearm["joint_cap_radius_px"]):
		_errors.append("Upper-arm distal tab escapes the foreground forearm-hand elbow cap")
	if float(forearm["hidden_elbow_root_overlap_px"]) < float(forearm["joint_cap_radius_px"]):
		_errors.append("Forearm-hand has insufficient proximal elbow overlap")

	var envelope: Dictionary = contract.get("rotation_envelope_deg", {})
	var rows := []
	for gate_value: Variant in contract.get("extreme_pose_gates", []):
		var gate: Dictionary = gate_value
		var upper_deg := float(gate["upper_arm_rotation_deg"])
		var forearm_deg := float(gate["forearm_hand_rotation_deg"])
		var palm_deg := float(gate["palm_internal_rotation_deg"])
		_validate_envelope(str(gate["name"]), "upper_arm", upper_deg, envelope["upper_arm"])
		_validate_envelope(str(gate["name"]), "forearm_hand", forearm_deg, envelope["forearm_hand"])
		_validate_envelope(str(gate["name"]), "palm_internal", palm_deg, envelope["palm_internal"])

		var elbow := shoulder + upper_vector.rotated(deg_to_rad(upper_deg))
		var palm := elbow + forearm_vector.rotated(deg_to_rad(upper_deg + forearm_deg))
		var arc := palm + arc_vector.rotated(deg_to_rad(upper_deg + forearm_deg + palm_deg))
		if absf(shoulder.distance_to(elbow) - upper_vector.length()) > 0.001:
			_errors.append("%s changes rigid upper-arm length" % gate["name"])
		if absf(elbow.distance_to(palm) - forearm_vector.length()) > 0.001:
			_errors.append("%s changes continuous forearm-hand length" % gate["name"])
		if elbow.distance_to(palm) < shoulder_cap_world * 2.0:
			_errors.append("%s collapses the forearm-hand into the elbow cap" % gate["name"])
		rows.append({
			"name": gate["name"],
			"shoulder": [shoulder.x, shoulder.y],
			"elbow": [elbow.x, elbow.y],
			"palm": [palm.x, palm.y],
			"magic_arc_anchor": [arc.x, arc.y],
			"upper_length": shoulder.distance_to(elbow),
			"forearm_hand_length": elbow.distance_to(palm),
		})
	return {
		"schema_version": 1,
		"candidate": "semantic_right_arm",
		"pose_count": rows.size(),
		"poses": rows,
		"error_count": _errors.size(),
	}


func _validate_envelope(pose_name: String, component: String, value: float, range_value: Variant) -> void:
	var limits: Array = range_value
	if value < float(limits[0]) - 0.0001 or value > float(limits[1]) + 0.0001:
		_errors.append("%s exceeds %s rotation envelope" % [pose_name, component])


func _pair(value: Variant) -> Vector2:
	var pair: Array = value
	return Vector2(float(pair[0]), float(pair[1]))


func _read_json(path: String) -> Dictionary:
	if not FileAccess.file_exists(path):
		_errors.append("Missing authored file: %s" % path)
		return {}
	var value: Variant = JSON.parse_string(FileAccess.get_file_as_string(path))
	if not value is Dictionary:
		_errors.append("Invalid JSON dictionary: %s" % path)
		return {}
	return value


func _finish(repo_root: String, metrics: Dictionary) -> void:
	var work_root := repo_root.path_join(".work/semantic-right-arm")
	DirAccess.make_dir_recursive_absolute(work_root)
	metrics["passed"] = _errors.is_empty()
	metrics["errors"] = _errors
	var file := FileAccess.open(work_root.path_join("validation-summary.json"), FileAccess.WRITE)
	if file != null:
		file.store_string(JSON.stringify(metrics, "  ", false) + "\n")
	if _errors.is_empty():
		print("Semantic near-arm graybox gate passed: 9 poses, 2 attachments, 0 raster assets")
		print("  anatomy: character-left / screen-right / camera-near")
		print("  layering: upper behind torso occluder; forearm+hand in front; slash consumer last")
		quit(0)
		return
	for message: String in _errors:
		push_error(message)
	quit(1)
