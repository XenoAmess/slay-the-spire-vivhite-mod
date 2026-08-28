extends "res://candidates/semantic_split_v3/build_semantic_split_v3_candidate.gd"

const VALIDATE_COMMAND := "validate-semantic-split-v3"


func _initialize() -> void:
	var args := OS.get_cmdline_user_args()
	if args.is_empty():
		args = PackedStringArray([VALIDATE_COMMAND])
	if args[0] in ["-h", "--help", "help"]:
		print("Usage: godot --headless --path tools/art --script res://candidates/semantic_split_v3/validate_semantic_split_v3_candidate.gd -- %s [--output-root PATH]" % VALIDATE_COMMAND)
		quit(0)
		return
	if args[0] != VALIDATE_COMMAND:
		quit(_fail("Unknown command: %s" % args[0]))
		return
	var options := _parse_options(args)
	if options.is_empty() and args.size() > 1:
		quit(2)
		return
	var output_root := _absolute_path(str(options.get("output-root", OUTPUT_ROOT)))
	if not _validate_written(output_root):
		quit(_fail(_last_error))
		return
	quit(0)


func _validate_written(output_root: String) -> bool:
	_last_error = ""
	var required := [
		SEM_OUTPUT_JSON, SEM_OUTPUT_ATLAS, SEM_OUTPUT_DATA, SEM_OUTPUT_MANIFEST, BASE_PAGE,
		DEATH_PAGE, HEAD_PAGE, GRAYBOX_PAGE, FAR_THIGH_PAGE, NEAR_THIGH_PAGE,
	]
	for file_name: String in required:
		if not FileAccess.file_exists(output_root.path_join(file_name)):
			return _set_error("Missing authored candidate file: %s" % file_name)
	if FileAccess.get_sha256(output_root.path_join(HEAD_PAGE)).to_lower() != EXPECTED_HEAD_PAGE_SHA:
		return _set_error("Output head page is not the frozen packed source")
	if FileAccess.get_sha256(output_root.path_join(FAR_THIGH_PAGE)).to_lower() != EXPECTED_FAR_THIGH_SHA:
		return _set_error("Output 0078 page is not byte-identical")
	if FileAccess.get_sha256(output_root.path_join(NEAR_THIGH_PAGE)).to_lower() != EXPECTED_NEAR_THIGH_SHA:
		return _set_error("Output 0083 page is not byte-identical")

	var skeleton_value = JSON.parse_string(FileAccess.get_file_as_string(output_root.path_join(SEM_OUTPUT_JSON)))
	var atlas_value = JSON.parse_string(FileAccess.get_file_as_string(output_root.path_join(SEM_OUTPUT_ATLAS)))
	var manifest_value = JSON.parse_string(FileAccess.get_file_as_string(output_root.path_join(SEM_OUTPUT_MANIFEST)))
	if not skeleton_value is Dictionary or not atlas_value is Dictionary or not manifest_value is Dictionary:
		return _set_error("Could not parse one or more authored JSON files")
	var skeleton: Dictionary = skeleton_value
	var atlas_data := str((atlas_value as Dictionary).get("atlas_data", ""))
	var manifest: Dictionary = manifest_value
	if not _validate_in_memory(skeleton, atlas_data):
		return false
	if bool(manifest.get("deployable", true)):
		return _set_error("Fail-closed manifest must remain deployable=false")
	if str(manifest.get("status", "")) != "fail_closed_cross_component_graybox_not_deployable":
		return _set_error("Unexpected candidate status")
	if not (manifest.get("production_runtime_ready_slots", []) as Array).is_empty():
		return _set_error("No slot may be runtime-production-ready in this graybox")
	if (manifest.get("new_evolink_semantic_generation_required", []) as Array).size() != 13:
		return _set_error("The frozen missing-art list must contain thirteen production attachments")
	if (manifest.get("production_slot_contract", []) as Array).size() != 19:
		return _set_error("The production slot contract must classify all nineteen semantic slots")

	var skin: Dictionary = skeleton["skins"][0]
	var attachments: Dictionary = skin["attachments"]
	for slot_name: String in PART_ATTACHMENTS:
		var expected := str(PART_ATTACHMENTS[slot_name])
		var actual_slot: Dictionary = attachments.get(slot_name, {})
		if expected.is_empty():
			if not actual_slot.is_empty():
				return _set_error("Merged hand/foot slot must remain empty: %s" % slot_name)
		elif not actual_slot.has(expected):
			return _set_error("Slot %s is missing %s" % [slot_name, expected])
	for forbidden_name: String in [
		"vivhite_leg_left_thigh", "vivhite_leg_left_lower", "vivhite_leg_left_foot",
		"vivhite_leg_right_thigh", "vivhite_leg_right_lower", "vivhite_leg_right_foot",
		"vivhite_arm_left_upper", "vivhite_arm_left_forearm", "vivhite_arm_left_hand",
		"vivhite_torso", "vivhite_skirt", "vivhite_arm_right_upper",
		"vivhite_arm_right_forearm", "vivhite_arm_right_hand",
	]:
		if FileAccess.get_file_as_string(output_root.path_join(SEM_OUTPUT_JSON)).contains('"%s"' % forbidden_name):
			return _set_error("Legacy flattened attachment leaked into semantic total: %s" % forbidden_name)

	var slot_names: Array[String] = []
	for slot_value: Variant in skeleton["slots"]:
		slot_names.append(str(slot_value["name"]))
	if not (
		slot_names.find("semantic_back_hair") < slot_names.find("part_torso")
		and slot_names.find("part_skirt") < slot_names.find("part_torso")
		and slot_names.find("semantic_head_face") < slot_names.find("semantic_butterfly")
		and slot_names.find("semantic_butterfly") < slot_names.find("semantic_front_hair")
		and slot_names.find("semantic_front_hair") < slot_names.find("part_arm_right_upper")
	):
		return _set_error("Cross-component draw order drifted")
	if str((atlas_value as Dictionary).get("source_path", "")) != "%s/%s" % [RESOURCE_ROOT, SEM_OUTPUT_ATLAS.replace(".spatlas", ".atlas")]:
		return _set_error("Atlas source_path drifted")
	var report := {
		"schema": 1,
		"status": "static_contract_passed",
		"deployable": false,
		"files_checked": required.size(),
		"animations_checked": REQUIRED_ANIMATIONS.size(),
		"events_checked": SEM_REQUIRED_EVENTS.size(),
		"real_source_pages_byte_identical": true,
		"graybox_proxy_regions": 8,
		"new_semantic_outputs_required": 13,
		"production_slots_classified": 19,
		"butterfly_before_front_hair": true,
		"legacy_flattened_body_attachments_absent": true,
	}
	if not _write_text(output_root.path_join("validation.json"), JSON.stringify(report, "  ", false) + "\n"):
		return false
	print("Validated fail-closed semantic_split_v3 candidate:")
	print("  files: %d" % required.size())
	print("  animations/events: 8/4")
	print("  deployable: false")
	return true
