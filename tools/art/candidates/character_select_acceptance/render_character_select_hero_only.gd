extends SceneTree

## Offline hero-only motion probe for the formal character-select Spine scene.
## It hides only the independent magic-sigil slot at runtime, then samples the
## exact `animation` timeline.  This proves the weighted Bai Qi mesh itself is
## animated instead of mistaking sigil rotation for character motion.

const DEFAULT_PCK := "G:/SteamLibrary/steamapps/common/Slay the Spire 2/SlayTheSpire2.pck"
const DEFAULT_OUTPUT := ".work/character-select-acceptance/spine-current/hero-only"
const SCENE_PATH := "res://Vivhite/skins/ironclad/scenes/character_select.tscn"
const SKELETON_DATA_PATH := (
	"res://Vivhite/skins/ironclad/spine/character_select/"
	+ "character_select_skeleton_data.tres"
)
const ANIMATION_NAME := "animation"
const SIGIL_SLOT := "vivhite_magic_backdrop"
const CANVAS_SIZE := Vector2i(2560, 1200)
const FRACTIONS: Array[float] = [0.0, 0.25, 0.5, 0.75, 1.0]
const SPINE_UPDATE_MODE_MANUAL := 2
const SCENE_ORIGIN := Vector2(320.0, 77.0)
const SPINE_POSITION := Vector2(-185.0, -20.0)
const SPINE_SCALE := Vector2(0.46, 0.46)

var _errors: Array[String] = []
var _repo_root := ""
var _output_root := ""


func _initialize() -> void:
	call_deferred("_run")


func _fail(message: String) -> void:
	_errors.append(message)
	push_error("[character-select-hero-only] %s" % message)


func _parse_args() -> Dictionary:
	var options := {"output": DEFAULT_OUTPUT, "pck": DEFAULT_PCK}
	var args := OS.get_cmdline_user_args()
	var index := 0
	while index < args.size():
		if index + 1 >= args.size() or not str(args[index]).begins_with("--"):
			_fail("Expected '--name value', got '%s'." % str(args[index]))
			return {}
		var name := str(args[index]).trim_prefix("--")
		if not options.has(name):
			_fail("Unknown option '--%s'." % name)
			return {}
		options[name] = str(args[index + 1])
		index += 2
	return options


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


func _object_names(items: Variant) -> Array[String]:
	var names: Array[String] = []
	if items != null:
		for item in items:
			if item != null and item.has_method("get_name"):
				names.append(str(item.call("get_name")))
	names.sort()
	return names


func _image_sha256(image: Image) -> String:
	var context := HashingContext.new()
	if context.start(HashingContext.HASH_SHA256) != OK:
		_fail("Could not start image SHA-256 context.")
		return ""
	if context.update(image.get_data()) != OK:
		_fail("Could not hash rendered image.")
		return ""
	return context.finish().hex_encode()


func _rect_report(rect: Rect2i) -> Dictionary:
	return {
		"x": rect.position.x,
		"y": rect.position.y,
		"width": rect.size.x,
		"height": rect.size.y,
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
	print("[character-select-hero-only] Report: %s" % path)


func _run() -> void:
	var options := _parse_args()
	_repo_root = _find_repo_root()
	if options.is_empty() or _repo_root.is_empty():
		quit(1)
		return
	_output_root = _safe_output(str(options.output))
	if _output_root.is_empty():
		quit(1)
		return
	DirAccess.make_dir_recursive_absolute(_output_root)

	var report := {
		"schema_version": 1,
		"success": false,
		"display_server": DisplayServer.get_name(),
		"rendering_driver": RenderingServer.get_current_rendering_driver_name(),
		"scene": SCENE_PATH,
		"animation": ANIMATION_NAME,
		"suppressed_slot": SIGIL_SLOT,
		"canvas_size": [CANVAS_SIZE.x, CANVAS_SIZE.y],
		"frames": [],
		"errors": [],
	}
	if DisplayServer.get_name() != "Windows":
		_fail("Expected Windows display server, got %s." % DisplayServer.get_name())
	if RenderingServer.get_current_rendering_driver_name().to_lower() != "vulkan":
		_fail("Expected Vulkan renderer.")
	var pck_path := str(options.pck).simplify_path()
	if not FileAccess.file_exists(pck_path) or not ProjectSettings.load_resource_pack(pck_path, false):
		_fail("Could not mount base-game PCK: %s" % pck_path)
	if not ClassDB.class_exists("SpineSprite"):
		_fail("The base-game Spine GDExtension is unavailable.")
	if not ResourceLoader.exists(SCENE_PATH):
		_fail("Character-select scene is missing: %s" % SCENE_PATH)
	if not ResourceLoader.exists(SKELETON_DATA_PATH):
		_fail("Character-select skeleton data is missing: %s" % SKELETON_DATA_PATH)
	if not _errors.is_empty():
		report.errors = _errors.duplicate()
		_write_report(report)
		quit(1)
		return

	var skeleton_data_value: Variant = ResourceLoader.load(SKELETON_DATA_PATH)
	if not skeleton_data_value is Resource or not (skeleton_data_value as Resource).is_class("SpineSkeletonDataResource"):
		_fail("Could not load character-select SpineSkeletonDataResource.")
		report.errors = _errors.duplicate()
		_write_report(report)
		quit(1)
		return
	var names := _object_names((skeleton_data_value as Resource).call("get_animations"))
	report["animation_names"] = names
	if names != [ANIMATION_NAME]:
		_fail("Expected exactly ['animation'], got %s." % names)
	if not _errors.is_empty():
		report.errors = _errors.duplicate()
		_write_report(report)
		quit(1)
		return

	root.size = CANVAS_SIZE
	root.content_scale_size = CANVAS_SIZE
	root.transparent_bg = true
	var viewport := SubViewport.new()
	viewport.size = CANVAS_SIZE
	viewport.transparent_bg = true
	viewport.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	viewport.render_target_clear_mode = SubViewport.CLEAR_MODE_ALWAYS
	root.add_child(viewport)
	var stage := Node2D.new()
	stage.position = SCENE_ORIGIN
	viewport.add_child(stage)
	var sprite := ClassDB.instantiate("SpineSprite") as Node2D
	if sprite == null:
		_fail("Could not instantiate SpineSprite.")
		report.errors = _errors.duplicate()
		_write_report(report)
		quit(1)
		return
	sprite.position = SPINE_POSITION
	sprite.scale = SPINE_SCALE
	sprite.call("set_update_mode", SPINE_UPDATE_MODE_MANUAL)
	sprite.set("skeleton_data_res", skeleton_data_value)
	stage.add_child(sprite)
	await process_frame
	await process_frame

	var state: Object = sprite.call("get_animation_state")
	var runtime_skeleton: Object = sprite.call("get_skeleton")
	if state == null or runtime_skeleton == null:
		_fail("SpineSprite created no animation state or runtime skeleton.")
	var sigil_slot_value: Variant = null
	if runtime_skeleton != null:
		sigil_slot_value = runtime_skeleton.call("find_slot", SIGIL_SLOT)
	if sigil_slot_value == null:
		_fail("Runtime skeleton has no %s slot." % SIGIL_SLOT)
	if not _errors.is_empty():
		report.errors = _errors.duplicate()
		_write_report(report)
		quit(1)
		return
	var sigil_slot: Object = sigil_slot_value as Object
	if not sigil_slot.has_method("get_color") or not sigil_slot.has_method("set_color"):
		_fail("Sigil slot exposes no color mutation API.")
		report.errors = _errors.duplicate()
		_write_report(report)
		quit(1)
		return
	var color: Color = sigil_slot.call("get_color")
	sigil_slot.call("set_color", Color(color.r, color.g, color.b, 0.0))

	var animation: Object = (skeleton_data_value as Resource).call("find_animation", ANIMATION_NAME)
	var duration := float(animation.call("get_duration"))
	report["duration"] = duration
	var hashes := {}
	for index in range(FRACTIONS.size()):
		var fraction := FRACTIONS[index]
		var sample_time := duration * fraction
		state.call("set_animation", ANIMATION_NAME, false, 0)
		# Slot-color timelines are absent in this rig, so the zero Alpha survives
		# animation application while all weighted hero-bone timelines evaluate.
		sprite.call("update_skeleton", sample_time)
		var current_color: Color = sigil_slot.call("get_color")
		if current_color.a > 0.0001:
			_fail("Sigil slot became visible at sample %d." % index)
		await process_frame
		await RenderingServer.frame_post_draw
		var image := viewport.get_texture().get_image()
		if image == null or image.is_empty():
			_fail("Vulkan returned no hero-only frame at sample %d." % index)
			continue
		if image.get_format() != Image.FORMAT_RGBA8:
			image.convert(Image.FORMAT_RGBA8)
		var used := image.get_used_rect()
		var touches_edge := used.has_area() and (
			used.position.x <= 0
			or used.position.y <= 0
			or used.end.x >= CANVAS_SIZE.x
			or used.end.y >= CANVAS_SIZE.y
		)
		if not used.has_area():
			_fail("Hero-only frame %d is empty." % index)
		if touches_edge:
			_fail("Hero-only frame %d touches the canvas edge." % index)
		var file_name := "frame-%02d.png" % index
		var save_error := image.save_png(_output_root.path_join(file_name))
		if save_error != OK:
			_fail("Could not save hero-only frame %d." % index)
		var hash := _image_sha256(image)
		hashes[hash] = true
		report.frames.append({
			"index": index,
			"fraction": fraction,
			"sample_time": sample_time,
			"path": file_name,
			"sha256": hash,
			"used_rect": _rect_report(used),
			"touches_canvas_edge": touches_edge,
		})
	report["unique_frame_hashes"] = hashes.size()
	report["hero_mesh_visibly_changes"] = hashes.size() >= 2
	if hashes.size() < 2:
		_fail("Hero-only samples are pixel-identical; hero mesh did not visibly move.")
	if report.frames.size() == FRACTIONS.size():
		report["loop_endpoint_matches"] = report.frames[0].sha256 == report.frames[-1].sha256
		if not report.loop_endpoint_matches:
			_fail("Hero-only loop endpoints do not match.")
	report.errors = _errors.duplicate()
	report.success = _errors.is_empty() and report.frames.size() == FRACTIONS.size()
	_write_report(report)
	quit(0 if report.success else 1)
