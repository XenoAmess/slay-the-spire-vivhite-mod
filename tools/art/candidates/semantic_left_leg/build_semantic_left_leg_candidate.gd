extends SceneTree

## Builds a preview-only semantic-group study for Vivhite's screen-left/far leg.
## The paid source PNGs are read-only. This tool only validates their native
## Alpha, applies rigid transform/size adaptation, and composites them for the
## setup and consumer-derived maximum joint rotations. It never creates a mask,
## thresholds source Alpha, repairs edges, deploys, or writes runtime assets.

const OUTPUT_RELATIVE := "Vivhite/tools/candidates/semantic_left_leg"
const CANVAS := Vector2i(1200, 1000)
const PREVIEW_SCALE := 0.70
const PREVIEW_HIP := Vector2(600.0, 100.0)

const THIGH_SOURCE := (
	"assets/vivhite-ironclad/generated/evolink-paid/2026-08-28/"
	+ "0078-split-leg-left-thigh-attachment-attempt-07/output.png"
)
const LOWER_SOURCE := (
	"assets/vivhite-ironclad/generated/evolink-paid/2026-08-28/"
	+ "0088-split-leg-left-lower-attachment-attempt-01/output.png"
)
const BOOT_SOURCE := (
	"assets/vivhite-ironclad/generated/evolink-paid/2026-08-28/"
	+ "0063-split-leg-left-boot-attachment-attempt-08/output.png"
)
const MASTER_0018 := (
	"assets/vivhite-ironclad/generated/evolink-paid/2026-08-28/"
	+ "0018-combat-body-master-attempt-01/output.png"
)
const MASTER_0022 := (
	"assets/vivhite-ironclad/generated/evolink-paid/2026-08-28/"
	+ "0022-combat-body-master-attempt-05/output.png"
)
const RUNTIME_MASTER := "assets/vivhite-ironclad/custom/combat/sources/vivhite-combat-body-master-v1.png"
const SPLIT_SKELETON := "assets/vivhite-ironclad/candidates/split_mesh/combat/vivhite_combat_split_mesh.spjson"

const EXPECTED_HASHES := {
	THIGH_SOURCE: "da48818eb18918236144a2dd0a186218a9fa1d7c6494ac36075532fadd7b72db",
	LOWER_SOURCE: "70b1d86a47279484e23f82f701dceb9a1ae88a1e8f66fbafd60a60f3091ee0ca",
	BOOT_SOURCE: "fd8dd7c3fc9380f540a690421b81ca6a76363407214a80586af63de58a75bf54",
	MASTER_0018: "86ffd64a637d170e213879e72d986b707ee181d4812c8e3fb1eda4abfab98bd1",
	MASTER_0022: "488e74758164dab0702ec6f943e02d23d9561caef29320275f698cb0000e232e",
	RUNTIME_MASTER: "86ffd64a637d170e213879e72d986b707ee181d4812c8e3fb1eda4abfab98bd1",
	SPLIT_SKELETON: "97b2d5f8dd8b14ca39bef1b18921a8c24f89930720c4a28d9234784be4dd816b",
}

# The hard-coded split builder samples these landmarks from 0018's 1680x2512
# canvas. The generated pieces are therefore tested against this real consumer,
# not silently against the visually different 0022 proposal.
const HIP_SOURCE_POINT := Vector2(575.0, 1190.0)
const KNEE_SOURCE_POINT := Vector2(500.0, 1530.0)
const ANKLE_SOURCE_POINT := Vector2(485.0, 1840.0)
const FOOT_ORIGIN_SOURCE_POINT := Vector2(485.0, 1940.0)

# Existing source prompts reserve these end bands for hidden overlap. Mapping
# the internal anchors, rather than the Alpha extrema, preserves overlap past
# the actual hip/knee/ankle joints.
const THIGH_TOP_ANCHOR_FRACTION := 0.18
const THIGH_BOTTOM_ANCHOR_FRACTION := 0.85
const LOWER_TOP_ANCHOR_FRACTION := 0.18
const LOWER_BOTTOM_ANCHOR_FRACTION := 0.82

# 0063's solid-body aspect ratio matches the old 340x390 foot UV. These two
# normalized coordinates preserve the old contract while making its ambiguity
# explicit: attachment origin != physical ankle rotation pivot.
const BOOT_PIVOT_BBOX_FRACTION := Vector2(0.4264705882, 0.0769230769)
const BOOT_ORIGIN_BBOX_FRACTION := Vector2(0.4264705882, 0.3333333333)
# The legacy UV fractions above do not land on 0063's actual cuff geometry.
# These review-only points were measured on the unmodified generated PNG and
# align the stocking with the physical cuff for a meaningful seam/rotation
# preview. They are not promoted as production artwork coordinates.
const BOOT_REVIEW_PHYSICAL_PIVOT := Vector2(570.0, 300.0)
const BOOT_REVIEW_PHYSICAL_ORIGIN := Vector2(570.0, 472.0)

const POSES := [
	{"id": "legacy_uv_setup", "thigh": 0.0, "knee": 0.0, "ankle": 0.0, "boot_anchor": "legacy_uv"},
	{"id": "setup", "thigh": 0.0, "knee": 0.0, "ankle": 0.0, "boot_anchor": "review_physical"},
	{"id": "max_knee_flex", "thigh": 0.0, "knee": -88.0, "ankle": 0.0, "boot_anchor": "review_physical"},
	{"id": "max_ankle_flex", "thigh": 0.0, "knee": 0.0, "ankle": 21.0, "boot_anchor": "review_physical"},
	{"id": "combined_death_extreme", "thigh": 58.0, "knee": -88.0, "ankle": 21.0, "boot_anchor": "review_physical"},
]

const BACKGROUNDS := {
	"black": Color("10141d"),
	"white": Color("f2f4f7"),
	"bluegray": Color("2d3f4b"),
}

var _repo_root := ""
var _output_root := ""
var _errors: Array[String] = []
var _source_images := {}
var _source_stats := {}
var _source_anchors := {}
var _runtime_contract := {}


func _initialize() -> void:
	if DisplayServer.get_name() != "headless":
		DisplayServer.window_set_flag(DisplayServer.WINDOW_FLAG_NO_FOCUS, true)
		DisplayServer.window_set_position(Vector2i(-32000, -32000))
	call_deferred("_run")


func _run() -> void:
	_repo_root = ProjectSettings.globalize_path("res://").path_join("../..").simplify_path()
	_output_root = _repo_root.path_join(OUTPUT_RELATIVE).simplify_path()
	if not _load_and_validate_inputs():
		_finish_failure()
		return
	if not _read_consumer_contract():
		_finish_failure()
		return
	if not _derive_source_anchors():
		_finish_failure()
		return
	DirAccess.make_dir_recursive_absolute(_output_root)
	DirAccess.make_dir_recursive_absolute(_output_root.path_join("poses"))
	DirAccess.make_dir_recursive_absolute(_output_root.path_join("composites"))

	var viewport := SubViewport.new()
	viewport.name = "VivhiteSemanticLeftLegViewport"
	viewport.size = CANVAS
	viewport.transparent_bg = true
	viewport.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	viewport.render_target_clear_mode = SubViewport.CLEAR_MODE_ALWAYS
	root.add_child(viewport)
	var stage := Node2D.new()
	viewport.add_child(stage)

	var pose_reports := []
	var bluegray_frames: Array[Image] = []
	var overlay_frames: Array[Image] = []
	for pose_value: Variant in POSES:
		var pose: Dictionary = pose_value
		var capture := await _capture_pose(stage, viewport, pose, false)
		var overlay_capture := await _capture_pose(stage, viewport, pose, true)
		if capture.is_empty() or overlay_capture.is_empty():
			_finish_failure()
			return
		var rgba: Image = capture["image"]
		var overlay: Image = overlay_capture["image"]
		var id := str(pose["id"])
		var rgba_path := _output_root.path_join("poses/%s_rgba.png" % id)
		if rgba.save_png(rgba_path) != OK:
			_fail("Could not save %s" % rgba_path)
			_finish_failure()
			return
		var overlay_path := _output_root.path_join("poses/%s_overlay.png" % id)
		if overlay.save_png(overlay_path) != OK:
			_fail("Could not save %s" % overlay_path)
			_finish_failure()
			return
		var background_paths := {}
		for background_name: String in BACKGROUNDS:
			var composite := _source_over(rgba, BACKGROUNDS[background_name])
			var composite_path := _output_root.path_join(
				"composites/%s_%s.png" % [id, background_name]
			)
			if composite.save_png(composite_path) != OK:
				_fail("Could not save %s" % composite_path)
				_finish_failure()
				return
			background_paths[background_name] = _relative_output(composite_path)
			if background_name == "bluegray":
				bluegray_frames.append(composite)
		overlay_frames.append(_source_over(overlay, BACKGROUNDS["bluegray"]))
		var geometry: Dictionary = capture["geometry"]
		pose_reports.append({
			"id": id,
			"boot_anchor_mode": str(pose["boot_anchor"]),
			"angles_degrees": {
				"thigh": float(pose["thigh"]),
				"knee": float(pose["knee"]),
				"ankle": float(pose["ankle"]),
			},
			"joints": _serialize_points(geometry["joints"]),
			"layer_order_back_to_front": ["0078_thigh", "0088_lower_stocking", "0063_boot"],
			"rgba": _relative_output(rgba_path),
			"overlay": _relative_output(overlay_path),
			"source_over": background_paths,
		})

	var contact_sheet := _make_contact_sheet(bluegray_frames, 2, Color("18222c"))
	var contact_path := _output_root.path_join("contact_sheet_bluegray.png")
	if contact_sheet.save_png(contact_path) != OK:
		_fail("Could not save contact sheet")
		_finish_failure()
		return
	var overlay_sheet := _make_contact_sheet(overlay_frames, 2, Color("18222c"))
	var overlay_sheet_path := _output_root.path_join("contact_sheet_overlay.png")
	if overlay_sheet.save_png(overlay_sheet_path) != OK:
		_fail("Could not save overlay contact sheet")
		_finish_failure()
		return

	var manifest := _build_manifest(pose_reports, contact_path, overlay_sheet_path)
	var manifest_path := _output_root.path_join("candidate.json")
	if not _write_json(manifest_path, manifest):
		_finish_failure()
		return
	print("Built semantic left-leg study: %s" % _output_root)
	print("  source topology: thigh + lower stocking + boot (research only)")
	print("  recommended topology: thigh + lower-leg-with-boot; keep knee, remove ankle seam")
	print("  poses: %d; consumer max knee=-88, ankle=+21" % POSES.size())
	quit(0)


func _load_and_validate_inputs() -> bool:
	for relative_path: String in EXPECTED_HASHES:
		var absolute_path := _repo_root.path_join(relative_path)
		if not FileAccess.file_exists(absolute_path):
			return _fail("Missing required input: %s" % relative_path)
		var observed_hash := FileAccess.get_sha256(absolute_path).to_lower()
		if observed_hash != str(EXPECTED_HASHES[relative_path]):
			return _fail("Input hash changed for %s: %s" % [relative_path, observed_hash])
	for relative_path: String in [THIGH_SOURCE, LOWER_SOURCE, BOOT_SOURCE, MASTER_0018, MASTER_0022]:
		var absolute_path := _repo_root.path_join(relative_path)
		var image := Image.load_from_file(absolute_path)
		if image == null or image.is_empty():
			return _fail("Could not decode %s" % relative_path)
		if image.get_format() != Image.FORMAT_RGBA8:
			return _fail("Source must decode natively as RGBA8: %s" % relative_path)
		if not _corners_transparent(image):
			return _fail("All four source corners must have Alpha=0: %s" % relative_path)
		_source_images[relative_path] = image
		if relative_path in [THIGH_SOURCE, LOWER_SOURCE, BOOT_SOURCE]:
			var stats := _analyze_alpha(image)
			if int(stats["alpha_128_count"]) <= 0:
				return _fail("Source has no A>=128 physical core: %s" % relative_path)
			if int(stats["edge_alpha_1_count"]) != 0:
				return _fail("Source Alpha touches its canvas edge: %s" % relative_path)
			_source_stats[relative_path] = stats
	return true


func _read_consumer_contract() -> bool:
	var path := _repo_root.path_join(SPLIT_SKELETON)
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(path))
	if not parsed is Dictionary:
		return _fail("Could not parse split candidate JSON")
	var skeleton: Dictionary = parsed
	var bones := {}
	for bone_value: Variant in skeleton.get("bones", []):
		var bone: Dictionary = bone_value
		bones[str(bone["name"])] = bone
	var required_parents := {
		"vivhite_knee_left": "vivhite_thigh_left",
		"vivhite_ankle_left": "vivhite_knee_left",
		"vivhite_foot_left": "vivhite_ankle_left",
	}
	for bone_name: String in required_parents:
		if not bones.has(bone_name):
			return _fail("Consumer is missing %s" % bone_name)
		if str(bones[bone_name].get("parent", "")) != str(required_parents[bone_name]):
			return _fail("Consumer parent mismatch for %s" % bone_name)
	var slot_indices := {}
	var slots: Array = skeleton.get("slots", [])
	for index in slots.size():
		var slot: Dictionary = slots[index]
		slot_indices[str(slot["name"])] = index
	var expected_slots := {
		"part_leg_left_thigh": 1,
		"part_leg_left_lower": 3,
		"part_leg_left_foot": 5,
	}
	for slot_name: String in expected_slots:
		if int(slot_indices.get(slot_name, -1)) != int(expected_slots[slot_name]):
			return _fail("Consumer slot order changed for %s" % slot_name)
	var draw_order_animations := []
	for animation_name: String in skeleton.get("animations", {}):
		var animation: Dictionary = skeleton["animations"][animation_name]
		if animation.has("drawOrder") or animation.has("draworder"):
			draw_order_animations.append(animation_name)
	if not draw_order_animations.is_empty():
		return _fail("Consumer unexpectedly has drawOrder animation(s): %s" % draw_order_animations)
	var extrema := {}
	for bone_name: String in ["vivhite_thigh_left", "vivhite_knee_left", "vivhite_ankle_left"]:
		extrema[bone_name] = _rotation_extrema(skeleton["animations"], bone_name)
	_runtime_contract = {
		"actual_body_input": RUNTIME_MASTER,
		"actual_body_sha256": EXPECTED_HASHES[RUNTIME_MASTER],
		"runtime_body_equals_0018": EXPECTED_HASHES[RUNTIME_MASTER] == EXPECTED_HASHES[MASTER_0018],
		"visual_proposal_0022_sha256": EXPECTED_HASHES[MASTER_0022],
		"visual_proposal_0022_bind_landmarks": (
			"absent: 0022 has no source-code consumer coordinates and is not the current split input"
		),
		"bone_chain": required_parents,
		"source_pixel_landmarks_0018": {
			"hip": _point(HIP_SOURCE_POINT),
			"knee": _point(KNEE_SOURCE_POINT),
			"ankle": _point(ANKLE_SOURCE_POINT),
			"foot_attachment_origin": _point(FOOT_ORIGIN_SOURCE_POINT),
		},
		"slot_indices": expected_slots,
		"slot_order_back_to_front": [
			"part_leg_left_thigh", "part_leg_left_lower", "part_leg_left_foot",
		],
		"has_draw_order_animation": false,
		"rotation_extrema_degrees": extrema,
	}
	return true


func _derive_source_anchors() -> bool:
	for source_path: String in [THIGH_SOURCE, LOWER_SOURCE]:
		var stats: Dictionary = _source_stats[source_path]
		var pca: Dictionary = stats["pca_alpha_128"]
		if float(pca.get("axis_length", 0.0)) < 32.0:
			return _fail("PCA axis is too short for %s" % source_path)
	var thigh_pca: Dictionary = _source_stats[THIGH_SOURCE]["pca_alpha_128"]
	var lower_pca: Dictionary = _source_stats[LOWER_SOURCE]["pca_alpha_128"]
	var boot_bbox := _dict_to_rect(_source_stats[BOOT_SOURCE]["alpha_128_bbox"])
	var boot_pivot := boot_bbox.position + boot_bbox.size * BOOT_PIVOT_BBOX_FRACTION
	var boot_origin := boot_bbox.position + boot_bbox.size * BOOT_ORIGIN_BBOX_FRACTION
	_source_anchors = {
		"thigh": {
			"start": _pca_point(thigh_pca, THIGH_TOP_ANCHOR_FRACTION),
			"end": _pca_point(thigh_pca, THIGH_BOTTOM_ANCHOR_FRACTION),
			"axis_angle_from_down_degrees": float(thigh_pca["angle_from_down_degrees"]),
		},
		"lower": {
			"start": _pca_point(lower_pca, LOWER_TOP_ANCHOR_FRACTION),
			"end": _pca_point(lower_pca, LOWER_BOTTOM_ANCHOR_FRACTION),
			"axis_angle_from_down_degrees": float(lower_pca["angle_from_down_degrees"]),
		},
		"boot": {
			"legacy_uv_ankle_pivot": boot_pivot,
			"legacy_uv_attachment_origin": boot_origin,
			"review_physical_ankle_pivot": BOOT_REVIEW_PHYSICAL_PIVOT,
			"review_physical_attachment_origin": BOOT_REVIEW_PHYSICAL_ORIGIN,
			"alpha_128_bbox": _rect(boot_bbox),
		},
	}
	return true


func _capture_pose(stage: Node2D, viewport: SubViewport, pose: Dictionary, overlay: bool) -> Dictionary:
	for child in stage.get_children():
		stage.remove_child(child)
		child.queue_free()
	await process_frame
	var geometry := _pose_geometry(pose)
	_add_component(
		stage,
		_source_images[THIGH_SOURCE],
		_source_anchors["thigh"]["start"],
		geometry["joints"]["hip"],
		float(geometry["angles_radians"]["thigh"]),
		float(geometry["scales"]["thigh"]),
		0,
		"0078_thigh"
	)
	_add_component(
		stage,
		_source_images[LOWER_SOURCE],
		_source_anchors["lower"]["start"],
		geometry["joints"]["knee"],
		float(geometry["angles_radians"]["lower"]),
		float(geometry["scales"]["lower"]),
		1,
		"0088_lower_stocking"
	)
	_add_component(
		stage,
		_source_images[BOOT_SOURCE],
		geometry["boot_source_ankle_pivot"],
		geometry["joints"]["ankle"],
		float(geometry["angles_radians"]["boot"]),
		float(geometry["scales"]["boot"]),
		2,
		"0063_boot"
	)
	if overlay:
		_add_debug_overlay(stage, geometry, str(pose["id"]))
	await process_frame
	await process_frame
	var image := viewport.get_texture().get_image()
	if image == null or image.is_empty():
		_fail("Viewport capture failed for %s" % pose["id"])
		return {}
	return {"image": image, "geometry": geometry}


func _pose_geometry(pose: Dictionary) -> Dictionary:
	var hip := PREVIEW_HIP
	var setup_thigh := (KNEE_SOURCE_POINT - HIP_SOURCE_POINT) * PREVIEW_SCALE
	var setup_lower := (ANKLE_SOURCE_POINT - KNEE_SOURCE_POINT) * PREVIEW_SCALE
	var setup_foot := (FOOT_ORIGIN_SOURCE_POINT - ANKLE_SOURCE_POINT) * PREVIEW_SCALE
	var thigh_angle := deg_to_rad(float(pose["thigh"]))
	var lower_angle := deg_to_rad(float(pose["thigh"]) + float(pose["knee"]))
	var boot_angle := deg_to_rad(
		float(pose["thigh"]) + float(pose["knee"]) + float(pose["ankle"])
	)
	var knee := hip + setup_thigh.rotated(thigh_angle)
	var ankle := knee + setup_lower.rotated(lower_angle)
	var foot_origin := ankle + setup_foot.rotated(boot_angle)
	var thigh_source_vector: Vector2 = (
		_source_anchors["thigh"]["end"] - _source_anchors["thigh"]["start"]
	)
	var lower_source_vector: Vector2 = (
		_source_anchors["lower"]["end"] - _source_anchors["lower"]["start"]
	)
	var boot_source_vector: Vector2 = (
		_boot_source_origin(pose) - _boot_source_pivot(pose)
	)
	return {
		"joints": {
			"hip": hip,
			"knee": knee,
			"ankle": ankle,
			"foot_attachment_origin": foot_origin,
		},
		"angles_radians": {
			"thigh": setup_thigh.angle() - thigh_source_vector.angle() + thigh_angle,
			"lower": setup_lower.angle() - lower_source_vector.angle() + lower_angle,
			"boot": setup_foot.angle() - boot_source_vector.angle() + boot_angle,
		},
		"scales": {
			"thigh": setup_thigh.length() / thigh_source_vector.length(),
			"lower": setup_lower.length() / lower_source_vector.length(),
			"boot": setup_foot.length() / boot_source_vector.length(),
		},
		"boot_source_ankle_pivot": _boot_source_pivot(pose),
		"boot_source_attachment_origin": _boot_source_origin(pose),
	}


func _add_component(
	stage: Node2D,
	image: Image,
	source_anchor: Vector2,
	target_anchor: Vector2,
	rotation: float,
	scale_factor: float,
	z_index: int,
	label: String,
) -> void:
	var sprite := Sprite2D.new()
	sprite.name = label
	sprite.texture = ImageTexture.create_from_image(image)
	sprite.centered = false
	sprite.offset = -source_anchor
	sprite.position = target_anchor
	sprite.rotation = rotation
	sprite.scale = Vector2.ONE * scale_factor
	sprite.z_index = z_index
	sprite.texture_filter = CanvasItem.TEXTURE_FILTER_LINEAR
	stage.add_child(sprite)


func _add_debug_overlay(stage: Node2D, geometry: Dictionary, pose_id: String) -> void:
	var joints: Dictionary = geometry["joints"]
	var line := Line2D.new()
	line.name = "bone_chain"
	line.width = 4.0
	line.default_color = Color("43d9ff")
	line.z_index = 20
	for joint_name: String in ["hip", "knee", "ankle", "foot_attachment_origin"]:
		line.add_point(joints[joint_name])
	stage.add_child(line)
	var colors := {
		"hip": Color("ffd54a"),
		"knee": Color("ff6b8b"),
		"ankle": Color("62ff9b"),
		"foot_attachment_origin": Color("b798ff"),
	}
	for joint_name: String in colors:
		var marker := Polygon2D.new()
		marker.name = joint_name
		marker.polygon = _circle_polygon(9.0, 24)
		marker.color = colors[joint_name]
		marker.position = joints[joint_name]
		marker.z_index = 21
		stage.add_child(marker)
	var label := Label.new()
	label.text = "%s | yellow hip, pink knee, green ankle pivot, violet foot-slot origin" % pose_id
	label.position = Vector2(18.0, 18.0)
	label.add_theme_font_size_override("font_size", 20)
	label.add_theme_color_override("font_color", Color.WHITE)
	label.add_theme_color_override("font_shadow_color", Color.BLACK)
	label.add_theme_constant_override("shadow_offset_x", 2)
	label.add_theme_constant_override("shadow_offset_y", 2)
	label.z_index = 30
	stage.add_child(label)


func _analyze_alpha(image: Image) -> Dictionary:
	var thresholds := [1, 16, 64, 128, 240]
	var counts := {}
	var mins := {}
	var maxs := {}
	for threshold: int in thresholds:
		counts[threshold] = 0
		mins[threshold] = Vector2i(image.get_width(), image.get_height())
		maxs[threshold] = Vector2i(-1, -1)
	var edge_alpha_1 := 0
	var sum_x := 0.0
	var sum_y := 0.0
	var sum_xx := 0.0
	var sum_yy := 0.0
	var sum_xy := 0.0
	for y in image.get_height():
		for x in image.get_width():
			var alpha := image.get_pixel(x, y).a8
			if alpha <= 0:
				continue
			if x == 0 or y == 0 or x == image.get_width() - 1 or y == image.get_height() - 1:
				edge_alpha_1 += 1
			for threshold: int in thresholds:
				if alpha >= threshold:
					counts[threshold] = int(counts[threshold]) + 1
					var minimum: Vector2i = mins[threshold]
					var maximum: Vector2i = maxs[threshold]
					mins[threshold] = Vector2i(mini(minimum.x, x), mini(minimum.y, y))
					maxs[threshold] = Vector2i(maxi(maximum.x, x), maxi(maximum.y, y))
			if alpha >= 128:
				sum_x += x
				sum_y += y
				sum_xx += float(x) * x
				sum_yy += float(y) * y
				sum_xy += float(x) * y
	var result := {
		"size": [image.get_width(), image.get_height()],
		"edge_alpha_1_count": edge_alpha_1,
	}
	for threshold: int in thresholds:
		var count := int(counts[threshold])
		result["alpha_%d_count" % threshold] = count
		if count > 0:
			var minimum: Vector2i = mins[threshold]
			var maximum: Vector2i = maxs[threshold]
			result["alpha_%d_bbox" % threshold] = [
				minimum.x, minimum.y, maximum.x - minimum.x + 1, maximum.y - minimum.y + 1,
			]
	var core_count := float(counts[128])
	var mean := Vector2(sum_x / core_count, sum_y / core_count)
	var cxx := sum_xx / core_count - mean.x * mean.x
	var cyy := sum_yy / core_count - mean.y * mean.y
	var cxy := sum_xy / core_count - mean.x * mean.y
	var theta := 0.5 * atan2(2.0 * cxy, cxx - cyy)
	var axis := Vector2(cos(theta), sin(theta)).normalized()
	if axis.y < 0.0:
		axis = -axis
	var min_projection := INF
	var max_projection := -INF
	for y in image.get_height():
		for x in image.get_width():
			if image.get_pixel(x, y).a8 < 128:
				continue
			var projection := (Vector2(x, y) - mean).dot(axis)
			min_projection = minf(min_projection, projection)
			max_projection = maxf(max_projection, projection)
	result["pca_alpha_128"] = {
		"mean": _point(mean),
		"axis": _point(axis),
		"min_projection": min_projection,
		"max_projection": max_projection,
		"axis_length": max_projection - min_projection,
		"angle_from_down_degrees": rad_to_deg(atan2(axis.x, axis.y)),
	}
	return result


func _rotation_extrema(animations: Dictionary, bone_name: String) -> Dictionary:
	var minimum := 0.0
	var maximum := 0.0
	var samples := 0
	for animation_name: String in animations:
		var animation: Dictionary = animations[animation_name]
		var bones: Dictionary = animation.get("bones", {})
		if not bones.has(bone_name):
			continue
		var timelines: Dictionary = bones[bone_name]
		if not timelines.has("rotate"):
			continue
		for key_value: Variant in timelines["rotate"]:
			var key: Dictionary = key_value
			var value := float(key.get("value", key.get("angle", 0.0)))
			minimum = minf(minimum, value)
			maximum = maxf(maximum, value)
			samples += 1
	return {"min": minimum, "max": maximum, "samples": samples}


func _build_manifest(pose_reports: Array, contact_path: String, overlay_sheet_path: String) -> Dictionary:
	var sources := {}
	for relative_path: String in [THIGH_SOURCE, LOWER_SOURCE, BOOT_SOURCE]:
		sources[relative_path] = {
			"sha256": EXPECTED_HASHES[relative_path],
			"alpha": _source_stats[relative_path],
		}
	var builder_thigh_angle := _angle_from_down(KNEE_SOURCE_POINT - HIP_SOURCE_POINT)
	var builder_lower_angle := _angle_from_down(ANKLE_SOURCE_POINT - KNEE_SOURCE_POINT)
	var thigh_angle := float(_source_anchors["thigh"]["axis_angle_from_down_degrees"])
	var lower_angle := float(_source_anchors["lower"]["axis_angle_from_down_degrees"])
	var boot_bbox := _dict_to_rect(_source_stats[BOOT_SOURCE]["alpha_128_bbox"])
	var boot_aspect := boot_bbox.size.x / boot_bbox.size.y
	var old_uv_aspect := 340.0 / 390.0
	var legacy_boot_pivot: Vector2 = _source_anchors["boot"]["legacy_uv_ankle_pivot"]
	var review_boot_pivot: Vector2 = _source_anchors["boot"]["review_physical_ankle_pivot"]
	return {
		"schema_version": 1,
		"candidate": "semantic_left_leg",
		"status": "isolated static research candidate; not runtime, not deployable",
		"screen_side": "screen-left / far leg",
		"canvas": [CANVAS.x, CANVAS.y],
		"sources": sources,
		"source_anchors": _serialize_nested_points(_source_anchors),
		"fit_metrics": {
			"builder_0018_thigh_axis_from_down_degrees": builder_thigh_angle,
			"source_0078_axis_from_down_degrees": thigh_angle,
			"source_0078_vs_builder_degrees": thigh_angle - builder_thigh_angle,
			"builder_0018_lower_axis_from_down_degrees": builder_lower_angle,
			"source_0088_axis_from_down_degrees": lower_angle,
			"source_0088_vs_builder_degrees": lower_angle - builder_lower_angle,
			"source_0063_alpha_128_aspect": boot_aspect,
			"legacy_foot_uv_aspect": old_uv_aspect,
			"source_0063_vs_legacy_aspect": boot_aspect - old_uv_aspect,
			"legacy_to_review_physical_pivot_distance_source_px": legacy_boot_pivot.distance_to(review_boot_pivot),
		},
		"consumer_contract": _runtime_contract,
		"poses": pose_reports,
		"contact_sheet": _relative_output(contact_path),
		"overlay_contact_sheet": _relative_output(overlay_sheet_path),
		"audit_conclusions": {
			"0018_0022_conflict": (
				"The split consumer and runtime master are byte-identical to 0018. "
				+ "0022 is a distinct visual/new-rig proposal and must not be mixed into this bind."
			),
			"draw_order": (
				"Current fixed order is thigh behind lower stocking behind boot; no animation changes it. "
				+ "Therefore 0088 cannot cover its top cap by drawing behind 0078, while 0063 correctly covers the ankle seam in front."
			),
			"ankle_pivot": (
				"The current foot slot origin maps to source (485,1940), but the physical ankle rotation pivot is (485,1840). "
				+ "They are intentionally distinct and both are shown in overlay previews. Applying the old UV-normalized "
				+ "pivot directly to 0063 misses its painted cuff; legacy_uv_setup preserves that failure, while setup uses "
				+ "a review-only physical cuff anchor so the seam can be inspected."
			),
			"topology_decision": (
				"Keep the knee as the one necessary articulation. Production should use two attachments: thigh + lower-leg-with-boot. "
				+ "Do not ship 0088 and 0063 as separate ankle attachments; their seam and independent ankle rotation are avoidable."
			),
			"current_three_piece_use": (
				"0078 + 0088 + 0063 are retained here only to test setup, fixed layer order, and the old maximum knee/ankle rotations."
			),
		},
		"production_recommendation": {
			"attachments": ["far_thigh", "far_lower_leg_with_boot"],
			"bones": ["far_thigh", "far_knee"],
			"preserve_knee_joint": true,
			"remove_separate_ankle_attachment": true,
			"layer_order_back_to_front": ["far_lower_leg_with_boot", "far_thigh", "near_leg", "skirt"],
			"reason": (
				"The knee needs the consumer's -88 degree relative motion. The ankle only reaches +21 degrees, "
				+ "while the separate white-stocking/boot seam and ambiguous foot-slot pivot create more visible risk than motion value. "
				+ "The merged lower piece should sit behind the thigh so its hidden knee tab is actually covered; this reverses the "
				+ "current fixed thigh-before-lower assumption for this far-leg group."
			),
		},
	}


func _boot_source_pivot(pose: Dictionary) -> Vector2:
	if str(pose.get("boot_anchor", "review_physical")) == "legacy_uv":
		return _source_anchors["boot"]["legacy_uv_ankle_pivot"]
	return _source_anchors["boot"]["review_physical_ankle_pivot"]


func _boot_source_origin(pose: Dictionary) -> Vector2:
	if str(pose.get("boot_anchor", "review_physical")) == "legacy_uv":
		return _source_anchors["boot"]["legacy_uv_attachment_origin"]
	return _source_anchors["boot"]["review_physical_attachment_origin"]


func _source_over(foreground: Image, background_color: Color) -> Image:
	var result := Image.create(foreground.get_width(), foreground.get_height(), false, Image.FORMAT_RGBA8)
	result.fill(background_color)
	result.blend_rect(foreground, Rect2i(Vector2i.ZERO, foreground.get_size()), Vector2i.ZERO)
	return result


func _make_contact_sheet(images: Array[Image], columns: int, background: Color) -> Image:
	var gutter := 12
	var rows := ceili(float(images.size()) / columns)
	var width := columns * CANVAS.x + (columns + 1) * gutter
	var height := rows * CANVAS.y + (rows + 1) * gutter
	var sheet := Image.create(width, height, false, Image.FORMAT_RGBA8)
	sheet.fill(background)
	for index in images.size():
		var column := index % columns
		var row := index / columns
		var destination := Vector2i(
			gutter + column * (CANVAS.x + gutter),
			gutter + row * (CANVAS.y + gutter),
		)
		sheet.blit_rect(images[index], Rect2i(Vector2i.ZERO, CANVAS), destination)
	return sheet


func _pca_point(pca: Dictionary, fraction: float) -> Vector2:
	var mean := _array_to_point(pca["mean"])
	var axis := _array_to_point(pca["axis"])
	var projection := lerpf(
		float(pca["min_projection"]),
		float(pca["max_projection"]),
		fraction,
	)
	return mean + axis * projection


func _angle_from_down(vector: Vector2) -> float:
	return rad_to_deg(atan2(vector.x, vector.y))


func _corners_transparent(image: Image) -> bool:
	for point: Vector2i in [
		Vector2i.ZERO,
		Vector2i(image.get_width() - 1, 0),
		Vector2i(0, image.get_height() - 1),
		Vector2i(image.get_width() - 1, image.get_height() - 1),
	]:
		if image.get_pixelv(point).a8 != 0:
			return false
	return true


func _circle_polygon(radius: float, segments: int) -> PackedVector2Array:
	var points := PackedVector2Array()
	for index in segments:
		var angle := TAU * index / segments
		points.append(Vector2(cos(angle), sin(angle)) * radius)
	return points


func _serialize_points(points: Dictionary) -> Dictionary:
	var result := {}
	for key: String in points:
		result[key] = _point(points[key])
	return result


func _serialize_nested_points(value: Variant) -> Variant:
	if value is Vector2:
		return _point(value)
	if value is Dictionary:
		var result := {}
		for key: Variant in value:
			result[key] = _serialize_nested_points(value[key])
		return result
	if value is Array:
		var result := []
		for item: Variant in value:
			result.append(_serialize_nested_points(item))
		return result
	return value


func _dict_to_rect(value: Variant) -> Rect2:
	var array: Array = value
	return Rect2(float(array[0]), float(array[1]), float(array[2]), float(array[3]))


func _array_to_point(value: Variant) -> Vector2:
	var array: Array = value
	return Vector2(float(array[0]), float(array[1]))


func _point(value: Vector2) -> Array:
	return [snappedf(value.x, 0.0001), snappedf(value.y, 0.0001)]


func _rect(value: Rect2) -> Array:
	return [
		snappedf(value.position.x, 0.0001),
		snappedf(value.position.y, 0.0001),
		snappedf(value.size.x, 0.0001),
		snappedf(value.size.y, 0.0001),
	]


func _relative_output(path: String) -> String:
	return path.replace("\\", "/").trim_prefix(_output_root.replace("\\", "/") + "/")


func _write_json(path: String, value: Variant) -> bool:
	var file := FileAccess.open(path, FileAccess.WRITE)
	if file == null:
		return _fail("Could not write %s" % path)
	file.store_string(JSON.stringify(value, "  ", false) + "\n")
	return true


func _fail(message: String) -> bool:
	_errors.append(message)
	push_error(message)
	return false


func _finish_failure() -> void:
	for error_message: String in _errors:
		printerr("semantic-left-leg: %s" % error_message)
	quit(2)
