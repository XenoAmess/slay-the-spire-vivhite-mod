extends SceneTree

## Renders a deterministic diagnostic contact sheet from the no-art consumer
## contract.  The colored capsules are graybox geometry only; they never become
## a Spine atlas or a production texture and do not create/repair any art Alpha.

const COMMAND := "render-semantic-right-arm-extremes"
const CONTRACT_PATH := "Vivhite/tools/candidates/semantic_right_arm/consumer-contract.json"
const OUTPUT_PATH := ".work/semantic-right-arm/extreme-poses.png"


class ArmGraybox extends Node2D:
	var contract: Dictionary
	var size := Vector2i(1440, 990)

	func _draw() -> void:
		draw_rect(Rect2(Vector2.ZERO, Vector2(size)), Color("111827"), true)
		var gates: Array = contract["extreme_pose_gates"]
		for index in range(gates.size()):
			_draw_pose(index, gates[index])

	func _draw_pose(index: int, gate: Dictionary) -> void:
		var columns := 3
		var cell_size := Vector2(460, 310)
		var cell_origin := Vector2(20 + (index % columns) * 475, 20 + (index / columns) * 320)
		draw_rect(Rect2(cell_origin, cell_size), Color("1f2937"), true)
		draw_rect(Rect2(cell_origin, cell_size), Color("475569"), false, 2.0)

		var landmarks: Dictionary = contract["landmarks"]
		var shoulder := _pair(landmarks["shoulder_pivot"]["world_units"])
		var elbow_setup := _pair(landmarks["elbow_pivot"]["world_units"])
		var palm_setup := _pair(landmarks["palm_deform_pivot"]["world_units"])
		var arc_setup := _pair(landmarks["magic_arc_anchor"]["world_units"])
		var upper_angle := float(gate["upper_arm_rotation_deg"])
		var forearm_angle := upper_angle + float(gate["forearm_hand_rotation_deg"])
		var palm_angle := forearm_angle + float(gate["palm_internal_rotation_deg"])
		var elbow := shoulder + (elbow_setup - shoulder).rotated(deg_to_rad(upper_angle))
		var palm := elbow + (palm_setup - elbow_setup).rotated(deg_to_rad(forearm_angle))
		var arc := palm + (arc_setup - palm_setup).rotated(deg_to_rad(palm_angle))

		var points := [shoulder, elbow, palm, arc]
		var bounds := Rect2(points[0], Vector2.ZERO)
		for point: Vector2 in points:
			bounds = bounds.expand(point)
		bounds = bounds.grow(80.0)
		var scale_factor: float = minf((cell_size.x - 30.0) / maxf(bounds.size.x, 1.0), (cell_size.y - 60.0) / maxf(bounds.size.y, 1.0))
		var center := cell_origin + Vector2(cell_size.x * 0.5, cell_size.y * 0.56)
		var bounds_center := bounds.position + bounds.size * 0.5
		var to_screen := func(point: Vector2) -> Vector2:
			return center + Vector2(point.x - bounds_center.x, -(point.y - bounds_center.y)) * scale_factor

		var shoulder_s: Vector2 = to_screen.call(shoulder)
		var elbow_s: Vector2 = to_screen.call(elbow)
		var palm_s: Vector2 = to_screen.call(palm)
		var arc_s: Vector2 = to_screen.call(arc)
		var upper_dir: Vector2 = (elbow_s - shoulder_s).normalized()
		var fore_dir: Vector2 = (palm_s - elbow_s).normalized()
		var px_to_world := float(contract["consumer"]["world_rect"][2]) / float(contract["consumer"]["source_size_px"][0])
		var upper: Dictionary = contract["attachments"]["upper_arm"]
		var forearm: Dictionary = contract["attachments"]["forearm_hand"]
		var root_overlap := float(upper["hidden_shoulder_root_overlap_px"]) * px_to_world * scale_factor
		var elbow_extension := float(upper["hidden_elbow_extension_px"]) * px_to_world * scale_factor
		var fore_overlap := float(forearm["hidden_elbow_root_overlap_px"]) * px_to_world * scale_factor
		var joint_radius := float(upper["joint_cap_radius_px"]) * px_to_world * scale_factor
		var occluder_radius := float(contract["attachments"]["shoulder_occluder_requirement"]["minimum_coverage_radius_px"]) * px_to_world * scale_factor

		# Draw order is the consumer contract: upper, torso sleeve occluder,
		# continuous forearm+hand, then the external slash anchor marker.
		draw_line(shoulder_s - upper_dir * root_overlap, elbow_s + upper_dir * elbow_extension, Color("60a5fa"), joint_radius * 1.55, true)
		draw_circle(shoulder_s, joint_radius, Color("60a5fa"))
		draw_circle(elbow_s, joint_radius, Color("60a5fa"))
		draw_circle(shoulder_s, occluder_radius, Color("334155"))
		draw_arc(shoulder_s, occluder_radius, 0.0, TAU, 48, Color("f8fafc"), 3.0, true)
		draw_line(elbow_s - fore_dir * fore_overlap, palm_s, Color("c084fc"), joint_radius * 1.45, true)
		draw_circle(elbow_s, joint_radius, Color("c084fc"))
		draw_circle(palm_s, joint_radius * 1.08, Color("f0abfc"))
		draw_line(palm_s, arc_s, Color("fbbf24"), 3.0, true)
		draw_circle(arc_s, 7.0, Color("fbbf24"))

		var label := "%s  U%+.0f F%+.0f P%+.0f" % [gate["name"], upper_angle, float(gate["forearm_hand_rotation_deg"]), float(gate["palm_internal_rotation_deg"])]
		draw_string(ThemeDB.fallback_font, cell_origin + Vector2(12, 24), label, HORIZONTAL_ALIGNMENT_LEFT, -1, 15, Color("e2e8f0"))
		draw_string(ThemeDB.fallback_font, cell_origin + Vector2(12, cell_size.y - 10), "blue upper < torso sleeve < violet forearm+hand < gold slash anchor", HORIZONTAL_ALIGNMENT_LEFT, -1, 12, Color("94a3b8"))

	func _pair(value: Variant) -> Vector2:
		var pair: Array = value
		return Vector2(float(pair[0]), float(pair[1]))


func _initialize() -> void:
	if DisplayServer.get_name() != "headless":
		DisplayServer.window_set_flag(DisplayServer.WINDOW_FLAG_NO_FOCUS, true)
		DisplayServer.window_set_position(Vector2i(-32000, -32000))
	call_deferred("_run")


func _run() -> void:
	var args := OS.get_cmdline_user_args()
	if args.is_empty():
		args = PackedStringArray([COMMAND])
	if args[0] != COMMAND:
		push_error("Usage: ... -- %s" % COMMAND)
		quit(2)
		return
	var repo_root := ProjectSettings.globalize_path("res://").path_join("../..").simplify_path()
	var value: Variant = JSON.parse_string(FileAccess.get_file_as_string(repo_root.path_join(CONTRACT_PATH)))
	if not value is Dictionary:
		push_error("Could not read semantic right-arm contract")
		quit(2)
		return
	var viewport := SubViewport.new()
	viewport.size = Vector2i(1440, 990)
	viewport.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	viewport.render_target_clear_mode = SubViewport.CLEAR_MODE_ALWAYS
	viewport.transparent_bg = false
	var canvas := ArmGraybox.new()
	canvas.contract = value
	viewport.add_child(canvas)
	root.add_child(viewport)
	RenderingServer.set_default_clear_color(Color("111827"))
	canvas.queue_redraw()
	await process_frame
	RenderingServer.force_draw(false)
	await RenderingServer.frame_post_draw
	var image := viewport.get_texture().get_image()
	if image == null or image.is_empty():
		push_error("Graybox SubViewport returned an empty image")
		quit(2)
		return
	var output := repo_root.path_join(OUTPUT_PATH)
	DirAccess.make_dir_recursive_absolute(output.get_base_dir())
	var error := image.save_png(output)
	if error != OK:
		push_error("Could not save %s: %s" % [output, error_string(error)])
		quit(2)
		return
	print("Rendered semantic right-arm extreme contact sheet: %s" % output)
	quit(0)
