extends SceneTree

## Static, read-only contract audit for the private character-select rig and
## its two semantic source layers.  It does not repack, resize, alter Alpha,
## start the game, or call a generation API.

const DEFAULT_OUTPUT := ".work/character-select-acceptance/sources-current"
const SPJSON := "Vivhite/Vivhite/skins/ironclad/spine/character_select/vivhite_character_select.spjson"
const SPATLAS := "Vivhite/Vivhite/skins/ironclad/spine/character_select/characterselect_ironclad.spatlas"
const PAGE := "Vivhite/Vivhite/skins/ironclad/spine/character_select/characterselect_ironclad.png"
const HERO_SOURCE := "assets/vivhite-ironclad/custom/character_select/sources/vivhite-character-select-hero-master-v1.png"
const SIGIL_SOURCE := "assets/vivhite-ironclad/custom/character_select/sources/vivhite-character-select-magic-sigil-v1.png"
const HERO_PAID_ORIGINAL := "assets/vivhite-ironclad/generated/evolink-paid/2026-08-28/0016-character-select-hero-attempt-04/output.png"
const SIGIL_PAID_ORIGINAL := "assets/vivhite-ironclad/generated/evolink-paid/2026-08-28/0017-character-select-magic-sigil-attempt-01/output.png"
const EXPECTED_PAGE_SIZE := Vector2i(3713, 2427)

var _errors: Array[String] = []
var _warnings: Array[String] = []
var _repo_root := ""
var _output_root := ""


func _initialize() -> void:
	call_deferred("_run")


func _fail(message: String) -> void:
	_errors.append(message)
	push_error("[character-select-source-audit] %s" % message)


func _warn(message: String) -> void:
	_warnings.append(message)
	push_warning("[character-select-source-audit] %s" % message)


func _find_repo_root() -> String:
	var current := ProjectSettings.globalize_path("res://").simplify_path()
	for _depth in range(8):
		if FileAccess.file_exists(current.path_join("AGENTS.md")):
			return current
		var parent := current.get_base_dir()
		if parent == current:
			break
		current = parent
	_fail("Could not locate repository root.")
	return ""


func _safe_output(requested: String) -> String:
	var work_root := _repo_root.path_join(".work").simplify_path()
	var output := requested
	if not output.is_absolute_path():
		output = _repo_root.path_join(output)
	output = output.simplify_path()
	var prefix := work_root.replace("\\", "/").to_lower().trim_suffix("/") + "/"
	if not output.replace("\\", "/").to_lower().begins_with(prefix):
		_fail("Output must stay below .work: %s" % output)
		return ""
	return output


func _text(relative_path: String) -> String:
	var absolute := _repo_root.path_join(relative_path).simplify_path()
	var file := FileAccess.open(absolute, FileAccess.READ)
	if file == null:
		_fail("Could not read %s." % relative_path)
		return ""
	var result := file.get_as_text()
	file.close()
	return result


func _edge_metrics(image: Image) -> Dictionary:
	var result := {
		"top": {"positive": 0, "visible_16": 0, "opaque_240": 0, "max_alpha": 0},
		"right": {"positive": 0, "visible_16": 0, "opaque_240": 0, "max_alpha": 0},
		"bottom": {"positive": 0, "visible_16": 0, "opaque_240": 0, "max_alpha": 0},
		"left": {"positive": 0, "visible_16": 0, "opaque_240": 0, "max_alpha": 0},
	}
	for y in range(image.get_height()):
		for x in range(image.get_width()):
			if x != 0 and y != 0 and x != image.get_width() - 1 and y != image.get_height() - 1:
				continue
			var alpha := image.get_pixel(x, y).a8
			var names: Array[String] = []
			if y == 0:
				names.append("top")
			if x == image.get_width() - 1:
				names.append("right")
			if y == image.get_height() - 1:
				names.append("bottom")
			if x == 0:
				names.append("left")
			for name in names:
				var edge: Dictionary = result[name]
				edge.max_alpha = maxi(int(edge.max_alpha), alpha)
				if alpha > 0:
					edge.positive = int(edge.positive) + 1
				if alpha >= 16:
					edge.visible_16 = int(edge.visible_16) + 1
				if alpha >= 240:
					edge.opaque_240 = int(edge.opaque_240) + 1
	return result


func _image_report(relative_path: String) -> Dictionary:
	var absolute := _repo_root.path_join(relative_path).simplify_path()
	var image := Image.load_from_file(absolute)
	if image == null or image.is_empty():
		_fail("Could not load PNG %s." % relative_path)
		return {}
	var source_format := int(image.get_format())
	if image.get_format() != Image.FORMAT_RGBA8:
		image.convert(Image.FORMAT_RGBA8)
	var corners := [
		image.get_pixel(0, 0).a8,
		image.get_pixel(image.get_width() - 1, 0).a8,
		image.get_pixel(0, image.get_height() - 1).a8,
		image.get_pixel(image.get_width() - 1, image.get_height() - 1).a8,
	]
	if corners != [0, 0, 0, 0]:
		_fail("%s has a non-transparent corner: %s." % [relative_path, corners])
	var used := image.get_used_rect()
	var touches_edge := used.has_area() and (
		used.position.x <= 0
		or used.position.y <= 0
		or used.end.x >= image.get_width()
		or used.end.y >= image.get_height()
	)
	if touches_edge:
		_warn("%s has non-zero Alpha touching an edge; inspect edge metrics." % relative_path)
	return {
		"path": relative_path,
		"sha256": FileAccess.get_sha256(absolute),
		"source_format": source_format,
		"decoded_format": "RGBA8" if image.get_format() == Image.FORMAT_RGBA8 else str(int(image.get_format())),
		"size": [image.get_width(), image.get_height()],
		"corners_alpha": corners,
		"used_rect": [used.position.x, used.position.y, used.size.x, used.size.y],
		"touches_edge": touches_edge,
		"edges": _edge_metrics(image),
	}


func _mesh_report(attachment: Dictionary) -> Dictionary:
	var uvs: Array = attachment.get("uvs", [])
	var vertices: Array = attachment.get("vertices", [])
	var triangles: Array = attachment.get("triangles", [])
	var vertex_count := uvs.size() / 2
	var cursor := 0
	var influences := 0
	var encoding_valid := true
	for _vertex in range(vertex_count):
		if cursor >= vertices.size():
			encoding_valid = false
			break
		var bone_count := int(vertices[cursor])
		cursor += 1
		influences += bone_count
		cursor += bone_count * 4
		if cursor > vertices.size():
			encoding_valid = false
			break
	encoding_valid = encoding_valid and cursor == vertices.size()
	if not encoding_valid:
		_fail("Hero weighted-mesh vertex encoding is malformed.")
	return {
		"type": attachment.get("type", "region"),
		"path": attachment.get("path", ""),
		"vertex_count": vertex_count,
		"influence_count": influences,
		"triangle_count": triangles.size() / 3,
		"hull": attachment.get("hull", 0),
		"encoding_valid": encoding_valid,
	}


func _write_report(report: Dictionary) -> void:
	DirAccess.make_dir_recursive_absolute(_output_root)
	var path := _output_root.path_join("report.json")
	var file := FileAccess.open(path, FileAccess.WRITE)
	if file == null:
		_fail("Could not write report: %s" % path)
		return
	file.store_string(JSON.stringify(report, "\t") + "\n")
	file.close()
	print("[character-select-source-audit] Report: %s" % path)


func _run() -> void:
	_repo_root = _find_repo_root()
	if _repo_root.is_empty():
		quit(1)
		return
	var requested_output := DEFAULT_OUTPUT
	var args := OS.get_cmdline_user_args()
	if args.size() == 2 and str(args[0]) == "--output":
		requested_output = str(args[1])
	elif not args.is_empty():
		_fail("Usage: --output .work/path")
	_output_root = _safe_output(requested_output)
	if _output_root.is_empty():
		quit(1)
		return

	var parsed: Variant = JSON.parse_string(_text(SPJSON))
	if not parsed is Dictionary:
		_fail("Could not parse %s." % SPJSON)
		parsed = {}
	var skeleton: Dictionary = parsed
	var bone_names: Array[String] = []
	for bone: Dictionary in skeleton.get("bones", []):
		bone_names.append(str(bone.get("name", "")))
	var slots: Array = skeleton.get("slots", [])
	var slot_names: Array[String] = []
	for slot: Dictionary in slots:
		slot_names.append(str(slot.get("name", "")))
	var skin_names: Array[String] = []
	var default_skin: Dictionary = {}
	for skin: Dictionary in skeleton.get("skins", []):
		var skin_name := str(skin.get("name", ""))
		skin_names.append(skin_name)
		if skin_name == "default":
			default_skin = skin
	var animations: Dictionary = skeleton.get("animations", {})
	var animation_names: Array[String] = []
	for animation_name in animations.keys():
		animation_names.append(str(animation_name))
	animation_names.sort()
	if animation_names != ["animation"]:
		_fail("Expected exactly ['animation'], got %s." % animation_names)
	if default_skin.is_empty():
		_fail("Rig has no default skin.")
	if slot_names != ["vivhite_magic_backdrop", "vivhite_hero"]:
		_fail("Unexpected slot order: %s." % slot_names)

	var attachments: Dictionary = default_skin.get("attachments", {})
	var hero_attachment: Dictionary = (
		attachments.get("vivhite_hero", {})
		.get("vivhite_character_select_hero", {})
	)
	var sigil_attachment: Dictionary = (
		attachments.get("vivhite_magic_backdrop", {})
		.get("vivhite_character_select_magic_sigil", {})
	)
	if hero_attachment.is_empty() or sigil_attachment.is_empty():
		_fail("Default skin does not expose both semantic attachments.")
	var animation: Dictionary = animations.get("animation", {})
	var timeline_bones: Array[String] = []
	for timeline_bone in (animation.get("bones", {}) as Dictionary).keys():
		timeline_bones.append(str(timeline_bone))
	timeline_bones.sort()
	if not timeline_bones.has("vivhite_magic_backdrop") or not timeline_bones.has("vivhite_rig"):
		_fail("Animation does not drive both sigil and hero roots.")

	var spatlas_value: Variant = JSON.parse_string(_text(SPATLAS))
	if not spatlas_value is Dictionary:
		_fail("Could not parse %s." % SPATLAS)
		spatlas_value = {}
	var atlas_data := str((spatlas_value as Dictionary).get("atlas_data", ""))
	for required in [
		"characterselect_ironclad.png\n",
		"size:3713,2427\n",
		"filter:Linear,Linear\n",
		"pma:false\n",
		"scale:0.5\n",
		"vivhite_character_select_hero\nbounds:12,12,2286,2400\n",
		"vivhite_character_select_magic_sigil\nbounds:2310,12,1380,1380\n",
	]:
		if not atlas_data.contains(required):
			_fail("Atlas data is missing exact contract text: %s" % required.replace("\n", "\\n"))

	var hero_source := _image_report(HERO_SOURCE)
	var sigil_source := _image_report(SIGIL_SOURCE)
	var page := _image_report(PAGE)
	if Vector2i(int(page.size[0]), int(page.size[1])) != EXPECTED_PAGE_SIZE:
		_fail("Packed page size is %s, expected %s." % [page.size, EXPECTED_PAGE_SIZE])
	var hero_paid_hash := FileAccess.get_sha256(_repo_root.path_join(HERO_PAID_ORIGINAL))
	var sigil_paid_hash := FileAccess.get_sha256(_repo_root.path_join(SIGIL_PAID_ORIGINAL))
	if str(hero_source.get("sha256", "")) != hero_paid_hash:
		_fail("Hero source is not byte-identical to paid original 0016.")
	if str(sigil_source.get("sha256", "")) != sigil_paid_hash:
		_fail("Sigil source is not byte-identical to paid original 0017.")

	var report := {
		"schema_version": 1,
		"success": false,
		"spine": {
			"path": SPJSON,
			"version": (skeleton.get("skeleton", {}) as Dictionary).get("spine", ""),
			"bone_count": bone_names.size(),
			"bone_names": bone_names,
			"slot_order": slot_names,
			"skin_names": skin_names,
			"animation_names": animation_names,
			"animation_bone_timelines": timeline_bones,
			"slot_timelines_present": animation.has("slots"),
			"hero_mesh": _mesh_report(hero_attachment),
			"sigil_attachment": sigil_attachment,
		},
		"atlas": {
			"path": SPATLAS,
			"page": page,
			"regions": [
				{"name": "vivhite_character_select_hero", "bounds": [12, 12, 2286, 2400]},
				{"name": "vivhite_character_select_magic_sigil", "bounds": [2310, 12, 1380, 1380]},
			],
			"pma": false,
			"filter": "Linear,Linear",
			"scale": 0.5,
		},
		"sources": {
			"hero": hero_source,
			"hero_paid_original": HERO_PAID_ORIGINAL,
			"hero_byte_identical_to_paid_original": str(hero_source.get("sha256", "")) == hero_paid_hash,
			"sigil": sigil_source,
			"sigil_paid_original": SIGIL_PAID_ORIGINAL,
			"sigil_byte_identical_to_paid_original": str(sigil_source.get("sha256", "")) == sigil_paid_hash,
		},
		"warnings": [],
		"errors": [],
	}
	report.warnings = _warnings.duplicate()
	report.errors = _errors.duplicate()
	report.success = _errors.is_empty()
	_write_report(report)
	quit(0 if report.success else 1)
