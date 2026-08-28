extends "../../compare/preview/render_combat_rig_compare.gd"

## Candidate-local Vulkan sampler for the exact atomic death-swap landmarks.
## It reuses the comparison renderer's capture and Alpha metrics but renders
## only `die`, avoiding a 141-sample pass over all eight animations.

const EXACT_DATA_PATH := "res://tools/candidates/whole_mesh/vivhite_combat_skeleton_data.tres"
const EXACT_OUTPUT := ".work/combat-rig-compare-preview/whole-mesh-atomic-death-exact-preswap"
const EXACT_TIMES: Array[float] = [
	0.0,
	0.82,
	0.94,
	1.0,
	1.0499,
	1.05,
	1.1666667,
	1.30,
	1.80,
	1.90,
	2.3333335,
]


func _initialize() -> void:
	if DisplayServer.get_name() != "headless":
		DisplayServer.window_set_flag(DisplayServer.WINDOW_FLAG_NO_FOCUS, true)
		DisplayServer.window_set_position(Vector2i(-32000, -32000))
	call_deferred("_run_exact")


func _run_exact() -> void:
	if DisplayServer.get_name() == "headless":
		push_error("[whole-mesh-atomic-exact] Vulkan display server is required")
		quit(2)
		return
	_output_root = ProjectSettings.globalize_path("res://").path_join("..").path_join(EXACT_OUTPUT).simplify_path()
	DirAccess.make_dir_recursive_absolute(_output_root)
	var skeleton_data := ResourceLoader.load(EXACT_DATA_PATH)
	if skeleton_data == null or not skeleton_data.is_class("SpineSkeletonDataResource"):
		push_error("[whole-mesh-atomic-exact] Could not load %s" % EXACT_DATA_PATH)
		quit(2)
		return
	var animation: Object = skeleton_data.call("find_animation", "die")
	if animation == null:
		push_error("[whole-mesh-atomic-exact] die animation is missing")
		quit(2)
		return
	var duration := float(animation.call("get_duration"))
	var viewport := SubViewport.new()
	viewport.name = "VivhiteWholeMeshAtomicDeathExactViewport"
	viewport.size = _canvas
	viewport.transparent_bg = true
	viewport.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	viewport.render_target_clear_mode = SubViewport.CLEAR_MODE_ALWAYS
	root.add_child(viewport)
	var stage := Node2D.new()
	viewport.add_child(stage)

	var reports := []
	var images: Array[Image] = []
	var validity: Array[bool] = []
	for index in EXACT_TIMES.size():
		var sample_time := EXACT_TIMES[index]
		var captured := await _capture_frame(
			stage,
			viewport,
			skeleton_data,
			"die",
			duration,
			sample_time / duration,
			index,
			"whole_mesh_atomic_exact",
		)
		if captured.is_empty():
			continue
		var report: Dictionary = captured.report
		report["requested_time"] = sample_time
		reports.append(report)
		images.append(captured.image)
		validity.append(bool(report.passed))

	var contact_sheet := _output_root.path_join("whole_mesh_atomic_exact/contact-sheets/die-exact.png")
	var sheet_ok := _write_contact_sheet(images, validity, contact_sheet, EXACT_TIMES.size())
	var success := reports.size() == EXACT_TIMES.size() and validity.all(func(value: bool) -> bool: return value) and sheet_ok
	_write_json(_output_root.path_join("summary.json"), {
		"candidate": EXACT_DATA_PATH,
		"contact_sheet": _relative_to_output(contact_sheet),
		"display_server": DisplayServer.get_name(),
		"frames": reports,
		"rendering_driver": RenderingServer.get_current_rendering_driver_name(),
		"requested_times": EXACT_TIMES,
		"success": success,
	})
	if success:
		print("[whole-mesh-atomic-exact] Rendered %d exact Vulkan death samples" % reports.size())
		quit(0)
		return
	push_error("[whole-mesh-atomic-exact] Exact Vulkan sampling failed")
	quit(1)
