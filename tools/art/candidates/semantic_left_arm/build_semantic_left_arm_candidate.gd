extends SceneTree

## Builds a diagnostic-only consumer for the arm that appears on screen-left in
## Vivhite's screen-right-facing combat stance.  Historical `*_left` names in
## split_mesh are screen-space aliases; this is the character's anatomical
## right arm and it is the far arm, drawn behind the torso.
##
## The generated pixels are deliberately simple opaque greybox geometry.  They
## are not character art, do not derive Alpha from any production image, and
## must never be copied into the runtime skin.

const COMMAND := "build-semantic-left-arm-candidate"
const DEFAULT_OUTPUT_ROOT := "Vivhite/tools/candidates/semantic_left_arm"
const OUTPUT_JSON := "semantic_left_arm.spjson"
const OUTPUT_ATLAS := "semantic_left_arm.spatlas"
const OUTPUT_PAGE := "semantic_left_arm_graybox.png"
const OUTPUT_DATA := "semantic_left_arm_skeleton_data.tres"
const OUTPUT_CONTRACT := "contract.json"
const OUTPUT_README := "README.md"
const MOUNT_ROOT := "res://tools/candidates/semantic_left_arm"
const SPINE_VERSION := "4.2.43"
const SCENE_SCALE := 0.28

const SOURCE_SIZE := Vector2(1680.0, 2512.0)
const WORLD_RECT := Rect2(-434.0, -61.0, 868.0, 1302.0)

const SOURCE_TORSO := Vector2(700.0, 590.0)
const SOURCE_CLAVICLE := Vector2(550.0, 565.0)
const SOURCE_SHOULDER := Vector2(585.0, 585.0)
const SOURCE_ELBOW := Vector2(465.0, 820.0)
const SOURCE_WRIST := Vector2(275.0, 1010.0)

const BONE_TORSO := "semantic_far_torso_upper"
const BONE_CLAVICLE := "semantic_far_shoulder_cover"
const BONE_UPPER := "semantic_far_upper_arm"
const BONE_FOREARM_HAND := "semantic_far_forearm_hand"
const BONE_WRIST := "semantic_far_wrist_anchor"

const REGION_UPPER := "gray_far_upper_arm"
const REGION_FOREARM_HAND := "gray_far_forearm_hand"
const REGION_TORSO := "gray_torso_shoulder_cover"
const REGION_MARKER_SHOULDER := "gray_marker_shoulder"
const REGION_MARKER_ELBOW := "gray_marker_elbow"
const REGION_MARKER_WRIST := "gray_marker_wrist"

const PAGE_SIZE := Vector2i(1024, 512)
const UPPER_POS := Vector2i(16, 16)
const UPPER_SIZE := Vector2i(320, 96)
const FOREARM_POS := Vector2i(352, 16)
const FOREARM_SIZE := Vector2i(384, 160)
const TORSO_POS := Vector2i(752, 16)
const TORSO_SIZE := Vector2i(256, 288)
const MARKER_SHOULDER_POS := Vector2i(16, 352)
const MARKER_ELBOW_POS := Vector2i(64, 352)
const MARKER_WRIST_POS := Vector2i(112, 352)
const MARKER_SIZE := Vector2i(32, 32)

# Diagnostic attachment dimensions in authored Spine world units.  Each piece
# owns a solid joint disk around the shared elbow pivot; the foreground
# forearm/hand therefore continues to cover the upper-arm end through the full
# audited relative rotation range.
const UPPER_WORLD_SIZE := Vector2(205.0, 58.0)
const FOREARM_WORLD_SIZE := Vector2(250.0, 104.0)
const TORSO_WORLD_SIZE := Vector2(251.0, 254.0)
const UPPER_PIVOT_PX := Vector2(62.0, 48.0)
const FOREARM_PIVOT_PX := Vector2(64.0, 80.0)
const SHOULDER_OVERLAP_WORLD := 39.71875
const UPPER_ELBOW_OVERHANG_WORLD := 28.325
const FOREARM_ELBOW_OVERHANG_WORLD := 41.6666667
const ELBOW_SOLID_RADIUS_WORLD := 27.0

const ANIMATION_DURATIONS := {
	"attack": 1.1666667,
	"attack_heavy": 1.5333334,
	"cast": 1.5666667,
	"die": 2.3333335,
	"hurt": 1.0,
	"idle_loop": 2.0,
	"low_health_loop": 1.4666667,
	"relaxed_loop": 12.000001,
}

var _last_error := ""


func _initialize() -> void:
	var args := OS.get_cmdline_user_args()
	if args.is_empty():
		args = PackedStringArray([COMMAND])
	if args[0] in ["-h", "--help", "help"]:
		print("Usage: godot --headless --path tools/art --script res://candidates/semantic_left_arm/build_semantic_left_arm_candidate.gd -- build-semantic-left-arm-candidate [--output-root PATH]")
		quit(0)
		return
	if args[0] != COMMAND:
		quit(_fail("Unknown command: %s" % args[0]))
		return
	var output_root := DEFAULT_OUTPUT_ROOT
	var index := 1
	while index < args.size():
		if str(args[index]) != "--output-root" or index + 1 >= args.size():
			quit(_fail("Expected --output-root PATH, got: %s" % str(args[index])))
			return
		output_root = str(args[index + 1])
		index += 2
	var absolute_output := _absolute_repo_path(output_root)
	if absolute_output.replace("\\", "/").contains("/Vivhite/Vivhite/skins/ironclad"):
		quit(_fail("Diagnostic candidate must never target the runtime skin: %s" % absolute_output))
		return
	if not _build(absolute_output):
		quit(_fail(_last_error))
		return
	quit(0)


func _build(output_root: String) -> bool:
	_last_error = ""
	if DirAccess.make_dir_recursive_absolute(output_root) != OK:
		return _set_error("Could not create output directory: %s" % output_root)
	var page := _build_graybox_page()
	if page.is_empty():
		return _set_error("Could not build graybox atlas page")
	var page_path := output_root.path_join(OUTPUT_PAGE)
	if page.save_png(page_path) != OK:
		return _set_error("Could not save graybox atlas page: %s" % page_path)

	var skeleton := _build_skeleton()
	var atlas_text := _build_atlas_text()
	var wrapper := {
		"atlas_data": atlas_text,
		"normal_texture_prefix": "n",
		"source_path": "%s/semantic_left_arm.atlas" % MOUNT_ROOT,
		"specular_texture_prefix": "s",
	}
	if not _write_text(output_root.path_join(OUTPUT_JSON), JSON.stringify(skeleton, "  ", false) + "\n"):
		return false
	if not _write_text(output_root.path_join(OUTPUT_ATLAS), JSON.stringify(wrapper, "", false) + "\n"):
		return false
	if not _write_text(output_root.path_join(OUTPUT_DATA), _build_tres()):
		return false
	if not _write_text(output_root.path_join(OUTPUT_CONTRACT), JSON.stringify(_build_contract(), "  ", false) + "\n"):
		return false
	if not _write_text(output_root.path_join(OUTPUT_README), _build_readme()):
		return false
	print("[semantic-left-arm] Built diagnostic candidate at %s" % output_root)
	print("[semantic-left-arm] Side: screen-left / far / anatomical-right")
	print("[semantic-left-arm] Pieces: upper-arm + combined forearm/empty-hand; torso owns shoulder cover")
	print("[semantic-left-arm] Paid generation calls: 0")
	return true


func _build_skeleton() -> Dictionary:
	var torso := _source_to_world(SOURCE_TORSO)
	var clavicle := _source_to_world(SOURCE_CLAVICLE)
	var shoulder := _source_to_world(SOURCE_SHOULDER)
	var elbow := _source_to_world(SOURCE_ELBOW)
	var wrist := _source_to_world(SOURCE_WRIST)
	var upper_axis := elbow - shoulder
	var forearm_axis := wrist - elbow
	var upper_angle := rad_to_deg(upper_axis.angle())
	var forearm_angle := rad_to_deg(forearm_axis.angle())
	var upper_center_distance := (UPPER_WORLD_SIZE.x * 0.5) - (UPPER_PIVOT_PX.x / UPPER_SIZE.x) * UPPER_WORLD_SIZE.x
	var forearm_center_distance := (FOREARM_WORLD_SIZE.x * 0.5) - (FOREARM_PIVOT_PX.x / FOREARM_SIZE.x) * FOREARM_WORLD_SIZE.x
	var upper_center := Vector2.from_angle(deg_to_rad(upper_angle)) * upper_center_distance
	var forearm_center := Vector2.from_angle(deg_to_rad(forearm_angle)) * forearm_center_distance
	var torso_source_center := Vector2(747.5, 675.0)
	var torso_center := _source_to_world(torso_source_center) - torso

	var bones := [
		{"name": "root"},
		{"name": BONE_TORSO, "parent": "root", "x": torso.x, "y": torso.y},
		{"name": BONE_CLAVICLE, "parent": BONE_TORSO, "x": clavicle.x - torso.x, "y": clavicle.y - torso.y, "length": clavicle.distance_to(shoulder)},
		{"name": BONE_UPPER, "parent": BONE_CLAVICLE, "x": shoulder.x - clavicle.x, "y": shoulder.y - clavicle.y, "length": upper_axis.length()},
		{"name": BONE_FOREARM_HAND, "parent": BONE_UPPER, "x": elbow.x - shoulder.x, "y": elbow.y - shoulder.y, "length": forearm_axis.length()},
		{"name": BONE_WRIST, "parent": BONE_FOREARM_HAND, "x": wrist.x - elbow.x, "y": wrist.y - elbow.y},
	]
	var slots := [
		# Spine draw order is array order: far upper first, foreground cuff/hand
		# second, torso/shoulder cover third.  This exactly expresses the depth
		# contract instead of relying on ambiguous file names.
		{"name": "far_upper_arm", "bone": BONE_UPPER, "attachment": REGION_UPPER},
		{"name": "far_forearm_hand", "bone": BONE_FOREARM_HAND, "attachment": REGION_FOREARM_HAND},
		{"name": "torso_shoulder_cover", "bone": BONE_TORSO, "attachment": REGION_TORSO},
		{"name": "marker_shoulder", "bone": BONE_UPPER, "attachment": REGION_MARKER_SHOULDER},
		{"name": "marker_elbow", "bone": BONE_FOREARM_HAND, "attachment": REGION_MARKER_ELBOW},
		{"name": "marker_wrist", "bone": BONE_WRIST, "attachment": REGION_MARKER_WRIST},
		# Required game-facing names are present solely to prove this isolated
		# graph remains loadable by the same comparison harness.  The far hand is
		# intentionally not the slash origin; the production preview parents that
		# VFX to the screen-right/near hand.
		{"name": "slash_mesh", "bone": "root"},
		{"name": "eye_attach_slot", "bone": "root"},
	]
	var attachments := {
		"far_upper_arm": {REGION_UPPER: _region(REGION_UPPER, upper_center, upper_angle, UPPER_WORLD_SIZE)},
		"far_forearm_hand": {REGION_FOREARM_HAND: _region(REGION_FOREARM_HAND, forearm_center, forearm_angle, FOREARM_WORLD_SIZE)},
		"torso_shoulder_cover": {REGION_TORSO: _region(REGION_TORSO, torso_center, 0.0, TORSO_WORLD_SIZE)},
		"marker_shoulder": {REGION_MARKER_SHOULDER: _region(REGION_MARKER_SHOULDER, Vector2.ZERO, 0.0, Vector2(18, 18))},
		"marker_elbow": {REGION_MARKER_ELBOW: _region(REGION_MARKER_ELBOW, Vector2.ZERO, 0.0, Vector2(18, 18))},
		"marker_wrist": {REGION_MARKER_WRIST: _region(REGION_MARKER_WRIST, Vector2.ZERO, 0.0, Vector2(18, 18))},
	}
	return {
		"skeleton": {
			"hash": "vivhite-semantic-left-arm-graybox-v1",
			"spine": SPINE_VERSION,
			"x": -520.0,
			"y": 540.0,
			"width": 720.0,
			"height": 560.0,
			"images": "./",
		},
		"bones": bones,
		"slots": slots,
		"skins": [{"name": "default", "attachments": attachments}],
		"events": {
			"attack_slash_start": {},
			"heavy_slash_start": {},
			"cast_eyes_start": {},
			"clear_vfx": {},
		},
		"animations": _build_animations(),
	}


func _region(path: String, offset: Vector2, rotation: float, size: Vector2) -> Dictionary:
	return {
		"path": path,
		"x": offset.x,
		"y": offset.y,
		"rotation": rotation,
		"width": size.x,
		"height": size.y,
	}


func _build_animations() -> Dictionary:
	return {
		"idle_loop": _animation(2.0, [
			{"time": 0.0, "upper": 0.0, "forearm": 0.0},
			{"time": 0.5, "upper": 0.0, "forearm": 1.1},
			{"time": 1.0, "upper": 0.0, "forearm": 0.0},
			{"time": 1.5, "upper": 0.0, "forearm": -0.7},
			{"time": 2.0, "upper": 0.0, "forearm": 0.0},
		]),
		"low_health_loop": _animation(1.4666667, [
			{"time": 0.0, "upper": 8.0, "forearm": 0.0},
			{"time": 0.3666667, "upper": 10.0, "forearm": 0.0},
			{"time": 0.7333334, "upper": 8.0, "forearm": 0.0},
			{"time": 1.4666667, "upper": 8.0, "forearm": 0.0},
		]),
		"relaxed_loop": _animation(12.000001, [
			{"time": 0.0, "upper": 0.0, "forearm": 0.0},
			{"time": 3.0, "upper": 0.0, "forearm": 0.83},
			{"time": 6.0, "upper": 0.0, "forearm": 0.0},
			{"time": 9.0, "upper": 0.0, "forearm": -0.53},
			{"time": 12.000001, "upper": 0.0, "forearm": 0.0},
		]),
		"attack": _animation(1.1666667, [
			{"time": 0.0, "upper": 12.0, "forearm": 0.0},
			{"time": 0.08, "upper": -12.0, "forearm": 0.0},
			{"time": 0.45, "upper": -12.0, "forearm": 0.0},
			{"time": 1.1666667, "upper": 0.0, "forearm": 0.0},
		], [{"time": 0.08, "name": "attack_slash_start"}, {"time": 0.45, "name": "clear_vfx"}]),
		"attack_heavy": _animation(1.5333334, [
			{"time": 0.0, "upper": 12.0, "forearm": 0.0},
			{"time": 0.12, "upper": -18.0, "forearm": 0.0},
			{"time": 0.72, "upper": -18.0, "forearm": 0.0},
			{"time": 1.5333334, "upper": 0.0, "forearm": 0.0},
		], [{"time": 0.12, "name": "heavy_slash_start"}, {"time": 0.72, "name": "clear_vfx"}]),
		"cast": _animation(1.5666667, [
			{"time": 0.0, "upper": 12.0, "forearm": 14.0},
			{"time": 0.25, "upper": -35.0, "forearm": -48.0},
			{"time": 1.0, "upper": -35.0, "forearm": -48.0},
			{"time": 1.5666667, "upper": 0.0, "forearm": 0.0},
		], [{"time": 0.25, "name": "cast_eyes_start"}, {"time": 1.0, "name": "clear_vfx"}]),
		"hurt": _animation(1.0, [
			{"time": 0.0, "upper": 0.0, "forearm": 0.0},
			{"time": 0.14, "upper": 18.0, "forearm": 0.0},
			{"time": 0.52, "upper": 18.0, "forearm": 0.0},
			{"time": 1.0, "upper": 0.0, "forearm": 0.0},
		], [{"time": 0.72, "name": "clear_vfx"}]),
		"die": _animation(2.3333335, [
			{"time": 0.0, "upper": 0.0, "forearm": 0.0},
			{"time": 0.48, "upper": 14.0, "forearm": -9.0},
			{"time": 1.18, "upper": 71.0, "forearm": 55.0},
			{"time": 1.75, "upper": 71.0, "forearm": 55.0},
			{"time": 2.3333335, "upper": 71.0, "forearm": 55.0},
		], [{"time": 0.0, "name": "clear_vfx"}]),
	}


func _animation(duration: float, poses: Array, events: Array = []) -> Dictionary:
	var upper := []
	var forearm := []
	var root_hold := []
	for pose: Dictionary in poses:
		upper.append({"time": pose["time"], "value": pose["upper"]})
		forearm.append({"time": pose["time"], "value": pose["forearm"]})
	root_hold.append({"time": 0.0, "value": 0.0})
	root_hold.append({"time": duration, "value": 0.0})
	var result := {"bones": {
		"root": {"rotate": root_hold},
		BONE_UPPER: {"rotate": upper},
		BONE_FOREARM_HAND: {"rotate": forearm},
	}}
	if not events.is_empty():
		result["events"] = events
	return result


func _build_graybox_page() -> Image:
	var page := Image.create_empty(PAGE_SIZE.x, PAGE_SIZE.y, false, Image.FORMAT_RGBA8)
	page.fill(Color(0, 0, 0, 0))
	var upper := Image.create_empty(UPPER_SIZE.x, UPPER_SIZE.y, false, Image.FORMAT_RGBA8)
	upper.fill(Color(0, 0, 0, 0))
	_draw_upper_arm(upper)
	var forearm := Image.create_empty(FOREARM_SIZE.x, FOREARM_SIZE.y, false, Image.FORMAT_RGBA8)
	forearm.fill(Color(0, 0, 0, 0))
	_draw_forearm_hand(forearm)
	var torso := Image.create_empty(TORSO_SIZE.x, TORSO_SIZE.y, false, Image.FORMAT_RGBA8)
	torso.fill(Color(0, 0, 0, 0))
	_draw_rounded_rect(torso, Rect2i(8, 6, 240, 276), 28, Color("26324f"))
	_draw_rounded_rect(torso, Rect2i(16, 18, 224, 78), 20, Color("44557c"))
	var shoulder_marker := _marker(Color("ff4fc3"))
	var elbow_marker := _marker(Color("ffdf4f"))
	var wrist_marker := _marker(Color("4fffe1"))
	_blit(page, upper, UPPER_POS)
	_blit(page, forearm, FOREARM_POS)
	_blit(page, torso, TORSO_POS)
	_blit(page, shoulder_marker, MARKER_SHOULDER_POS)
	_blit(page, elbow_marker, MARKER_ELBOW_POS)
	_blit(page, wrist_marker, MARKER_WRIST_POS)
	return page


func _draw_upper_arm(image: Image) -> void:
	# Pixel x=62 is the shoulder pivot and x=275 is the elbow pivot after
	# mapping this attachment into UPPER_WORLD_SIZE.  The two 45 px joint disks
	# are therefore 27.19 authored-world units in radius.  The narrower tails
	# deliberately reach both region edges: under the torso they provide the
	# frozen 39.71875-world shoulder underlap, and at the elbow they preserve the
	# full overhang consumed by the foreground forearm cuff.
	for y in image.get_height():
		for x in image.get_width():
			var point := Vector2(x, y)
			var inside: bool = (
				(x <= 62 and abs(y - 48) <= 27)
				or (x >= 62 and x <= 275 and abs(y - 48) <= 27)
				or point.distance_to(Vector2(62, 48)) <= 45
				or point.distance_to(Vector2(275, 48)) <= 45
			)
			if inside:
				var color := Color("526fa7")
				if x <= 62:
					color = Color("d14bca")
				elif x >= 263:
					color = Color("42d5e8")
				image.set_pixel(x, y, color)


func _draw_forearm_hand(image: Image) -> void:
	# Proximal yellow is the elbow overlap/cuff, cyan is the forearm, and pink
	# is the single empty hand.  Pixel x=64 is exactly the elbow pivot.  Its
	# 42 px disk maps to 27.3 authored-world units, so both sides of the elbow
	# meet the stress radius promised by contract.json.  The narrower proximal
	# tail reaches x=0 and realizes the full 41.6667-world hidden overlap.
	# The object remains one connected Alpha island.
	for y in image.get_height():
		for x in image.get_width():
			var color := Color(0, 0, 0, 0)
			var center := Vector2(x, y)
			var arm_inside: bool = (
				(x <= 278 and abs(y - 80) <= 27)
				or center.distance_to(Vector2(64, 80)) <= 42
				or center.distance_to(Vector2(278, 80)) <= 27
			)
			if arm_inside:
				color = Color("f3c94c") if x <= 74 else Color("45c6de")
			var palm_inside := pow((x - 304.0) / 45.0, 2.0) + pow((y - 80.0) / 35.0, 2.0) <= 1.0
			if palm_inside:
				color = Color("f29bb5")
			for endpoint in [Vector2(374, 42), Vector2(381, 62), Vector2(382, 82), Vector2(374, 104), Vector2(352, 126)]:
				if _distance_to_segment(center, Vector2(320, 80), endpoint) <= 5.5:
					color = Color("f29bb5")
			if color.a > 0.0:
				image.set_pixel(x, y, color)


func _distance_to_segment(point: Vector2, start: Vector2, finish: Vector2) -> float:
	var segment := finish - start
	if segment.length_squared() <= 0.00001:
		return point.distance_to(start)
	var t := clampf((point - start).dot(segment) / segment.length_squared(), 0.0, 1.0)
	return point.distance_to(start + segment * t)


func _draw_rounded_rect(image: Image, rect: Rect2i, radius: int, color: Color) -> void:
	for y in range(rect.position.y, rect.end.y):
		for x in range(rect.position.x, rect.end.x):
			var nearest_x := clampi(x, rect.position.x + radius, rect.end.x - radius - 1)
			var nearest_y := clampi(y, rect.position.y + radius, rect.end.y - radius - 1)
			if Vector2(x, y).distance_to(Vector2(nearest_x, nearest_y)) <= radius:
				image.set_pixel(x, y, color)


func _marker(color: Color) -> Image:
	var image := Image.create_empty(MARKER_SIZE.x, MARKER_SIZE.y, false, Image.FORMAT_RGBA8)
	image.fill(Color(0, 0, 0, 0))
	for y in image.get_height():
		for x in image.get_width():
			var distance := Vector2(x - 15.5, y - 15.5).length()
			if distance <= 14.0 and distance >= 7.0:
				image.set_pixel(x, y, color)
	return image


func _blit(page: Image, source: Image, position: Vector2i) -> void:
	page.blend_rect(source, Rect2i(Vector2i.ZERO, source.get_size()), position)


func _build_atlas_text() -> String:
	var lines := [
		OUTPUT_PAGE,
		"size:%d,%d" % [PAGE_SIZE.x, PAGE_SIZE.y],
		"filter:Linear,Linear",
		"pma:false",
		"repeat:none",
	]
	for region in [
		[REGION_UPPER, UPPER_POS, UPPER_SIZE],
		[REGION_FOREARM_HAND, FOREARM_POS, FOREARM_SIZE],
		[REGION_TORSO, TORSO_POS, TORSO_SIZE],
		[REGION_MARKER_SHOULDER, MARKER_SHOULDER_POS, MARKER_SIZE],
		[REGION_MARKER_ELBOW, MARKER_ELBOW_POS, MARKER_SIZE],
		[REGION_MARKER_WRIST, MARKER_WRIST_POS, MARKER_SIZE],
	]:
		lines.append(str(region[0]))
		lines.append("bounds:%d,%d,%d,%d" % [region[1].x, region[1].y, region[2].x, region[2].y])
	return "\n".join(lines) + "\n"


func _build_tres() -> String:
	return """[gd_resource type="SpineSkeletonDataResource" load_steps=3 format=3]

[ext_resource type="SpineAtlasResource" path="%s/%s" id="1_atlas"]
[ext_resource type="SpineSkeletonFileResource" path="%s/%s" id="2_skeleton"]

[resource]
atlas_res = ExtResource("1_atlas")
skeleton_file_res = ExtResource("2_skeleton")
default_mix = 0.05
""" % [MOUNT_ROOT, OUTPUT_ATLAS, MOUNT_ROOT, OUTPUT_JSON]


func _build_contract() -> Dictionary:
	var torso := _source_to_world(SOURCE_TORSO)
	var clavicle := _source_to_world(SOURCE_CLAVICLE)
	var shoulder := _source_to_world(SOURCE_SHOULDER)
	var elbow := _source_to_world(SOURCE_ELBOW)
	var wrist := _source_to_world(SOURCE_WRIST)
	return {
		"schema_version": 1,
		"status": "diagnostic_graybox_only_not_publishable",
		"paid_generation_calls": 0,
		"side_contract": {
			"screen_side": "screen-left",
			"depth_side": "far arm behind torso",
			"anatomical_side": "character-right",
			"legacy_alias": "split_mesh arm_left_* means screen-left, not anatomical-left",
			"identity_evidence": "The asymmetric blue/gold shoulder ornament is on viewer-left in the frontal character design, hence anatomical-right; the same ornament identifies this limb in 0018 and 0022.",
		},
		"source_audit": {
			"runtime_consumer_scene": "Vivhite/Vivhite/skins/ironclad/scenes/combat.tscn",
			"runtime_consumer_scene_evidence": "The SpineSprite consumes one skeleton at scale 0.28; source code names only slash_mesh and eye_attach_slot. No C#/scene consumer names an arm region.",
			"current_runtime_rig_builder": "tools/art/build_vivhite_combat_rig.gd",
			"current_runtime_topology": "one vivhite_body weighted-mesh attachment; arm-named deform bones are sibling controls under vivhite_rig, not independent drawable arm parts",
			"target_split_builder": "tools/art/build_vivhite_combat_split_mesh_candidate.gd",
			"target_split_topology": "hierarchical shoulder -> upper arm -> forearm -> hand chain with arm slots behind torso; this is the consumer contract researched here",
			"runtime_builder_source": "assets/vivhite-ironclad/custom/combat/sources/vivhite-combat-body-master-v1.png",
			"runtime_builder_source_sha256": "86ffd64a637d170e213879e72d986b707ee181d4812c8e3fb1eda4abfab98bd1",
			"runtime_builder_source_equals": "0018-combat-body-master-attempt-01/output.png",
			"visual_direction_cross_check": "0022-combat-body-master-attempt-05/output.png",
			"visual_direction_cross_check_sha256": "488e74758164dab0702ec6f943e02d23d9561caef29320275f698cb0000e232e",
			"classification": "Each master is one full-body single-frame RGBA image, not a sprite sheet or independent arm attachment.",
			"publishable_independent_far_arm_source_found": false,
			"usable_existing_sources": [],
			"research_only_sources": [
				"0018 full-body master: authoritative current pivot/scale evidence but flattened joints and whole-body lighting",
				"0022 full-body master: direction/silhouette cross-check only; low-detail identity",
				"legacy-contaminated arm regions: prohibited bloodline and not reusable",
			],
		},
		"consumer_contract": {
			"scene_scale": SCENE_SCALE,
			"source_canvas_px": [SOURCE_SIZE.x, SOURCE_SIZE.y],
			"authored_world_rect": [WORLD_RECT.position.x, WORLD_RECT.position.y, WORLD_RECT.size.x, WORLD_RECT.size.y],
			"fixed_draw_order_back_to_front": ["far_upper_arm", "far_forearm_hand", "torso_shoulder_cover"],
			"shoulder_cover_owner": "torso/shoulder-cover group owns the asymmetric blue/gold pauldron; far upper-arm art supplies solid skin underlap and must not duplicate the pauldron",
			"vfx_owner": "Far arm owns no Ironclad slash VFX anchor. Current split consumer parents slash_mesh to the screen-right/near hand; cast eye VFX belongs to head.",
			"two_piece_default": true,
			"third_hand_split_gate": "Split a separate hand only if real art fails the cast/death extreme contact sheet because the audited wrist rotation envelope (-20 to +31 degrees) cannot be represented by the combined forearm-hand silhouette.",
		},
		"diagnostic_output_layout": {
			"classification": "one packed atlas page containing six independent regions; not a single illustration",
			"page": OUTPUT_PAGE,
			"regions": [REGION_UPPER, REGION_FOREARM_HAND, REGION_TORSO, REGION_MARKER_SHOULDER, REGION_MARKER_ELBOW, REGION_MARKER_WRIST],
			"production_use": false,
		},
		"pivots": {
			"torso_upper": _point_record(SOURCE_TORSO, torso),
			"clavicle_cover": _point_record(SOURCE_CLAVICLE, clavicle),
			"shoulder_upper_arm": _point_record(SOURCE_SHOULDER, shoulder),
			"elbow_forearm_hand": _point_record(SOURCE_ELBOW, elbow),
			"wrist_measurement_anchor": _point_record(SOURCE_WRIST, wrist),
		},
		"bones": {
			"clavicle_to_shoulder_world": [shoulder.x - clavicle.x, shoulder.y - clavicle.y],
			"shoulder_to_elbow_world": [elbow.x - shoulder.x, elbow.y - shoulder.y],
			"elbow_to_wrist_world": [wrist.x - elbow.x, wrist.y - elbow.y],
			"upper_length_world": shoulder.distance_to(elbow),
			"forearm_length_world": elbow.distance_to(wrist),
		},
		"hidden_overlap": {
			"shoulder_upper_proximal_world_min": SHOULDER_OVERLAP_WORLD,
			"upper_beyond_elbow_world_min": UPPER_ELBOW_OVERHANG_WORLD,
			"forearm_before_elbow_world_min": FOREARM_ELBOW_OVERHANG_WORLD,
			"shared_elbow_solid_radius_world_min": ELBOW_SOLID_RADIUS_WORLD,
			"scene_pixel_equivalents_at_0_28": {
				"shoulder_upper_proximal": SHOULDER_OVERLAP_WORLD * SCENE_SCALE,
				"upper_beyond_elbow": UPPER_ELBOW_OVERHANG_WORLD * SCENE_SCALE,
				"forearm_before_elbow": FOREARM_ELBOW_OVERHANG_WORLD * SCENE_SCALE,
				"shared_elbow_radius": ELBOW_SOLID_RADIUS_WORLD * SCENE_SCALE,
			},
		},
		"audited_rotation_envelope_degrees": {
			"far_upper_arm": [-35.0, 71.0],
			"far_forearm_hand_relative_to_upper": [-48.0, 55.0],
			"legacy_wrist_measurement_only": [-20.0, 31.0],
			"source": "tools/art/build_vivhite_combat_split_mesh_candidate.gd and generated split_mesh Spine timelines",
		},
		"acceptance": {
			"required_animations": ANIMATION_DURATIONS.keys(),
			"static": [
				"default skin; exact parent chain and pivots",
				"far arm slots precede torso slot; no drawOrder animation",
				"two connected pieces and three visible pivot markers",
				"all eight animation durations and audited rotation extrema",
			],
			"vulkan": [
				"actual Spine GDExtension and Vulkan",
				"eight animations at five samples; non-empty, no canvas edge contact, no static animation",
				"manual review of cast and death extreme elbow/shoulder coverage",
			],
		},
	}


func _point_record(source: Vector2, world: Vector2) -> Dictionary:
	return {"source_px": [source.x, source.y], "world": [world.x, world.y]}


func _build_readme() -> String:
	return """# semantic_left_arm 灰盒消费者

本候选只研究战斗画面左侧、角色远侧、角色解剖右臂。旧 `split_mesh` 的
`arm_left_*` 是屏幕侧别名；角色正面设定中蓝金肩饰位于 viewer-left，证明它是
角色解剖右侧。

## 冻结结构

- `semantic_left_arm_graybox.png` 是含 6 个独立 region 的 packed atlas 页，不是单幅插画；
  其中只有上臂、前臂手是未来美术消费者，躯干盖板与 3 个关节点标记只用于诊断。
- 两个正式美术对象：`far_upper_arm` 与 `far_forearm_hand`；腕点只保留测量锚点。
- 固定后到前层序：上臂、前臂手、躯干/肩盖。蓝金肩饰归躯干/肩盖所有，上臂不得重复。
- 肩、肘、腕沿用当前实际 `0018` 消费者的 `(585,585)`、`(465,820)`、`(275,1010)` 源画布点。
- 上臂旋转门禁 `-35°..+71°`，前臂手相对旋转门禁 `-48°..+55°`。
- 当前远手不消费 `slash_mesh`；刀光/魔法弧仍属于屏幕右侧近手。

## 素材审计

运行时 `combat.tscn` 只消费一个 `SpineSprite`（场景缩放 `0.28`）以及
`slash_mesh` / `eye_attach_slot` 两个 VFX slot；它不按名称消费任何手臂 region。当前正式
`build_vivhite_combat_rig.gd` 也只有一张 `vivhite_body` 加权网格，手臂名骨骼只是同级形变
控制，不是可复用拆件。这里的父子链和层序来自目标 `build_vivhite_combat_split_mesh_candidate.gd`
消费者，而不是沿用原战士姿势。

仓库没有可发布的独立远侧手臂源。`0018` 与 `0022` 都是单帧整身图，只能提供身份、
方向和关节点；旧战士拆出的手臂 region 位于污染历史目录，禁止使用。因此这里生成的
PNG 只是程序绘制的诊断色块，不是白绮美术，也不允许发布。

## 升级门禁

真实美术先按两件接入。若真实 Vulkan 接触表证明 cast/death 极限姿势必须消费旧腕部
`-20°..+31°` 旋转，才把空手拆成第三件；不得为了“骨更多”提前增加接缝。
"""


func _source_to_world(point: Vector2) -> Vector2:
	return Vector2(
		WORLD_RECT.position.x + WORLD_RECT.size.x * point.x / SOURCE_SIZE.x,
		WORLD_RECT.position.y + WORLD_RECT.size.y * (1.0 - point.y / SOURCE_SIZE.y),
	)


func _absolute_repo_path(path: String) -> String:
	if path.is_absolute_path():
		return path.simplify_path()
	return _repo_root().path_join(path).simplify_path()


func _repo_root() -> String:
	return ProjectSettings.globalize_path("res://").path_join("../..").simplify_path()


func _write_text(path: String, text: String) -> bool:
	var file := FileAccess.open(path, FileAccess.WRITE)
	if file == null:
		return _set_error("Could not open output for writing: %s" % path)
	file.store_string(text)
	file.close()
	return true


func _set_error(message: String) -> bool:
	_last_error = message
	return false


func _fail(message: String) -> int:
	push_error("[semantic-left-arm] %s" % message)
	return 2
