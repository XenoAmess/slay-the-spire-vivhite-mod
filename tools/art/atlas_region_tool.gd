extends SceneTree

## Deterministic Spine-atlas region workspace tool.
##
## The tool deliberately treats the checked-in .atlas text as immutable source
## of truth.  Region masters are stored unrotated at their trimmed logical
## `bounds` size.  Packing resamples each master independently and then applies
## the page's original rotate:90 flag, so combat and merchant can use the same
## artwork workflow despite their different packing layouts.

const FORMAT_VERSION := 1
const LAYOUT_FILE := "atlas-layout.json"
const PACK_REPORT_FILE := "atlas-pack-report.json"
const WEAPON_REGIONS := {
	"sword blade": true,
	"sword_handle": true,
}
const SPELL_LAYER_REGIONS := {
	"sword blade": true,
}
const SPELL_ALPHA_MAX := 191
const DOMAIN_ATLASES := {
	"combat": "combat/ironclad.atlas",
	"merchant": "merchant/ironclad_shop.atlas",
	"rest_site": "rest_site/restsite_ironclad.atlas",
	"character_select": "character_select/characterselect_ironclad.atlas",
}
const FLAG_OPTIONS := {
	"--force-layout": true,
	"--replace-masters": true,
	"--force-work": true,
}

var _last_error := ""


func _initialize() -> void:
	var status := _run(OS.get_cmdline_user_args())
	quit(status)


func _run(args: PackedStringArray) -> int:
	if args.is_empty() or args[0] in ["-h", "--help", "help"]:
		_print_help()
		return 0

	var parsed := _parse_options(args)
	if parsed.is_empty():
		return _fail("Invalid command-line options. Use --help for usage.")

	var command: String = parsed["command"]
	var options: Dictionary = parsed["options"]
	match command:
		"unpack":
			return _command_unpack(options)
		"pack":
			return _command_pack(options)
		"init-all":
			return _command_init_all(options)
		"verify-roundtrip":
			return _command_verify_roundtrip(options)
		"verify-all":
			return _command_verify_all(options)
		_:
			return _fail("Unknown command: %s" % command)


func _parse_options(args: PackedStringArray) -> Dictionary:
	var options := {}
	var index := 1
	while index < args.size():
		var token := args[index]
		if not token.begins_with("--"):
			printerr("Unexpected positional argument: %s" % token)
			return {}
		if FLAG_OPTIONS.has(token):
			options[token.trim_prefix("--")] = true
			index += 1
			continue
		if index + 1 >= args.size() or args[index + 1].begins_with("--"):
			printerr("Missing value for option: %s" % token)
			return {}
		options[token.trim_prefix("--")] = args[index + 1]
		index += 2
	return {"command": args[0], "options": options}


func _command_unpack(options: Dictionary) -> int:
	var atlas_path := _required_path(options, "atlas")
	var output_path := _required_path(options, "output")
	if atlas_path.is_empty() or output_path.is_empty():
		return 2
	var result := _unpack_atlas(
		atlas_path,
		output_path,
		bool(options.get("replace-masters", false)),
		bool(options.get("force-layout", false))
	)
	if not result:
		return _fail(_last_error)
	return 0


func _command_pack(options: Dictionary) -> int:
	var workspace := _required_path(options, "workspace")
	if workspace.is_empty():
		return 2
	var output := _absolute_path(str(options.get("output", workspace)))
	var policy := str(options.get("weapon-policy", "clear"))
	if policy not in ["clear", "spell"]:
		return _fail("--weapon-policy must be clear or spell. Preserve is reserved for round-trip verification.")
	var result := _pack_workspace(workspace, output, policy, "")
	if not result:
		return _fail(_last_error)
	return 0


func _command_init_all(options: Dictionary) -> int:
	var source_root := _required_path(options, "source-root")
	var custom_root := _required_path(options, "custom-root")
	if source_root.is_empty() or custom_root.is_empty():
		return 2
	var replace_masters := bool(options.get("replace-masters", false))
	var force_layout := bool(options.get("force-layout", false))
	for domain: String in DOMAIN_ATLASES:
		var atlas_path := source_root.path_join(str(DOMAIN_ATLASES[domain]))
		var output_path := custom_root.path_join(domain)
		if not _unpack_atlas(atlas_path, output_path, replace_masters, force_layout):
			return _fail("%s: %s" % [domain, _last_error])
	print("Initialized all four atlas workspaces under %s" % custom_root)
	return 0


func _command_verify_roundtrip(options: Dictionary) -> int:
	var atlas_path := _required_path(options, "atlas")
	var work_path := _required_path(options, "work")
	if atlas_path.is_empty() or work_path.is_empty():
		return 2
	if not _verify_roundtrip(atlas_path, work_path, bool(options.get("force-work", false))):
		return _fail(_last_error)
	return 0


func _command_verify_all(options: Dictionary) -> int:
	var source_root := _required_path(options, "source-root")
	var work_root := _required_path(options, "work-root")
	if source_root.is_empty() or work_root.is_empty():
		return 2
	var force_work := bool(options.get("force-work", false))
	for domain: String in DOMAIN_ATLASES:
		var atlas_path := source_root.path_join(str(DOMAIN_ATLASES[domain]))
		var work_path := work_root.path_join(domain)
		if not _verify_roundtrip(atlas_path, work_path, force_work):
			return _fail("%s: %s" % [domain, _last_error])
	print("All four atlases passed byte/pixel round-trip verification.")
	return 0


func _required_path(options: Dictionary, key: String) -> String:
	if not options.has(key) or str(options[key]).is_empty():
		printerr("Missing required option --%s" % key)
		return ""
	return _absolute_path(str(options[key]))


func _absolute_path(path: String) -> String:
	if path.is_absolute_path():
		return path.simplify_path()
	# The minimal Godot project lives at <repo>/tools/art. Resolve CLI-relative
	# paths against the repository root so documented commands are independent
	# of Godot's process working-directory behavior.
	var repository_root := ProjectSettings.globalize_path("res://").path_join("../..").simplify_path()
	return repository_root.path_join(path).simplify_path()


func _unpack_atlas(atlas_path: String, output_path: String, replace_masters: bool, force_layout: bool) -> bool:
	_last_error = ""
	if not FileAccess.file_exists(atlas_path):
		return _set_error("Atlas does not exist: %s" % atlas_path)
	var parsed := _parse_atlas(atlas_path)
	if parsed.is_empty():
		return false
	if not _validate_source_pages(parsed, atlas_path.get_base_dir()):
		return false

	var layout_path := output_path.path_join(LAYOUT_FILE)
	var local_atlas_path := output_path.path_join(atlas_path.get_file())
	if FileAccess.file_exists(layout_path) and not force_layout:
		var existing_atlas_hash := ""
		var existing_layout = JSON.parse_string(FileAccess.get_file_as_string(layout_path))
		if existing_layout is Dictionary:
			existing_atlas_hash = str(existing_layout.get("atlas_sha256", ""))
		var source_hash := FileAccess.get_sha256(atlas_path)
		if existing_atlas_hash != source_hash:
			return _set_error(
				"Workspace layout belongs to another atlas. Pass --force-layout to replace layout metadata; masters remain protected unless --replace-masters is also supplied."
			)

	if not _make_dir(output_path):
		return false
	if not _copy_file_exact(atlas_path, local_atlas_path):
		return false

	var manifest_pages: Array = []
	var created := 0
	var kept := 0
	for page: Dictionary in parsed["pages"]:
		var source_page_path := atlas_path.get_base_dir().path_join(str(page["name"]))
		var page_image := _load_rgba(source_page_path)
		if page_image == null:
			return false
		var manifest_regions: Array = []
		for region: Dictionary in page["regions"]:
			var master_rel := _master_relative_path(str(region["name"]))
			if master_rel.is_empty():
				return false
			var master_path := output_path.path_join(master_rel)
			var logical_image := _extract_logical_region(page_image, region)
			if logical_image == null:
				return false
			if FileAccess.file_exists(master_path) and not replace_masters:
				kept += 1
			else:
				if not _save_png(logical_image, master_path):
					return false
				created += 1
			manifest_regions.append({
				"name": region["name"],
				"master": master_rel.replace("\\", "/"),
				"bounds": region["bounds"],
				"packed_rect": region["packed_rect"],
				"rotate": region["rotate"],
				"offsets": region["offsets"],
				"alpha_bbox": _rect_to_array(logical_image.get_used_rect()),
				"weapon_attachment": WEAPON_REGIONS.has(region["name"]),
			})
		manifest_pages.append({
			"name": page["name"],
			"size": page["size"],
			"source_png_sha256": FileAccess.get_sha256(source_page_path),
			"regions": manifest_regions,
		})

	var manifest := {
		"format_version": FORMAT_VERSION,
		"atlas_file": atlas_path.get_file(),
		"atlas_sha256": FileAccess.get_sha256(atlas_path),
		"logical_master_rule": "unrotated trimmed bounds; offsets are retained unchanged in the atlas",
		"default_weapon_policy": "clear",
		"spell_alpha_max": SPELL_ALPHA_MAX,
		"manual_weapon_audit": ["top arm"] if atlas_path.get_file().begins_with("characterselect_") else [],
		"pages": manifest_pages,
	}
	if not _write_text(layout_path, JSON.stringify(manifest, "\t", false) + "\n"):
		return false
	print("Unpacked %d regions from %s (%d created/replaced, %d existing masters kept)." % [
		_count_regions(parsed), atlas_path.get_file(), created, kept
	])
	return true


func _pack_workspace(workspace: String, output: String, weapon_policy: String, preserve_page_root: String) -> bool:
	_last_error = ""
	var atlas_path := _find_workspace_atlas(workspace)
	if atlas_path.is_empty():
		return false
	if not _validate_workspace_layout(workspace, atlas_path):
		return false
	var parsed := _parse_atlas(atlas_path)
	if parsed.is_empty():
		return false
	if not _make_dir(output):
		return false
	var output_atlas := output.path_join(atlas_path.get_file())
	if output_atlas != atlas_path and not _copy_file_exact(atlas_path, output_atlas):
		return false

	var report_pages: Array = []
	var resized_count := 0
	var cleared_count := 0
	var spell_count := 0
	for page: Dictionary in parsed["pages"]:
		var page_size: Array = page["size"]
		var packed_page: Image
		if not preserve_page_root.is_empty():
			var preserve_path := preserve_page_root.path_join(str(page["name"]))
			packed_page = _load_rgba(preserve_path)
			if packed_page == null:
				return false
		else:
			packed_page = Image.create(int(page_size[0]), int(page_size[1]), false, Image.FORMAT_RGBA8)
			packed_page.fill(Color(0, 0, 0, 0))
		var region_reports: Array = []
		for region: Dictionary in page["regions"]:
			var region_name := str(region["name"])
			var bounds: Array = region["bounds"]
			var target_size := Vector2i(int(bounds[2]), int(bounds[3]))
			var logical_image: Image
			var source_kind := "master"
			if weapon_policy == "clear" and WEAPON_REGIONS.has(region_name):
				logical_image = _transparent_image(target_size)
				source_kind = "forced-transparent"
				cleared_count += 1
			elif weapon_policy == "spell" and region_name == "sword_handle":
				logical_image = _transparent_image(target_size)
				source_kind = "forced-empty-hand"
				cleared_count += 1
			elif weapon_policy == "spell" and SPELL_LAYER_REGIONS.has(region_name):
				var spell_path := workspace.path_join(_spell_relative_path(region_name))
				if FileAccess.file_exists(spell_path):
					logical_image = _load_rgba(spell_path)
					if logical_image == null:
						return false
					_clamp_alpha(logical_image, SPELL_ALPHA_MAX)
					source_kind = "alpha-clamped-spell-layer"
					spell_count += 1
				else:
					logical_image = _transparent_image(target_size)
					source_kind = "missing-spell-layer-transparent"
					cleared_count += 1
			else:
				var master_path := workspace.path_join(_master_relative_path(region_name))
				logical_image = _load_rgba(master_path)
				if logical_image == null:
					return false
			if logical_image.get_size() != target_size:
				logical_image.resize(target_size.x, target_size.y, Image.INTERPOLATE_LANCZOS)
				resized_count += 1
			if source_kind == "alpha-clamped-spell-layer":
				# Lanczos filtering may overshoot a channel by a small amount, so
				# enforce the transparency ceiling again at the final logical size.
				_clamp_alpha(logical_image, SPELL_ALPHA_MAX)
			var maximum_alpha := _max_alpha(logical_image)
			if source_kind in ["forced-transparent", "forced-empty-hand", "missing-spell-layer-transparent"] and maximum_alpha != 0:
				return _set_error("Empty-hand policy failed for region %s" % region_name)
			if source_kind == "alpha-clamped-spell-layer" and maximum_alpha > SPELL_ALPHA_MAX:
				return _set_error("Spell alpha policy failed for region %s" % region_name)
			if int(region["rotate"]) == 90:
				logical_image.rotate_90(CLOCKWISE)
			var packed_rect := _array_to_rect(region["packed_rect"])
			if logical_image.get_size() != packed_rect.size:
				return _set_error("Packed size mismatch for region %s" % region_name)
			packed_page.blit_rect(logical_image, Rect2i(Vector2i.ZERO, logical_image.get_size()), packed_rect.position)
			region_reports.append({
				"name": region_name,
				"source": source_kind,
				"max_alpha": maximum_alpha,
				"packed_rect": region["packed_rect"],
			})
		var page_path := output.path_join(str(page["name"]))
		if not _save_png(packed_page, page_path):
			return false
		report_pages.append({
			"name": page["name"],
			"size": page_size,
			"png_sha256": FileAccess.get_sha256(page_path),
			"regions": region_reports,
		})

	var report := {
		"format_version": FORMAT_VERSION,
		"atlas_file": atlas_path.get_file(),
		"atlas_sha256": FileAccess.get_sha256(atlas_path),
		"weapon_policy": weapon_policy,
		"resized_region_count": resized_count,
		"forced_transparent_region_count": cleared_count,
		"spell_layer_region_count": spell_count,
		"pages": report_pages,
	}
	if not _write_text(output.path_join(PACK_REPORT_FILE), JSON.stringify(report, "\t", false) + "\n"):
		return false
	print("Packed %d regions to %s (policy=%s, resized=%d, transparent=%d, spell=%d)." % [
		_count_regions(parsed), output, weapon_policy, resized_count, cleared_count, spell_count
	])
	return true


func _verify_roundtrip(atlas_path: String, work_path: String, force_work: bool) -> bool:
	_last_error = ""
	if DirAccess.dir_exists_absolute(work_path) and not force_work:
		return _set_error("Verification work directory already exists; choose a new path or pass --force-work: %s" % work_path)
	if not _unpack_atlas(atlas_path, work_path, true, true):
		return false
	var parsed := _parse_atlas(atlas_path)
	if parsed.is_empty():
		return false
	# `preserve` is intentionally internal: it starts from the original padding
	# pixels and proves unpack -> unrotate -> rotate -> pack is lossless.
	if not _pack_workspace(work_path, work_path, "preserve", atlas_path.get_base_dir()):
		return false

	var copied_atlas := work_path.path_join(atlas_path.get_file())
	if FileAccess.get_sha256(atlas_path) != FileAccess.get_sha256(copied_atlas):
		return _set_error("Atlas text changed during round trip: %s" % atlas_path.get_file())
	for page: Dictionary in parsed["pages"]:
		var source_path := atlas_path.get_base_dir().path_join(str(page["name"]))
		var packed_path := work_path.path_join(str(page["name"]))
		var source_image := _load_rgba(source_path)
		var packed_image := _load_rgba(packed_path)
		if source_image == null or packed_image == null:
			return false
		if source_image.get_size() != packed_image.get_size() or source_image.get_data() != packed_image.get_data():
			return _set_error("Pixel round trip differs for page %s" % page["name"])
		var byte_exact := FileAccess.get_sha256(source_path) == FileAccess.get_sha256(packed_path)
		print("[PASS] %s pixels exact; PNG bytes %s" % [page["name"], "exact" if byte_exact else "re-encoded"])
	print("[PASS] %s atlas bytes and all page pixels are exact." % atlas_path.get_file())
	return true


func _parse_atlas(atlas_path: String) -> Dictionary:
	var text := FileAccess.get_file_as_string(atlas_path)
	if text.is_empty():
		_set_error("Atlas is empty or unreadable: %s" % atlas_path)
		return {}
	var pages: Array = []
	var current_page: Dictionary = {}
	var current_region: Dictionary = {}
	var after_blank := true
	for raw_line: String in text.split("\n", true):
		var line := raw_line.strip_edges()
		if line.is_empty():
			after_blank = true
			current_region = {}
			continue
		if current_page.is_empty() or (after_blank and line.to_lower().ends_with(".png")):
			current_page = {"name": line, "headers": {}, "regions": []}
			pages.append(current_page)
			current_region = {}
			after_blank = false
			continue
		after_blank = false
		var colon := line.find(":")
		if colon < 0:
			current_region = {"name": line, "properties": {}}
			current_page["regions"].append(current_region)
			continue
		var key := line.substr(0, colon).strip_edges()
		var value := line.substr(colon + 1).strip_edges()
		if current_region.is_empty():
			current_page["headers"][key] = value
		else:
			current_region["properties"][key] = value

	var seen_names := {}
	for page: Dictionary in pages:
		var size_values := _parse_int_list(str(page["headers"].get("size", "")), 2)
		if size_values.is_empty():
			_set_error("Page %s has no valid size header" % page["name"])
			return {}
		page["size"] = size_values
		var packed_rects: Array[Rect2i] = []
		for region: Dictionary in page["regions"]:
			var name := str(region["name"])
			if seen_names.has(name):
				_set_error("Duplicate region name is not supported: %s" % name)
				return {}
			seen_names[name] = true
			if _master_relative_path(name).is_empty():
				return {}
			var properties: Dictionary = region["properties"]
			var bounds := _parse_int_list(str(properties.get("bounds", "")), 4)
			if bounds.is_empty() or int(bounds[2]) <= 0 or int(bounds[3]) <= 0:
				_set_error("Region %s has invalid bounds" % name)
				return {}
			var rotate_value := str(properties.get("rotate", "0")).to_lower()
			var rotation := 90 if rotate_value in ["90", "true"] else 0
			if rotate_value not in ["0", "false", "90", "true"]:
				_set_error("Only rotate:90 is supported; %s uses %s" % [name, rotate_value])
				return {}
			var packed_width := int(bounds[3]) if rotation == 90 else int(bounds[2])
			var packed_height := int(bounds[2]) if rotation == 90 else int(bounds[3])
			var packed_rect := Rect2i(int(bounds[0]), int(bounds[1]), packed_width, packed_height)
			var page_rect := Rect2i(0, 0, int(size_values[0]), int(size_values[1]))
			if not page_rect.encloses(packed_rect):
				_set_error("Region %s is outside page %s" % [name, page["name"]])
				return {}
			for other: Rect2i in packed_rects:
				if other.intersects(packed_rect):
					_set_error("Packed regions overlap on page %s near %s" % [page["name"], name])
					return {}
			packed_rects.append(packed_rect)
			var offsets := _parse_int_list(str(properties.get("offsets", "")), 4)
			if offsets.is_empty():
				offsets = [0, 0, int(bounds[2]), int(bounds[3])]
			region["bounds"] = bounds
			region["rotate"] = rotation
			region["offsets"] = offsets
			region["packed_rect"] = _rect_to_array(packed_rect)
	return {"pages": pages, "atlas_text": text}


func _validate_source_pages(parsed: Dictionary, page_root: String) -> bool:
	for page: Dictionary in parsed["pages"]:
		var page_path := page_root.path_join(str(page["name"]))
		var image := _load_rgba(page_path)
		if image == null:
			return false
		var size: Array = page["size"]
		if image.get_width() != int(size[0]) or image.get_height() != int(size[1]):
			return _set_error("Page dimensions differ from atlas header: %s" % page_path)
	return true


func _extract_logical_region(page_image: Image, region: Dictionary) -> Image:
	var packed_rect := _array_to_rect(region["packed_rect"])
	var logical := page_image.get_region(packed_rect)
	if logical == null or logical.is_empty():
		_set_error("Could not crop region %s" % region["name"])
		return null
	if int(region["rotate"]) == 90:
		logical.rotate_90(COUNTERCLOCKWISE)
	var bounds: Array = region["bounds"]
	var expected := Vector2i(int(bounds[2]), int(bounds[3]))
	if logical.get_size() != expected:
		_set_error("Logical size mismatch for region %s" % region["name"])
		return null
	return logical


func _find_workspace_atlas(workspace: String) -> String:
	if not DirAccess.dir_exists_absolute(workspace):
		_set_error("Workspace does not exist: %s" % workspace)
		return ""
	var atlases: PackedStringArray = []
	for name: String in DirAccess.get_files_at(workspace):
		if name.to_lower().ends_with(".atlas"):
			atlases.append(name)
	if atlases.size() != 1:
		_set_error("Workspace must contain exactly one .atlas file: %s" % workspace)
		return ""
	return workspace.path_join(atlases[0])


func _validate_workspace_layout(workspace: String, atlas_path: String) -> bool:
	var layout_path := workspace.path_join(LAYOUT_FILE)
	if not FileAccess.file_exists(layout_path):
		return _set_error("Workspace is missing %s: %s" % [LAYOUT_FILE, workspace])
	var layout = JSON.parse_string(FileAccess.get_file_as_string(layout_path))
	if not layout is Dictionary:
		return _set_error("Workspace layout is not valid JSON: %s" % layout_path)
	if int(layout.get("format_version", -1)) != FORMAT_VERSION:
		return _set_error("Unsupported workspace layout version: %s" % layout_path)
	if str(layout.get("atlas_file", "")) != atlas_path.get_file():
		return _set_error("Workspace atlas filename differs from the initialized layout")
	if str(layout.get("atlas_sha256", "")) != FileAccess.get_sha256(atlas_path):
		return _set_error(
			"Atlas metadata changed after initialization. Restore it or explicitly re-run unpack with --force-layout; page names, bounds, rotate and offsets are immutable."
		)
	return true


func _master_relative_path(region_name: String) -> String:
	var normalized := region_name.replace("\\", "/")
	var invalid_chars := '<>:"|?*'
	for component: String in normalized.split("/", false):
		if component in ["", ".", ".."]:
			_set_error("Unsafe region path component in %s" % region_name)
			return ""
		for invalid: String in invalid_chars:
			if component.contains(invalid):
				_set_error("Region name cannot be represented safely on Windows: %s" % region_name)
				return ""
	return "regions".path_join(normalized + ".png")


func _spell_relative_path(region_name: String) -> String:
	var master_path := _master_relative_path(region_name)
	if master_path.is_empty():
		return ""
	return "spell_layers".path_join(master_path.trim_prefix("regions/"))


func _parse_int_list(value: String, expected: int) -> Array:
	if value.is_empty():
		return []
	var result: Array = []
	for part: String in value.split(",", false):
		var stripped := part.strip_edges()
		if not stripped.is_valid_int():
			return []
		result.append(stripped.to_int())
	return result if result.size() == expected else []


func _load_rgba(path: String) -> Image:
	if not FileAccess.file_exists(path):
		_set_error("PNG does not exist: %s" % path)
		return null
	var image := Image.load_from_file(path)
	if image == null or image.is_empty():
		_set_error("Could not load PNG: %s" % path)
		return null
	if image.get_format() != Image.FORMAT_RGBA8:
		image.convert(Image.FORMAT_RGBA8)
	return image


func _transparent_image(size: Vector2i) -> Image:
	var image := Image.create(size.x, size.y, false, Image.FORMAT_RGBA8)
	image.fill(Color(0, 0, 0, 0))
	return image


func _clamp_alpha(image: Image, maximum: int) -> void:
	if image.get_format() != Image.FORMAT_RGBA8:
		image.convert(Image.FORMAT_RGBA8)
	var bytes := image.get_data()
	for index in range(3, bytes.size(), 4):
		if bytes[index] > maximum:
			bytes[index] = maximum
	image.set_data(image.get_width(), image.get_height(), false, Image.FORMAT_RGBA8, bytes)


func _max_alpha(image: Image) -> int:
	if image.get_format() != Image.FORMAT_RGBA8:
		image.convert(Image.FORMAT_RGBA8)
	var bytes := image.get_data()
	var maximum := 0
	for index in range(3, bytes.size(), 4):
		maximum = maxi(maximum, int(bytes[index]))
	return maximum


func _save_png(image: Image, path: String) -> bool:
	if not _make_dir(path.get_base_dir()):
		return false
	var error := image.save_png(path)
	if error != OK:
		return _set_error("Could not save PNG (%s): %s" % [error_string(error), path])
	return true


func _copy_file_exact(source: String, destination: String) -> bool:
	if source == destination:
		return true
	if not _make_dir(destination.get_base_dir()):
		return false
	var source_file := FileAccess.open(source, FileAccess.READ)
	if source_file == null:
		return _set_error("Could not open source file: %s" % source)
	var bytes := source_file.get_buffer(source_file.get_length())
	var output_file := FileAccess.open(destination, FileAccess.WRITE)
	if output_file == null:
		return _set_error("Could not open destination file: %s" % destination)
	output_file.store_buffer(bytes)
	output_file.close()
	return true


func _write_text(path: String, content: String) -> bool:
	if not _make_dir(path.get_base_dir()):
		return false
	var file := FileAccess.open(path, FileAccess.WRITE)
	if file == null:
		return _set_error("Could not write file: %s" % path)
	file.store_string(content)
	file.close()
	return true


func _make_dir(path: String) -> bool:
	if DirAccess.dir_exists_absolute(path):
		return true
	var error := DirAccess.make_dir_recursive_absolute(path)
	if error != OK:
		return _set_error("Could not create directory (%s): %s" % [error_string(error), path])
	return true


func _count_regions(parsed: Dictionary) -> int:
	var count := 0
	for page: Dictionary in parsed["pages"]:
		count += page["regions"].size()
	return count


func _rect_to_array(rect: Rect2i) -> Array:
	return [rect.position.x, rect.position.y, rect.size.x, rect.size.y]


func _array_to_rect(values: Array) -> Rect2i:
	return Rect2i(int(values[0]), int(values[1]), int(values[2]), int(values[3]))


func _set_error(message: String) -> bool:
	_last_error = message
	return false


func _fail(message: String) -> int:
	printerr("ERROR: %s" % message)
	return 2


func _print_help() -> void:
	print("""Spine atlas region workspace tool

Usage (arguments after Godot's -- separator):
  unpack --atlas <file.atlas> --output <workspace> [--replace-masters] [--force-layout]
  pack --workspace <workspace> [--output <directory>] [--weapon-policy clear|spell]
  init-all --source-root <assets/ironclad-v0.111.0> --custom-root <assets/vivhite-ironclad/custom>
           [--replace-masters] [--force-layout]
  verify-roundtrip --atlas <file.atlas> --work <empty-directory> [--force-work]
  verify-all --source-root <assets/ironclad-v0.111.0> --work-root <directory> [--force-work]

Region masters are unrotated, trimmed PNGs. Packing keeps atlas text, page
dimensions, names, bounds, rotate flags, and offsets unchanged. Production
packing defaults to empty hands by forcing sword blade and sword_handle fully
transparent. `spell` still clears the handle and accepts only an alpha-clamped
spell_layers/sword blade.png projection. Preserve mode exists only inside the
round-trip verifier.
""")
