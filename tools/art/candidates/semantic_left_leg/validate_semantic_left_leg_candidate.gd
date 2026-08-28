extends SceneTree

## Static gate for the isolated semantic left-leg research candidate. A passing
## exit code means the audit evidence is complete and internally consistent;
## it deliberately does not mean these three source parts are publishable.

const OUTPUT_RELATIVE := "Vivhite/tools/candidates/semantic_left_leg"
const CANVAS := Vector2i(1200, 1000)
const EXPECTED_POSES := [
	"legacy_uv_setup",
	"setup",
	"max_knee_flex",
	"max_ankle_flex",
	"combined_death_extreme",
]
const EXPECTED_SOURCE_HASHES := {
	"assets/vivhite-ironclad/generated/evolink-paid/2026-08-28/0078-split-leg-left-thigh-attachment-attempt-07/output.png": "da48818eb18918236144a2dd0a186218a9fa1d7c6494ac36075532fadd7b72db",
	"assets/vivhite-ironclad/generated/evolink-paid/2026-08-28/0088-split-leg-left-lower-attachment-attempt-01/output.png": "70b1d86a47279484e23f82f701dceb9a1ae88a1e8f66fbafd60a60f3091ee0ca",
	"assets/vivhite-ironclad/generated/evolink-paid/2026-08-28/0063-split-leg-left-boot-attachment-attempt-08/output.png": "fd8dd7c3fc9380f540a690421b81ca6a76363407214a80586af63de58a75bf54",
}
const BACKGROUND_COLORS := {
	"black": Color("10141d"),
	"white": Color("f2f4f7"),
	"bluegray": Color("2d3f4b"),
}

var _repo_root := ""
var _output_root := ""
var _errors: Array[String] = []


func _initialize() -> void:
	_repo_root = ProjectSettings.globalize_path("res://").path_join("../..").simplify_path()
	_output_root = _repo_root.path_join(OUTPUT_RELATIVE).simplify_path()
	var report := _validate()
	if not _write_json(_output_root.path_join("validation.json"), report):
		quit(2)
		return
	if not _errors.is_empty():
		for error_message: String in _errors:
			printerr("semantic-left-leg gate: %s" % error_message)
		quit(2)
		return
	print("Semantic left-leg research gate passed.")
	print("  poses: %d; RGBA/background/contact-sheet artifacts verified" % EXPECTED_POSES.size())
	print("  production gate: intentionally false (three-piece seam/pivot evidence)")
	print("  decision: keep knee; merge lower stocking + boot; remove separate ankle attachment")
	quit(0)


func _validate() -> Dictionary:
	var manifest_path := _output_root.path_join("candidate.json")
	var manifest := _read_json(manifest_path)
	if manifest.is_empty():
		_fail("Missing or invalid candidate.json")
		return _report(false, {})
	if int(manifest.get("schema_version", 0)) != 1:
		_fail("Unexpected candidate schema version")
	if str(manifest.get("candidate", "")) != "semantic_left_leg":
		_fail("Unexpected candidate id")
	if str(manifest.get("status", "")).find("not runtime") < 0:
		_fail("Research-only status must be explicit")
	var canvas: Array = manifest.get("canvas", [])
	if canvas.size() != 2 or int(canvas[0]) != CANVAS.x or int(canvas[1]) != CANVAS.y:
		_fail("Canvas contract changed")

	var sources: Dictionary = manifest.get("sources", {})
	for source_path: String in EXPECTED_SOURCE_HASHES:
		if not sources.has(source_path):
			_fail("Manifest is missing source %s" % source_path)
			continue
		var manifest_hash := str(sources[source_path].get("sha256", ""))
		if manifest_hash != EXPECTED_SOURCE_HASHES[source_path]:
			_fail("Manifest source hash mismatch for %s" % source_path)
		var absolute_source := _repo_root.path_join(source_path)
		if not FileAccess.file_exists(absolute_source):
			_fail("Source disappeared: %s" % source_path)
		elif FileAccess.get_sha256(absolute_source).to_lower() != EXPECTED_SOURCE_HASHES[source_path]:
			_fail("Source bytes changed: %s" % source_path)
		var alpha: Dictionary = sources[source_path].get("alpha", {})
		if int(alpha.get("alpha_128_count", 0)) <= 0:
			_fail("Source has no opaque physical core: %s" % source_path)
		if int(alpha.get("edge_alpha_1_count", -1)) != 0:
			_fail("Source Alpha touches canvas edge: %s" % source_path)

	var consumer: Dictionary = manifest.get("consumer_contract", {})
	if not bool(consumer.get("runtime_body_equals_0018", false)):
		_fail("Runtime/source truth no longer proves 0018 identity")
	if bool(consumer.get("has_draw_order_animation", true)):
		_fail("Unexpected drawOrder animation")
	if str(consumer.get("visual_proposal_0022_bind_landmarks", "")).find("absent") < 0:
		_fail("0022's missing consumer landmarks must remain an explicit evidence gap")
	var slot_indices: Dictionary = consumer.get("slot_indices", {})
	if int(slot_indices.get("part_leg_left_thigh", -1)) != 1:
		_fail("Thigh slot index changed")
	if int(slot_indices.get("part_leg_left_lower", -1)) != 3:
		_fail("Lower-leg slot index changed")
	if int(slot_indices.get("part_leg_left_foot", -1)) != 5:
		_fail("Foot slot index changed")
	var extrema: Dictionary = consumer.get("rotation_extrema_degrees", {})
	_validate_extrema(extrema, "vivhite_thigh_left", -8.0, 58.0)
	_validate_extrema(extrema, "vivhite_knee_left", -88.0, 0.0)
	_validate_extrema(extrema, "vivhite_ankle_left", 0.0, 21.0)
	var fit: Dictionary = manifest.get("fit_metrics", {})
	if absf(float(fit.get("source_0078_vs_builder_degrees", INF))) > 6.0:
		_fail("0078 no longer fits the 0018/builder thigh axis tolerance")
	if absf(float(fit.get("source_0088_vs_builder_degrees", INF))) > 1.0:
		_fail("0088 no longer fits the 0018/builder lower-leg axis tolerance")
	if absf(float(fit.get("source_0063_vs_legacy_aspect", INF))) > 0.01:
		_fail("0063 no longer matches the old foot UV aspect tolerance")
	if float(fit.get("legacy_to_review_physical_pivot_distance_source_px", 0.0)) < 100.0:
		_fail("Legacy UV and painted cuff pivots must remain explicitly distinguishable")

	var recommendation: Dictionary = manifest.get("production_recommendation", {})
	if recommendation.get("attachments", []) != ["far_thigh", "far_lower_leg_with_boot"]:
		_fail("Production attachment decision changed")
	if recommendation.get("bones", []) != ["far_thigh", "far_knee"]:
		_fail("Production bone decision changed")
	if not bool(recommendation.get("preserve_knee_joint", false)):
		_fail("Knee must remain articulated")
	if not bool(recommendation.get("remove_separate_ankle_attachment", false)):
		_fail("Separate ankle attachment must remain rejected")
	if recommendation.get("layer_order_back_to_front", []) != [
		"far_lower_leg_with_boot", "far_thigh", "near_leg", "skirt",
	]:
		_fail("Recommended far-leg layer order changed")

	var manifest_poses := {}
	for pose_value: Variant in manifest.get("poses", []):
		var pose: Dictionary = pose_value
		manifest_poses[str(pose.get("id", ""))] = pose
	var rgba_hashes := {}
	for pose_id: String in EXPECTED_POSES:
		if not manifest_poses.has(pose_id):
			_fail("Manifest is missing pose %s" % pose_id)
			continue
		var rgba_path := _output_root.path_join("poses/%s_rgba.png" % pose_id)
		var overlay_path := _output_root.path_join("poses/%s_overlay.png" % pose_id)
		var rgba := _load_rgba(rgba_path, CANVAS)
		var overlay := _load_rgba(overlay_path, CANVAS)
		if rgba.is_empty() or overlay.is_empty():
			continue
		var bounds := _alpha_bounds(rgba, 1)
		if bounds.size.x <= 0 or bounds.size.y <= 0:
			_fail("Pose is empty: %s" % pose_id)
		elif _touches_margin(bounds, CANVAS, 4):
			_fail("Pose is clipped or too close to canvas: %s => %s" % [pose_id, bounds])
		rgba_hashes[pose_id] = FileAccess.get_sha256(rgba_path).to_lower()
		for background_name: String in BACKGROUND_COLORS:
			var composite_path := _output_root.path_join(
				"composites/%s_%s.png" % [pose_id, background_name]
			)
			var composite := _load_rgba(composite_path, CANVAS)
			if composite.is_empty():
				continue
			if not _opaque_corners_equal(composite, BACKGROUND_COLORS[background_name]):
				_fail("SourceOver corner/background mismatch: %s/%s" % [pose_id, background_name])
	if rgba_hashes.size() == EXPECTED_POSES.size():
		var unique_hashes := {}
		for pose_id: String in rgba_hashes:
			unique_hashes[rgba_hashes[pose_id]] = true
		if unique_hashes.size() != EXPECTED_POSES.size():
			_fail("All five pose captures must be visually distinct")

	var expected_sheet_size := Vector2i(
		2 * CANVAS.x + 3 * 12,
		3 * CANVAS.y + 4 * 12,
	)
	_load_rgba(_output_root.path_join("contact_sheet_bluegray.png"), expected_sheet_size)
	_load_rgba(_output_root.path_join("contact_sheet_overlay.png"), expected_sheet_size)

	var research_passed := _errors.is_empty()
	return _report(research_passed, {
		"candidate_manifest_sha256": FileAccess.get_sha256(manifest_path).to_lower(),
		"pose_rgba_sha256": rgba_hashes,
		"verified_pose_count": rgba_hashes.size(),
	})


func _report(research_passed: bool, evidence: Dictionary) -> Dictionary:
	return {
		"schema_version": 1,
		"candidate": "semantic_left_leg",
		"research_gate_passed": research_passed,
		"production_gate_passed": false,
		"production_blockers": [
			"0078/0088/0063 are three independently drawn research parts, not the selected two-attachment production topology.",
			"The current fixed thigh->lower->foot order exposes the 0088 knee cap instead of hiding it under the thigh.",
			"The old UV-normalized foot origin and physical 0063 cuff pivot are not interchangeable.",
			"The separate 0088/0063 ankle seam adds visible risk for only +21 degrees of historical ankle motion.",
		],
		"selected_topology": "keep knee; far thigh + far lower-leg-with-boot; no separate ankle attachment",
		"errors": _errors,
		"evidence": evidence,
	}


func _validate_extrema(extrema: Dictionary, bone_name: String, expected_min: float, expected_max: float) -> void:
	if not extrema.has(bone_name):
		_fail("Missing rotation extrema for %s" % bone_name)
		return
	var value: Dictionary = extrema[bone_name]
	if absf(float(value.get("min", INF)) - expected_min) > 0.0001:
		_fail("Minimum rotation changed for %s" % bone_name)
	if absf(float(value.get("max", INF)) - expected_max) > 0.0001:
		_fail("Maximum rotation changed for %s" % bone_name)


func _load_rgba(path: String, expected_size: Vector2i) -> Image:
	if not FileAccess.file_exists(path):
		_fail("Missing generated artifact: %s" % path)
		return Image.new()
	var image := Image.load_from_file(path)
	if image == null or image.is_empty():
		_fail("Could not decode generated artifact: %s" % path)
		return Image.new()
	if image.get_format() != Image.FORMAT_RGBA8:
		_fail("Artifact is not RGBA8: %s" % path)
		return Image.new()
	if image.get_size() != expected_size:
		_fail("Artifact size mismatch: %s => %s" % [path, image.get_size()])
		return Image.new()
	return image


func _alpha_bounds(image: Image, threshold: int) -> Rect2i:
	var minimum := Vector2i(image.get_width(), image.get_height())
	var maximum := Vector2i(-1, -1)
	for y in image.get_height():
		for x in image.get_width():
			if image.get_pixel(x, y).a8 < threshold:
				continue
			minimum.x = mini(minimum.x, x)
			minimum.y = mini(minimum.y, y)
			maximum.x = maxi(maximum.x, x)
			maximum.y = maxi(maximum.y, y)
	if maximum.x < minimum.x or maximum.y < minimum.y:
		return Rect2i()
	return Rect2i(minimum, maximum - minimum + Vector2i.ONE)


func _touches_margin(bounds: Rect2i, size: Vector2i, margin: int) -> bool:
	return (
		bounds.position.x < margin
		or bounds.position.y < margin
		or bounds.end.x > size.x - margin
		or bounds.end.y > size.y - margin
	)


func _opaque_corners_equal(image: Image, expected: Color) -> bool:
	for point: Vector2i in [
		Vector2i.ZERO,
		Vector2i(image.get_width() - 1, 0),
		Vector2i(0, image.get_height() - 1),
		Vector2i(image.get_width() - 1, image.get_height() - 1),
	]:
		var observed := image.get_pixelv(point)
		if observed.a8 != 255:
			return false
		if (
			abs(observed.r8 - expected.r8) > 1
			or abs(observed.g8 - expected.g8) > 1
			or abs(observed.b8 - expected.b8) > 1
		):
			return false
	return true


func _read_json(path: String) -> Dictionary:
	if not FileAccess.file_exists(path):
		return {}
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(path))
	if parsed is Dictionary:
		return parsed
	return {}


func _write_json(path: String, value: Variant) -> bool:
	DirAccess.make_dir_recursive_absolute(path.get_base_dir())
	var file := FileAccess.open(path, FileAccess.WRITE)
	if file == null:
		push_error("Could not write validation report: %s" % path)
		return false
	file.store_string(JSON.stringify(value, "  ", false) + "\n")
	return true


func _fail(message: String) -> void:
	_errors.append(message)
	push_error(message)
