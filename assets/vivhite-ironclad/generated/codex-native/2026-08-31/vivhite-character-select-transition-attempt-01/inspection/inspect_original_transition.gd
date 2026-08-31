extends SceneTree

const MATERIAL_PATH := "res://materials/transitions/ironclad_transition_mat.tres"
const TEXTURE_PATH := "res://images/ui/transitions/ironclad_transition.png"


func _initialize() -> void:
	var args := OS.get_cmdline_user_args()
	if args.size() != 2:
		_fail("expected arguments: <SlayTheSpire2.pck> <output-directory>", 2)
		return

	var pck_path := ProjectSettings.globalize_path(args[0]).replace("\\", "/")
	var output_dir := args[1].replace("\\", "/")
	if not output_dir.begins_with("res://") and not output_dir.begins_with("user://"):
		output_dir = ProjectSettings.localize_path(ProjectSettings.globalize_path(output_dir))
	var output_filesystem_dir := ProjectSettings.globalize_path(output_dir).replace("\\", "/")
	var mkdir_error := DirAccess.make_dir_recursive_absolute(output_filesystem_dir)
	if mkdir_error != OK:
		_fail("could not create output directory: %s" % error_string(mkdir_error), 3)
		return

	if not ProjectSettings.load_resource_pack(pck_path, true):
		_fail("could not mount game PCK: %s" % pck_path, 4)
		return

	var material_text := FileAccess.get_file_as_string(MATERIAL_PATH)
	if material_text.is_empty():
		_fail("could not read material text: %s" % MATERIAL_PATH, 5)
		return
	_write_text(output_dir.path_join("original-ironclad-transition-material.tres"), material_text)

	var import_path := TEXTURE_PATH + ".import"
	var import_text := FileAccess.get_file_as_string(import_path)
	if import_text.is_empty():
		_fail("could not read texture import metadata: %s" % import_path, 6)
		return
	_write_text(output_dir.path_join("original-ironclad-transition.png.import"), import_text)

	var loaded_material := ResourceLoader.load(MATERIAL_PATH, "ShaderMaterial", ResourceLoader.CACHE_MODE_IGNORE)
	if loaded_material == null or not (loaded_material is ShaderMaterial):
		_fail("material did not load as ShaderMaterial", 7)
		return
	var material := loaded_material as ShaderMaterial

	var loaded_texture := ResourceLoader.load(TEXTURE_PATH, "Texture2D", ResourceLoader.CACHE_MODE_IGNORE)
	if loaded_texture == null or not (loaded_texture is Texture2D):
		_fail("transition image did not load as Texture2D", 8)
		return
	var texture := loaded_texture as Texture2D
	var image := texture.get_image()
	if image == null or image.is_empty():
		_fail("transition texture produced no image", 9)
		return
	if image.is_compressed():
		var decompress_error := image.decompress()
		if decompress_error != OK:
			_fail("transition image decompression failed: %s" % error_string(decompress_error), 10)
			return

	var decoded_path := output_dir.path_join("original-ironclad-transition-decoded.png")
	var save_error := image.save_png(decoded_path)
	if save_error != OK:
		_fail("could not save decoded transition PNG: %s" % error_string(save_error), 11)
		return

	var alpha_stats := _alpha_stats(image)
	var shader_path := ""
	var shader_code := ""
	if material.shader != null:
		shader_path = material.shader.resource_path
		shader_code = material.shader.code
		_write_text(output_dir.path_join("original-transition-shader.gdshader"), shader_code)

	var parameters: Array[Dictionary] = []
	for property_value in material.get_property_list():
		var property: Dictionary = property_value
		var property_name := str(property.get("name", ""))
		if not property_name.begins_with("shader_parameter/"):
			continue
		var parameter_name := property_name.trim_prefix("shader_parameter/")
		var value: Variant = material.get_shader_parameter(parameter_name)
		parameters.append({
			"name": parameter_name,
			"type": type_string(typeof(value)),
			"value": _json_value(value),
		})

	var report := {
		"schema": "vivhite-character-select-transition-source-inspection/v1",
		"game_pck": {
			"path": pck_path,
			"sha256": FileAccess.get_sha256(pck_path),
		},
		"material": {
			"path": MATERIAL_PATH,
			"class": material.get_class(),
			"shader_path": shader_path,
			"shader_code_sha256": _sha256_text(shader_code),
			"parameters": parameters,
		},
		"texture": {
			"path": TEXTURE_PATH,
			"class": texture.get_class(),
			"width": image.get_width(),
			"height": image.get_height(),
			"format_enum": int(image.get_format()),
			"mipmaps": image.has_mipmaps(),
			"decoded_png_sha256": FileAccess.get_sha256(decoded_path),
			"alpha": alpha_stats,
		},
	}
	_write_text(
		output_dir.path_join("original-source-inspection.json"),
		JSON.stringify(report, "  ") + "\n"
	)
	print("[PASS] inspected original Ironclad character-select transition")
	quit(0)


func _alpha_stats(image: Image) -> Dictionary:
	var minimum := 255
	var maximum := 0
	var translucent := 0
	var transparent := 0
	var opaque := 0
	for y in image.get_height():
		for x in image.get_width():
			var alpha := int(round(image.get_pixel(x, y).a * 255.0))
			minimum = mini(minimum, alpha)
			maximum = maxi(maximum, alpha)
			if alpha == 0:
				transparent += 1
			elif alpha == 255:
				opaque += 1
			else:
				translucent += 1
	return {
		"minimum": minimum,
		"maximum": maximum,
		"transparent_pixels": transparent,
		"translucent_pixels": translucent,
		"opaque_pixels": opaque,
	}


func _json_value(value: Variant) -> Variant:
	if value is Texture2D:
		var value_texture := value as Texture2D
		return {
			"resource_path": value_texture.resource_path,
			"class": value_texture.get_class(),
			"width": value_texture.get_width(),
			"height": value_texture.get_height(),
		}
	if value is Color or value is Vector2 or value is Vector3 or value is Vector4:
		return str(value)
	if typeof(value) in [TYPE_NIL, TYPE_BOOL, TYPE_INT, TYPE_FLOAT, TYPE_STRING]:
		return value
	return str(value)


func _sha256_text(value: String) -> String:
	var context := HashingContext.new()
	context.start(HashingContext.HASH_SHA256)
	context.update(value.to_utf8_buffer())
	return context.finish().hex_encode()


func _write_text(path: String, content: String) -> void:
	var file := FileAccess.open(path, FileAccess.WRITE)
	if file == null:
		_fail("could not write evidence file: %s" % path, 12)
		return
	file.store_string(content)


func _fail(message: String, code: int) -> void:
	printerr("[FAIL] %s" % message)
	quit(code)
