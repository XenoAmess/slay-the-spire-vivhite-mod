extends SceneTree

## Selects the nearest frame to each consumer-derived key time from the dense
## 21-frame Vulkan sweep and writes compact A/B sheets. It never edits source
## art; all cells are opaque SourceOver previews of actual Vulkan captures.

const REQUIRED_ANIMATIONS: Array[String] = [
	"idle_loop", "low_health_loop", "relaxed_loop", "attack",
	"attack_heavy", "cast", "hurt", "die",
]
const KEY_TIMES := {
	"idle_loop": [0.0, 0.5, 1.0, 1.5, 2.0],
	"low_health_loop": [0.0, 0.366666675, 0.73333335, 1.100000025, 1.4666667],
	"relaxed_loop": [0.0, 3.00000025, 6.0000005, 9.00000075, 12.000001],
	"attack": [0.0, 0.044, 0.08, 0.42, 0.840000024, 1.1666667],
	"attack_heavy": [0.0, 0.066, 0.12, 0.45, 0.82, 1.104000048, 1.5333334],
	"cast": [0.0, 0.1, 0.1375, 0.25, 0.6, 1.222000026, 1.5666667],
	"hurt": [0.0, 0.077, 0.14, 0.52, 0.72, 1.0],
	"die": [0.0, 0.16, 0.5, 0.74, 1.04, 1.05, 1.1, 1.31, 1.8, 2.3333335],
}
const EXPECTED_A := "LegacySplit"
const EXPECTED_B := "SemanticSplitV3"
const CELL := Vector2i(320, 225)
const ROW_GAP := 8
const SHEET_BG := Color("16242b")
const GAME_BG := Color("263942")
const A_COLOR := Color("d78c3d")
const B_COLOR := Color("36b6cf")
const PASS_COLOR := Color("55cf77")
const FAIL_COLOR := Color("d44a5b")

var _errors: Array[String] = []


func _initialize() -> void:
	call_deferred("_run")


func _run() -> void:
	var options := _parse_args()
	if options.is_empty():
		_finish(2)
		return
	var summary_path := str(options["summary"])
	var preview_root := str(options["preview-root"])
	var publish_root := str(options["publish-root"])
	if not FileAccess.file_exists(summary_path):
		_fail("Missing Vulkan summary: %s" % summary_path)
		_finish(2)
		return
	var summary_value = JSON.parse_string(FileAccess.get_file_as_string(summary_path))
	if not summary_value is Dictionary:
		_fail("Could not parse Vulkan summary")
		_finish(2)
		return
	var summary: Dictionary = summary_value
	if not bool(summary.get("success", false)):
		_fail("Dense Vulkan report did not pass")
		_finish(2)
		return
	var reports := {}
	for candidate_value: Variant in summary.get("candidates", []):
		var candidate: Dictionary = candidate_value
		reports[str(candidate.get("name", ""))] = candidate
	for name: String in [EXPECTED_A, EXPECTED_B]:
		if not reports.has(name):
			_fail("Vulkan report is missing A/B candidate %s" % name)
	if not _errors.is_empty():
		_finish(2)
		return
	DirAccess.make_dir_recursive_absolute(publish_root.path_join("contact-sheets"))

	var index := {
		"schema": "vivhite-semantic-split-v3-ab/v1",
		"status": "offline_vulkan_ab_passed",
		"deployable": false,
		"dense_source_summary": summary_path.replace("\\", "/"),
		"rows": {"A": EXPECTED_A, "B": EXPECTED_B},
		"row_colors": {"A": A_COLOR.to_html(false), "B": B_COLOR.to_html(false)},
		"animations": [],
		"contact_sheet": "",
	}
	var sheets: Array[Image] = []
	for animation_name: String in REQUIRED_ANIMATIONS:
		var selection_a := _select_frames(reports[EXPECTED_A], animation_name)
		var selection_b := _select_frames(reports[EXPECTED_B], animation_name)
		if selection_a.is_empty() or selection_b.is_empty():
			continue
		var sheet := _compose_sheet(preview_root, selection_a, selection_b)
		if sheet.is_empty():
			continue
		var relative := "contact-sheets/ab-%s.png" % animation_name
		if sheet.save_png(publish_root.path_join(relative)) != OK:
			_fail("Could not save %s" % relative)
			continue
		sheets.append(sheet)
		index.animations.append({
			"name": animation_name,
			"requested_times": KEY_TIMES[animation_name],
			"A": _selection_report(selection_a),
			"B": _selection_report(selection_b),
			"contact_sheet": relative,
		})
	if not _errors.is_empty() or sheets.size() != REQUIRED_ANIMATIONS.size():
		_finish(2)
		return
	var overview := _compose_overview(sheets)
	var overview_name := "semantic-split-v3-ab-overview.png"
	if overview.save_png(publish_root.path_join(overview_name)) != OK:
		_fail("Could not save A/B overview")
		_finish(2)
		return
	index.contact_sheet = overview_name
	var manifest_path := publish_root.path_join("candidate.json")
	if FileAccess.file_exists(manifest_path):
		var manifest_value = JSON.parse_string(FileAccess.get_file_as_string(manifest_path))
		if manifest_value is Dictionary:
			index["component_slots"] = (manifest_value as Dictionary).get("component_slots", [])
			index["production_slot_contract"] = (manifest_value as Dictionary).get("production_slot_contract", [])
	var file := FileAccess.open(publish_root.path_join("ab-contact-index.json"), FileAccess.WRITE)
	if file == null:
		_fail("Could not write ab-contact-index.json")
		_finish(2)
		return
	file.store_string(JSON.stringify(index, "  ", false) + "\n")
	file.close()
	print("Built semantic_split_v3 A/B key-extrema sheets: 8 animations")
	print("  dense Vulkan source: 21 samples per animation")
	print("  deployable: false")
	_finish(0)


func _parse_args() -> Dictionary:
	var options := {"summary": "", "preview-root": "", "publish-root": ""}
	var args := OS.get_cmdline_user_args()
	var index := 0
	while index < args.size():
		if not str(args[index]).begins_with("--") or index + 1 >= args.size():
			_fail("Expected --name value")
			return {}
		var name := str(args[index]).trim_prefix("--")
		if not options.has(name):
			_fail("Unknown option --%s" % name)
			return {}
		options[name] = str(args[index + 1]).simplify_path()
		index += 2
	for name: String in options:
		if str(options[name]).is_empty():
			_fail("Missing --%s" % name)
	return options if _errors.is_empty() else {}


func _find_animation(candidate: Dictionary, animation_name: String) -> Dictionary:
	for animation_value: Variant in candidate.get("animations", []):
		var animation: Dictionary = animation_value
		if str(animation.get("name", "")) == animation_name:
			return animation
	_fail("%s is missing animation %s" % [candidate.get("name", "candidate"), animation_name])
	return {}


func _select_frames(candidate: Dictionary, animation_name: String) -> Array:
	var animation := _find_animation(candidate, animation_name)
	if animation.is_empty():
		return []
	var frames: Array = animation.get("frames", [])
	if frames.size() != 21:
		_fail("%s/%s must have 21 dense samples, got %d" % [candidate.get("name", "candidate"), animation_name, frames.size()])
		return []
	var duration := float(animation.get("duration", 0.0))
	var selection: Array = []
	for requested_value: Variant in KEY_TIMES[animation_name]:
		var requested := minf(float(requested_value), duration)
		var best: Dictionary = {}
		var best_delta := INF
		for frame_value: Variant in frames:
			var frame: Dictionary = frame_value
			var delta := absf(float(frame.get("sample_time", 0.0)) - requested)
			if delta < best_delta:
				best = frame
				best_delta = delta
		var max_delta := duration / 40.0 + 0.0002
		if best.is_empty() or best_delta > max_delta or not bool(best.get("passed", false)):
			_fail("%s/%s has no passing dense sample near %.6f" % [candidate.get("name", "candidate"), animation_name, requested])
			return []
		selection.append({"requested_time": requested, "actual_time": float(best.sample_time), "duration": duration, "delta": best_delta, "path": str(best.path), "passed": true})
	return selection


func _compose_sheet(preview_root: String, selection_a: Array, selection_b: Array) -> Image:
	var columns := maxi(selection_a.size(), selection_b.size())
	var sheet := Image.create(columns * CELL.x, CELL.y * 2 + ROW_GAP, false, Image.FORMAT_RGBA8)
	sheet.fill(SHEET_BG)
	for row in 2:
		var selection: Array = selection_a if row == 0 else selection_b
		var row_color := A_COLOR if row == 0 else B_COLOR
		for column in selection.size():
			var frame: Dictionary = selection[column]
			var path := preview_root.path_join(str(frame.path)).simplify_path()
			var image := Image.load_from_file(path)
			if image == null or image.is_empty():
				_fail("Could not load Vulkan frame %s" % path)
				return Image.new()
			var opaque := Image.create(image.get_width(), image.get_height(), false, Image.FORMAT_RGBA8)
			opaque.fill(GAME_BG)
			opaque.blend_rect(image, Rect2i(Vector2i.ZERO, image.get_size()), Vector2i.ZERO)
			opaque.resize(CELL.x, CELL.y, Image.INTERPOLATE_LANCZOS)
			var dest := Vector2i(column * CELL.x, row * (CELL.y + ROW_GAP))
			sheet.blit_rect(opaque, Rect2i(Vector2i.ZERO, CELL), dest)
			_draw_border(sheet, Rect2i(dest, CELL), PASS_COLOR if bool(frame.passed) else FAIL_COLOR)
			sheet.fill_rect(Rect2i(dest + Vector2i(4, 4), Vector2i(CELL.x - 8, 5)), row_color)
			var progress := clampf(float(frame.requested_time) / maxf(float(frame.duration), 0.0001), 0.0, 1.0)
			sheet.fill_rect(Rect2i(dest + Vector2i(4, CELL.y - 8), Vector2i(maxi(2, int((CELL.x - 8) * progress)), 4)), row_color)
	return sheet


func _draw_border(image: Image, rect: Rect2i, color: Color) -> void:
	image.fill_rect(Rect2i(rect.position, Vector2i(rect.size.x, 3)), color)
	image.fill_rect(Rect2i(rect.position + Vector2i(0, rect.size.y - 3), Vector2i(rect.size.x, 3)), color)
	image.fill_rect(Rect2i(rect.position, Vector2i(3, rect.size.y)), color)
	image.fill_rect(Rect2i(rect.position + Vector2i(rect.size.x - 3, 0), Vector2i(3, rect.size.y)), color)


func _compose_overview(sheets: Array[Image]) -> Image:
	var cell_size := Vector2i(1600, 280)
	var overview := Image.create(cell_size.x * 2, cell_size.y * 4, false, Image.FORMAT_RGBA8)
	overview.fill(SHEET_BG)
	for index in sheets.size():
		var image := (sheets[index] as Image).duplicate()
		image.resize(cell_size.x, cell_size.y, Image.INTERPOLATE_LANCZOS)
		var dest := Vector2i((index % 2) * cell_size.x, (index / 2) * cell_size.y)
		overview.blit_rect(image, Rect2i(Vector2i.ZERO, cell_size), dest)
	return overview


func _selection_report(selection: Array) -> Array:
	var result: Array = []
	for item_value: Variant in selection:
		var item: Dictionary = item_value
		result.append({
			"requested_time": item.requested_time,
			"actual_time": item.actual_time,
			"quantization_delta": item.delta,
			"source_frame": item.path,
			"passed": item.passed,
		})
	return result


func _fail(message: String) -> void:
	_errors.append(message)
	push_error("[semantic-split-v3-ab] %s" % message)


func _finish(code: int) -> void:
	if not _errors.is_empty():
		for message: String in _errors:
			print("ERROR: %s" % message)
	quit(code)
