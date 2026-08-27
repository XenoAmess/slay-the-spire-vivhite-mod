extends SceneTree

## Renders only the private Vivhite character-select Spine rig. The base-game
## PCK is mounted read-only to provide the game's Spine GDExtension and shared
## dependencies. Input resources and their pixels/Alpha are never modified.

const DEFAULT_RESOURCE := (
	"res://Vivhite/skins/ironclad/spine/character_select/"
	+ "character_select_skeleton_data.tres"
)
const DEFAULT_SCENE := "res://Vivhite/skins/ironclad/scenes/character_select.tscn"
const DEFAULT_OUTPUT := ".work/vivhite-character-select-preview"
const ANIMATION_NAME := "animation"
const AUTO_PLAYER_SCRIPT := "res://src/Core/Nodes/Animation/NSpineAutoPlayer.cs"
const EXPECTED_DURATION := 5.3333335
const DURATION_TOLERANCE := 0.001
const EXPECTED_SPINE_VERSION := "4.2.43"
const CANVAS_SIZE := Vector2i(2560, 1200)
const SAMPLE_FRACTIONS: Array[float] = [0.0, 0.25, 0.5, 0.75, 1.0]
const SPINE_UPDATE_MODE_MANUAL := 2

# These values reproduce Vivhite/skins/ironclad/scenes/character_select.tscn.
# On a 2560x1200 parent, the centered Control begins at (320, 77).
const LAYOUT_ANCHOR := Vector2(0.5, 0.5)
const LAYOUT_OFFSETS := Rect2(-960.0, -523.0, 2560.0, 1200.0)
const LAYOUT_PIVOT := Vector2(1280.0, 600.0)
const SPINE_POSITION := Vector2(-185.0, -20.0)
const SPINE_SCALE := Vector2(0.46, 0.46)

var _errors: Array[String] = []
var _output_root := ""


func _initialize() -> void:
	call_deferred("_render_preview")


func _fail(message: String) -> void:
	_errors.append(message)
	push_error("[vivhite-character-select-preview] %s" % message)


func _print_help() -> void:
	print("Usage:")
	print(
		"  godot --path Vivhite --rendering-driver vulkan --script "
		+ "tools/art/render_vivhite_character_select_preview.gd --"
	)
	print(
		"    --pck PATH [--scene RES_OR_ABSOLUTE_PATH] "
		+ "[--resource RES_OR_ABSOLUTE_PATH] [--output .work/PATH]"
	)


func _parse_args() -> Dictionary:
	var options := {
		"output": DEFAULT_OUTPUT,
		"pck": OS.get_environment("VIVHITE_STS2_PCK_PATH"),
		"resource": DEFAULT_RESOURCE,
		"scene": DEFAULT_SCENE,
	}
	var args := OS.get_cmdline_user_args()
	if args.size() == 1 and str(args[0]) in ["-h", "--help", "help"]:
		_print_help()
		return {"help": true}
	var index := 0
	while index < args.size():
		var key := str(args[index])
		if not key.begins_with("--") or index + 1 >= args.size():
			_fail("Expected '--name value', got '%s'." % key)
			return {}
		var name := key.trim_prefix("--")
		if not options.has(name):
			_fail("Unknown option '%s'." % key)
			return {}
		index += 1
		options[name] = str(args[index])
		index += 1
	return options


func _find_repository_root() -> String:
	var current := ProjectSettings.globalize_path("res://").simplify_path()
	for _depth in range(8):
		if FileAccess.file_exists(current.path_join("AGENTS.md")):
			return current
		var parent := current.get_base_dir()
		if parent == current:
			break
		current = parent
	_fail("Could not locate the repository root above '%s'." % ProjectSettings.globalize_path("res://"))
	return ""


func _safe_output_root(requested: String, repository_root: String) -> String:
	var work_root := repository_root.path_join(".work").simplify_path()
	var output := requested
	if output.is_empty():
		output = repository_root.path_join(DEFAULT_OUTPUT)
	elif not output.is_absolute_path():
		output = repository_root.path_join(output)
	output = output.simplify_path()
	var normalized_output := output.replace("\\", "/").to_lower()
	var required_prefix := work_root.replace("\\", "/").to_lower().trim_suffix("/") + "/"
	if not normalized_output.begins_with(required_prefix):
		_fail("Output must stay below '%s', got '%s'." % [work_root, output])
		return ""
	return output


func _resource_path(requested: String, repository_root: String) -> String:
	if requested.begins_with("res://"):
		return requested.simplify_path()

	var absolute_path := requested
	if not absolute_path.is_absolute_path():
		var repository_candidate := repository_root.path_join(requested).simplify_path()
		var project_candidate := (
			ProjectSettings.globalize_path("res://").path_join(requested).simplify_path()
		)
		if FileAccess.file_exists(repository_candidate):
			absolute_path = repository_candidate
		elif FileAccess.file_exists(project_candidate):
			absolute_path = project_candidate
		else:
			_fail("Project resource does not exist: %s" % requested)
			return ""
	absolute_path = absolute_path.simplify_path()
	var localized := ProjectSettings.localize_path(absolute_path)
	if not localized.begins_with("res://"):
		_fail(
			"Resource must be inside the selected Godot project: %s"
			% absolute_path
		)
		return ""
	return localized


func _object_names(items: Variant) -> Array[String]:
	var names: Array[String] = []
	if items == null:
		return names
	for item in items:
		if item != null and item.has_method("get_name"):
			names.append(str(item.call("get_name")))
	names.sort()
	return names


func _image_sha256(image: Image) -> String:
	var context := HashingContext.new()
	var start_error := context.start(HashingContext.HASH_SHA256)
	if start_error != OK:
		_fail("Could not start the SHA-256 context (error %d)." % start_error)
		return ""
	var update_error := context.update(image.get_data())
	if update_error != OK:
		_fail("Could not hash a rendered frame (error %d)." % update_error)
		return ""
	return context.finish().hex_encode()


func _rect_report(rect: Rect2i) -> Dictionary:
	return {
		"height": rect.size.y,
		"width": rect.size.x,
		"x": rect.position.x,
		"y": rect.position.y,
	}


func _approximately_equal(a: float, b: float) -> bool:
	return absf(a - b) <= 0.0001


func _instantiate_character_select_scene(
	packed_scene: PackedScene,
	expected_skeleton_data: Resource,
) -> Dictionary:
	var instance := packed_scene.instantiate()
	if instance == null:
		_fail("Could not instantiate the character-select PackedScene.")
		return {}
	if not instance is Control:
		_fail("Character-select scene root must be a Control, got %s." % instance.get_class())
		instance.free()
		return {}
	var scene_root: Control = instance

	var sprite_node := scene_root.get_node_or_null("SpineSprite")
	if sprite_node == null or not sprite_node.is_class("SpineSprite"):
		_fail("Character-select scene has no direct SpineSprite child.")
		scene_root.free()
		return {}
	var sprite: Node2D = sprite_node as Node2D
	if sprite.get_parent() != scene_root:
		_fail("Character-select SpineSprite is not a direct child of the scene root.")
	var backdrop := scene_root.get_node_or_null("VivhiteBackdrop")
	if backdrop == null or not backdrop is CanvasItem:
		_fail("Character-select scene has no direct VivhiteBackdrop CanvasItem.")
	elif backdrop.get_parent() != scene_root:
		_fail("VivhiteBackdrop must be a direct child of the scene root.")

	var auto_player := sprite.get_node_or_null("NSpineAutoPlayer")
	var auto_player_runtime_available := false
	if auto_player == null:
		_fail("Character-select scene has no SpineSprite/NSpineAutoPlayer node.")
	elif auto_player.get_parent() != sprite:
		_fail("NSpineAutoPlayer must be a direct child of SpineSprite.")
	else:
		var script_value: Variant = auto_player.get_script()
		if not script_value is Script:
			_fail("NSpineAutoPlayer has no script resource.")
		else:
			var auto_player_script: Script = script_value
			auto_player_runtime_available = auto_player_script.can_instantiate()
			if auto_player_script.resource_path != AUTO_PLAYER_SCRIPT:
				_fail(
					"NSpineAutoPlayer uses '%s'; expected '%s'."
					% [auto_player_script.resource_path, AUTO_PLAYER_SCRIPT]
				)

	var scene_skeleton_value: Variant = sprite.get("skeleton_data_res")
	if not scene_skeleton_value is Resource:
		_fail("The real character-select scene exposes no skeleton_data_res.")
	else:
		var scene_skeleton_data: Resource = scene_skeleton_value
		if scene_skeleton_data.resource_path.to_lower() != expected_skeleton_data.resource_path.to_lower():
			_fail(
				"The real scene references '%s', not the requested private skeleton data '%s'."
				% [scene_skeleton_data.resource_path, expected_skeleton_data.resource_path]
			)

	var layout_matches := (
		_approximately_equal(scene_root.anchor_left, LAYOUT_ANCHOR.x)
		and _approximately_equal(scene_root.anchor_top, LAYOUT_ANCHOR.y)
		and _approximately_equal(scene_root.anchor_right, LAYOUT_ANCHOR.x)
		and _approximately_equal(scene_root.anchor_bottom, LAYOUT_ANCHOR.y)
		and _approximately_equal(scene_root.offset_left, LAYOUT_OFFSETS.position.x)
		and _approximately_equal(scene_root.offset_top, LAYOUT_OFFSETS.position.y)
		and _approximately_equal(scene_root.offset_right, LAYOUT_OFFSETS.end.x)
		and _approximately_equal(scene_root.offset_bottom, LAYOUT_OFFSETS.end.y)
		and scene_root.pivot_offset.is_equal_approx(LAYOUT_PIVOT)
		and sprite.position.is_equal_approx(SPINE_POSITION)
		and sprite.scale.is_equal_approx(SPINE_SCALE)
	)
	if not layout_matches:
		_fail("The real character-select scene no longer matches its researched 2560x1200 layout.")

	return {
		"auto_player": auto_player,
		"auto_player_runtime_available": auto_player_runtime_available,
		"backdrop": backdrop,
		"instance": scene_root,
		"layout": {
			"control_anchor": [
				scene_root.anchor_left,
				scene_root.anchor_top,
				scene_root.anchor_right,
				scene_root.anchor_bottom,
			],
			"control_offsets": [
				scene_root.offset_left,
				scene_root.offset_top,
				scene_root.offset_right,
				scene_root.offset_bottom,
			],
			"control_pivot": [scene_root.pivot_offset.x, scene_root.pivot_offset.y],
			"matches_researched_layout": layout_matches,
			"spine_position": [sprite.position.x, sprite.position.y],
			"spine_scale": [sprite.scale.x, sprite.scale.y],
		},
		"scene_skeleton_data": (
			(scene_skeleton_value as Resource).resource_path
			if scene_skeleton_value is Resource
			else ""
		),
		"sprite": sprite,
	}


func _capture_frame(
	viewport: SubViewport,
	backdrop: CanvasItem,
	sprite: Node2D,
	state: Object,
	sample_index: int,
	sample_time: float,
	fraction: float,
) -> Dictionary:
	backdrop.visible = true
	state.call("set_animation", ANIMATION_NAME, false, 0)
	sprite.call("update_skeleton", sample_time)

	await process_frame
	await RenderingServer.frame_post_draw
	var image := viewport.get_texture().get_image()
	if image == null or image.is_empty():
		_fail("Vulkan returned an empty image for sample %d." % sample_index)
		return {}
	if image.get_format() != Image.FORMAT_RGBA8:
		image.convert(Image.FORMAT_RGBA8)

	# The real scene intentionally paints an opaque full-canvas backdrop. Hide
	# only that scene node for one additional render so clipping checks measure
	# the Spine attachments instead of mistaking the designed background edges
	# for cropped character art. Neither source pixels nor Alpha are modified.
	backdrop.visible = false
	await process_frame
	await RenderingServer.frame_post_draw
	var spine_only := viewport.get_texture().get_image()
	backdrop.visible = true
	if spine_only == null or spine_only.is_empty():
		_fail("Vulkan returned no Spine-only clipping sample for %d." % sample_index)
		return {}
	if spine_only.get_format() != Image.FORMAT_RGBA8:
		spine_only.convert(Image.FORMAT_RGBA8)
	var spine_only_path := (
		_output_root.path_join("spine-only/frame-%02d.png" % sample_index).simplify_path()
	)
	DirAccess.make_dir_recursive_absolute(spine_only_path.get_base_dir())
	var spine_only_save_error := spine_only.save_png(spine_only_path)
	if spine_only_save_error != OK:
		_fail(
			"Could not save Spine-only sample %d (error %d)."
			% [sample_index, spine_only_save_error]
		)

	var relative_path := "frames/frame-%02d-t%.7f.png" % [sample_index, sample_time]
	var absolute_path := _output_root.path_join(relative_path).simplify_path()
	DirAccess.make_dir_recursive_absolute(absolute_path.get_base_dir())
	var save_error := image.save_png(absolute_path)
	if save_error != OK:
		_fail("Could not save '%s' (error %d)." % [absolute_path, save_error])

	var used_rect := spine_only.get_used_rect()
	var non_empty := used_rect.has_area()
	var touches_canvas_edge := non_empty and (
		used_rect.position.x <= 0
		or used_rect.position.y <= 0
		or used_rect.end.x >= CANVAS_SIZE.x
		or used_rect.end.y >= CANVAS_SIZE.y
	)
	if not non_empty:
		_fail("Sample %d is fully transparent." % sample_index)
	if touches_canvas_edge:
		_fail(
			"Sample %d touches the 2560x1200 canvas edge and may be clipped: %s"
			% [sample_index, used_rect]
		)

	var frame_report := {
		"fraction": fraction,
		"non_empty": non_empty,
		"path": relative_path,
		"sample_time": sample_time,
		"sha256": _image_sha256(image),
		"touches_canvas_edge": touches_canvas_edge,
		"used_rect": _rect_report(used_rect),
	}
	return frame_report


func _write_report(report: Dictionary) -> void:
	if _output_root.is_empty():
		return
	DirAccess.make_dir_recursive_absolute(_output_root)
	var report_path := _output_root.path_join("report.json")
	var file := FileAccess.open(report_path, FileAccess.WRITE)
	if file == null:
		_fail("Could not open report for writing: %s" % report_path)
		return
	file.store_string(JSON.stringify(report, "\t") + "\n")
	file.close()
	print("[vivhite-character-select-preview] Report: %s" % report_path)


func _render_preview() -> void:
	var options := _parse_args()
	if options.has("help"):
		quit(0)
		return
	if options.is_empty():
		quit(1)
		return

	var repository_root := _find_repository_root()
	if repository_root.is_empty():
		quit(1)
		return
	_output_root = _safe_output_root(str(options.output), repository_root)
	if _output_root.is_empty():
		quit(1)
		return

	var report := {
		"animation": ANIMATION_NAME,
		"animation_changed": false,
		"auto_player_runtime_available": false,
		"canvas_size": [CANVAS_SIZE.x, CANVAS_SIZE.y],
		"display_server": DisplayServer.get_name(),
		"errors": [],
		"frames": [],
		"generated_utc": Time.get_datetime_string_from_system(true),
		"layout": {},
		"output_root": _output_root.replace("\\", "/"),
		"sample_fractions": SAMPLE_FRACTIONS,
		"scene": "",
		"scene_contract_valid": false,
		"schema_version": 1,
		"success": false,
	}

	if DisplayServer.get_name() == "headless":
		_fail(
			"A real Vulkan display is required; Godot's headless display cannot capture "
			+ "a ViewportTexture."
		)
		report.errors = _errors.duplicate()
		_write_report(report)
		quit(1)
		return
	var rendering_driver := RenderingServer.get_current_rendering_driver_name()
	report["rendering_driver"] = rendering_driver
	if rendering_driver.to_lower() != "vulkan":
		_fail("Expected Vulkan, but Godot selected '%s'." % rendering_driver)

	var pck_path := str(options.pck).simplify_path()
	report["base_pck"] = pck_path.replace("\\", "/")
	if pck_path.is_empty() or not FileAccess.file_exists(pck_path):
		_fail("A valid base-game PCK is required via --pck or VIVHITE_STS2_PCK_PATH.")
	elif not ProjectSettings.load_resource_pack(pck_path, false):
		_fail("Could not mount base-game PCK '%s'." % pck_path)

	for type_name in ["SpineSprite", "SpineSkeletonDataResource"]:
		if not ClassDB.class_exists(type_name):
			_fail("The game's Spine GDExtension class '%s' is unavailable." % type_name)
	if not _errors.is_empty():
		report.errors = _errors.duplicate()
		_write_report(report)
		quit(1)
		return

	var resource_path := _resource_path(str(options.resource), repository_root)
	report["resource"] = resource_path
	if resource_path.is_empty() or not ResourceLoader.exists(resource_path):
		_fail("Skeleton-data resource does not exist: %s" % resource_path)
		report.errors = _errors.duplicate()
		_write_report(report)
		quit(1)
		return
	var skeleton_data: Resource = ResourceLoader.load(resource_path)
	if skeleton_data == null or not skeleton_data.is_class("SpineSkeletonDataResource"):
		_fail("Could not load SpineSkeletonDataResource '%s'." % resource_path)
		report.errors = _errors.duplicate()
		_write_report(report)
		quit(1)
		return

	var skeleton_file_value: Variant = skeleton_data.get("skeleton_file_res")
	var atlas_value: Variant = skeleton_data.get("atlas_res")
	if not skeleton_file_value is Resource:
		_fail("Skeleton data exposes no skeleton_file_res.")
	else:
		var skeleton_file: Resource = skeleton_file_value
		report["skeleton_resource"] = skeleton_file.resource_path
		if not skeleton_file.resource_path.to_lower().ends_with(".spjson"):
			_fail(
				"Character-select preview requires a private .spjson rig, got '%s'."
				% skeleton_file.resource_path
			)
	if not atlas_value is Resource:
		_fail("Skeleton data exposes no atlas_res.")
	else:
		var atlas: Resource = atlas_value
		report["atlas_resource"] = atlas.resource_path

	var spine_version := str(skeleton_data.call("get_version"))
	report["spine_version"] = spine_version
	if spine_version != EXPECTED_SPINE_VERSION:
		_fail("Expected Spine %s, got %s." % [EXPECTED_SPINE_VERSION, spine_version])
	var animation_names := _object_names(skeleton_data.call("get_animations"))
	report["animation_names"] = animation_names
	if animation_names != [ANIMATION_NAME]:
		_fail(
			"Character-select rig must contain exactly ['%s']; got %s."
			% [ANIMATION_NAME, animation_names]
		)
	var skin_names := _object_names(skeleton_data.call("get_skins"))
	report["skin_names"] = skin_names
	if not skin_names.has("default"):
		_fail("Character-select rig is missing the default skin.")
	var animation: Object = skeleton_data.call("find_animation", ANIMATION_NAME)
	if animation == null:
		_fail("Character-select rig has no '%s' animation." % ANIMATION_NAME)
	var duration := 0.0 if animation == null else float(animation.call("get_duration"))
	report["duration"] = duration
	if absf(duration - EXPECTED_DURATION) > DURATION_TOLERANCE:
		_fail(
			"Animation duration must be %.7f seconds, got %.7f."
			% [EXPECTED_DURATION, duration]
		)
	if not _errors.is_empty():
		report.errors = _errors.duplicate()
		_write_report(report)
		quit(1)
		return

	var scene_path := _resource_path(str(options.scene), repository_root)
	report["scene"] = scene_path
	if scene_path.is_empty() or not ResourceLoader.exists(scene_path):
		_fail("Character-select scene does not exist: %s" % scene_path)
		report.errors = _errors.duplicate()
		_write_report(report)
		quit(1)
		return
	var packed_scene_value: Variant = ResourceLoader.load(scene_path)
	if not packed_scene_value is PackedScene:
		_fail("Could not load PackedScene '%s'." % scene_path)
		report.errors = _errors.duplicate()
		_write_report(report)
		quit(1)
		return
	var packed_scene: PackedScene = packed_scene_value
	var scene_contract := _instantiate_character_select_scene(packed_scene, skeleton_data)
	if scene_contract.is_empty():
		report.errors = _errors.duplicate()
		_write_report(report)
		quit(1)
		return
	report["layout"] = scene_contract.layout
	report["scene_skeleton_data"] = scene_contract.scene_skeleton_data
	var auto_player: Node = scene_contract.auto_player
	var auto_player_runtime_available: bool = scene_contract.auto_player_runtime_available
	report["auto_player_runtime_available"] = auto_player_runtime_available
	var backdrop: CanvasItem = scene_contract.backdrop
	var auto_player_script_value: Variant = auto_player.get_script()
	if auto_player_script_value is Script:
		report["auto_player_script"] = (auto_player_script_value as Script).resource_path
	if not _errors.is_empty():
		report.errors = _errors.duplicate()
		_write_report(report)
		quit(1)
		return

	root.size = CANVAS_SIZE
	root.content_scale_size = CANVAS_SIZE
	root.transparent_bg = true
	root.title = "Vivhite character-select private rig preview (offline)"

	var viewport := SubViewport.new()
	viewport.name = "VivhiteCharacterSelectPreviewViewport"
	viewport.size = CANVAS_SIZE
	viewport.transparent_bg = true
	viewport.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	viewport.render_target_clear_mode = SubViewport.CLEAR_MODE_ALWAYS
	root.add_child(viewport)
	var scene_instance: Control = scene_contract.instance
	var sprite: Node2D = scene_contract.sprite
	# Stop automatic clock advancement, but leave the real NSpineAutoPlayer in
	# place. Its _Ready still has to select the scene's sole animation below.
	sprite.call("set_update_mode", SPINE_UPDATE_MODE_MANUAL)
	viewport.add_child(scene_instance)
	await process_frame
	await process_frame

	var state: Object = sprite.call("get_animation_state")
	if state == null:
		_fail("The real scene's SpineSprite did not create an animation state.")
	else:
		var current_entry: Object = state.call("get_current", 0)
		if current_entry == null:
			if auto_player_runtime_available:
				_fail("NSpineAutoPlayer did not start track 0 after entering the scene tree.")
			else:
				# A standalone mod project can mount the game's C# Script resource,
				# but Godot does not register classes from sts2.dll as project script
				# classes. Keep the exact real scene/script-path contract and defer
				# execution of NSpineAutoPlayer itself to the in-game integration test.
				report["auto_player_execution"] = "deferred_to_in_game_integration"
				push_warning(
					"NSpineAutoPlayer C# class is unavailable in the standalone project; "
					+ "rendering the real scene by explicitly selecting its sole animation."
				)
		elif not current_entry.has_method("get_animation"):
			_fail("NSpineAutoPlayer created an unreadable Spine track entry.")
		else:
			var current_animation: Object = current_entry.call("get_animation")
			if current_animation == null or not current_animation.has_method("get_name"):
				_fail("NSpineAutoPlayer track 0 has no animation object.")
			else:
				var auto_animation_name := str(current_animation.call("get_name"))
				report["auto_player_animation"] = auto_animation_name
				if auto_animation_name != ANIMATION_NAME:
					_fail(
						"NSpineAutoPlayer started '%s', expected '%s'."
						% [auto_animation_name, ANIMATION_NAME]
					)
				else:
					report["auto_player_execution"] = "verified_in_standalone_preview"
	if not _errors.is_empty():
		report.errors = _errors.duplicate()
		_write_report(report)
		quit(1)
		return
	report["scene_contract_valid"] = true

	var unique_hashes := {}
	for sample_index in range(SAMPLE_FRACTIONS.size()):
		var fraction := SAMPLE_FRACTIONS[sample_index]
		var sample_time := duration * fraction
		var frame_report: Dictionary = await _capture_frame(
			viewport,
			backdrop,
			sprite,
			state,
			sample_index,
			sample_time,
			fraction,
		)
		if not frame_report.is_empty():
			report.frames.append(frame_report)
			var frame_hash := str(frame_report.get("sha256", ""))
			if not frame_hash.is_empty():
				unique_hashes[frame_hash] = true

	var animation_changed := unique_hashes.size() >= 2
	report["animation_changed"] = animation_changed
	report["unique_frame_hashes"] = unique_hashes.size()
	if report.frames.size() != SAMPLE_FRACTIONS.size():
		_fail(
			"Rendered %d frames; expected %d."
			% [report.frames.size(), SAMPLE_FRACTIONS.size()]
		)
	if not animation_changed:
		_fail("All five samples are pixel-identical; the animation did not visibly change.")
	if report.frames.size() == SAMPLE_FRACTIONS.size():
		report["loop_endpoint_matches"] = (
			str(report.frames[0].get("sha256", ""))
			== str(report.frames[-1].get("sha256", ""))
		)

	report.errors = _errors.duplicate()
	report["success"] = _errors.is_empty()
	_write_report(report)
	if _errors.is_empty():
		print(
			("[vivhite-character-select-preview] Rendered 5 Vulkan frames over %.7fs; "
			+ "%d unique frame hashes; no frame touched the canvas edge.")
			% [duration, unique_hashes.size()]
		)
		quit(0)
		return
	quit(1)
