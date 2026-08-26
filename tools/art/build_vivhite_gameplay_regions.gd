extends SceneTree

## Deterministically transfers the approved AI gameplay sheets into the four
## Spine region workspaces created by atlas_region_tool.gd.
##
## This script never changes atlas metadata. With the exception of the
## character-select composite `top arm`, it keeps every template region's
## alpha byte-for-byte and replaces only RGB using a semantic AI crop. The top
## arm uses an isolated empty-hand cutout because its vanilla alpha contains a
## sword. Combat and merchant share the same source recipes.

const FORMAT_VERSION := 1
const BUILD_REPORT := "gameplay-region-build-report.json"
const AUDIT_REPORT := "gameplay-static-audit.json"
const BLACK_THRESHOLD := 8

const DOMAIN_TEMPLATE_ATLASES := {
	"combat": "combat/ironclad.atlas",
	"merchant": "merchant/ironclad_shop.atlas",
	"rest_site": "rest_site/restsite_ironclad.atlas",
	"character_select": "character_select/characterselect_ironclad.atlas",
}

const SOURCE_FILES := {
	"anchor": "anchor/vivhite-master-front-final.png",
	"base": "gameplay/merchant-page1-registration-ai.png",
	"attack": "gameplay/merchant-page2-ai.png",
	"death": "gameplay/merchant-page3-ai.png",
	"rest": "gameplay/rest-site-ai.png",
	"select": "gameplay/character-select-ai.png",
}

# Pixel-space source crops. Crops intentionally include a small black safety
# margin; _active_rect trims that margin before resampling.
const CROPS := {
	"anchor": {
		"head": [260, 10, 430, 350],
		"hair": [260, 5, 440, 330],
		"neck": [300, 275, 340, 210],
		"body": [225, 285, 500, 510],
		"arm": [145, 345, 655, 525],
		"hand": [135, 665, 675, 230],
		"hip": [210, 610, 520, 390],
		"leg": [260, 855, 430, 600],
		"foot": [245, 1350, 455, 315],
	},
	"base": {
		"head": [20, 65, 175, 145],
		"hair": [205, 55, 350, 205],
		"neck": [470, 55, 230, 180],
		"body": [0, 195, 610, 355],
		"arm": [855, 45, 570, 245],
		"hand": [1370, 50, 310, 210],
		"hip": [650, 170, 470, 280],
		"leg": [1380, 235, 390, 590],
		"foot": [1420, 45, 350, 230],
		"effect_slash": [0, 400, 1110, 390],
		"effect_zap": [1260, 100, 514, 720],
		"shadow": [625, 155, 520, 290],
	},
	"attack": {
		"head": [0, 0, 405, 215],
		"hair": [0, 0, 405, 215],
		"neck": [300, 0, 530, 260],
		"body": [0, 225, 535, 440],
		"arm": [300, 0, 530, 670],
		"hand": [330, 0, 480, 270],
		"hip": [0, 565, 625, 470],
		"leg": [430, 255, 700, 750],
		"foot": [430, 850, 700, 542],
	},
	"death": {
		"head": [960, 0, 350, 235],
		"hair": [960, 0, 350, 235],
		"neck": [1080, 180, 500, 350],
		"body": [1060, 190, 600, 390],
		"arm": [1120, 60, 646, 650],
		"hand": [1260, 190, 506, 390],
		"hip": [410, 0, 780, 430],
		"leg": [300, 0, 850, 500],
		"foot": [760, 500, 880, 391],
	},
	"rest": {
		"head": [0, 0, 360, 275],
		"hair": [0, 0, 635, 290],
		"neck": [0, 205, 525, 440],
		"body": [0, 205, 600, 450],
		"arm": [735, 190, 485, 470],
		"hand": [815, 200, 405, 450],
		"hip": [470, 160, 525, 360],
		"leg": [0, 590, 1220, 530],
		"foot": [650, 555, 570, 610],
		"effect_zap": [0, 570, 710, 560],
		"shadow": [20, 590, 1160, 500],
	},
	"select": {
		"bg": [0, 0, 1065, 505],
		"fire": [0, 500, 1065, 509],
		"body": [1055, 0, 315, 535],
		"head": [1055, 0, 315, 300],
		"hair": [1055, 0, 315, 300],
		"effect_zap": [1350, 165, 209, 375],
		"effect_slash": [1050, 520, 285, 480],
		"empty_arm": [1275, 700, 284, 309],
	},
}

var _last_error := ""
var _sources := {}


func _initialize() -> void:
	var status := _run(OS.get_cmdline_user_args())
	quit(status)


func _run(args: PackedStringArray) -> int:
	if args.is_empty() or args[0] in ["-h", "--help", "help"]:
		_print_help()
		return 0
	var parsed := _parse_options(args)
	if parsed.is_empty():
		return 2
	var options: Dictionary = parsed["options"]
	var template_root := _absolute_path(str(options.get("template-root", "assets/ironclad-v0.111.0")))
	var generated_root := _absolute_path(str(options.get("generated-root", "assets/vivhite-ironclad/generated")))
	var custom_root := _absolute_path(str(options.get("custom-root", "assets/vivhite-ironclad/custom")))
	match str(parsed["command"]):
		"build":
			if not _build_all(template_root, generated_root, custom_root):
				return _fail(_last_error)
			return 0
		"audit":
			if not _audit_all(template_root, custom_root):
				return _fail(_last_error)
			return 0
		_:
			return _fail("Unknown command: %s" % parsed["command"])


func _parse_options(args: PackedStringArray) -> Dictionary:
	var options := {}
	var index := 1
	while index < args.size():
		var token := args[index]
		if not token.begins_with("--") or index + 1 >= args.size():
			printerr("Expected --name value, got: %s" % token)
			return {}
		options[token.trim_prefix("--")] = args[index + 1]
		index += 2
	return {"command": args[0], "options": options}


func _absolute_path(path: String) -> String:
	if path.is_absolute_path():
		return path.simplify_path()
	var repository_root := ProjectSettings.globalize_path("res://").path_join("../..").simplify_path()
	return repository_root.path_join(path).simplify_path()


func _build_all(template_root: String, generated_root: String, custom_root: String) -> bool:
	_last_error = ""
	if not _load_sources(generated_root):
		return false
	var report_domains := []
	var total_regions := 0
	for domain: String in DOMAIN_TEMPLATE_ATLASES:
		var domain_report := _build_domain(domain, template_root, custom_root)
		if domain_report.is_empty():
			return false
		report_domains.append(domain_report)
		total_regions += int(domain_report["region_count"])
	var report := {
		"format_version": FORMAT_VERSION,
		"rule": "semantic AI crop RGB + template geometry/alpha; character_select/top arm uses isolated empty-hand AI alpha",
		"source_files": _source_hash_report(generated_root),
		"region_count": total_regions,
		"domains": report_domains,
	}
	if not _write_json(custom_root.path_join(BUILD_REPORT), report):
		return false
	print("Built %d custom gameplay region masters across four domains." % total_regions)
	return true


func _build_domain(domain: String, template_root: String, custom_root: String) -> Dictionary:
	var layout_path := custom_root.path_join(domain).path_join("atlas-layout.json")
	var layout = _load_json(layout_path)
	if not layout is Dictionary:
		return {}
	var template_domain := template_root.path_join(str(DOMAIN_TEMPLATE_ATLASES[domain])).get_base_dir()
	var page_images := {}
	var region_reports := []
	for page_value in layout["pages"]:
		var page: Dictionary = page_value
		var page_path := template_domain.path_join(str(page["name"]))
		var page_image := _load_rgba(page_path)
		if page_image == null:
			return {}
		page_images[page["name"]] = page_image
		for region_value in page["regions"]:
			var region: Dictionary = region_value
			var template_region := _extract_template_region(page_image, region)
			if template_region == null:
				return {}
			var recipe := _recipe(domain, str(region["name"]))
			var output: Image
			if bool(recipe.get("transparent", false)):
				output = _transparent_image(template_region.get_size())
			elif bool(recipe.get("empty_hand_cutout", false)):
				output = _empty_hand_cutout(template_region.get_size(), recipe)
			else:
				output = _transfer_rgb(template_region, recipe)
			if output == null:
				_last_error = "%s/%s (%s): %s" % [domain, region["name"], recipe.get("id", "unknown"), _last_error]
				return {}
			var template_pixel_hash := _hash_bytes(template_region.get_data())
			var output_pixel_hash := _hash_bytes(output.get_data())
			if template_pixel_hash == output_pixel_hash:
				_set_error("Generated region still matches the template: %s/%s" % [domain, region["name"]])
				return {}
			if not bool(recipe.get("empty_hand_cutout", false)) and not bool(recipe.get("transparent", false)):
				if _alpha_hash(template_region) != _alpha_hash(output):
					_set_error("Template alpha changed unexpectedly: %s/%s" % [domain, region["name"]])
					return {}
			if not bool(recipe.get("transparent", false)) and not output.get_used_rect().has_area():
				_set_error("Generated non-weapon region is empty: %s/%s" % [domain, region["name"]])
				return {}
			var output_path := custom_root.path_join(domain).path_join(str(region["master"]))
			if not _save_png(output, output_path):
				return {}
			region_reports.append({
				"name": region["name"],
				"master": region["master"],
				"recipe": recipe["id"],
				"template_pixel_sha256": template_pixel_hash,
				"output_pixel_sha256": output_pixel_hash,
				"output_png_sha256": FileAccess.get_sha256(output_path),
				"alpha_preserved": _alpha_hash(template_region) == _alpha_hash(output),
				"alpha_bbox": _rect_array(output.get_used_rect()),
				"transparent_weapon": bool(recipe.get("transparent", false)),
			})
	return {
		"domain": domain,
		"region_count": region_reports.size(),
		"regions": region_reports,
	}


func _recipe(domain: String, region_name: String) -> Dictionary:
	if region_name in ["sword blade", "sword_handle"]:
		return {"id": "forced-empty-weapon", "transparent": true}
	if domain == "character_select":
		match region_name:
			"bg":
				return _crop_recipe("select", "bg", "background", "select-bg")
			"fire":
				return _crop_recipe("select", "fire", "effect", "select-fire")
			"bod":
				return _crop_recipe("select", "body", "body", "select-body-panel")
			"top arm":
				var recipe := _crop_recipe("select", "empty_arm", "skin", "select-empty-hand-arm")
				recipe["empty_hand_cutout"] = true
				return recipe
			"back arm":
				return _crop_recipe("select", "empty_arm", "arm", "select-back-arm")
			"eye shine":
				return _crop_recipe("select", "effect_zap", "effect", "select-eye-magic")
			_:
				var category := "hair" if "hair" in region_name else "head"
				return _crop_recipe("select", category, category, "select-%s" % category)

	if domain == "rest_site":
		var rest_category := _semantic_category(region_name)
		if rest_category in ["head", "hair"]:
			return _crop_recipe("anchor", rest_category, rest_category, "rest-anchor-%s" % rest_category)
		if rest_category == "effect":
			return _crop_recipe("select", "effect_slash", rest_category, "rest-select-magic")
		if rest_category == "shadow":
			return _crop_recipe("base", "shadow", rest_category, "rest-base-shadow")
		var rest_crop := "effect_zap" if rest_category == "effect" else rest_category
		return _crop_recipe("rest", rest_crop, rest_category, "rest-%s" % rest_category)

	var source_key := "base"
	if region_name.begins_with("attack/"):
		source_key = "attack"
	elif region_name.begins_with("death/"):
		source_key = "death"
	var category := _semantic_category(region_name)
	var crop_key := category
	if category == "effect":
		crop_key = "effect_zap" if ("zap" in region_name or "eye" in region_name or "shine" in region_name or "puff" in region_name) else "effect_slash"
	if not CROPS[source_key].has(crop_key):
		# Pose sheets intentionally focus on their body parts. Fall back to the
		# registered base/effect sheet or the identity anchor without changing
		# the semantic category.
		if CROPS["base"].has(crop_key):
			source_key = "base"
		elif CROPS["anchor"].has(crop_key):
			source_key = "anchor"
		else:
			source_key = "anchor"
			crop_key = "body"
	return _crop_recipe(source_key, crop_key, category, "%s-%s" % [source_key, category])


func _crop_recipe(source_key: String, crop_key: String, category: String, id: String) -> Dictionary:
	return {
		"id": id,
		"source": source_key,
		"crop": CROPS[source_key][crop_key],
		"category": category,
	}


func _semantic_category(region_name: String) -> String:
	var name := region_name.to_lower()
	if "slash" in name or "zap" in name or "eye glow" in name or "shine" in name or "puff" in name or "highlight" in name:
		return "effect"
	if "shadow" in name or "chadow" in name:
		return "shadow"
	if "hair" in name:
		return "hair"
	if "head" in name:
		return "head"
	if "hand" in name:
		return "hand"
	if "foot" in name or "ankle" in name:
		return "foot"
	if "lower leg" in name or " knee" in name or name.ends_with("knee_death") or " l leg" in name or " r leg" in name:
		return "leg"
	if "upper leg" in name or "hip" in name or "hips" in name or "belt" in name:
		return "hip"
	if "arm" in name or "shoulder" in name or "bracer" in name or "mask" in name:
		return "arm"
	if "neck" in name or "collar" in name:
		return "neck"
	return "body"


func _transfer_rgb(template: Image, recipe: Dictionary) -> Image:
	var source: Image = _sources[str(recipe["source"])]
	var source_crop := _semantic_crop(source, recipe["crop"])
	if source_crop == null:
		return null
	var palette := _average_active_color(source_crop)
	source_crop.resize(template.get_width(), template.get_height(), Image.INTERPOLATE_LANCZOS)
	if source_crop.get_format() != Image.FORMAT_RGBA8:
		source_crop.convert(Image.FORMAT_RGBA8)
	var template_bytes := template.get_data()
	var source_bytes := source_crop.get_data()
	var output_bytes := PackedByteArray()
	output_bytes.resize(template_bytes.size())
	var category := str(recipe["category"])
	for offset in range(0, template_bytes.size(), 4):
		var alpha := int(template_bytes[offset + 3])
		if alpha == 0:
			output_bytes[offset] = 0
			output_bytes[offset + 1] = 0
			output_bytes[offset + 2] = 0
			output_bytes[offset + 3] = 0
			continue
		var red := int(source_bytes[offset])
		var green := int(source_bytes[offset + 1])
		var blue := int(source_bytes[offset + 2])
		var active := maxi(red, maxi(green, blue)) > BLACK_THRESHOLD
		if not active:
			var original_luma := (int(template_bytes[offset]) + int(template_bytes[offset + 1]) + int(template_bytes[offset + 2])) / 765.0
			var shade := 0.62 + 0.52 * original_luma
			red = clampi(int(palette.r * 255.0 * shade), 0, 255)
			green = clampi(int(palette.g * 255.0 * shade), 0, 255)
			blue = clampi(int(palette.b * 255.0 * shade), 0, 255)
		var styled := _style_color(Color8(red, green, blue), category, offset / 4)
		output_bytes[offset] = clampi(int(styled.r * 255.0), 0, 255)
		output_bytes[offset + 1] = clampi(int(styled.g * 255.0), 0, 255)
		output_bytes[offset + 2] = clampi(int(styled.b * 255.0), 0, 255)
		output_bytes[offset + 3] = alpha
	var output := Image.create_from_data(template.get_width(), template.get_height(), false, Image.FORMAT_RGBA8, output_bytes)
	return output


func _style_color(color: Color, category: String, pixel_index: int) -> Color:
	match category:
		"hair":
			return color.lerp(Color("cbd2f4"), 0.38)
		"head", "hand":
			return color.lerp(Color("f8dfe1"), 0.22)
		"effect":
			var cyan_mix := 0.18 + 0.12 * float(pixel_index % 11) / 10.0
			var magic := Color("8c55ff").lerp(Color("53e2ff"), cyan_mix)
			return color.lerp(magic, 0.48)
		"shadow":
			return Color(color.r * 0.12 + 0.035, color.g * 0.08 + 0.02, color.b * 0.28 + 0.10, 1.0)
		_:
			return color.lerp(Color("eeeefe"), 0.06)


func _empty_hand_cutout(target_size: Vector2i, recipe: Dictionary) -> Image:
	var source: Image = _sources[str(recipe["source"])]
	var crop := _raw_crop(source, recipe["crop"])
	if crop == null:
		return null
	var active := _active_rect(crop)
	if not active.has_area():
		_set_error("Empty-hand crop contains no foreground")
		return null
	crop = crop.get_region(active)
	var scale := minf(float(target_size.x) * 0.82 / float(crop.get_width()), float(target_size.y) * 0.82 / float(crop.get_height()))
	var fitted_size := Vector2i(maxi(1, int(crop.get_width() * scale)), maxi(1, int(crop.get_height() * scale)))
	crop.resize(fitted_size.x, fitted_size.y, Image.INTERPOLATE_LANCZOS)
	if crop.get_format() != Image.FORMAT_RGBA8:
		crop.convert(Image.FORMAT_RGBA8)
	var output := _transparent_image(target_size)
	var output_bytes := output.get_data()
	var crop_bytes := crop.get_data()
	var origin := Vector2i((target_size.x - fitted_size.x) / 2, (target_size.y - fitted_size.y) / 2)
	for y in range(fitted_size.y):
		for x in range(fitted_size.x):
			var source_offset := (y * fitted_size.x + x) * 4
			var red := int(crop_bytes[source_offset])
			var green := int(crop_bytes[source_offset + 1])
			var blue := int(crop_bytes[source_offset + 2])
			var maximum := maxi(red, maxi(green, blue))
			if maximum <= 3:
				continue
			var alpha := clampi((maximum - 3) * 32, 0, 255)
			var destination_offset := ((origin.y + y) * target_size.x + origin.x + x) * 4
			output_bytes[destination_offset] = red
			output_bytes[destination_offset + 1] = green
			output_bytes[destination_offset + 2] = blue
			output_bytes[destination_offset + 3] = alpha
	output.set_data(target_size.x, target_size.y, false, Image.FORMAT_RGBA8, output_bytes)
	return output


func _semantic_crop(source: Image, crop_values: Array) -> Image:
	var crop := _raw_crop(source, crop_values)
	if crop == null:
		return null
	var active := _active_rect(crop)
	if active.has_area():
		return crop.get_region(active)
	_set_error("AI semantic crop contains no foreground")
	return null


func _raw_crop(source: Image, crop_values: Array) -> Image:
	var requested := Rect2i(int(crop_values[0]), int(crop_values[1]), int(crop_values[2]), int(crop_values[3]))
	var bounds := Rect2i(Vector2i.ZERO, source.get_size())
	var clipped := requested.intersection(bounds)
	if not clipped.has_area():
		_set_error("AI source crop is outside the image: %s" % [crop_values])
		return null
	return source.get_region(clipped)


func _active_rect(image: Image) -> Rect2i:
	var bytes := image.get_data()
	var min_x := image.get_width()
	var min_y := image.get_height()
	var max_x := -1
	var max_y := -1
	for y in range(image.get_height()):
		for x in range(image.get_width()):
			var offset := (y * image.get_width() + x) * 4
			if maxi(int(bytes[offset]), maxi(int(bytes[offset + 1]), int(bytes[offset + 2]))) <= BLACK_THRESHOLD:
				continue
			min_x = mini(min_x, x)
			min_y = mini(min_y, y)
			max_x = maxi(max_x, x)
			max_y = maxi(max_y, y)
	if max_x < 0:
		return Rect2i()
	return Rect2i(min_x, min_y, max_x - min_x + 1, max_y - min_y + 1)


func _average_active_color(image: Image) -> Color:
	var bytes := image.get_data()
	var red_total := 0.0
	var green_total := 0.0
	var blue_total := 0.0
	var count := 0
	for offset in range(0, bytes.size(), 16):
		var red := int(bytes[offset])
		var green := int(bytes[offset + 1])
		var blue := int(bytes[offset + 2])
		if maxi(red, maxi(green, blue)) <= BLACK_THRESHOLD:
			continue
		red_total += red
		green_total += green
		blue_total += blue
		count += 1
	if count == 0:
		return Color("9a86d9")
	return Color(red_total / count / 255.0, green_total / count / 255.0, blue_total / count / 255.0, 1.0)


func _extract_template_region(page_image: Image, region: Dictionary) -> Image:
	var packed_values: Array = region["packed_rect"]
	var packed_rect := Rect2i(int(packed_values[0]), int(packed_values[1]), int(packed_values[2]), int(packed_values[3]))
	var logical := page_image.get_region(packed_rect)
	if int(region["rotate"]) == 90:
		logical.rotate_90(COUNTERCLOCKWISE)
	var bounds: Array = region["bounds"]
	if logical.get_size() != Vector2i(int(bounds[2]), int(bounds[3])):
		_set_error("Template logical-size mismatch: %s" % region["name"])
		return null
	return logical


func _audit_all(template_root: String, custom_root: String) -> bool:
	_last_error = ""
	var domain_reports := []
	var all_page_count := 0
	var all_region_count := 0
	for domain: String in DOMAIN_TEMPLATE_ATLASES:
		var result := _audit_domain(domain, template_root, custom_root)
		if result.is_empty():
			return false
		domain_reports.append(result)
		all_page_count += int(result["page_count"])
		all_region_count += int(result["region_count"])
	var report := {
		"format_version": FORMAT_VERSION,
		"passed": true,
		"page_count": all_page_count,
		"region_count": all_region_count,
		"requirements": {
			"all_region_pixels_differ_from_template": true,
			"all_packed_png_hashes_differ_from_template": true,
			"all_packed_regions_match_current_masters": true,
			"all_masters_match_build_report": true,
			"combat_and_merchant_weapons_alpha_zero": true,
			"character_select_top_arm_source": "select-empty-hand-arm",
		},
		"domains": domain_reports,
	}
	if not _write_json(custom_root.path_join(AUDIT_REPORT), report):
		return false
	print("Static audit passed for %d region masters and %d packed atlas pages." % [all_region_count, all_page_count])
	return true


func _audit_domain(domain: String, template_root: String, custom_root: String) -> Dictionary:
	var workspace := custom_root.path_join(domain)
	var layout = _load_json(workspace.path_join("atlas-layout.json"))
	if not layout is Dictionary:
		return {}
	var build_report = _load_json(custom_root.path_join(BUILD_REPORT))
	if not build_report is Dictionary:
		return {}
	var build_domain: Dictionary = {}
	for domain_value in build_report.get("domains", []):
		if domain_value is Dictionary and str(domain_value.get("domain", "")) == domain:
			build_domain = domain_value
			break
	if build_domain.is_empty():
		_set_error("Build report has no domain entry: %s" % domain)
		return {}
	var built_regions := {}
	for built_value in build_domain.get("regions", []):
		if built_value is Dictionary:
			built_regions[str(built_value.get("name", ""))] = built_value
	var template_domain := template_root.path_join(str(DOMAIN_TEMPLATE_ATLASES[domain])).get_base_dir()
	var page_reports := []
	var region_reports := []
	for page_value in layout["pages"]:
		var page: Dictionary = page_value
		var template_page_path := template_domain.path_join(str(page["name"]))
		var custom_page_path := workspace.path_join(str(page["name"]))
		var template_page := _load_rgba(template_page_path)
		var custom_page := _load_rgba(custom_page_path)
		if template_page == null or custom_page == null:
			return {}
		if template_page.get_size() != custom_page.get_size():
			_set_error("Packed page size changed: %s/%s" % [domain, page["name"]])
			return {}
		if FileAccess.get_sha256(template_page_path) == FileAccess.get_sha256(custom_page_path):
			_set_error("Packed page still matches template hash: %s/%s" % [domain, page["name"]])
			return {}
		page_reports.append({
			"name": page["name"],
			"size": [custom_page.get_width(), custom_page.get_height()],
			"template_sha256": FileAccess.get_sha256(template_page_path),
			"custom_sha256": FileAccess.get_sha256(custom_page_path),
		})
		for region_value in page["regions"]:
			var region: Dictionary = region_value
			var template_region := _extract_template_region(template_page, region)
			if template_region == null:
				return {}
			var master_path := workspace.path_join(str(region["master"]))
			var custom_master := _load_rgba(master_path)
			if custom_master == null:
				return {}
			var region_name := str(region["name"])
			if not built_regions.has(region_name):
				_set_error("Build report has no region entry: %s/%s" % [domain, region_name])
				return {}
			var built_region: Dictionary = built_regions[region_name]
			if custom_master.get_size() != template_region.get_size():
				_set_error("Master size changed: %s/%s" % [domain, region_name])
				return {}
			var master_pixel_hash := _hash_bytes(custom_master.get_data())
			if master_pixel_hash == _hash_bytes(template_region.get_data()):
				_set_error("Master pixels still match template: %s/%s" % [domain, region_name])
				return {}
			if str(built_region.get("output_pixel_sha256", "")) != master_pixel_hash:
				_set_error("Master no longer matches its build report: %s/%s" % [domain, region_name])
				return {}
			if domain == "character_select" and region_name == "top arm" and str(built_region.get("recipe", "")) != "select-empty-hand-arm":
				_set_error("Character-select top arm was not built from the approved empty-hand recipe.")
				return {}
			var is_weapon := region_name in ["sword blade", "sword_handle"]
			if is_weapon and custom_master.get_used_rect().has_area():
				_set_error("Weapon master is not transparent: %s/%s" % [domain, region_name])
				return {}
			var packed_values: Array = region["packed_rect"]
			var packed_region := custom_page.get_region(Rect2i(int(packed_values[0]), int(packed_values[1]), int(packed_values[2]), int(packed_values[3])))
			var expected_packed := custom_master.duplicate()
			if int(region["rotate"]) == 90:
				expected_packed.rotate_90(CLOCKWISE)
			if expected_packed.get_size() != packed_region.get_size() or _hash_bytes(expected_packed.get_data()) != _hash_bytes(packed_region.get_data()):
				_set_error("Packed region does not match the current master; run atlas pack again: %s/%s" % [domain, region_name])
				return {}
			if is_weapon and packed_region.get_used_rect().has_area():
				_set_error("Packed weapon pixels are not transparent: %s/%s" % [domain, region_name])
				return {}
			region_reports.append({
				"name": region_name,
				"pixel_differs": true,
				"matches_build_report": true,
				"packed_matches_master": true,
				"weapon_alpha_zero": is_weapon,
				"alpha_bbox": _rect_array(custom_master.get_used_rect()),
			})
	return {
		"domain": domain,
		"page_count": page_reports.size(),
		"region_count": region_reports.size(),
		"pages": page_reports,
		"regions": region_reports,
	}


func _load_sources(generated_root: String) -> bool:
	_sources.clear()
	for source_key: String in SOURCE_FILES:
		var path := generated_root.path_join(str(SOURCE_FILES[source_key]))
		var image := _load_rgba(path)
		if image == null:
			return false
		_sources[source_key] = image
	return true


func _source_hash_report(generated_root: String) -> Dictionary:
	var result := {}
	for source_key: String in SOURCE_FILES:
		var relative := str(SOURCE_FILES[source_key])
		result[source_key] = {"file": relative, "sha256": FileAccess.get_sha256(generated_root.path_join(relative))}
	return result


func _load_json(path: String):
	if not FileAccess.file_exists(path):
		_set_error("Required JSON does not exist: %s" % path)
		return null
	var value = JSON.parse_string(FileAccess.get_file_as_string(path))
	if not value is Dictionary:
		_set_error("Invalid JSON object: %s" % path)
		return null
	return value


func _load_rgba(path: String) -> Image:
	if not FileAccess.file_exists(path):
		_set_error("Required PNG does not exist: %s" % path)
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


func _save_png(image: Image, path: String) -> bool:
	var error := DirAccess.make_dir_recursive_absolute(path.get_base_dir())
	if error != OK and error != ERR_ALREADY_EXISTS:
		return _set_error("Could not create output directory: %s" % path.get_base_dir())
	error = image.save_png(path)
	if error != OK:
		return _set_error("Could not save PNG: %s" % path)
	return true


func _write_json(path: String, value: Dictionary) -> bool:
	var error := DirAccess.make_dir_recursive_absolute(path.get_base_dir())
	if error != OK and error != ERR_ALREADY_EXISTS:
		return _set_error("Could not create report directory: %s" % path.get_base_dir())
	var file := FileAccess.open(path, FileAccess.WRITE)
	if file == null:
		return _set_error("Could not write report: %s" % path)
	file.store_string(JSON.stringify(value, "\t", false) + "\n")
	file.close()
	return true


func _hash_bytes(bytes: PackedByteArray) -> String:
	var context := HashingContext.new()
	context.start(HashingContext.HASH_SHA256)
	context.update(bytes)
	return context.finish().hex_encode()


func _alpha_hash(image: Image) -> String:
	var bytes := image.get_data()
	var alpha := PackedByteArray()
	alpha.resize(image.get_width() * image.get_height())
	var target := 0
	for offset in range(3, bytes.size(), 4):
		alpha[target] = bytes[offset]
		target += 1
	return _hash_bytes(alpha)


func _rect_array(rect: Rect2i) -> Array:
	return [rect.position.x, rect.position.y, rect.size.x, rect.size.y]


func _set_error(message: String) -> bool:
	_last_error = message
	return false


func _fail(message: String) -> int:
	printerr("ERROR: %s" % message)
	return 2


func _print_help() -> void:
	print("""Vivhite gameplay region builder

Usage:
  build [--template-root assets/ironclad-v0.111.0]
        [--generated-root assets/vivhite-ironclad/generated]
        [--custom-root assets/vivhite-ironclad/custom]
  audit [same root options]

Run this after atlas_region_tool.gd init-all and before packing. Combat and
merchant use identical semantic recipes and AI sources. Sword blade/handle
masters are always transparent. Character-select top arm is rebuilt from the
empty-hand AI panel and never inherits the vanilla sword alpha.
""")
