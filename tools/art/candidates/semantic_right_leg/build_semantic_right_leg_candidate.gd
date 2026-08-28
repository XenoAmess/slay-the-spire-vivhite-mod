extends SceneTree

## Builds an isolated, non-publishable right-leg semantic-group contact sheet.
## It only SourceOver-composites the untouched EvoLink PNGs for diagnosis. It
## never crops, thresholds, masks, repairs, mirrors, or writes runtime art.

const COMMAND := "build-semantic-right-leg-candidate"
const OUTPUT_ROOT_REL := "Vivhite/tools/candidates/semantic_right_leg"

const THIGH_REL := "assets/vivhite-ironclad/generated/evolink-paid/2026-08-28/0083-split-leg-right-thigh-attachment-attempt-04/output.png"
const LOWER_REL := "assets/vivhite-ironclad/generated/evolink-paid/2026-08-28/0100-split-leg-right-lower-attachment-attempt-05/output.png"
const BODY_0018_REL := "assets/vivhite-ironclad/generated/evolink-paid/2026-08-28/0018-combat-body-master-attempt-01/output.png"
const BODY_0022_REL := "assets/vivhite-ironclad/generated/evolink-paid/2026-08-28/0022-combat-body-master-attempt-05/output.png"
const BODY_BUILDER_REL := "assets/vivhite-ironclad/custom/combat/sources/vivhite-combat-body-master-v1.png"
const SPLIT_JSON_REL := "assets/vivhite-ironclad/candidates/split_mesh/combat/vivhite_combat_split_mesh.spjson"
const SPLIT_BUILDER_REL := "tools/art/build_vivhite_combat_split_mesh_candidate.gd"
const COMBAT_SCENE_REL := "Vivhite/Vivhite/skins/ironclad/scenes/combat.tscn"
const REGISTRATION_REL := "Vivhite/VivhiteCode/Characters/IroncladReplacementAssets.cs"

const EXPECTED_SHA256 := {
	"0018": "86ffd64a637d170e213879e72d986b707ee181d4812c8e3fb1eda4abfab98bd1",
	"0022": "488e74758164dab0702ec6f943e02d23d9561caef29320275f698cb0000e232e",
	"0064": "6e106b1fe7718bab68af2967de5e0ae757d6f58caf0ff60d97959f80a3dd290d",
	"0065": "eeecd4df3054b6dc89db1b0f41b1e0596374b4c2b1f6e5fe64a2f0f4d496c94f",
	"0066": "a14d0caf909f362a852842ab8db3e26d10148b8885d14cd9b583b1aa6e509a9e",
	"0067": "6a4d84c61bb0bbf24486f2c4d1211caa3b89f0b9ce2f7bbf60de2254c28e5277",
	"0068": "2c9c346dad4331fe9a266d901ee2c568505284a80b4d5a8718f7329d9f4de32f",
	"0069": "e45ec010d7231b080b71f9c82053cf54b12af0d5fc7d1a21e419a7e0639f253b",
	"0070": "1605b0590d02b612453128afba2bbeed1b290d2d0e0742ba09e7cf363391cf57",
	"0071": "70ae428b8798704147062e03db5fa5284fddce04d925835f31a53d1889096f60",
	"0083": "f74ec591dbc2718426af1e3e04562cf6ddcae639367c14e5df23e3cbe78714f7",
	"0100": "9035dcf28f251935467db70edeebae481ac8c71fa7531f7fabedc337b6e8a5d2",
}

const BOOT_IDS := ["0064", "0065", "0066", "0067", "0068", "0069", "0070", "0071"]
const BOOT_DIRS := [
	"0064-split-leg-right-boot-attachment-attempt-01",
	"0065-split-leg-right-boot-attachment-attempt-02",
	"0066-split-leg-right-boot-attachment-attempt-03",
	"0067-split-leg-right-boot-attachment-attempt-04",
	"0068-split-leg-right-boot-attachment-attempt-05",
	"0069-split-leg-right-boot-attachment-attempt-06",
	"0070-split-leg-right-boot-attachment-attempt-07",
	"0071-split-leg-right-boot-attachment-attempt-08",
]

const PANEL_SIZE := Vector2i(800, 950)
const CONTACT_SIZE := Vector2i(PANEL_SIZE.x * 3, PANEL_SIZE.y * 2)
const BOOT_CELL_SIZE := Vector2i(420, 450)
const BOOT_SHEET_SIZE := Vector2i(BOOT_CELL_SIZE.x * 4, BOOT_CELL_SIZE.y * 2)
const AXIS_SHEET_SIZE := Vector2i(1120, 720)

const HIP := Vector2(400.0, 110.0)
const KNEE := Vector2(450.0, 320.0)
const ANKLE := Vector2(550.0, 690.0)
const TARGET_TOE := Vector2(740.0, 825.0)
const THIGH_PROXIMAL_FRACTION := 0.12
const THIGH_DISTAL_FRACTION := 0.86
const LOWER_PROXIMAL_FRACTION := 0.18
const LOWER_DISTAL_FRACTION := 0.82

const MAX_KNEE_ROTATION_DEG := 82.0
const MAX_ANKLE_ROTATION_DEG := -18.0
const BUILDER_LOWER_AXIS_DEG := 57.681201
const BODY_0018_VISIBLE_AXIS_DEG := 68.2
const BODY_0022_TARGET_AXIS_DEG := 74.2

# 0064 manual semantic landmarks are only used to demonstrate its already
# audited direction after the cuff has been aligned to the shin. They do not
# alter the source pixels.
const BOOT_0064_ANKLE_NORM := Vector2(0.517, 0.358)
const BOOT_0064_CUFF_NORM := Vector2(0.535, 0.202)
const BOOT_0064_TOE_NORM := Vector2(0.235, 0.735)
const BOOT_0064_HEEL_NORM := Vector2(0.735, 0.665)
const BOOT_TARGET_LENGTH := 180.0

const OUTPUT_FILES := [
	"right-leg-contact-black.png",
	"right-leg-contact-white.png",
	"right-leg-contact-game.png",
	"right-boot-0064-0071-contact-game.png",
	"right-leg-axis-conflict.png",
]

var _repo_root := ""
var _output_root := ""
var _errors: Array[String] = []
var _sources := {}
var _textures := {}
var _consumer_audit := {}
var _boot_direction := {}


func _initialize() -> void:
	call_deferred("_run")


func _run() -> void:
	var args := OS.get_cmdline_user_args()
	if args.is_empty():
		args = PackedStringArray([COMMAND])
	if args[0] in ["-h", "--help", "help"]:
		print("Usage: godot --headless --path tools/art --script res://candidates/semantic_right_leg/build_semantic_right_leg_candidate.gd -- %s [--output-root PATH]" % COMMAND)
		quit(0)
		return
	if args[0] != COMMAND:
		_fail("Unknown command: %s" % args[0])
		quit(2)
		return

	_repo_root = ProjectSettings.globalize_path("res://../..").simplify_path()
	_output_root = _repo_root.path_join(OUTPUT_ROOT_REL)
	var index := 1
	while index < args.size():
		if args[index] == "--output-root" and index + 1 < args.size():
			_output_root = _absolute_path(args[index + 1])
			index += 2
		else:
			_fail("Unknown or incomplete option: %s" % args[index])
			quit(2)
			return
	if _output_root.replace("\\", "/").contains("/Vivhite/Vivhite/skins/ironclad"):
		_fail("Diagnostic output may not target the runtime skin: %s" % _output_root)
		quit(2)
		return

	_load_sources()
	_audit_consumer()
	if not _errors.is_empty():
		_print_errors()
		quit(2)
		return

	DirAccess.make_dir_recursive_absolute(_output_root)
	await _render_pose_contact("right-leg-contact-black.png", Color(0.0, 0.0, 0.0, 1.0), true)
	await _render_pose_contact("right-leg-contact-white.png", Color(1.0, 1.0, 1.0, 1.0), false)
	await _render_pose_contact("right-leg-contact-game.png", Color("243743"), true)
	await _render_boot_contact()
	await _render_axis_conflict()
	_write_contract()
	if not _errors.is_empty():
		_print_errors()
		quit(2)
		return

	print("Built isolated semantic right-leg diagnostic candidate:")
	print("  output: %s" % _output_root)
	print("  selected: 0083 thigh + 0100 lower + 0064 direction-blocked boot")
	print("  stress: setup, knee %s deg, ankle %s deg" % [_signed_degrees(MAX_KNEE_ROTATION_DEG), _signed_degrees(MAX_ANKLE_ROTATION_DEG)])
	print("  recommendation: two attachments (thigh + newly generated lower-leg/boot union); ankle DOF locked")
	quit(0)


func _absolute_path(path: String) -> String:
	if path.is_absolute_path():
		return path.simplify_path()
	return _repo_root.path_join(path).simplify_path()


func _source_path(rel_path: String) -> String:
	return _repo_root.path_join(rel_path)


func _boot_rel(index: int) -> String:
	return "assets/vivhite-ironclad/generated/evolink-paid/2026-08-28/%s/output.png" % BOOT_DIRS[index]


func _load_sources() -> void:
	var contracts := [
		{"id": "0018", "path": BODY_0018_REL, "role": "builder_actual_full_body_reference"},
		{"id": "0022", "path": BODY_0022_REL, "role": "new_rig_visual_direction_target"},
		{"id": "0083", "path": THIGH_REL, "role": "selected_static_right_thigh"},
		{"id": "0100", "path": LOWER_REL, "role": "selected_static_right_lower_leg"},
	]
	for boot_index in range(BOOT_IDS.size()):
		contracts.append({
			"id": BOOT_IDS[boot_index],
			"path": _boot_rel(boot_index),
			"role": "direction_audit_right_boot" if boot_index > 0 else "selected_style_only_direction_blocked_boot",
		})
	for contract: Dictionary in contracts:
		var id := str(contract["id"])
		var abs_path := _source_path(str(contract["path"]))
		if not FileAccess.file_exists(abs_path):
			_fail("Missing source %s: %s" % [id, abs_path])
			continue
		var actual_hash := FileAccess.get_sha256(abs_path).to_lower()
		if actual_hash != str(EXPECTED_SHA256[id]):
			_fail("Source %s SHA-256 changed: %s" % [id, actual_hash])
			continue
		var image := Image.load_from_file(abs_path)
		if image == null or image.is_empty():
			_fail("Could not decode source %s" % id)
			continue
		if image.get_format() != Image.FORMAT_RGBA8:
			_fail("Source %s must decode natively as RGBA8, got %s" % [id, image.get_format()])
			continue
		var stats := _analyze_alpha(image)
		if not bool(stats["corners_zero"]):
			_fail("Source %s does not have four transparent corners" % id)
			continue
		_sources[id] = {
			"id": id,
			"path": str(contract["path"]),
			"role": str(contract["role"]),
			"sha256": actual_hash,
			"image": image,
			"stats": stats,
		}
		_textures[id] = ImageTexture.create_from_image(image)

	if not _sources.has("0083") or not _sources.has("0100") or not _sources.has("0064"):
		return
	var lower_angle := float(_sources["0100"]["stats"]["pca_axis_degrees"])
	if absf(lower_angle - 61.48) > 2.0:
		_fail("0100 PCA axis drifted outside the audited 61.48 +/- 2 deg gate: %.3f" % lower_angle)
	var custom_path := _source_path(BODY_BUILDER_REL)
	if not FileAccess.file_exists(custom_path):
		_fail("Builder body source is missing: %s" % custom_path)
	elif FileAccess.get_sha256(custom_path).to_lower() != str(EXPECTED_SHA256["0018"]):
		_fail("Builder body source is no longer byte-identical to 0018")


func _analyze_alpha(image: Image) -> Dictionary:
	var thresholds := [1, 16, 64, 128]
	var boxes := {}
	var counts := {}
	for threshold in thresholds:
		boxes[str(threshold)] = Rect2i()
		counts[str(threshold)] = 0
	var mins := {}
	var maxs := {}
	for threshold in thresholds:
		mins[str(threshold)] = Vector2i(image.get_width(), image.get_height())
		maxs[str(threshold)] = Vector2i(-1, -1)

	var core_points := PackedVector2Array()
	var sum_position := Vector2.ZERO
	var edge_nonzero := 0
	var width := image.get_width()
	var height := image.get_height()
	var rgba := image.get_data()
	for y in range(image.get_height()):
		for x in range(image.get_width()):
			var alpha_byte := int(rgba[(y * width + x) * 4 + 3])
			if alpha_byte > 0 and (x == 0 or y == 0 or x == width - 1 or y == height - 1):
				edge_nonzero += 1
			for threshold in thresholds:
				if alpha_byte >= threshold:
					var key := str(threshold)
					counts[key] = int(counts[key]) + 1
					mins[key] = Vector2i(mini(mins[key].x, x), mini(mins[key].y, y))
					maxs[key] = Vector2i(maxi(maxs[key].x, x), maxi(maxs[key].y, y))
			if alpha_byte >= 128:
				var point := Vector2(x, y)
				core_points.append(point)
				sum_position += point
	for threshold in thresholds:
		var key := str(threshold)
		if int(counts[key]) > 0:
			boxes[key] = Rect2i(mins[key], maxs[key] - mins[key] + Vector2i.ONE)
	if core_points.is_empty():
		return {
			"canvas": [image.get_width(), image.get_height()],
			"corners_zero": false,
			"edge_nonzero_pixels": edge_nonzero,
			"counts": counts,
			"bboxes": _boxes_to_arrays(boxes),
			"pca_axis_degrees": 0.0,
		}
	var centroid := sum_position / core_points.size()
	var cov_xx := 0.0
	var cov_xy := 0.0
	var cov_yy := 0.0
	for point in core_points:
		var delta := point - centroid
		cov_xx += delta.x * delta.x
		cov_xy += delta.x * delta.y
		cov_yy += delta.y * delta.y
	var axis_angle := 0.5 * atan2(2.0 * cov_xy, cov_xx - cov_yy)
	var axis := Vector2(cos(axis_angle), sin(axis_angle)).normalized()
	if axis.y < 0.0:
		axis = -axis
	var projection_min := INF
	var projection_max := -INF
	for point in core_points:
		var projection := point.dot(axis)
		projection_min = minf(projection_min, projection)
		projection_max = maxf(projection_max, projection)
	var degrees := rad_to_deg(atan2(axis.y, axis.x))
	return {
		"canvas": [image.get_width(), image.get_height()],
		"corners_zero": (
			rgba[3] == 0
			and rgba[(width - 1) * 4 + 3] == 0
			and rgba[((height - 1) * width) * 4 + 3] == 0
			and rgba[(height * width - 1) * 4 + 3] == 0
		),
		"edge_nonzero_pixels": edge_nonzero,
		"counts": counts,
		"bboxes": _boxes_to_arrays(boxes),
		"pca_axis_degrees": degrees,
		"pca_axis": [axis.x, axis.y],
		"pca_centroid": [centroid.x, centroid.y],
		"pca_projection": [projection_min, projection_max],
	}


func _boxes_to_arrays(boxes: Dictionary) -> Dictionary:
	var result := {}
	for key: String in boxes:
		var rect: Rect2i = boxes[key]
		result[key] = [rect.position.x, rect.position.y, rect.size.x, rect.size.y]
	return result


func _audit_consumer() -> void:
	var split_path := _source_path(SPLIT_JSON_REL)
	var split_text := FileAccess.get_file_as_string(split_path)
	var skeleton: Variant = JSON.parse_string(split_text)
	if not skeleton is Dictionary:
		_fail("Could not parse split candidate Spine JSON")
		return
	var slot_indices := {}
	var slots: Array = skeleton.get("slots", [])
	for slot_index in range(slots.size()):
		slot_indices[str(slots[slot_index].get("name", ""))] = slot_index
	var expected_slots := {
		"part_leg_right_thigh": 7,
		"part_leg_right_lower": 9,
		"part_leg_right_foot": 11,
	}
	for slot_name: String in expected_slots:
		if int(slot_indices.get(slot_name, -1)) != int(expected_slots[slot_name]):
			_fail("Split slot order changed for %s: expected %s, got %s" % [slot_name, expected_slots[slot_name], slot_indices.get(slot_name, -1)])
	var draw_order_animations: Array[String] = []
	for animation_name: String in skeleton.get("animations", {}):
		var animation: Dictionary = skeleton["animations"][animation_name]
		if animation.has("drawOrder") or animation.has("draworder"):
			draw_order_animations.append(animation_name)
	if not draw_order_animations.is_empty():
		_fail("Right-leg layer audit requires no drawOrder animation, found: %s" % draw_order_animations)

	var builder_text := FileAccess.get_file_as_string(_source_path(SPLIT_BUILDER_REL))
	var scene_text := FileAccess.get_file_as_string(_source_path(COMBAT_SCENE_REL))
	var registration_text := FileAccess.get_file_as_string(_source_path(REGISTRATION_REL))
	if not builder_text.contains('"vivhite_knee_right": _source_point_world(Vector2(880, 1580))'):
		_fail("Split builder right-knee setup point changed")
	if not builder_text.contains('"vivhite_ankle_right": _source_point_world(Vector2(1190, 2070))'):
		_fail("Split builder right-ankle setup point changed")
	if not scene_text.contains("scale = Vector2(0.28, 0.28)"):
		_fail("Combat scene no longer preserves the 0.28 consumer scale")
	if not registration_text.contains("CombatSkeletonDataPath: CombatSkeletonDataPath"):
		_fail("Ironclad replacement registration no longer consumes the private combat skeleton")

	_consumer_audit = {
		"registration": REGISTRATION_REL,
		"scene": COMBAT_SCENE_REL,
		"scene_scale": 0.28,
		"split_builder": SPLIT_BUILDER_REL,
		"split_spine_json": SPLIT_JSON_REL,
		"normal_slot_indices": expected_slots,
		"normal_draw_order": ["right_thigh", "right_lower", "right_foot"],
		"draw_order_animation_count": draw_order_animations.size(),
		"builder_setup_points_px": {
			"right_knee": [880, 1580],
			"right_ankle": [1190, 2070],
		},
		"builder_lower_axis_degrees": BUILDER_LOWER_AXIS_DEG,
		"candidate_die_rotation_extrema_degrees": {
			"right_knee_max": MAX_KNEE_ROTATION_DEG,
			"right_ankle_min": MAX_ANKLE_ROTATION_DEG,
		},
	}


func _pca_pivot(id: String, fraction: float) -> Vector2:
	var stats: Dictionary = _sources[id]["stats"]
	var center_values: Array = stats["pca_centroid"]
	var axis_values: Array = stats["pca_axis"]
	var projection_values: Array = stats["pca_projection"]
	var center := Vector2(float(center_values[0]), float(center_values[1]))
	var axis := Vector2(float(axis_values[0]), float(axis_values[1]))
	var target_projection := lerpf(float(projection_values[0]), float(projection_values[1]), fraction)
	return center + axis * (target_projection - center.dot(axis))


func _source_axis(id: String) -> Vector2:
	var values: Array = _sources[id]["stats"]["pca_axis"]
	return Vector2(float(values[0]), float(values[1]))


func _angle(vector: Vector2) -> float:
	return atan2(vector.y, vector.x)


func _signed_degrees(value: float) -> String:
	return ("+" if value >= 0.0 else "") + str(int(round(value)))


func _rotated(vector: Vector2, angle: float) -> Vector2:
	return vector.rotated(angle)


func _attachment_transform(id: String, source_proximal: Vector2, source_distal: Vector2, target_proximal: Vector2, target_distal: Vector2) -> Dictionary:
	var source_vector := source_distal - source_proximal
	var target_vector := target_distal - target_proximal
	return {
		"pivot": source_proximal,
		"position": target_proximal,
		"rotation": _angle(target_vector) - _angle(source_vector),
		"scale": target_vector.length() / source_vector.length(),
	}


func _boot_landmarks() -> Dictionary:
	var image: Image = _sources["0064"]["image"]
	var canvas := Vector2(image.get_width(), image.get_height())
	return {
		"ankle": BOOT_0064_ANKLE_NORM * canvas,
		"cuff": BOOT_0064_CUFF_NORM * canvas,
		"toe": BOOT_0064_TOE_NORM * canvas,
		"heel": BOOT_0064_HEEL_NORM * canvas,
	}


func _pose_geometry(knee_degrees: float, ankle_degrees: float, ankle_locked: bool) -> Dictionary:
	var knee_rotation := deg_to_rad(knee_degrees)
	var current_ankle := KNEE + _rotated(ANKLE - KNEE, knee_rotation)
	var thigh_proximal := _pca_pivot("0083", THIGH_PROXIMAL_FRACTION)
	var thigh_distal := _pca_pivot("0083", THIGH_DISTAL_FRACTION)
	var lower_proximal := _pca_pivot("0100", LOWER_PROXIMAL_FRACTION)
	var lower_distal := _pca_pivot("0100", LOWER_DISTAL_FRACTION)
	var thigh_transform := _attachment_transform("0083", thigh_proximal, thigh_distal, HIP, KNEE)
	var lower_transform := _attachment_transform("0100", lower_proximal, lower_distal, KNEE, ANKLE)
	lower_transform["rotation"] = float(lower_transform["rotation"]) + knee_rotation
	lower_transform["position"] = KNEE

	var boot: Dictionary = _boot_landmarks()
	var boot_ankle: Vector2 = boot["ankle"]
	var boot_cuff: Vector2 = boot["cuff"]
	var boot_toe: Vector2 = boot["toe"]
	var boot_heel: Vector2 = boot["heel"]
	var setup_boot_rotation := _angle(KNEE - ANKLE) - _angle(boot_cuff - boot_ankle)
	var boot_scale: float = BOOT_TARGET_LENGTH / (boot_toe - boot_ankle).length()
	var applied_ankle_degrees := 0.0 if ankle_locked else ankle_degrees
	var boot_rotation := setup_boot_rotation + knee_rotation + deg_to_rad(applied_ankle_degrees)
	var toe := current_ankle + _rotated((boot_toe - boot_ankle) * boot_scale, boot_rotation)
	var heel := current_ankle + _rotated((boot_heel - boot_ankle) * boot_scale, boot_rotation)
	_boot_direction = {
		"toe": [toe.x, toe.y],
		"heel": [heel.x, heel.y],
		"toe_is_screen_left_of_heel": toe.x < heel.x,
		"target_requires_toe_screen_right_of_heel": true,
	}
	return {
		"hip": HIP,
		"knee": KNEE,
		"ankle": current_ankle,
		"toe": toe,
		"heel": heel,
		"target_toe": TARGET_TOE,
		"thigh": thigh_transform,
		"lower": lower_transform,
		"boot": {
			"pivot": boot_ankle,
			"position": current_ankle,
			"rotation": boot_rotation,
			"scale": boot_scale,
		},
		"knee_degrees": knee_degrees,
		"requested_ankle_degrees": ankle_degrees,
		"applied_ankle_degrees": applied_ankle_degrees,
		"ankle_locked": ankle_locked,
	}


func _new_viewport(size: Vector2i, background: Color) -> Dictionary:
	var viewport := SubViewport.new()
	viewport.size = size
	viewport.transparent_bg = false
	viewport.disable_3d = true
	viewport.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	get_root().add_child(viewport)
	var canvas := Node2D.new()
	viewport.add_child(canvas)
	var bg := ColorRect.new()
	bg.color = background
	bg.size = Vector2(size)
	bg.mouse_filter = Control.MOUSE_FILTER_IGNORE
	bg.z_index = -100
	canvas.add_child(bg)
	return {"viewport": viewport, "canvas": canvas}


func _add_label(parent: Node, text_value: String, position: Vector2, color: Color, font_size := 22) -> void:
	var label := Label.new()
	label.text = text_value
	label.position = position
	label.add_theme_color_override("font_color", color)
	label.add_theme_color_override("font_shadow_color", Color(0, 0, 0, 0.65))
	label.add_theme_constant_override("shadow_offset_x", 1)
	label.add_theme_constant_override("shadow_offset_y", 1)
	label.add_theme_font_size_override("font_size", font_size)
	label.z_index = 100
	parent.add_child(label)


func _add_line(parent: Node, points: PackedVector2Array, color: Color, width := 3.0, z := 50) -> void:
	var line := Line2D.new()
	line.points = points
	line.default_color = color
	line.width = width
	line.antialiased = true
	line.z_index = z
	parent.add_child(line)


func _add_joint(parent: Node, point: Vector2, color: Color, radius := 7.0) -> void:
	var polygon := Polygon2D.new()
	var points := PackedVector2Array()
	for index in range(20):
		var angle := TAU * index / 20.0
		points.append(point + Vector2(cos(angle), sin(angle)) * radius)
	polygon.polygon = points
	polygon.color = color
	polygon.z_index = 70
	parent.add_child(polygon)


func _add_attachment(parent: Node, id: String, transform: Dictionary, z_index: int) -> void:
	var sprite := Sprite2D.new()
	sprite.texture = _textures[id]
	sprite.centered = false
	sprite.offset = -Vector2(transform["pivot"])
	sprite.position = Vector2(transform["position"])
	sprite.rotation = float(transform["rotation"])
	var scale_value := float(transform["scale"])
	sprite.scale = Vector2(scale_value, scale_value)
	sprite.z_index = z_index
	parent.add_child(sprite)


func _add_panel(canvas: Node2D, origin: Vector2, title: String, knee_degrees: float, ankle_degrees: float, ankle_locked: bool, dark_text: bool) -> void:
	var panel := Node2D.new()
	panel.position = origin
	canvas.add_child(panel)
	var text_color := Color("e9f4ff") if dark_text else Color("17232d")
	var border_color := Color(0.31, 0.65, 0.82, 0.8) if dark_text else Color(0.08, 0.33, 0.48, 0.8)
	_add_line(panel, PackedVector2Array([Vector2(1, 1), Vector2(PANEL_SIZE.x - 2, 1), Vector2(PANEL_SIZE.x - 2, PANEL_SIZE.y - 2), Vector2(1, PANEL_SIZE.y - 2), Vector2(1, 1)]), border_color, 2.0, 90)
	_add_label(panel, title, Vector2(14, 10), text_color, 24)
	var geometry := _pose_geometry(knee_degrees, ankle_degrees, ankle_locked)
	_add_attachment(panel, "0083", geometry["thigh"], 7)
	_add_attachment(panel, "0100", geometry["lower"], 9)
	_add_attachment(panel, "0064", geometry["boot"], 11)
	_add_line(panel, PackedVector2Array([geometry["hip"], geometry["knee"], geometry["ankle"]]), Color("37d7ff"), 3.0, 60)
	_add_line(panel, PackedVector2Array([geometry["ankle"], geometry["target_toe"]]), Color("52e095"), 3.0, 61)
	_add_line(panel, PackedVector2Array([geometry["toe"], geometry["heel"]]), Color("ff5d78"), 3.0, 62)
	_add_joint(panel, geometry["hip"], Color("37d7ff"))
	_add_joint(panel, geometry["knee"], Color("ffcf4a"))
	_add_joint(panel, geometry["ankle"], Color("ff8a52"))
	_add_joint(panel, geometry["toe"], Color("ff5d78"), 5.0)
	_add_joint(panel, geometry["heel"], Color("b68cff"), 5.0)
	var route := "2-piece: thigh + lower/boot locked" if ankle_locked else "3-piece: thigh + lower + boot"
	_add_label(panel, route, Vector2(14, 45), text_color, 19)
	_add_label(panel, "slots 7 -> 9 -> 11 (front)", Vector2(14, 70), text_color, 17)
	if ankle_locked:
		_add_label(panel, "ankle request %s deg; applied 0 deg" % _signed_degrees(ankle_degrees), Vector2(14, 95), Color("52e095"), 18)
	else:
		_add_label(panel, "knee %s deg / ankle %s deg" % [_signed_degrees(knee_degrees), _signed_degrees(ankle_degrees)], Vector2(14, 95), text_color, 18)
	_add_label(panel, "RED toe--heel: 0064 points wrong way", Vector2(14, PANEL_SIZE.y - 66), Color("ff5d78"), 18)
	_add_label(panel, "GREEN: required screen-right toe", Vector2(14, PANEL_SIZE.y - 39), Color("52e095"), 18)


func _render_pose_contact(file_name: String, background: Color, dark_text: bool) -> void:
	var scene := _new_viewport(CONTACT_SIZE, background)
	var viewport: SubViewport = scene["viewport"]
	var canvas: Node2D = scene["canvas"]
	var panels := [
		["3-piece / setup", 0.0, 0.0, false],
		["3-piece / max knee", MAX_KNEE_ROTATION_DEG, 0.0, false],
		["3-piece / max ankle", 0.0, MAX_ANKLE_ROTATION_DEG, false],
		["2-piece / setup", 0.0, 0.0, true],
		["2-piece / max knee", MAX_KNEE_ROTATION_DEG, 0.0, true],
		["2-piece / ankle stress", 0.0, MAX_ANKLE_ROTATION_DEG, true],
	]
	for panel_index in range(panels.size()):
		var column := panel_index % 3
		var row := panel_index / 3
		var panel: Array = panels[panel_index]
		_add_panel(canvas, Vector2(column * PANEL_SIZE.x, row * PANEL_SIZE.y), str(panel[0]), float(panel[1]), float(panel[2]), bool(panel[3]), dark_text)
	await process_frame
	await RenderingServer.frame_post_draw
	var image := viewport.get_texture().get_image()
	if image == null or image.is_empty():
		_fail("Could not capture %s" % file_name)
	else:
		var error := image.save_png(_output_root.path_join(file_name))
		if error != OK:
			_fail("Could not write %s: %s" % [file_name, error])
	viewport.queue_free()
	await process_frame


func _render_boot_contact() -> void:
	var scene := _new_viewport(BOOT_SHEET_SIZE, Color("243743"))
	var viewport: SubViewport = scene["viewport"]
	var canvas: Node2D = scene["canvas"]
	for boot_index in range(BOOT_IDS.size()):
		var id := str(BOOT_IDS[boot_index])
		var column := boot_index % 4
		var row := boot_index / 4
		var origin := Vector2(column * BOOT_CELL_SIZE.x, row * BOOT_CELL_SIZE.y)
		_add_line(canvas, PackedVector2Array([origin + Vector2(1, 1), origin + Vector2(BOOT_CELL_SIZE.x - 2, 1), origin + Vector2(BOOT_CELL_SIZE.x - 2, BOOT_CELL_SIZE.y - 2), origin + Vector2(1, BOOT_CELL_SIZE.y - 2), origin + Vector2(1, 1)]), Color(0.31, 0.65, 0.82, 0.75), 2.0, 90)
		_add_label(canvas, "%s: toe screen-left / heel screen-right" % id, origin + Vector2(12, 10), Color("eef7ff"), 17)
		var bbox_values: Array = _sources[id]["stats"]["bboxes"]["128"]
		var bbox := Rect2(float(bbox_values[0]), float(bbox_values[1]), float(bbox_values[2]), float(bbox_values[3]))
		var scale_value := minf(360.0 / bbox.size.x, 350.0 / bbox.size.y)
		var target_center := origin + Vector2(BOOT_CELL_SIZE.x * 0.5, BOOT_CELL_SIZE.y * 0.57)
		var sprite := Sprite2D.new()
		sprite.texture = _textures[id]
		sprite.centered = false
		sprite.position = target_center - bbox.get_center() * scale_value
		sprite.scale = Vector2(scale_value, scale_value)
		sprite.z_index = 10
		canvas.add_child(sprite)
		_add_label(canvas, "new target: toe must be screen-right", origin + Vector2(12, BOOT_CELL_SIZE.y - 34), Color("ff7187"), 16)
	await process_frame
	await RenderingServer.frame_post_draw
	var image := viewport.get_texture().get_image()
	if image == null or image.is_empty():
		_fail("Could not capture right-boot contact sheet")
	elif image.save_png(_output_root.path_join("right-boot-0064-0071-contact-game.png")) != OK:
		_fail("Could not write right-boot contact sheet")
	viewport.queue_free()
	await process_frame


func _render_axis_conflict() -> void:
	var scene := _new_viewport(AXIS_SHEET_SIZE, Color("172731"))
	var viewport: SubViewport = scene["viewport"]
	var canvas: Node2D = scene["canvas"]
	_add_label(canvas, "Right lower-leg axis audit (screen-space degrees from +X)", Vector2(34, 25), Color("eef7ff"), 28)
	_add_label(canvas, "0018 is the builder's byte-exact body source; 0022 is the selected new-rig direction target.", Vector2(34, 65), Color("bed2df"), 18)
	var origin := Vector2(220, 610)
	var length := 450.0
	var axes := [
		["builder hard-coded 57.68 deg", BUILDER_LOWER_AXIS_DEG, Color("ff6f7d")],
		["0100 art PCA %.2f deg" % float(_sources["0100"]["stats"]["pca_axis_degrees"]), float(_sources["0100"]["stats"]["pca_axis_degrees"]), Color("ffbf54")],
		["0018 visible estimate 68.2 deg", BODY_0018_VISIBLE_AXIS_DEG, Color("75c5ff")],
		["0022 / new target 74.2 deg", BODY_0022_TARGET_AXIS_DEG, Color("5be49a")],
	]
	for axis_index in range(axes.size()):
		var item: Array = axes[axis_index]
		var degrees := float(item[1])
		var end := origin + Vector2(cos(deg_to_rad(degrees)), -sin(deg_to_rad(degrees))) * length
		_add_line(canvas, PackedVector2Array([origin, end]), item[2], 5.0, 20 + axis_index)
		_add_joint(canvas, end, item[2], 6.0)
		_add_label(canvas, str(item[0]), Vector2(650, 150 + axis_index * 70), item[2], 21)
	_add_joint(canvas, origin, Color("ffffff"), 8.0)
	_add_label(canvas, "The old foot bone is only ankle->foot origin; it has no toe child, so it cannot resolve toe semantics.", Vector2(34, 665), Color("ff9faf"), 18)
	await process_frame
	await RenderingServer.frame_post_draw
	var image := viewport.get_texture().get_image()
	if image == null or image.is_empty():
		_fail("Could not capture axis conflict sheet")
	elif image.save_png(_output_root.path_join("right-leg-axis-conflict.png")) != OK:
		_fail("Could not write axis conflict sheet")
	viewport.queue_free()
	await process_frame


func _source_report(id: String) -> Dictionary:
	var item: Dictionary = _sources[id]
	return {
		"id": id,
		"path": item["path"],
		"role": item["role"],
		"sha256": item["sha256"],
		"alpha": item["stats"],
	}


func _write_contract() -> void:
	if not bool(_boot_direction.get("toe_is_screen_left_of_heel", false)):
		_fail("0064 direction diagnostic no longer proves toe-left / heel-right after cuff alignment")
		return
	var source_reports := []
	for id in ["0018", "0022", "0083", "0100"] + BOOT_IDS:
		source_reports.append(_source_report(str(id)))
	var outputs := []
	for file_name in OUTPUT_FILES:
		var output_path := _output_root.path_join(file_name)
		if not FileAccess.file_exists(output_path):
			_fail("Required preview output is missing: %s" % file_name)
			continue
		outputs.append({"path": file_name, "sha256": FileAccess.get_sha256(output_path).to_lower()})
	var contract := {
		"schema": 1,
		"name": "semantic_right_leg",
		"classification": "offline diagnostic contact sheets; not a runtime sprite, spritesheet, or atlas page",
		"status": "research_only_not_publishable",
		"output_root": OUTPUT_ROOT_REL,
		"sources": source_reports,
		"consumer_audit": _consumer_audit,
		"axis_conflict": {
			"builder_hard_coded_degrees": BUILDER_LOWER_AXIS_DEG,
			"builder_actual_source_0018_visible_degrees": BODY_0018_VISIBLE_AXIS_DEG,
			"selected_new_rig_target_0022_degrees": BODY_0022_TARGET_AXIS_DEG,
			"selected_lower_0100_pca_degrees": _sources["0100"]["stats"]["pca_axis_degrees"],
			"resolution": "0022/new-rig direction is the target; old builder coordinates are diagnostic history, not production truth",
		},
		"stress_poses": [
			{"id": "setup", "right_knee_degrees": 0.0, "right_ankle_degrees": 0.0},
			{"id": "max_knee", "right_knee_degrees": MAX_KNEE_ROTATION_DEG, "right_ankle_degrees": 0.0},
			{"id": "max_ankle", "right_knee_degrees": 0.0, "right_ankle_degrees": MAX_ANKLE_ROTATION_DEG},
		],
		"three_piece_route": {
			"attachments": ["0083_right_thigh", "0100_right_lower", "0064_style_only_boot"],
			"fixed_draw_order": [7, 9, 11],
			"result": "blocked",
			"blocking_reasons": [
				"All 0064-0071 boots have toe screen-left and heel screen-right, opposite the selected 0022/new-rig target.",
				"0100 draws over 0083 under the fixed slot order; its closed upper outline becomes a visible knee cross-seam at setup and grows under +82 degree flexion.",
				"A separate boot adds an avoidable ankle seam and requires hidden pixels during the -18 degree ankle extreme.",
			],
			"boot_direction_measurement_0064": _boot_direction,
		},
		"two_piece_route": {
			"attachments": ["right_thigh", "right_lower_leg_and_boot_union"],
			"joint_dofs": ["hip", "knee"],
			"ankle_dof": "locked_in_art_attachment",
			"result": "recommended_topology_only",
			"reason": "Preserves the necessary knee articulation while removing the direction-blocked boot asset, ankle hidden-pixel seam, and foot-over-lower draw-order dependency.",
			"production_art_required": "Generate one native-transparent continuous lower-leg+boot attachment from the clean references after this topology is accepted; do not merge 0100 and 0064 into runtime art.",
		},
		"static_gates": {
			"selected_sources_rgba8": true,
			"selected_sources_four_corners_alpha_zero": true,
			"source_pixels_or_alpha_modified": false,
			"sourceover_backgrounds": ["black", "white", "game_blue_gray"],
			"fixed_draw_order_verified_from_spine_json": true,
			"draw_order_animation_count": 0,
			"setup_and_extreme_rotation_contact_sheets_present": true,
			"runtime_skin_modified": false,
			"paid_generation_calls": 0,
		},
		"outputs": outputs,
		"next_gate": "If the two-piece topology is retained, generate a new screen-right-toe lower-leg+boot union, then repeat setup/+82 knee SourceOver and Vulkan tests. Existing 0064-0071 may only remain style/audit evidence.",
	}
	var file := FileAccess.open(_output_root.path_join("candidate.json"), FileAccess.WRITE)
	if file == null:
		_fail("Could not open candidate.json for writing")
		return
	file.store_string(JSON.stringify(contract, "  ", false) + "\n")
	file.close()


func _fail(message: String) -> void:
	_errors.append(message)


func _print_errors() -> void:
	for message in _errors:
		push_error("[semantic-right-leg] %s" % message)
	print("semantic right-leg candidate failed with %d error(s)" % _errors.size())
