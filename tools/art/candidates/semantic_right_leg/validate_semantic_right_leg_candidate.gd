extends SceneTree

## Independent static gate for the isolated semantic right-leg research files.

const COMMAND := "validate-semantic-right-leg-candidate"
const OUTPUT_ROOT_REL := "Vivhite/tools/candidates/semantic_right_leg"
const SPLIT_JSON_REL := "assets/vivhite-ironclad/candidates/split_mesh/combat/vivhite_combat_split_mesh.spjson"
const EXPECTED_SOURCE_HASHES := {
	"0018": "86ffd64a637d170e213879e72d986b707ee181d4812c8e3fb1eda4abfab98bd1",
	"0022": "488e74758164dab0702ec6f943e02d23d9561caef29320275f698cb0000e232e",
	"0064": "6e106b1fe7718bab68af2967de5e0ae757d6f58caf0ff60d97959f80a3dd290d",
	"0065": "eeecd4df3054b6dc89db1b0f41b1e0596374b4c2b1f6e5fe64a2f0f4d496c94f",
	"0066": "a14d0caf909f362a852842ab8db3e26d10148b8885d14cd9b583b1aa6e509a9e",
	"0067": "6a4d84c61bb0bbf24486f2c4d1211caa3b89f0b9ce2f7bbf60de2254c28e5277",
	"0068": "2c9c346dad4331fe9a266d901ee2c568505284a80b4d5a8718f7329d9f4de32f",
	"0069": "e45ec010d7231b080b71f9c82053cf54b12af0d5fc7d1a21e419a7e0639f253b",
	"0070": "1605b0590d02b612453128afba2bbeed1b290d2d0e0742ba09e7cf363391cf57",
	"0071": "70ae428b8798704147062e03db5fa5284fddce04d925835f31a53d1889096f60",
	"0083": "f74ec591dbc2718426af1e3e04562cf6ddcae639367c14e5df23e3cbe78714f7",
	"0100": "9035dcf28f251935467db70edeebae481ac8c71fa7531f7fabedc337b6e8a5d2",
}

var _repo_root := ""
var _output_root := ""
var _errors: Array[String] = []


func _initialize() -> void:
	_repo_root = ProjectSettings.globalize_path("res://../..").simplify_path()
	_output_root = _repo_root.path_join(OUTPUT_ROOT_REL)
	var args := OS.get_cmdline_user_args()
	if args.is_empty():
		args = PackedStringArray([COMMAND])
	if args[0] != COMMAND:
		push_error("Unknown command: %s" % args[0])
		quit(2)
		return
	var index := 1
	while index < args.size():
		if args[index] == "--output-root" and index + 1 < args.size():
			_output_root = args[index + 1] if args[index + 1].is_absolute_path() else _repo_root.path_join(args[index + 1])
			index += 2
		else:
			_error("Unknown or incomplete option: %s" % args[index])
			break
	_validate()
	if _errors.is_empty():
		print("Validated semantic right-leg candidate: 12 immutable sources, 5 SourceOver sheets, fixed 7/9/11 order, 3-piece blocked, 2-piece topology recommended.")
		quit(0)
	else:
		for message in _errors:
			push_error("[semantic-right-leg-validator] %s" % message)
		quit(2)


func _validate() -> void:
	var contract_path := _output_root.path_join("candidate.json")
	if not FileAccess.file_exists(contract_path):
		_error("Missing candidate.json")
		return
	var value: Variant = JSON.parse_string(FileAccess.get_file_as_string(contract_path))
	if not value is Dictionary:
		_error("candidate.json is not a JSON object")
		return
	var contract: Dictionary = value
	if int(contract.get("schema", 0)) != 1:
		_error("Unexpected schema")
	if str(contract.get("status", "")) != "research_only_not_publishable":
		_error("Candidate must remain research-only and non-publishable")
	if str(contract.get("classification", "")).contains("runtime sprite") and not str(contract["classification"]).contains("not a runtime sprite"):
		_error("Contact sheets must not be classified as runtime art")

	var source_ids := {}
	for source: Dictionary in contract.get("sources", []):
		var id := str(source.get("id", ""))
		source_ids[id] = true
		var rel_path := str(source.get("path", ""))
		var path := _repo_root.path_join(rel_path)
		if not FileAccess.file_exists(path):
			_error("Missing immutable source %s at %s" % [id, rel_path])
			continue
		var actual_hash := FileAccess.get_sha256(path).to_lower()
		if actual_hash != str(EXPECTED_SOURCE_HASHES.get(id, "")) or actual_hash != str(source.get("sha256", "")):
			_error("Immutable source hash mismatch for %s" % id)
		var alpha: Dictionary = source.get("alpha", {})
		if not bool(alpha.get("corners_zero", false)):
			_error("Source %s lost the four-corner Alpha gate" % id)
	for expected_id: String in EXPECTED_SOURCE_HASHES:
		if not source_ids.has(expected_id):
			_error("candidate.json omitted source %s" % expected_id)

	var output_count := 0
	for output: Dictionary in contract.get("outputs", []):
		var file_name := str(output.get("path", ""))
		var path := _output_root.path_join(file_name)
		if not FileAccess.file_exists(path):
			_error("Missing preview output %s" % file_name)
			continue
		if FileAccess.get_sha256(path).to_lower() != str(output.get("sha256", "")):
			_error("Preview output changed after contract write: %s" % file_name)
		var image := Image.load_from_file(path)
		if image == null or image.is_empty():
			_error("Could not decode preview output %s" % file_name)
			continue
		if not _opaque_corners(image):
			_error("SourceOver preview must have an opaque background: %s" % file_name)
		output_count += 1
	if output_count != 5:
		_error("Expected exactly five diagnostic PNG outputs, got %d" % output_count)

	var consumer: Dictionary = contract.get("consumer_audit", {})
	var indices: Dictionary = consumer.get("normal_slot_indices", {})
	if int(indices.get("part_leg_right_thigh", -1)) != 7 or int(indices.get("part_leg_right_lower", -1)) != 9 or int(indices.get("part_leg_right_foot", -1)) != 11:
		_error("Frozen right-leg draw order is not 7 -> 9 -> 11")
	if int(consumer.get("draw_order_animation_count", -1)) != 0:
		_error("Expected no drawOrder animation")
	_validate_spine_order()

	var axes: Dictionary = contract.get("axis_conflict", {})
	if absf(float(axes.get("builder_hard_coded_degrees", 0.0)) - 57.681201) > 0.01:
		_error("Builder axis audit drifted")
	if absf(float(axes.get("builder_actual_source_0018_visible_degrees", 0.0)) - 68.2) > 0.01:
		_error("0018 axis audit drifted")
	if absf(float(axes.get("selected_new_rig_target_0022_degrees", 0.0)) - 74.2) > 0.01:
		_error("0022 target axis audit drifted")
	if absf(float(axes.get("selected_lower_0100_pca_degrees", 0.0)) - 61.48) > 2.0:
		_error("0100 PCA no longer matches its audited geometry")

	var three_piece: Dictionary = contract.get("three_piece_route", {})
	if str(three_piece.get("result", "")) != "blocked" or three_piece.get("blocking_reasons", []).size() < 3:
		_error("Three-piece route must remain explicitly blocked with evidence")
	var direction: Dictionary = three_piece.get("boot_direction_measurement_0064", {})
	if not bool(direction.get("toe_is_screen_left_of_heel", false)) or not bool(direction.get("target_requires_toe_screen_right_of_heel", false)):
		_error("Right-boot direction block is missing")
	var two_piece: Dictionary = contract.get("two_piece_route", {})
	if str(two_piece.get("result", "")) != "recommended_topology_only" or str(two_piece.get("ankle_dof", "")) != "locked_in_art_attachment":
		_error("Two-piece lower-leg/boot union recommendation is missing")
	if not str(two_piece.get("production_art_required", "")).contains("do not merge 0100 and 0064"):
		_error("Contract must forbid treating the diagnostic composite as runtime art")
	var gates: Dictionary = contract.get("static_gates", {})
	if bool(gates.get("source_pixels_or_alpha_modified", true)):
		_error("Diagnostic may not modify source pixels or Alpha")
	if bool(gates.get("runtime_skin_modified", true)):
		_error("Diagnostic may not modify the runtime skin")
	if int(gates.get("paid_generation_calls", -1)) != 0:
		_error("This research line must make zero paid generation calls")


func _validate_spine_order() -> void:
	var path := _repo_root.path_join(SPLIT_JSON_REL)
	var value: Variant = JSON.parse_string(FileAccess.get_file_as_string(path))
	if not value is Dictionary:
		_error("Could not independently parse split Spine JSON")
		return
	var skeleton: Dictionary = value
	var indices := {}
	var slots: Array = skeleton.get("slots", [])
	for index in range(slots.size()):
		indices[str(slots[index].get("name", ""))] = index
	if int(indices.get("part_leg_right_thigh", -1)) != 7 or int(indices.get("part_leg_right_lower", -1)) != 9 or int(indices.get("part_leg_right_foot", -1)) != 11:
		_error("Independent Spine order check failed")
	for animation_name: String in skeleton.get("animations", {}):
		var animation: Dictionary = skeleton["animations"][animation_name]
		if animation.has("drawOrder") or animation.has("draworder"):
			_error("Independent Spine check found drawOrder in %s" % animation_name)


func _opaque_corners(image: Image) -> bool:
	return (
		image.get_pixel(0, 0).a >= 0.999
		and image.get_pixel(image.get_width() - 1, 0).a >= 0.999
		and image.get_pixel(0, image.get_height() - 1).a >= 0.999
		and image.get_pixel(image.get_width() - 1, image.get_height() - 1).a >= 0.999
	)


func _error(message: String) -> void:
	_errors.append(message)
