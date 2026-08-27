extends SceneTree

## Audits the isolated Vulkan frame capture produced for the Vivhite Ironclad
## replacement. The analyzer deliberately reloads every PNG instead of trusting
## renderer-side measurements. Reports and contact sheets are confined to
## `.work` and never touch the game install or the distributable Mod tree.
## Source frames are read-only: checkerboard/green/black residue is reported as
## failure and is never removed or converted into transparency.

const FORMAT_VERSION := 1
const DEFAULT_INPUT := ".work/ironclad-render-acceptance"
const DEFAULT_EXPECTED_FRAMES := 5

const ALPHA_THRESHOLD := 8
const GREEN_MIN_COUNT := 8
const GREEN_MAX_RATIO := 0.0001
const BLACK_CELL_SIZE := 8
const BLACK_WINDOW_CELLS := 2
const BLACK_WINDOW_RATIO := 0.96
const CHECKER_CELL_SIZES := [4, 6, 8, 12, 16, 24, 32]
const CHECKER_NEUTRAL_SPREAD := 18
const CHECKER_SAME_LUMA := 12
const CHECKER_DIFFERENT_LUMA := 24
const CHECKER_MIN_TESTED := 24
const CHECKER_MIN_MATCHES := 16
const CHECKER_MATCH_RATIO := 0.60
const DIFF_MAX_DIM := 256
const DIFF_PIXEL_THRESHOLD := 16
const DIFF_CHANGED_RATIO_THRESHOLD := 0.001
const DIFF_MEAN_THRESHOLD := 0.0002

const CONTACT_TILE := Vector2i(288, 288)
const CONTACT_GAP := 8
const CONTACT_PADDING := 8
const CONTACT_COLUMNS := 5
const CHECKER_SIZE := 16

const EXPECTED_ANIMATIONS := {
	"combat": [
		"idle_loop",
		"low_health_loop",
		"relaxed_loop",
		"attack",
		"attack_heavy",
		"cast",
		"hurt",
		"die",
	],
	"merchant": ["relaxed_loop"],
	"rest_site": [
		"glory_loop",
		"hive_loop",
		"overgrowth_loop",
		"_tracks/light_off",
		"_tracks/light_on",
	],
	"character_select": ["animation"],
}

var _last_error := ""


func _initialize() -> void:
	var status := _run(OS.get_cmdline_user_args())
	quit(status)


func _run(args: PackedStringArray) -> int:
	if args.size() == 1 and args[0] == "--self-test":
		return _self_test()
	if not args.is_empty() and args[0] in ["-h", "--help", "help"]:
		_print_help()
		return 0

	var options := _parse_options(args)
	if options.is_empty() and not args.is_empty():
		return 2
	var input_root := _absolute_path(str(options.get("input", DEFAULT_INPUT)))
	var output_root := _absolute_path(
		str(options.get("output", input_root.path_join("analysis")))
	)
	var expected_frames := int(options.get("expected-frames", DEFAULT_EXPECTED_FRAMES))
	var enforce_contract_value := str(options.get("enforce-full-contract", "true")).to_lower()
	if enforce_contract_value not in ["true", "false", "1", "0", "yes", "no"]:
		return _fail("--enforce-full-contract must be true or false.", 2)
	var enforce_contract := enforce_contract_value in ["true", "1", "yes"]
	if expected_frames < 2:
		return _fail("--expected-frames must be at least 2.", 2)
	if not _is_below_work(input_root) or not _is_below_work(output_root):
		return _fail("Input and output must both stay below the repository .work directory.", 2)

	var result := _analyze_root(input_root, output_root, expected_frames, enforce_contract)
	if result.is_empty():
		return _fail(_last_error, 3)
	print(JSON.stringify({
		"passed": result["passed"],
		"summary": result["summary"],
		"report": output_root.path_join("summary.json"),
	}))
	return 0 if bool(result["passed"]) else 1


func _parse_options(args: PackedStringArray) -> Dictionary:
	var options := {}
	var index := 0
	while index < args.size():
		var token := str(args[index])
		if not token.begins_with("--") or index + 1 >= args.size():
			_last_error = "Expected --name value, got: %s" % token
			printerr(_last_error)
			return {}
		var name := token.trim_prefix("--")
		if name not in ["input", "output", "expected-frames", "enforce-full-contract"]:
			_last_error = "Unknown option: %s" % token
			printerr(_last_error)
			return {}
		options[name] = args[index + 1]
		index += 2
	return options


func _print_help() -> void:
	print(
		"Usage: analyze_ironclad_render_output.gd -- "
		+ "[--input .work/ironclad-render-acceptance] "
		+ "[--output .work/ironclad-render-acceptance/analysis] "
		+ "[--expected-frames 5] [--enforce-full-contract true]\n"
		+ "       analyze_ironclad_render_output.gd -- --self-test"
	)


func _analyze_root(
	input_root: String,
	output_root: String,
	expected_frames: int,
	enforce_contract: bool
) -> Dictionary:
	_last_error = ""
	var frames_root := input_root.path_join("frames")
	if not DirAccess.dir_exists_absolute(frames_root):
		_set_error("Frame directory does not exist: %s" % frames_root)
		return {}

	var render_report_path := input_root.path_join("report.json")
	var render_report = _load_json(render_report_path)
	if render_report == null:
		_set_error("Renderer report is missing or invalid: %s" % render_report_path)
		return {}
	var metadata := _read_render_metadata(render_report)
	var renderer_success := bool(render_report.get("success", false)) if render_report is Dictionary else false
	var rig_summary = render_report.get("rig_summary", {}) if render_report is Dictionary else {}
	var renderer_rig_mode := str(render_report.get("rig_mode", "strict")) if render_report is Dictionary else "strict"
	var full_migration_ready := bool(render_report.get("full_migration_ready", false)) if render_report is Dictionary else false
	var groups := _collect_frame_groups(frames_root)
	if groups.is_empty():
		_set_error("No PNG frames were found below: %s" % frames_root)
		return {}
	if DirAccess.make_dir_recursive_absolute(output_root) != OK:
		_set_error("Could not create analysis directory: %s" % output_root)
		return {}
	var contact_root := output_root.path_join("contact-sheets")
	if DirAccess.make_dir_recursive_absolute(contact_root) != OK:
		_set_error("Could not create contact-sheet directory: %s" % contact_root)
		return {}

	var animation_reports := []
	var found_contract_keys := {}
	var frame_total := 0
	var failed_frames := 0
	var issue_total := 0
	var sorted_groups: Array = groups.keys()
	sorted_groups.sort()
	for group_value in sorted_groups:
		var group := str(group_value)
		var identity := _identity_for_group(group, metadata)
		var animation_report := _analyze_animation(
			frames_root,
			group,
			groups[group],
			identity,
			contact_root,
			expected_frames
		)
		if animation_report.is_empty():
			return {}
		var contract_key := "%s\n%s" % [
			_normalize_set_name(str(animation_report["set"])),
			str(animation_report["animation"]),
		]
		found_contract_keys[contract_key] = true
		animation_reports.append(animation_report)
		frame_total += int(animation_report["frame_count"])
		issue_total += animation_report["issues"].size()
		for frame_value in animation_report["frames"]:
			issue_total += frame_value["issues"].size()
			if not bool(frame_value["passed"]):
				failed_frames += 1

	var coverage_issues := []
	if enforce_contract:
		var expected_keys := _expected_contract_keys()
		for contract_key_value in expected_keys:
			var contract_key := str(contract_key_value)
			if not found_contract_keys.has(contract_key):
				coverage_issues.append({
					"code": "missing_animation",
					"animation": _contract_key_display(contract_key),
				})
		for contract_key_value in found_contract_keys:
			var contract_key := str(contract_key_value)
			if contract_key not in expected_keys:
				coverage_issues.append({
					"code": "unexpected_animation",
					"animation": _contract_key_display(contract_key),
				})
	var light_off := _find_animation_report(
		animation_reports, "rest_site", "_tracks/light_off"
	)
	var light_on := _find_animation_report(
		animation_reports, "rest_site", "_tracks/light_on"
	)
	if (
		not light_off.is_empty()
		and not light_on.is_empty()
		and not light_off["frames"].is_empty()
		and not light_on["frames"].is_empty()
		and light_off["frames"][0]["sha256"] == light_on["frames"][0]["sha256"]
	):
		coverage_issues.append({
			"code": "light_track_states_identical",
			"animation": "rest_site:_tracks/light_off vs _tracks/light_on",
		})

	var failed_animations := 0
	for animation_value in animation_reports:
		if not bool(animation_value["passed"]):
			failed_animations += 1
	issue_total += coverage_issues.size()
	var visual_checks_passed := (
		renderer_success
		and failed_animations == 0
		and coverage_issues.is_empty()
	)
	var full_acceptance_passed := visual_checks_passed and full_migration_ready
	var passed := full_acceptance_passed if renderer_rig_mode == "strict" else visual_checks_passed
	var report := {
		"format_version": FORMAT_VERSION,
		"input_root": _relative_to_repo(input_root),
		"renderer_report": _relative_to_repo(render_report_path),
		"renderer_success": renderer_success,
		"rig_summary": rig_summary,
		"rig_mode": renderer_rig_mode,
		"visual_checks_passed": visual_checks_passed,
		"full_acceptance_passed": full_acceptance_passed,
		"output_root": _relative_to_repo(output_root),
		"thresholds": {
			"alpha_byte": ALPHA_THRESHOLD,
			"green_min_count": GREEN_MIN_COUNT,
			"green_max_ratio": GREEN_MAX_RATIO,
			"black_rgb_byte_max": 6,
			"black_alpha_byte_min": 250,
			"black_window_pixels": BLACK_CELL_SIZE * BLACK_WINDOW_CELLS,
			"black_window_ratio": BLACK_WINDOW_RATIO,
			"checker_match_ratio": CHECKER_MATCH_RATIO,
			"checker_min_matches": CHECKER_MIN_MATCHES,
			"diff_changed_ratio": DIFF_CHANGED_RATIO_THRESHOLD,
			"diff_mean_rgba": DIFF_MEAN_THRESHOLD,
		},
		"summary": {
			"animation_count": animation_reports.size(),
			"expected_animation_count": _expected_animation_count() if enforce_contract else animation_reports.size(),
			"frame_count": frame_total,
			"failed_animation_count": failed_animations,
			"failed_frame_count": failed_frames,
			"issue_count": issue_total,
			"coverage_issue_count": coverage_issues.size(),
		},
		"coverage_issues": coverage_issues,
		"animations": animation_reports,
		"passed": passed,
	}
	if not _write_json(output_root.path_join("summary.json"), report):
		return {}
	return report


func _collect_frame_groups(frames_root: String) -> Dictionary:
	var groups := {}
	_collect_pngs_recursive(frames_root, "", groups)
	for group in groups:
		groups[group].sort()
	return groups


func _collect_pngs_recursive(directory: String, relative: String, groups: Dictionary) -> void:
	var access := DirAccess.open(directory)
	if access == null:
		return
	var directories := []
	var files := []
	access.list_dir_begin()
	var entry := access.get_next()
	while not entry.is_empty():
		if entry not in [".", ".."]:
			if access.current_is_dir():
				directories.append(entry)
			elif entry.to_lower().ends_with(".png"):
				files.append(entry)
		entry = access.get_next()
	access.list_dir_end()
	directories.sort()
	files.sort()
	if not files.is_empty():
		var group := relative.replace("\\", "/").trim_prefix("/")
		if group.is_empty():
			group = "ungrouped"
		groups[group] = []
		for file_value in files:
			groups[group].append(directory.path_join(str(file_value)))
	for child_value in directories:
		var child := str(child_value)
		var child_relative := child if relative.is_empty() else relative.path_join(child)
		_collect_pngs_recursive(directory.path_join(child), child_relative, groups)


func _read_render_metadata(value: Variant) -> Dictionary:
	var metadata := {}
	if not value is Dictionary:
		return metadata
	var report: Dictionary = value
	var sets_value = report.get("sets", [])
	if not sets_value is Array:
		return metadata
	for set_value in sets_value:
		if not set_value is Dictionary:
			continue
		var set_report: Dictionary = set_value
		var set_name := str(set_report.get("name", set_report.get("set", "")))
		var set_rig_metadata := {
			"data_source": str(set_report.get("data_source", "unknown")),
			"declared_skeleton_resource": str(set_report.get("declared_skeleton_resource", "")),
			"migration_status": str(set_report.get("migration_status", "unknown")),
			"skeleton_data_resource": str(set_report.get("resource", "")),
			"rig_kind": str(set_report.get("rig_kind", "unknown")),
			"skeleton_resource": str(set_report.get("skeleton_resource", "")),
		}
		var animations_value = set_report.get("animations", [])
		if not animations_value is Array:
			continue
		for animation_value in animations_value:
			if not animation_value is Dictionary:
				continue
			var animation: Dictionary = animation_value
			var animation_name := str(animation.get("name", animation.get("animation", "")))
			var safe_name := str(animation.get("safe_name", animation.get("directory", "")))
			var group := ""
			var frames_value = animation.get("frames", [])
			var frame_metadata := {}
			if frames_value is Array:
				for frame_value in frames_value:
					if frame_value is Dictionary:
						var frame_path := str(frame_value.get("path", frame_value.get("output", "")))
						if not frame_path.is_empty():
							frame_metadata[frame_path.replace("\\", "/").get_file()] = {
								"fraction": frame_value.get("fraction", null),
								"sample_time": frame_value.get("sample_time", null),
							}
			if frames_value is Array and not frames_value.is_empty() and frames_value[0] is Dictionary:
				var first_frame: Dictionary = frames_value[0]
				var path := str(first_frame.get("path", first_frame.get("output", ""))).replace("\\", "/")
				var marker := "/frames/"
				var marker_index := path.find(marker)
				if marker_index >= 0:
					group = path.substr(marker_index + marker.length()).get_base_dir()
				elif path.begins_with("frames/"):
					group = path.trim_prefix("frames/").get_base_dir()
			if group.is_empty() and not set_name.is_empty() and not safe_name.is_empty():
				group = set_name.path_join(safe_name).replace("\\", "/")
			if not group.is_empty():
				metadata[group] = {
					"set": set_name,
					"animation": animation_name,
					"safe_name": safe_name,
					"duration": animation.get("duration", null),
					"data_source": set_rig_metadata.data_source,
					"declared_skeleton_resource": set_rig_metadata.declared_skeleton_resource,
					"frame_metadata": frame_metadata,
					"migration_status": set_rig_metadata.migration_status,
					"skeleton_data_resource": set_rig_metadata.skeleton_data_resource,
					"rig_kind": set_rig_metadata.rig_kind,
					"skeleton_resource": set_rig_metadata.skeleton_resource,
				}
	return metadata


func _identity_for_group(group: String, metadata: Dictionary) -> Dictionary:
	if metadata.has(group):
		return metadata[group]
	var pieces := group.split("/", false)
	var set_name := str(pieces[0]) if not pieces.is_empty() else "unknown"
	var safe_name := str(pieces[pieces.size() - 1]) if pieces.size() > 1 else set_name
	var animation_name := _animation_from_safe_name(set_name, safe_name)
	return {
		"set": set_name,
		"animation": animation_name,
		"safe_name": safe_name,
		"duration": null,
	}


func _animation_from_safe_name(set_name: String, safe_name: String) -> String:
	var normalized_set := _normalize_set_name(set_name)
	if EXPECTED_ANIMATIONS.has(normalized_set):
		for expected_value in EXPECTED_ANIMATIONS[normalized_set]:
			var expected := str(expected_value)
			if safe_name in _safe_name_candidates(expected):
				return expected
	return safe_name


func _safe_name_candidates(animation: String) -> Array:
	return [
		animation,
		animation.replace("/", "-"),
		animation.replace("/", "_"),
		animation.replace("/", "--"),
	]


func _analyze_animation(
	frames_root: String,
	group: String,
	paths_value: Variant,
	identity: Dictionary,
	contact_root: String,
	expected_frames: int
) -> Dictionary:
	var paths: Array = paths_value
	var frame_reports := []
	var diff_payloads := []
	var source_images := []
	var issues := []
	var dimensions := Vector2i.ZERO
	for path_index in paths.size():
		var path := str(paths[path_index])
		var analysis := _analyze_frame(path)
		if analysis.is_empty():
			_set_error("Could not analyze frame: %s" % path)
			return {}
		var image: Image = analysis["_image"]
		var diff_payload: Dictionary = analysis["_diff"]
		analysis.erase("_image")
		analysis.erase("_diff")
		analysis["path"] = _relative_to_repo(path)
		var frame_metadata = identity.get("frame_metadata", {})
		if frame_metadata is Dictionary and frame_metadata.has(path.get_file()):
			var sample: Dictionary = frame_metadata[path.get_file()]
			analysis["fraction"] = sample.get("fraction", null)
			analysis["sample_time"] = sample.get("sample_time", null)
			var duration_value = identity.get("duration", null)
			if duration_value != null and analysis["fraction"] != null and analysis["sample_time"] != null:
				var expected_fraction := float(path_index) / float(maxi(1, expected_frames - 1))
				var actual_fraction := float(analysis["fraction"])
				var expected_time := float(duration_value) * actual_fraction
				if absf(actual_fraction - expected_fraction) > 0.000001:
					analysis["issues"].append("nonuniform_sample_fraction")
					analysis["passed"] = false
				if absf(float(analysis["sample_time"]) - expected_time) > 0.00001:
					analysis["issues"].append("sample_time_mismatch")
					analysis["passed"] = false
		elif identity.get("duration", null) != null:
			analysis["issues"].append("missing_sample_metadata")
			analysis["passed"] = false
		if dimensions == Vector2i.ZERO:
			dimensions = Vector2i(int(analysis["width"]), int(analysis["height"]))
		elif dimensions != Vector2i(int(analysis["width"]), int(analysis["height"])):
			analysis["issues"].append("dimension_mismatch")
			analysis["passed"] = false
		frame_reports.append(analysis)
		diff_payloads.append(diff_payload)
		source_images.append(image)
	if paths.size() != expected_frames:
		issues.append("wrong_frame_count")

	var differences := []
	var maximum_changed_ratio := 0.0
	var maximum_mean_rgba := 0.0
	for index in range(1, diff_payloads.size()):
		var difference := _compare_diff_payloads(diff_payloads[index - 1], diff_payloads[index])
		difference["from_frame"] = index - 1
		difference["to_frame"] = index
		differences.append(difference)
		maximum_changed_ratio = maxf(maximum_changed_ratio, float(difference["changed_ratio"]))
		maximum_mean_rgba = maxf(maximum_mean_rgba, float(difference["mean_absolute_rgba"]))
	var varying := (
		maximum_changed_ratio >= DIFF_CHANGED_RATIO_THRESHOLD
		or maximum_mean_rgba >= DIFF_MEAN_THRESHOLD
	)
	var duration_value = identity.get("duration", null)
	var animation_name := str(identity.get("animation", group.get_file()))
	# The named light tracks are persistent visual states, not motion clips.
	# They must remain constant within the clip to avoid a one-frame setup-color
	# flash, while light_off and light_on are compared against each other above.
	var variation_required := (
		(duration_value == null or float(duration_value) > 0.000001)
		and animation_name not in ["_tracks/light_off", "_tracks/light_on"]
	)
	if variation_required and not varying:
		issues.append("no_frame_variation")

	var contact_name := group.replace("/", "__").replace("\\", "__") + ".png"
	var contact_path := contact_root.path_join(contact_name)
	if not _write_contact_sheet(source_images, frame_reports, contact_path):
		return {}
	var any_frame_failed := false
	for frame_value in frame_reports:
		if not bool(frame_value["passed"]):
			any_frame_failed = true
	var passed := issues.is_empty() and not any_frame_failed
	return {
		"set": str(identity.get("set", "unknown")),
		"animation": animation_name,
		"safe_name": str(identity.get("safe_name", group.get_file())),
		"duration": identity.get("duration", null),
		"data_source": str(identity.get("data_source", "unknown")),
		"declared_skeleton_resource": str(identity.get("declared_skeleton_resource", "")),
		"migration_status": str(identity.get("migration_status", "unknown")),
		"rig_kind": str(identity.get("rig_kind", "unknown")),
		"skeleton_data_resource": str(identity.get("skeleton_data_resource", "")),
		"skeleton_resource": str(identity.get("skeleton_resource", "")),
		"group": group,
		"frame_count": frame_reports.size(),
		"expected_frame_count": expected_frames,
		"dimensions": [dimensions.x, dimensions.y],
		"varying": varying,
		"variation_required": variation_required,
		"maximum_changed_ratio": maximum_changed_ratio,
		"maximum_mean_absolute_rgba": maximum_mean_rgba,
		"differences": differences,
		"contact_sheet": _relative_to_repo(contact_path),
		"frames": frame_reports,
		"issues": issues,
		"passed": passed,
	}


func _analyze_frame(path: String) -> Dictionary:
	var image := Image.new()
	var load_error := image.load(path)
	if load_error != OK:
		_set_error("Could not load PNG %s: %s" % [path, error_string(load_error)])
		return {}
	image.convert(Image.FORMAT_RGBA8)
	var width := image.get_width()
	var height := image.get_height()
	if width <= 0 or height <= 0:
		_set_error("PNG has invalid dimensions: %s" % path)
		return {}
	var pixels := image.get_data()
	var nontransparent := 0
	var green_pixels := 0
	var min_x := width
	var min_y := height
	var max_x := -1
	var max_y := -1
	var edge_left := 0
	var edge_top := 0
	var edge_right := 0
	var edge_bottom := 0

	var black_grid_width := int(ceil(float(width) / float(BLACK_CELL_SIZE)))
	var black_grid_height := int(ceil(float(height) / float(BLACK_CELL_SIZE)))
	var black_cells := PackedInt32Array()
	black_cells.resize(black_grid_width * black_grid_height)
	for pixel_index in width * height:
		var byte_index := pixel_index * 4
		var red := int(pixels[byte_index])
		var green := int(pixels[byte_index + 1])
		var blue := int(pixels[byte_index + 2])
		var alpha := int(pixels[byte_index + 3])
		if alpha <= ALPHA_THRESHOLD:
			continue
		var x := pixel_index % width
		var y := pixel_index / width
		nontransparent += 1
		min_x = mini(min_x, x)
		min_y = mini(min_y, y)
		max_x = maxi(max_x, x)
		max_y = maxi(max_y, y)
		if x == 0:
			edge_left += 1
		if x == width - 1:
			edge_right += 1
		if y == 0:
			edge_top += 1
		if y == height - 1:
			edge_bottom += 1
		if green >= 96 and green - red >= 48 and green - blue >= 32:
			green_pixels += 1
		if alpha >= 250 and red <= 6 and green <= 6 and blue <= 6:
			var cell_x := x / BLACK_CELL_SIZE
			var cell_y := y / BLACK_CELL_SIZE
			var cell_index := cell_y * black_grid_width + cell_x
			black_cells[cell_index] += 1

	var bounds := Rect2i()
	if nontransparent > 0:
		bounds = Rect2i(min_x, min_y, max_x - min_x + 1, max_y - min_y + 1)
	var edge_pixels := edge_left + edge_top + edge_right + edge_bottom
	var green_ratio := float(green_pixels) / float(maxi(1, nontransparent))
	var green_limit := maxi(GREEN_MIN_COUNT, int(ceil(float(nontransparent) * GREEN_MAX_RATIO)))
	var green_residue := green_pixels > green_limit
	var black_windows := _black_windows(
		black_cells,
		black_grid_width,
		black_grid_height,
		width,
		height
	)
	var checkerboard := _checkerboard_evidence(pixels, width, height, bounds)
	var issues := []
	if nontransparent == 0:
		issues.append("empty_alpha")
	if edge_pixels > 0:
		issues.append("canvas_edge_contact")
	if green_residue:
		issues.append("green_residue")
	if not black_windows.is_empty():
		issues.append("black_block")
	if bool(checkerboard["detected"]):
		issues.append("checkerboard_residue")
	return {
		"width": width,
		"height": height,
		"sha256": FileAccess.get_sha256(path),
		"nontransparent_pixels": nontransparent,
		"nontransparent_ratio": float(nontransparent) / float(width * height),
		"alpha_bounds": [bounds.position.x, bounds.position.y, bounds.size.x, bounds.size.y],
		"touches_canvas_edge": edge_pixels > 0,
		"edge_pixels": {
			"left": edge_left,
			"top": edge_top,
			"right": edge_right,
			"bottom": edge_bottom,
		},
		"green_pixels": green_pixels,
		"green_ratio": green_ratio,
		"green_limit": green_limit,
		"green_residue": green_residue,
		"black_block_count": black_windows.size(),
		"black_block_samples": black_windows.slice(0, mini(20, black_windows.size())),
		"checkerboard_residue": checkerboard,
		"issues": issues,
		"passed": issues.is_empty(),
		"_image": image,
		"_diff": _make_diff_payload(image),
	}


func _neutral_luma(pixels: PackedByteArray, width: int, x: int, y: int) -> int:
	var byte_index := (y * width + x) * 4
	var red := int(pixels[byte_index])
	var green := int(pixels[byte_index + 1])
	var blue := int(pixels[byte_index + 2])
	var alpha := int(pixels[byte_index + 3])
	if (
		alpha < 240
		or maxi(red, maxi(green, blue)) - mini(red, mini(green, blue)) > CHECKER_NEUTRAL_SPREAD
	):
		return -1
	return (red + green + blue) / 3


func _checkerboard_evidence(
	pixels: PackedByteArray,
	width: int,
	height: int,
	bounds: Rect2i
) -> Dictionary:
	var best := {
		"cell_size": 0,
		"detected": false,
		"matches": 0,
		"match_ratio": 0.0,
		"tested": 0,
	}
	if not bounds.has_area():
		return best
	for cell_value in CHECKER_CELL_SIZES:
		var cell := int(cell_value)
		if bounds.size.x <= cell or bounds.size.y <= cell:
			continue
		var step := maxi(4, cell / 2)
		var tested := 0
		var matches := 0
		for y in range(bounds.position.y, mini(height, bounds.end.y - cell), step):
			for x in range(bounds.position.x, mini(width, bounds.end.x - cell), step):
				var top_left := _neutral_luma(pixels, width, x, y)
				var top_right := _neutral_luma(pixels, width, x + cell, y)
				var bottom_left := _neutral_luma(pixels, width, x, y + cell)
				var bottom_right := _neutral_luma(pixels, width, x + cell, y + cell)
				if mini(top_left, mini(top_right, mini(bottom_left, bottom_right))) < 0:
					continue
				tested += 1
				if (
					absi(top_left - bottom_right) <= CHECKER_SAME_LUMA
					and absi(top_right - bottom_left) <= CHECKER_SAME_LUMA
					and absi(top_left - top_right) >= CHECKER_DIFFERENT_LUMA
				):
					matches += 1
		var ratio := float(matches) / float(maxi(1, tested))
		if ratio > float(best["match_ratio"]):
			best = {
				"cell_size": cell,
				"detected": (
					tested >= CHECKER_MIN_TESTED
					and matches >= CHECKER_MIN_MATCHES
					and ratio >= CHECKER_MATCH_RATIO
				),
				"matches": matches,
				"match_ratio": ratio,
				"tested": tested,
			}
	return best


func _black_windows(
	cells: PackedInt32Array,
	grid_width: int,
	grid_height: int,
	image_width: int,
	image_height: int
) -> Array:
	var windows := []
	if grid_width < BLACK_WINDOW_CELLS or grid_height < BLACK_WINDOW_CELLS:
		return windows
	var window_size := BLACK_CELL_SIZE * BLACK_WINDOW_CELLS
	var required := int(ceil(float(window_size * window_size) * BLACK_WINDOW_RATIO))
	for cell_y in range(0, grid_height - BLACK_WINDOW_CELLS + 1):
		for cell_x in range(0, grid_width - BLACK_WINDOW_CELLS + 1):
			var origin_x := cell_x * BLACK_CELL_SIZE
			var origin_y := cell_y * BLACK_CELL_SIZE
			if origin_x + window_size > image_width or origin_y + window_size > image_height:
				continue
			var black_count := 0
			for offset_y in BLACK_WINDOW_CELLS:
				for offset_x in BLACK_WINDOW_CELLS:
					black_count += cells[
						(cell_y + offset_y) * grid_width + cell_x + offset_x
					]
			if black_count >= required:
				windows.append({
					"rect": [origin_x, origin_y, window_size, window_size],
					"black_pixels": black_count,
				})
	return windows


func _make_diff_payload(source: Image) -> Dictionary:
	var image: Image = source.duplicate()
	var width: int = image.get_width()
	var height: int = image.get_height()
	var longest := maxi(width, height)
	if longest > DIFF_MAX_DIM:
		var scale := float(DIFF_MAX_DIM) / float(longest)
		width = maxi(1, int(round(float(width) * scale)))
		height = maxi(1, int(round(float(height) * scale)))
		image.resize(width, height, Image.INTERPOLATE_BILINEAR)
	image.convert(Image.FORMAT_RGBA8)
	return {
		"width": width,
		"height": height,
		"data": image.get_data(),
	}


func _compare_diff_payloads(first: Dictionary, second: Dictionary) -> Dictionary:
	if int(first["width"]) != int(second["width"]) or int(first["height"]) != int(second["height"]):
		return {
			"comparable": false,
			"changed_pixels": 0,
			"changed_ratio": 0.0,
			"mean_absolute_rgba": 0.0,
		}
	var first_data: PackedByteArray = first["data"]
	var second_data: PackedByteArray = second["data"]
	var pixel_count := int(first["width"]) * int(first["height"])
	var changed_pixels := 0
	var absolute_total := 0
	for pixel_index in pixel_count:
		var byte_index := pixel_index * 4
		var pixel_difference := 0
		for channel in 4:
			var difference := absi(int(first_data[byte_index + channel]) - int(second_data[byte_index + channel]))
			pixel_difference += difference
			absolute_total += difference
		if pixel_difference >= DIFF_PIXEL_THRESHOLD:
			changed_pixels += 1
	return {
		"comparable": true,
		"changed_pixels": changed_pixels,
		"changed_ratio": float(changed_pixels) / float(maxi(1, pixel_count)),
		"mean_absolute_rgba": float(absolute_total) / float(maxi(1, pixel_count * 4 * 255)),
	}


func _write_contact_sheet(images: Array, frame_reports: Array, path: String) -> bool:
	if images.is_empty():
		_set_error("Cannot create an empty contact sheet: %s" % path)
		return false
	var columns := mini(CONTACT_COLUMNS, images.size())
	var rows := int(ceil(float(images.size()) / float(columns)))
	var sheet_size := Vector2i(
		CONTACT_PADDING * 2 + columns * CONTACT_TILE.x + (columns - 1) * CONTACT_GAP,
		CONTACT_PADDING * 2 + rows * CONTACT_TILE.y + (rows - 1) * CONTACT_GAP
	)
	var sheet := Image.create(sheet_size.x, sheet_size.y, false, Image.FORMAT_RGBA8)
	sheet.fill(Color("11131c"))
	for index in images.size():
		var column := index % columns
		var row := index / columns
		var origin := Vector2i(
			CONTACT_PADDING + column * (CONTACT_TILE.x + CONTACT_GAP),
			CONTACT_PADDING + row * (CONTACT_TILE.y + CONTACT_GAP)
		)
		var border_color := Color("35d0d0") if bool(frame_reports[index]["passed"]) else Color("ef476f")
		sheet.fill_rect(Rect2i(origin, CONTACT_TILE), border_color)
		var interior := Rect2i(origin + Vector2i(3, 3), CONTACT_TILE - Vector2i(6, 6))
		_draw_checker(sheet, interior)
		var source: Image = images[index]
		var available := interior.size - Vector2i(8, 8)
		var scale := minf(
			float(available.x) / float(source.get_width()),
			float(available.y) / float(source.get_height())
		)
		var target_size := Vector2i(
			maxi(1, int(round(float(source.get_width()) * scale))),
			maxi(1, int(round(float(source.get_height()) * scale)))
		)
		var thumbnail := source.duplicate()
		thumbnail.resize(target_size.x, target_size.y, Image.INTERPOLATE_LANCZOS)
		var destination := interior.position + (interior.size - target_size) / 2
		sheet.blend_rect(
			thumbnail,
			Rect2i(Vector2i.ZERO, target_size),
			destination
		)
	if DirAccess.make_dir_recursive_absolute(path.get_base_dir()) != OK:
		_set_error("Could not create contact sheet directory: %s" % path.get_base_dir())
		return false
	var save_error := sheet.save_png(path)
	if save_error != OK:
		_set_error("Could not save contact sheet %s: %s" % [path, error_string(save_error)])
		return false
	return true


func _draw_checker(target: Image, rect: Rect2i) -> void:
	var light := Color("373b4c")
	var dark := Color("272a38")
	for y in range(rect.position.y, rect.end.y, CHECKER_SIZE):
		for x in range(rect.position.x, rect.end.x, CHECKER_SIZE):
			var cell_x := (x - rect.position.x) / CHECKER_SIZE
			var cell_y := (y - rect.position.y) / CHECKER_SIZE
			var color := light if (cell_x + cell_y) % 2 == 0 else dark
			var size := Vector2i(
				mini(CHECKER_SIZE, rect.end.x - x),
				mini(CHECKER_SIZE, rect.end.y - y)
			)
			target.fill_rect(Rect2i(Vector2i(x, y), size), color)


func _expected_contract_keys() -> Array:
	var keys := []
	for set_name in EXPECTED_ANIMATIONS:
		for animation_value in EXPECTED_ANIMATIONS[set_name]:
			keys.append("%s\n%s" % [set_name, animation_value])
	return keys


func _find_animation_report(reports: Array, set_name: String, animation_name: String) -> Dictionary:
	for report_value in reports:
		var report: Dictionary = report_value
		if (
			_normalize_set_name(str(report["set"])) == _normalize_set_name(set_name)
			and str(report["animation"]) == animation_name
		):
			return report
	return {}


func _expected_animation_count() -> int:
	var count := 0
	for set_name in EXPECTED_ANIMATIONS:
		count += EXPECTED_ANIMATIONS[set_name].size()
	return count


func _contract_key_display(key: String) -> String:
	return key.replace("\n", ":")


func _normalize_set_name(value: String) -> String:
	return value.to_lower().replace("-", "_").replace(" ", "_")


func _load_json(path: String) -> Variant:
	if not FileAccess.file_exists(path):
		return null
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null:
		return null
	var parsed = JSON.parse_string(file.get_as_text())
	return parsed


func _write_json(path: String, value: Variant) -> bool:
	if DirAccess.make_dir_recursive_absolute(path.get_base_dir()) != OK:
		_set_error("Could not create JSON output directory: %s" % path.get_base_dir())
		return false
	var file := FileAccess.open(path, FileAccess.WRITE)
	if file == null:
		_set_error("Could not open JSON output: %s" % path)
		return false
	file.store_string(JSON.stringify(value, "  ", true) + "\n")
	return true


func _absolute_path(path: String) -> String:
	if path.is_absolute_path():
		return path.simplify_path()
	return _repository_root().path_join(path).simplify_path()


func _repository_root() -> String:
	return ProjectSettings.globalize_path("res://").path_join("../..").simplify_path()


func _is_below_work(path: String) -> bool:
	var work_root := _repository_root().path_join(".work").simplify_path().replace("\\", "/").trim_suffix("/")
	var candidate := path.simplify_path().replace("\\", "/")
	return candidate.begins_with(work_root + "/")


func _relative_to_repo(path: String) -> String:
	var repo := _repository_root().replace("\\", "/").trim_suffix("/")
	var normalized := path.replace("\\", "/")
	if normalized.begins_with(repo + "/"):
		return normalized.trim_prefix(repo + "/")
	return normalized


func _self_test() -> int:
	var root := _repository_root().path_join(".work/ironclad-render-analyzer-self-test")
	var frames_root := root.path_join("frames")
	var valid_dir := frames_root.path_join("fixture/valid_motion")
	var invalid_dir := frames_root.path_join("fixture/invalid_pixels")
	for directory in [valid_dir, invalid_dir]:
		if DirAccess.make_dir_recursive_absolute(directory) != OK:
			return _fail("Could not create self-test directory: %s" % directory, 3)

	for index in 2:
		var valid := Image.create(64, 64, false, Image.FORMAT_RGBA8)
		valid.fill(Color(0.0, 0.0, 0.0, 0.0))
		valid.fill_rect(Rect2i(18 + index * 6, 20, 20, 24), Color("c8b8ff"))
		if valid.save_png(valid_dir.path_join("frame-%02d.png" % index)) != OK:
			return _fail("Could not write valid self-test frame.", 3)

	var empty := Image.create(64, 64, false, Image.FORMAT_RGBA8)
	empty.fill(Color(0.0, 0.0, 0.0, 0.0))
	if empty.save_png(invalid_dir.path_join("frame-00.png")) != OK:
		return _fail("Could not write empty self-test frame.", 3)
	var bad := Image.create(64, 64, false, Image.FORMAT_RGBA8)
	bad.fill(Color("00ff00"))
	for checker_y in range(0, 40, 8):
		for checker_x in range(0, 40, 8):
			var checker_parity := int(checker_x / 8 + checker_y / 8) % 2
			var checker_color := Color("e0e0e0") if checker_parity == 0 else Color("a8a8a8")
			bad.fill_rect(Rect2i(checker_x, checker_y, 8, 8), checker_color)
	bad.fill_rect(Rect2i(24, 24, 24, 24), Color("000000"))
	if bad.save_png(invalid_dir.path_join("frame-01.png")) != OK:
		return _fail("Could not write invalid self-test frame.", 3)

	var fixture_report := {
		"format_version": 1,
		"success": true,
		"rig_mode": "combat_partial",
		"full_migration_ready": false,
		"rig_summary": {
			"private_spjson_sets": ["fixture"],
			"legacy_sets": [],
		},
		"sets": [{
			"name": "fixture",
			"resource": "res://fixture/fixture_skeleton_data.tres",
			"skeleton_resource": "res://fixture/fixture.spjson",
			"rig_kind": "private_spjson",
			"migration_status": "custom_private_rig",
			"animations": [
				{
					"name": "valid_motion",
					"safe_name": "valid_motion",
					"duration": 1.0,
					"frames": [
						{
							"path": "frames/fixture/valid_motion/frame-00.png",
							"fraction": 0.0,
							"sample_time": 0.0,
						},
						{
							"path": "frames/fixture/valid_motion/frame-01.png",
							"fraction": 1.0,
							"sample_time": 1.0,
						},
					],
				},
				{
					"name": "invalid_pixels",
					"safe_name": "invalid_pixels",
					"duration": 1.0,
					"frames": [
						{
							"path": "frames/fixture/invalid_pixels/frame-00.png",
							"fraction": 0.0,
							"sample_time": 0.0,
						},
						{
							"path": "frames/fixture/invalid_pixels/frame-01.png",
							"fraction": 1.0,
							"sample_time": 1.0,
						},
					],
				},
			],
		}],
	}
	if not _write_json(root.path_join("report.json"), fixture_report):
		return _fail(_last_error, 3)
	var source_hashes := {}
	for fixture_path in [
		valid_dir.path_join("frame-00.png"),
		valid_dir.path_join("frame-01.png"),
		invalid_dir.path_join("frame-00.png"),
		invalid_dir.path_join("frame-01.png"),
	]:
		source_hashes[fixture_path] = FileAccess.get_sha256(fixture_path)
	var report := _analyze_root(root, root.path_join("analysis"), 2, false)
	if report.is_empty():
		return _fail(_last_error, 3)
	for fixture_path in source_hashes:
		if FileAccess.get_sha256(fixture_path) != source_hashes[fixture_path]:
			return _fail("Analyzer modified a source frame: %s" % fixture_path, 4)
	var by_name := {}
	for animation_value in report["animations"]:
		by_name[str(animation_value["animation"])] = animation_value
	if not by_name.has("valid_motion") or not bool(by_name["valid_motion"]["passed"]):
		return _fail("Self-test expected valid_motion to pass.", 4)
	if not by_name.has("invalid_pixels") or bool(by_name["invalid_pixels"]["passed"]):
		return _fail("Self-test expected invalid_pixels to fail.", 4)
	if (
		str(by_name["valid_motion"]["rig_kind"]) != "private_spjson"
		or str(by_name["valid_motion"]["skeleton_resource"]) != "res://fixture/fixture.spjson"
	):
		return _fail("Self-test did not preserve private rig metadata.", 4)
	var observed := {}
	for frame_value in by_name["invalid_pixels"]["frames"]:
		for issue_value in frame_value["issues"]:
			observed[str(issue_value)] = true
	for expected_issue in [
		"empty_alpha",
		"canvas_edge_contact",
		"green_residue",
		"black_block",
		"checkerboard_residue",
	]:
		if not observed.has(expected_issue):
			return _fail("Self-test did not detect: %s" % expected_issue, 4)
	print(JSON.stringify({
		"self_test": "passed",
		"report": _relative_to_repo(root.path_join("analysis/summary.json")),
	}))
	return 0


func _set_error(message: String) -> void:
	_last_error = message
	printerr("[ironclad-render-analysis] %s" % message)


func _fail(message: String, code: int) -> int:
	printerr("[ironclad-render-analysis] %s" % message)
	return code
