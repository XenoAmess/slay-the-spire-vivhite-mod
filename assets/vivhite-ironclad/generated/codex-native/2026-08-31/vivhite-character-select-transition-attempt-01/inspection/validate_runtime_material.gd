extends SceneTree


func _initialize() -> void:
	var args := OS.get_cmdline_user_args()
	if args.size() != 1:
		printerr("usage: validate_runtime_material.gd <report-json>")
		quit(2)
		return

	var material_path := "res://Vivhite/skins/ironclad/transitions/vivhite_character_select_transition_mat.tres"
	var texture_path := "res://Vivhite/skins/ironclad/transitions/vivhite_character_select_transition.png"
	var resource := ResourceLoader.load(material_path, "ShaderMaterial", ResourceLoader.CACHE_MODE_IGNORE)
	if resource == null or not resource is ShaderMaterial:
		printerr("could not load ShaderMaterial: %s" % material_path)
		quit(3)
		return
	var material := resource as ShaderMaterial
	var texture := material.get_shader_parameter("transitionTex") as Texture2D
	if texture == null:
		printerr("transitionTex did not resolve as Texture2D")
		quit(4)
		return
	var shader_code := material.shader.code if material.shader != null else ""
	var report := {
		"schema": "vivhite-transition-runtime-material-validation/v1",
		"material": {
			"path": material_path,
			"class": material.get_class(),
			"resource_local_to_scene": material.resource_local_to_scene,
			"threshold": material.get_shader_parameter("threshold"),
			"shader_code_sha256": shader_code.sha256_text(),
			"samples_transition_red_channel": "texture(transitionTex, UV).r" in shader_code,
		},
		"texture": {
			"expected_path": texture_path,
			"resolved_path": texture.resource_path,
			"class": texture.get_class(),
			"width": texture.get_width(),
			"height": texture.get_height(),
		},
	}
	var report_file := FileAccess.open(args[0], FileAccess.WRITE)
	if report_file == null:
		printerr("could not write report: %s" % args[0])
		quit(5)
		return
	report_file.store_string(JSON.stringify(report, "  ") + "\n")
	print("[PASS] runtime material loaded: %s" % material_path)
	quit(0)
