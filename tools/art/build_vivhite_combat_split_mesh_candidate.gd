extends "res://build_vivhite_combat_rig.gd"

## Builds an isolated, preview-only "split parts + hierarchical bones" combat
## candidate. It never writes below Vivhite/Vivhite/skins/ironclad and it never
## deploys. The current native-RGBA master is sampled through independent Spine
## mesh UV subdomains; its Alpha bytes are not thresholded, masked, repaired or
## otherwise rewritten. Because the master contains a whole-body halo and has
## flattened joints, this candidate is deliberately marked non-publishable.

const SPLIT_COMMAND := "build-split-mesh-candidate"
const SPLIT_OUTPUT_ROOT := "assets/vivhite-ironclad/candidates/split_mesh/combat"
const SPLIT_MOUNT_ROOT := "res://candidates/split_mesh/combat"

const SPLIT_JSON := "vivhite_combat_split_mesh.spjson"
const SPLIT_ATLAS := "vivhite_combat_split_mesh.spatlas"
const SPLIT_PAGE := "vivhite_combat_split_mesh.png"
const SPLIT_DEATH_PAGE := "vivhite_combat_split_mesh_death.png"
const SPLIT_DATA := "vivhite_combat_split_mesh_skeleton_data.tres"
const SPLIT_MANIFEST := "candidate.json"
const SPLIT_REGION := "vivhite_split_master"
const SPLIT_DEATH_REGION := "vivhite_combat_death_side"
const SPLIT_DEFAULT_DEATH_SOURCE := (
	"assets/vivhite-ironclad/custom/combat/sources/"
	+ "vivhite-combat-death-side-collapse-v2.png"
)

# Preserve the accepted gameplay scale contract: the consuming scene remains
# at 0.28 and this authored character space is 70% of the original prototype.
const SPLIT_SCENE_SCALE := 0.28
const SPLIT_CHARACTER_SCALE := 0.70
const SPLIT_FLOOR_OFFSET := -61.0
const SPLIT_SOURCE_SIZE := Vector2(1680.0, 2512.0)
const SPLIT_WORLD_RECT := Rect2(
	-620.0 * SPLIT_CHARACTER_SCALE,
	SPLIT_FLOOR_OFFSET,
	1240.0 * SPLIT_CHARACTER_SCALE,
	1860.0 * SPLIT_CHARACTER_SCALE
)

const SPLIT_ATLAS_SIZE := Vector2i(3072, 2304)
const SPLIT_REGION_POS := Vector2i(16, 16)
const SPLIT_REGION_SIZE := Vector2i(1536, 2272)
const SPLIT_ARC_POS := Vector2i(1568, 16)
const SPLIT_ARC_SIZE := Vector2i(1488, 1104)
const SPLIT_SIGIL_POS := Vector2i(1808, 1152)
const SPLIT_SIGIL_SIZE := Vector2i(1248, 1136)

# Keep the authored side-collapse drawing isolated on a second page. Replacing
# this rigid landing attachment therefore cannot perturb any standing-part UV,
# magic ribbon, or sigil region on the proven first page.
const SPLIT_DEATH_ATLAS_SIZE := Vector2i(2048, 1536)
const SPLIT_DEATH_REGION_POS := Vector2i(16, 16)
const SPLIT_DEATH_REGION_SIZE := Vector2i(2016, 1504)
const SPLIT_DEATH_WORLD_WIDTH := 1302.0
const SPLIT_DEATH_WORLD_HEIGHT := 970.8571428571
const SPLIT_DEATH_ALPHA_EDGE_CENTER_Y := 412.8
const SPLIT_DEATH_SOLID_CONTACT_SHIFT := 224.8
const SPLIT_DEATH_ENTRY_OFFSET_Y := 298.8
const SPLIT_DEATH_ENTRY_WORLD_Y := 486.8
# v2's accepted whole-body glow extends below the painted hands and boots. The
# final bone therefore aligns the solid contact edge rather than the faintest
# Alpha pixel; the glow may continue below the floor without making her hover.
const SPLIT_DEATH_FINAL_CENTER := Vector2(55.0, 188.0)
const SPLIT_DEATH_SWAP_TIME := 1.05
const SPLIT_DEATH_IMPACT_TIME := 1.17

const SPLIT_BONE_PELVIS := "vivhite_pelvis"
const SPLIT_BONE_SKIRT := "vivhite_skirt_center"
const SPLIT_BONE_TORSO_LOWER := "vivhite_torso_lower"
const SPLIT_BONE_TORSO_UPPER := "vivhite_torso_upper"
const SPLIT_BONE_NECK := "vivhite_neck"
const SPLIT_BONE_HEAD := "vivhite_head"
const SPLIT_BONE_DEATH := "vivhite_death_pose"
const SPLIT_SLOT_DEATH := "vivhite_death_body"

# Spine 4.2 serializes Bezier handles in absolute timeline coordinates. These
# normalized profiles are converted for every rotate/translate segment while
# preserving all authored key poses and durations.
const SPLIT_LOOP_EASING := Vector4(0.25, 0.0, 0.75, 1.0)
const SPLIT_ACTION_EASING := Vector4(0.20, 0.0, 0.68, 1.0)

# This is the exact per-transition mix contract from the extracted Ironclad
# SpineSkeletonDataResource. A zero mix is intentionally serialized by omitting
# the property, matching the vanilla resource's default value for the mix type.
const SPLIT_ANIMATION_MIXES := [
	{"id": "SpineAnimationMix_idle_attack", "from": "idle_loop", "to": "attack", "mix": 0.10},
	{"id": "SpineAnimationMix_attack_attack", "from": "attack", "to": "attack", "mix": 0.0},
	{"id": "SpineAnimationMix_hurt_hurt", "from": "hurt", "to": "hurt", "mix": 0.0},
	{"id": "SpineAnimationMix_hurt_die", "from": "hurt", "to": "die", "mix": 0.0},
	{"id": "SpineAnimationMix_idle_hurt", "from": "idle_loop", "to": "hurt", "mix": 0.03},
	{"id": "SpineAnimationMix_hurt_idle", "from": "hurt", "to": "idle_loop", "mix": 0.10},
	{"id": "SpineAnimationMix_idle_heavy", "from": "idle_loop", "to": "attack_heavy", "mix": 0.02},
	{"id": "SpineAnimationMix_heavy_heavy", "from": "attack_heavy", "to": "attack_heavy", "mix": 0.0},
	{"id": "SpineAnimationMix_attack_heavy", "from": "attack", "to": "attack_heavy", "mix": 0.0},
	{"id": "SpineAnimationMix_heavy_attack", "from": "attack_heavy", "to": "attack", "mix": 0.0},
]

# These are preview UV subdomains, not publishable independent drawings. Each
# rectangle is copied by the GPU from the one unmodified whole-body region.
# Overlap bands hide hard joint cuts in setup pose and intentionally make the
# limitations of flattened source art visible once a child bone rotates.
const SPLIT_PARTS := [
	{"name": "leg_left_thigh", "bone": "vivhite_thigh_left", "rect": Rect2(445, 1140, 270, 330)},
	{"name": "leg_left_lower", "bone": "vivhite_knee_left", "rect": Rect2(380, 1240, 310, 690)},
	{"name": "leg_left_foot", "bone": "vivhite_foot_left", "rect": Rect2(340, 1810, 340, 390)},
	{"name": "leg_right_thigh", "bone": "vivhite_thigh_right", "rect": Rect2(675, 1120, 300, 390)},
	{"name": "leg_right_lower", "bone": "vivhite_knee_right", "rect": Rect2(735, 1240, 600, 900)},
	{"name": "leg_right_foot", "bone": "vivhite_foot_right", "rect": Rect2(1100, 2000, 280, 480)},
	{"name": "arm_left_upper", "bone": "vivhite_upper_arm_left", "rect": Rect2(400, 590, 250, 310)},
	{"name": "arm_left_forearm", "bone": "vivhite_forearm_left", "rect": Rect2(245, 780, 280, 290)},
	{"name": "arm_left_hand", "bone": "vivhite_hand_left", "rect": Rect2(95, 1000, 220, 190)},
	{"name": "torso", "bone": SPLIT_BONE_TORSO_UPPER, "rect": Rect2(505, 430, 485, 490)},
	{"name": "skirt", "bone": SPLIT_BONE_SKIRT, "rect": Rect2(445, 825, 805, 470)},
	{"name": "head_front_hair_butterfly", "bone": SPLIT_BONE_HEAD, "rect": Rect2(500, 5, 590, 510)},
	{"name": "arm_right_upper", "bone": "vivhite_upper_arm_right", "rect": Rect2(745, 475, 340, 260)},
	{"name": "arm_right_forearm", "bone": "vivhite_forearm_right", "rect": Rect2(980, 500, 400, 270)},
	{"name": "arm_right_hand", "bone": "vivhite_hand_right", "rect": Rect2(1360, 350, 300, 300)},
]

const SPLIT_REQUIRED_REDRAWS := [
	{
		"id": "back_hair",
		"reason": "Back hair is flattened into the head silhouette and has no hidden neck/shoulder pixels.",
		"delivery": "Independent native-transparent back-hair attachment with clean joint overlap and no baked halo.",
	},
	{
		"id": "head_front_hair_butterfly",
		"reason": "Face, front hair, rear hair and butterfly overlap in one flattened drawing.",
		"delivery": "Separate head/face, front-hair locks, rear-hair locks and butterfly attachments.",
	},
	{
		"id": "torso_skirt",
		"reason": "Shoulders, bodice, skirt and upper thighs are flattened and lack pixels behind overlaps.",
		"delivery": "Torso, pelvis and 3-5 skirt-panel attachments with concealed overlap padding.",
	},
	{
		"id": "limbs",
		"reason": "Every shoulder/elbow/wrist/hip/knee/ankle is continuous in the source and the global halo crosses each cut.",
		"delivery": "Left/right upper arm, forearm, hand, thigh, lower leg and foot as individually generated native-transparent parts.",
	},
]


func _initialize() -> void:
	var args := OS.get_cmdline_user_args()
	if args.is_empty():
		args = PackedStringArray([SPLIT_COMMAND])
	if args[0] in ["-h", "--help", "help"]:
		print("Usage:")
		print("  godot --headless --path tools/art --script res://build_vivhite_combat_split_mesh_candidate.gd -- build-split-mesh-candidate")
		print("    [--body-source PATH] [--arc-source PATH] [--sigil-source PATH] [--death-source PATH] [--output-root PATH]")
		quit(0)
		return
	if args[0] != SPLIT_COMMAND:
		quit(_fail("Unknown command: %s" % args[0]))
		return
	var options := _parse_options(args)
	if options.is_empty() and args.size() > 1:
		quit(2)
		return
	var body_path := _absolute_path(str(options.get("body-source", DEFAULT_BODY_SOURCE)))
	var arc_path := _absolute_path(str(options.get("arc-source", DEFAULT_ARC_SOURCE)))
	var sigil_path := _absolute_path(str(options.get("sigil-source", DEFAULT_SIGIL_SOURCE)))
	var death_path := _absolute_path(str(options.get("death-source", SPLIT_DEFAULT_DEATH_SOURCE)))
	var output_root := _absolute_path(str(options.get("output-root", SPLIT_OUTPUT_ROOT)))
	if not _build_split_candidate(body_path, arc_path, sigil_path, death_path, output_root):
		quit(_fail(_last_error))
		return
	quit(0)


func _build_split_candidate(
	body_path: String,
	arc_path: String,
	sigil_path: String,
	death_path: String,
	output_root: String,
) -> bool:
	_last_error = ""
	if output_root.replace("\\", "/").contains("/Vivhite/Vivhite/skins/ironclad"):
		return _set_error("Split candidate output may not target the live runtime skin: %s" % output_root)
	var body := _load_native_rgba(body_path, "combat body master")
	if body.is_empty():
		return false
	if body.get_size() != Vector2i(int(SPLIT_SOURCE_SIZE.x), int(SPLIT_SOURCE_SIZE.y)):
		return _set_error("Split UV contract requires a 1680x2512 master, got %s" % body.get_size())
	var arc := _load_native_rgba(arc_path, "combat magic arc")
	if arc.is_empty():
		return false
	var sigil := _load_native_rgba(sigil_path, "shared magic sigil")
	if sigil.is_empty():
		return false
	var death := _load_native_rgba(death_path, "side-collapse death source")
	if death.is_empty():
		return false
	var arc_region := _prepare_region(arc, SPLIT_ARC_SIZE, "combat magic arc")
	if arc_region.is_empty():
		return false
	var sigil_region := _prepare_region(sigil, SPLIT_SIGIL_SIZE, "shared magic sigil")
	if sigil_region.is_empty():
		return false
	var death_region := _prepare_region(death, SPLIT_DEATH_REGION_SIZE, "side-collapse death source")
	if death_region.is_empty():
		return false

	for part: Dictionary in SPLIT_PARTS:
		var rect: Rect2 = part["rect"]
		if rect.position.x < 0 or rect.position.y < 0 or rect.end.x > SPLIT_SOURCE_SIZE.x or rect.end.y > SPLIT_SOURCE_SIZE.y:
			return _set_error("Part %s is outside the source canvas: %s" % [part["name"], rect])

	# Preserve the model-authored Alpha exactly until the single allowed resize.
	# No alpha-bounds crop is used for the body because every mesh attachment
	# relies on stable full-canvas UV coordinates.
	var body_region := body.duplicate()
	body_region.resize(SPLIT_REGION_SIZE.x, SPLIT_REGION_SIZE.y, Image.INTERPOLATE_LANCZOS)
	var page := _transparent_image(SPLIT_ATLAS_SIZE)
	page.blend_rect(body_region, Rect2i(Vector2i.ZERO, SPLIT_REGION_SIZE), SPLIT_REGION_POS)
	page.blend_rect(arc_region["image"], Rect2i(Vector2i.ZERO, SPLIT_ARC_SIZE), SPLIT_ARC_POS)
	page.blend_rect(sigil_region["image"], Rect2i(Vector2i.ZERO, SPLIT_SIGIL_SIZE), SPLIT_SIGIL_POS)
	var death_page := _transparent_image(SPLIT_DEATH_ATLAS_SIZE)
	death_page.blend_rect(
		death_region["image"],
		Rect2i(Vector2i.ZERO, SPLIT_DEATH_REGION_SIZE),
		SPLIT_DEATH_REGION_POS,
	)

	var skeleton := _build_split_skeleton()
	var atlas_data := _build_split_atlas_data()
	if not _validate_split_candidate(skeleton, atlas_data):
		return false
	if not _make_dir(output_root):
		return false
	var page_path := output_root.path_join(SPLIT_PAGE)
	var save_error := page.save_png(page_path)
	if save_error != OK:
		return _set_error("Could not save split candidate atlas (%s): %s" % [error_string(save_error), page_path])
	var death_page_path := output_root.path_join(SPLIT_DEATH_PAGE)
	var death_save_error := death_page.save_png(death_page_path)
	if death_save_error != OK:
		return _set_error("Could not save split death atlas (%s): %s" % [error_string(death_save_error), death_page_path])
	if not _write_text(output_root.path_join(SPLIT_JSON), JSON.stringify(skeleton, "  ", false) + "\n"):
		return false
	var atlas_wrapper := {
		"atlas_data": atlas_data,
		"normal_texture_prefix": "n",
		"source_path": "%s/%s" % [SPLIT_MOUNT_ROOT, SPLIT_ATLAS.replace(".spatlas", ".atlas")],
		"specular_texture_prefix": "s",
	}
	if not _write_text(output_root.path_join(SPLIT_ATLAS), JSON.stringify(atlas_wrapper, "", false) + "\n"):
		return false
	if not _write_text(output_root.path_join(SPLIT_DATA), _build_split_tres()):
		return false
	if not _write_text(output_root.path_join(SPLIT_MANIFEST), JSON.stringify(
		_build_candidate_manifest(body_path, arc_path, sigil_path, death_path, body, death), "  ", false
	) + "\n"):
		return false
	if not _validate_split_written(output_root):
		return false
	print("Built isolated split-mesh candidate (preview only; not publishable):")
	print("  output: %s" % output_root)
	print("  parts:  %d normal + %d death-preview attachments + 1 rigid landing attachment" % [SPLIT_PARTS.size(), SPLIT_PARTS.size()])
	print("  bones:  %d hierarchical bones" % skeleton["bones"].size())
	print("  source Alpha bounds: %s" % _alpha_bounds(body))
	print("  death Alpha bounds:  %s" % _alpha_bounds(death))
	print("  scene-space motion: attack=%.1fpx heavy=%.1fpx hurt=%.1fpx" % [104.0 * SPLIT_SCENE_SCALE, 164.0 * SPLIT_SCENE_SCALE, 120.0 * SPLIT_SCENE_SCALE])
	return true


func _load_native_rgba(path: String, label: String) -> Image:
	if not FileAccess.file_exists(path):
		_set_error("Required %s does not exist: %s" % [label, path])
		return Image.new()
	var image := Image.load_from_file(path)
	if image == null or image.is_empty():
		_set_error("Could not decode %s: %s" % [label, path])
		return Image.new()
	if image.get_format() != Image.FORMAT_RGBA8:
		_set_error("%s must decode directly as RGBA8: %s" % [label, path])
		return Image.new()
	if not _validate_native_alpha(image, path, label):
		return Image.new()
	return image


func _build_split_skeleton() -> Dictionary:
	var bones := _build_split_bones()
	var bone_world := _bone_world_positions()
	var slots := [{"name": "vivhite_magic_sigil", "bone": BONE_SIGIL}]
	var attachments := {
		"vivhite_magic_sigil": {SIGIL_REGION_NAME: _region_attachment(SIGIL_REGION_NAME, 1420.0, 1420.0)},
	}
	for part: Dictionary in SPLIT_PARTS:
		var part_name := str(part["name"])
		var slot_name := "part_%s" % part_name
		var death_slot_name := "death_%s" % part_name
		var normal_attachment := "vivhite_%s" % part_name
		var death_attachment := "vivhite_death_%s" % part_name
		slots.append({"name": slot_name, "bone": str(part["bone"]), "attachment": normal_attachment})
		slots.append({"name": death_slot_name, "bone": str(part["bone"])})
		attachments[slot_name] = {
			normal_attachment: _build_uv_mesh(part["rect"], str(part["bone"]), bone_world),
		}
		attachments[death_slot_name] = {
			death_attachment: _build_uv_mesh(part["rect"], str(part["bone"]), bone_world),
		}
	slots.append({"name": SPLIT_SLOT_DEATH, "bone": SPLIT_BONE_DEATH})
	attachments[SPLIT_SLOT_DEATH] = {
		SPLIT_DEATH_REGION: _region_attachment(
			SPLIT_DEATH_REGION,
			SPLIT_DEATH_WORLD_WIDTH,
			SPLIT_DEATH_WORLD_HEIGHT,
		),
	}
	slots.append({"name": "slash_mesh", "bone": BONE_ARC})
	slots.append({"name": "eye_attach_slot", "bone": BONE_EYES})
	attachments["slash_mesh"] = {
		ARC_REGION_NAME: _region_attachment(ARC_REGION_NAME, 1340.0, 900.0),
	}
	var events := {}
	for event_name: String in REQUIRED_EVENTS:
		events[event_name] = {}
	return {
		"skeleton": {
			"hash": "vivhite-split-mesh-preview-v3-hybrid-death-v2",
			"spine": SPINE_VERSION,
			"x": -900.0,
			"y": -260.0,
			"width": 3320.0,
			"height": 2340.0,
			"images": "./",
		},
		"bones": bones,
		"slots": slots,
		"skins": [{"name": "default", "attachments": attachments}],
		"events": events,
		"animations": _build_split_animations(),
	}


func _build_split_bones() -> Array:
	var world := _bone_world_positions()
	var parents := {
		BONE_ROOT: "",
		BONE_SIGIL: BONE_ROOT,
		BONE_RIG: BONE_ROOT,
		SPLIT_BONE_DEATH: BONE_ROOT,
		SPLIT_BONE_PELVIS: BONE_RIG,
		SPLIT_BONE_TORSO_LOWER: SPLIT_BONE_PELVIS,
		SPLIT_BONE_TORSO_UPPER: SPLIT_BONE_TORSO_LOWER,
		SPLIT_BONE_NECK: SPLIT_BONE_TORSO_UPPER,
		SPLIT_BONE_HEAD: SPLIT_BONE_NECK,
		"vivhite_hair_back": SPLIT_BONE_HEAD,
		"vivhite_hair_left": SPLIT_BONE_HEAD,
		"vivhite_hair_right": SPLIT_BONE_HEAD,
		"vivhite_butterfly": SPLIT_BONE_HEAD,
		"vivhite_shoulder_left": SPLIT_BONE_TORSO_UPPER,
		"vivhite_upper_arm_left": "vivhite_shoulder_left",
		"vivhite_forearm_left": "vivhite_upper_arm_left",
		"vivhite_hand_left": "vivhite_forearm_left",
		"vivhite_shoulder_right": SPLIT_BONE_TORSO_UPPER,
		"vivhite_upper_arm_right": "vivhite_shoulder_right",
		"vivhite_forearm_right": "vivhite_upper_arm_right",
		"vivhite_hand_right": "vivhite_forearm_right",
		SPLIT_BONE_SKIRT: SPLIT_BONE_PELVIS,
		"vivhite_skirt_left": SPLIT_BONE_SKIRT,
		"vivhite_skirt_right": SPLIT_BONE_SKIRT,
		"vivhite_thigh_left": SPLIT_BONE_PELVIS,
		"vivhite_knee_left": "vivhite_thigh_left",
		"vivhite_ankle_left": "vivhite_knee_left",
		"vivhite_foot_left": "vivhite_ankle_left",
		"vivhite_thigh_right": SPLIT_BONE_PELVIS,
		"vivhite_knee_right": "vivhite_thigh_right",
		"vivhite_ankle_right": "vivhite_knee_right",
		"vivhite_foot_right": "vivhite_ankle_right",
		BONE_ARC: "vivhite_hand_right",
		BONE_EYES: SPLIT_BONE_HEAD,
	}
	var primary_children := {
		SPLIT_BONE_PELVIS: SPLIT_BONE_TORSO_LOWER,
		SPLIT_BONE_TORSO_LOWER: SPLIT_BONE_TORSO_UPPER,
		SPLIT_BONE_TORSO_UPPER: SPLIT_BONE_NECK,
		SPLIT_BONE_NECK: SPLIT_BONE_HEAD,
		"vivhite_shoulder_left": "vivhite_upper_arm_left",
		"vivhite_upper_arm_left": "vivhite_forearm_left",
		"vivhite_forearm_left": "vivhite_hand_left",
		"vivhite_shoulder_right": "vivhite_upper_arm_right",
		"vivhite_upper_arm_right": "vivhite_forearm_right",
		"vivhite_forearm_right": "vivhite_hand_right",
		"vivhite_thigh_left": "vivhite_knee_left",
		"vivhite_knee_left": "vivhite_ankle_left",
		"vivhite_ankle_left": "vivhite_foot_left",
		"vivhite_thigh_right": "vivhite_knee_right",
		"vivhite_knee_right": "vivhite_ankle_right",
		"vivhite_ankle_right": "vivhite_foot_right",
	}
	var order := [
		BONE_ROOT, BONE_SIGIL, BONE_RIG, SPLIT_BONE_DEATH, SPLIT_BONE_PELVIS,
		SPLIT_BONE_TORSO_LOWER, SPLIT_BONE_TORSO_UPPER, SPLIT_BONE_NECK,
		SPLIT_BONE_HEAD, "vivhite_hair_back", "vivhite_hair_left",
		"vivhite_hair_right", "vivhite_butterfly",
		"vivhite_shoulder_left", "vivhite_upper_arm_left", "vivhite_forearm_left", "vivhite_hand_left",
		"vivhite_shoulder_right", "vivhite_upper_arm_right", "vivhite_forearm_right", "vivhite_hand_right",
		SPLIT_BONE_SKIRT, "vivhite_skirt_left", "vivhite_skirt_right",
		"vivhite_thigh_left", "vivhite_knee_left", "vivhite_ankle_left", "vivhite_foot_left",
		"vivhite_thigh_right", "vivhite_knee_right", "vivhite_ankle_right", "vivhite_foot_right",
		BONE_ARC, BONE_EYES,
	]
	var result := []
	for bone_name: String in order:
		var bone := {"name": bone_name}
		var parent_name := str(parents[bone_name])
		if not parent_name.is_empty():
			bone["parent"] = parent_name
			var local: Vector2 = world[bone_name] - world[parent_name]
			bone["x"] = local.x
			bone["y"] = local.y
		if primary_children.has(bone_name):
			bone["length"] = (world[str(primary_children[bone_name])] as Vector2).distance_to(world[bone_name])
		result.append(bone)
	return result


func _bone_world_positions() -> Dictionary:
	return {
		BONE_ROOT: Vector2.ZERO,
		BONE_SIGIL: _source_point_world(Vector2(470, 950)),
		BONE_RIG: Vector2.ZERO,
		SPLIT_BONE_DEATH: SPLIT_DEATH_FINAL_CENTER,
		SPLIT_BONE_PELVIS: _source_point_world(Vector2(700, 1110)),
		SPLIT_BONE_TORSO_LOWER: _source_point_world(Vector2(700, 820)),
		SPLIT_BONE_TORSO_UPPER: _source_point_world(Vector2(700, 590)),
		SPLIT_BONE_NECK: _source_point_world(Vector2(720, 445)),
		SPLIT_BONE_HEAD: _source_point_world(Vector2(760, 300)),
		"vivhite_hair_back": _source_point_world(Vector2(700, 230)),
		"vivhite_hair_left": _source_point_world(Vector2(570, 300)),
		"vivhite_hair_right": _source_point_world(Vector2(900, 300)),
		"vivhite_butterfly": _source_point_world(Vector2(1010, 180)),
		# The shoulder and upper-arm origins must be distinct. Keeping the upper
		# arm at the visual joint preserves attachment placement, while moving the
		# shoulder inward creates a real clavicle-to-arm bind segment.
		"vivhite_shoulder_left": _source_point_world(Vector2(550, 565)),
		"vivhite_upper_arm_left": _source_point_world(Vector2(585, 585)),
		"vivhite_forearm_left": _source_point_world(Vector2(465, 820)),
		"vivhite_hand_left": _source_point_world(Vector2(275, 1010)),
		"vivhite_shoulder_right": _source_point_world(Vector2(775, 525)),
		"vivhite_upper_arm_right": _source_point_world(Vector2(810, 545)),
		"vivhite_forearm_right": _source_point_world(Vector2(1040, 650)),
		"vivhite_hand_right": _source_point_world(Vector2(1430, 555)),
		SPLIT_BONE_SKIRT: _source_point_world(Vector2(700, 880)),
		"vivhite_skirt_left": _source_point_world(Vector2(560, 900)),
		"vivhite_skirt_right": _source_point_world(Vector2(850, 900)),
		"vivhite_thigh_left": _source_point_world(Vector2(575, 1190)),
		"vivhite_knee_left": _source_point_world(Vector2(500, 1530)),
		"vivhite_ankle_left": _source_point_world(Vector2(485, 1840)),
		"vivhite_foot_left": _source_point_world(Vector2(485, 1940)),
		"vivhite_thigh_right": _source_point_world(Vector2(790, 1190)),
		"vivhite_knee_right": _source_point_world(Vector2(880, 1580)),
		"vivhite_ankle_right": _source_point_world(Vector2(1190, 2070)),
		"vivhite_foot_right": _source_point_world(Vector2(1220, 2160)),
		BONE_ARC: _source_point_world(Vector2(1500, 530)),
		BONE_EYES: _source_point_world(Vector2(780, 300)),
	}


func _source_point_world(point: Vector2) -> Vector2:
	return Vector2(
		SPLIT_WORLD_RECT.position.x + SPLIT_WORLD_RECT.size.x * point.x / SPLIT_SOURCE_SIZE.x,
		SPLIT_WORLD_RECT.position.y + SPLIT_WORLD_RECT.size.y * (1.0 - point.y / SPLIT_SOURCE_SIZE.y)
	)


func _build_uv_mesh(source_rect: Rect2, bone_name: String, bone_world: Dictionary) -> Dictionary:
	var u0 := source_rect.position.x / SPLIT_SOURCE_SIZE.x
	var v0 := source_rect.position.y / SPLIT_SOURCE_SIZE.y
	var u1 := source_rect.end.x / SPLIT_SOURCE_SIZE.x
	var v1 := source_rect.end.y / SPLIT_SOURCE_SIZE.y
	var top_left := _source_point_world(source_rect.position) - (bone_world[bone_name] as Vector2)
	var top_right := _source_point_world(Vector2(source_rect.end.x, source_rect.position.y)) - (bone_world[bone_name] as Vector2)
	var bottom_right := _source_point_world(source_rect.end) - (bone_world[bone_name] as Vector2)
	var bottom_left := _source_point_world(Vector2(source_rect.position.x, source_rect.end.y)) - (bone_world[bone_name] as Vector2)
	return {
		"type": "mesh",
		"path": SPLIT_REGION,
		"uvs": [u0, v0, u1, v0, u1, v1, u0, v1],
		"triangles": [0, 3, 1, 1, 3, 2],
		"vertices": [
			top_left.x, top_left.y,
			top_right.x, top_right.y,
			bottom_right.x, bottom_right.y,
			bottom_left.x, bottom_left.y,
		],
		"hull": 4,
		"width": source_rect.size.x / SPLIT_SOURCE_SIZE.x * SPLIT_WORLD_RECT.size.x,
		"height": source_rect.size.y / SPLIT_SOURCE_SIZE.y * SPLIT_WORLD_RECT.size.y,
	}


func _build_split_animations() -> Dictionary:
	var animations := {
		"idle_loop": _split_loop_animation(2.0, 1.0),
		"low_health_loop": _split_low_health_animation(),
		"relaxed_loop": _split_loop_animation(12.000001, 0.75),
		"attack": _split_attack_animation(false),
		"attack_heavy": _split_attack_animation(true),
		"cast": _split_cast_animation(),
		"hurt": _split_hurt_animation(),
		"die": _split_die_animation(),
	}
	_apply_split_easing(animations)
	return animations


func _apply_split_easing(animations: Dictionary) -> void:
	for animation_name: String in animations:
		var animation: Dictionary = animations[animation_name]
		var profile := SPLIT_LOOP_EASING if animation_name.ends_with("_loop") else SPLIT_ACTION_EASING
		var bones: Dictionary = animation.get("bones", {})
		for bone_name: String in bones:
			var timelines: Dictionary = bones[bone_name]
			for timeline_name: String in ["rotate", "translate"]:
				if timelines.has(timeline_name):
					_add_split_timeline_easing(timelines[timeline_name], timeline_name, profile)


func _add_split_timeline_easing(keys: Array, timeline_name: String, profile: Vector4) -> void:
	for index in range(keys.size() - 1):
		var start: Dictionary = keys[index]
		var finish: Dictionary = keys[index + 1]
		if start.has("curve"):
			continue
		var start_time := float(start.get("time", 0.0))
		var finish_time := float(finish.get("time", 0.0))
		var control_time_1 := lerpf(start_time, finish_time, profile.x)
		var control_time_2 := lerpf(start_time, finish_time, profile.z)
		if timeline_name == "rotate":
			var start_value := float(start.get("value", 0.0))
			var finish_value := float(finish.get("value", 0.0))
			start["curve"] = [
				control_time_1,
				lerpf(start_value, finish_value, profile.y),
				control_time_2,
				lerpf(start_value, finish_value, profile.w),
			]
		else:
			var start_x := float(start.get("x", 0.0))
			var finish_x := float(finish.get("x", 0.0))
			var start_y := float(start.get("y", 0.0))
			var finish_y := float(finish.get("y", 0.0))
			start["curve"] = [
				control_time_1,
				lerpf(start_x, finish_x, profile.y),
				control_time_2,
				lerpf(start_x, finish_x, profile.w),
				control_time_1,
				lerpf(start_y, finish_y, profile.y),
				control_time_2,
				lerpf(start_y, finish_y, profile.w),
			]


func _split_loop_animation(duration: float, strength: float) -> Dictionary:
	return {"bones": {
		BONE_RIG: {"translate": _translate_loop(duration, Vector2.ZERO, Vector2(-3, 7 * strength), Vector2.ZERO, Vector2(3, -4 * strength))},
		SPLIT_BONE_TORSO_LOWER: {"rotate": _rotate_loop(duration, 0, 1.4 * strength, 0, -1.0 * strength)},
		SPLIT_BONE_TORSO_UPPER: {"rotate": _rotate_loop(duration, 0, -1.8 * strength, 0, 1.2 * strength)},
		SPLIT_BONE_HEAD: {"rotate": _rotate_loop(duration, 0, 1.2 * strength, 0, -0.8 * strength)},
		"vivhite_forearm_left": {"rotate": _rotate_loop(duration, 0, 1.1 * strength, 0, -0.7 * strength)},
		"vivhite_forearm_right": {"rotate": _rotate_loop(duration, 0, -1.3 * strength, 0, 0.8 * strength)},
		SPLIT_BONE_SKIRT: {"rotate": _rotate_loop(duration, 0, -1.0 * strength, 0, 0.8 * strength)},
		"vivhite_hair_left": {"rotate": _rotate_loop(duration, 0, 2.4 * strength, 0, -1.8 * strength)},
		"vivhite_hair_right": {"rotate": _rotate_loop(duration, 0, -2.1 * strength, 0, 1.5 * strength)},
	}}


func _split_low_health_animation() -> Dictionary:
	var duration := float(ANIMATION_DURATIONS["low_health_loop"])
	return {"bones": {
		BONE_RIG: {"translate": _translate_loop(duration, Vector2(0, -15), Vector2(-4, -24), Vector2(0, -15), Vector2(3, -21))},
		SPLIT_BONE_PELVIS: {"rotate": _rotate_loop(duration, -3, -5, -3, -4)},
		SPLIT_BONE_TORSO_LOWER: {"rotate": _rotate_loop(duration, -5, -7, -5, -6)},
		SPLIT_BONE_TORSO_UPPER: {"rotate": _rotate_loop(duration, -4, -6, -4, -5)},
		SPLIT_BONE_HEAD: {"rotate": _rotate_loop(duration, 6, 9, 6, 8)},
		"vivhite_upper_arm_left": {"rotate": _rotate_loop(duration, 8, 10, 8, 9)},
		"vivhite_upper_arm_right": {"rotate": _rotate_loop(duration, -8, -10, -8, -9)},
	}}


func _split_attack_animation(heavy: bool) -> Dictionary:
	var name := "attack_heavy" if heavy else "attack"
	var duration := float(ANIMATION_DURATIONS[name])
	var strike := float(EVENT_TIMES["heavy_slash_start" if heavy else "attack_slash_start"])
	var recover := duration * 0.72
	var lunge := 164.0 if heavy else 104.0
	var torso_turn := 23.0 if heavy else 15.0
	var upper_turn := 46.0 if heavy else 32.0
	var fore_turn := 62.0 if heavy else 43.0
	return {
		"slots": {"slash_mesh": {"attachment": [
			{"time": 0.0, "name": null},
			{"time": strike, "name": ARC_REGION_NAME},
			{"time": recover, "name": null},
		]}},
		"bones": {
			BONE_RIG: {"translate": [
				{"time": 0.0, "x": -24.0 if heavy else -16.0, "y": 0.0},
				{"time": strike, "x": lunge, "y": 28.0 if heavy else 18.0},
				{"time": recover, "x": 18.0, "y": 4.0},
				{"time": duration, "x": 0.0, "y": 0.0},
			]},
			SPLIT_BONE_PELVIS: {"rotate": _action_rotate(duration, -8.0, torso_turn * 0.48, strike, recover)},
			SPLIT_BONE_TORSO_LOWER: {"rotate": _action_rotate(duration, -12.0, torso_turn, strike, recover)},
			SPLIT_BONE_TORSO_UPPER: {"rotate": _action_rotate(duration, -10.0, torso_turn, strike, recover)},
			"vivhite_upper_arm_right": {"rotate": _action_rotate(duration, -28.0, upper_turn, strike, recover)},
			"vivhite_forearm_right": {"rotate": _action_rotate(duration, -35.0, fore_turn, strike, recover)},
			"vivhite_hand_right": {"rotate": _action_rotate(duration, -18.0, 28.0 if heavy else 20.0, strike, recover)},
			"vivhite_upper_arm_left": {"rotate": _action_rotate(duration, 12.0, -18.0 if heavy else -12.0, strike, recover)},
			"vivhite_thigh_left": {"rotate": _action_rotate(duration, 5.0, -8.0, strike, recover)},
			"vivhite_thigh_right": {"rotate": _action_rotate(duration, -5.0, 8.0, strike, recover)},
			BONE_ARC: {"rotate": _action_rotate(duration, -24.0, 38.0 if heavy else 30.0, strike, recover)},
		},
		"events": [
			{"time": strike, "name": "heavy_slash_start" if heavy else "attack_slash_start"},
			{"time": recover, "name": "clear_vfx"},
		],
	}


func _split_cast_animation() -> Dictionary:
	var duration := float(ANIMATION_DURATIONS["cast"])
	var start := float(EVENT_TIMES["cast_eyes_start"])
	var clear := duration * 0.78
	return {
		"slots": {"vivhite_magic_sigil": {"attachment": [
			{"time": 0.0, "name": null},
			{"time": 0.10, "name": SIGIL_REGION_NAME},
			{"time": clear, "name": null},
		]}},
		"bones": {
			BONE_RIG: {"translate": [
				{"time": 0.0, "x": 0.0, "y": 0.0},
				{"time": start, "x": 8.0, "y": 32.0},
				{"time": clear, "x": 2.0, "y": 12.0},
				{"time": duration, "x": 0.0, "y": 0.0},
			]},
			SPLIT_BONE_TORSO_UPPER: {"rotate": _action_rotate(duration, -4.0, 9.0, start, clear)},
			SPLIT_BONE_HEAD: {"rotate": _action_rotate(duration, 2.0, -7.0, start, clear)},
			"vivhite_upper_arm_left": {"rotate": _action_rotate(duration, 12.0, -35.0, start, clear)},
			"vivhite_forearm_left": {"rotate": _action_rotate(duration, 14.0, -48.0, start, clear)},
			"vivhite_hand_left": {"rotate": _action_rotate(duration, 6.0, -20.0, start, clear)},
			"vivhite_upper_arm_right": {"rotate": _action_rotate(duration, -12.0, 32.0, start, clear)},
			"vivhite_forearm_right": {"rotate": _action_rotate(duration, -15.0, 44.0, start, clear)},
			"vivhite_hand_right": {"rotate": _action_rotate(duration, -8.0, 22.0, start, clear)},
			BONE_SIGIL: {"rotate": [
				{"time": 0.0, "value": -10.0},
				{"time": clear, "value": 22.0},
				{"time": duration, "value": -10.0},
			]},
		},
		"events": [
			{"time": start, "name": "cast_eyes_start"},
			{"time": clear, "name": "clear_vfx"},
		],
	}


func _split_hurt_animation() -> Dictionary:
	var duration := float(ANIMATION_DURATIONS["hurt"])
	return {"bones": {
		BONE_RIG: {"translate": [
			{"time": 0.0, "x": 0.0, "y": 0.0},
			{"time": 0.14, "x": -120.0, "y": -18.0},
			{"time": 0.52, "x": 28.0, "y": 5.0},
			{"time": duration, "x": 0.0, "y": 0.0},
		]},
		SPLIT_BONE_PELVIS: {"rotate": _action_rotate(duration, 0.0, -10.0, 0.14, 0.52)},
		SPLIT_BONE_TORSO_LOWER: {"rotate": _action_rotate(duration, 0.0, -16.0, 0.14, 0.52)},
		SPLIT_BONE_TORSO_UPPER: {"rotate": _action_rotate(duration, 0.0, -13.0, 0.14, 0.52)},
		SPLIT_BONE_HEAD: {"rotate": _action_rotate(duration, 0.0, 16.0, 0.14, 0.52)},
		"vivhite_upper_arm_left": {"rotate": _action_rotate(duration, 0.0, 18.0, 0.14, 0.52)},
		"vivhite_forearm_right": {"rotate": _action_rotate(duration, 0.0, -22.0, 0.14, 0.52)},
	}, "events": [{"time": 0.72, "name": "clear_vfx"}]}


func _split_die_animation() -> Dictionary:
	var duration := float(ANIMATION_DURATIONS["die"])
	var slot_timelines := {}
	for part: Dictionary in SPLIT_PARTS:
		var part_name := str(part["name"])
		slot_timelines["part_%s" % part_name] = {"attachment": [{"time": 0.0, "name": null}]}
		slot_timelines["death_%s" % part_name] = {
			"attachment": [
				{"time": 0.0, "name": "vivhite_death_%s" % part_name},
				{"time": SPLIT_DEATH_SWAP_TIME, "name": null},
			],
		}
	slot_timelines[SPLIT_SLOT_DEATH] = {
		"attachment": [
			{"time": 0.0, "name": null},
			{"time": SPLIT_DEATH_SWAP_TIME, "name": SPLIT_DEATH_REGION},
		],
	}
	return {
		"slots": slot_timelines,
		"bones": {
			# Root translation establishes landing position; it does not rotate the
			# whole standing card. Collapse comes from the chained joints below.
			BONE_RIG: {
				"translate": [
					{"time": 0.0, "x": 0.0, "y": 0.0},
					{"time": 0.34, "x": -16.0, "y": -22.0},
					{"time": 0.92, "x": 54.0, "y": -105.0},
					{"time": 1.58, "x": 155.0, "y": -178.0},
					{"time": 1.92, "x": 168.0, "y": -170.0},
					{"time": duration, "x": 164.0, "y": -174.0},
				],
				"rotate": [
					{"time": 0.0, "value": 0.0},
					{"time": 0.92, "value": -4.0},
					{"time": duration, "value": -7.0},
				],
			},
			SPLIT_BONE_PELVIS: {"rotate": _staggered_terminal(duration, 0.18, -7.0, 0.90, -34.0, -42.0)},
			SPLIT_BONE_TORSO_LOWER: {"rotate": _staggered_terminal(duration, 0.26, -6.0, 1.02, -38.0, -55.0)},
			SPLIT_BONE_TORSO_UPPER: {"rotate": _staggered_terminal(duration, 0.32, 8.0, 1.12, -31.0, -46.0)},
			SPLIT_BONE_HEAD: {"rotate": _staggered_terminal(duration, 0.40, 12.0, 1.28, 33.0, 26.0)},
			"vivhite_upper_arm_left": {"rotate": _staggered_terminal(duration, 0.20, 14.0, 0.98, 58.0, 71.0)},
			"vivhite_forearm_left": {"rotate": _staggered_terminal(duration, 0.36, -9.0, 1.18, 42.0, 55.0)},
			"vivhite_hand_left": {"rotate": _staggered_terminal(duration, 0.48, 5.0, 1.38, 31.0, 24.0)},
			"vivhite_upper_arm_right": {"rotate": _staggered_terminal(duration, 0.24, -13.0, 1.04, -62.0, -77.0)},
			"vivhite_forearm_right": {"rotate": _staggered_terminal(duration, 0.42, 11.0, 1.24, -39.0, -54.0)},
			"vivhite_hand_right": {"rotate": _staggered_terminal(duration, 0.52, -7.0, 1.42, -28.0, -21.0)},
			"vivhite_thigh_left": {"rotate": _staggered_terminal(duration, 0.16, 8.0, 0.74, 47.0, 58.0)},
			"vivhite_knee_left": {"rotate": _staggered_terminal(duration, 0.30, -12.0, 0.92, -74.0, -88.0)},
			"vivhite_ankle_left": {"rotate": _staggered_terminal(duration, 0.58, 4.0, 1.20, 21.0, 15.0)},
			"vivhite_thigh_right": {"rotate": _staggered_terminal(duration, 0.22, -7.0, 0.82, -42.0, -51.0)},
			"vivhite_knee_right": {"rotate": _staggered_terminal(duration, 0.38, 15.0, 1.02, 69.0, 82.0)},
			"vivhite_ankle_right": {"rotate": _staggered_terminal(duration, 0.62, -5.0, 1.28, -18.0, -12.0)},
			"vivhite_hair_left": {"rotate": _staggered_terminal(duration, 0.44, 8.0, 1.34, 43.0, 35.0)},
			"vivhite_hair_right": {"rotate": _staggered_terminal(duration, 0.50, -9.0, 1.40, -39.0, -32.0)},
			SPLIT_BONE_SKIRT: {"rotate": _staggered_terminal(duration, 0.34, 5.0, 1.18, 24.0, 18.0)},
			# The side-collapse drawing is rigid by design. It enters while the
			# articulated preview reaches the landing phase. The atomic attachment
			# swap avoids a double-image ghost; this rigid art then falls for 120 ms,
			# rebounds once, and becomes perfectly still.
			SPLIT_BONE_DEATH: {"translate": [
				{"time": 0.0, "x": -32.0, "y": 356.8},
				{"time": 0.82, "x": -32.0, "y": 356.8},
				{"time": SPLIT_DEATH_SWAP_TIME, "x": -18.0, "y": SPLIT_DEATH_ENTRY_OFFSET_Y},
				{"time": SPLIT_DEATH_IMPACT_TIME, "x": 0.0, "y": 0.0},
				{"time": 1.31, "x": 7.0, "y": 11.0},
				{"time": 1.53, "x": 1.5, "y": 2.5},
				{"time": 1.80, "x": 0.0, "y": 0.0},
				{"time": duration, "x": 0.0, "y": 0.0},
			]},
		},
		"events": [{"time": 0.0, "name": "clear_vfx"}],
	}


func _staggered_terminal(duration: float, early_time: float, early: float, impact_time: float, impact: float, settle: float) -> Array:
	return [
		{"time": 0.0, "value": 0.0},
		{"time": early_time, "value": early},
		{"time": impact_time, "value": impact},
		{"time": minf(duration, impact_time + 0.28), "value": settle + (4.0 if settle < 0.0 else -4.0)},
		{"time": duration, "value": settle},
	]


func _build_split_atlas_data() -> String:
	return "\n".join(PackedStringArray([
		SPLIT_PAGE,
		"size:%d,%d" % [SPLIT_ATLAS_SIZE.x, SPLIT_ATLAS_SIZE.y],
		"filter:Linear,Linear",
		"pma:false",
		"repeat:none",
		SPLIT_REGION,
		"bounds:%d,%d,%d,%d" % [SPLIT_REGION_POS.x, SPLIT_REGION_POS.y, SPLIT_REGION_SIZE.x, SPLIT_REGION_SIZE.y],
		ARC_REGION_NAME,
		"bounds:%d,%d,%d,%d" % [SPLIT_ARC_POS.x, SPLIT_ARC_POS.y, SPLIT_ARC_SIZE.x, SPLIT_ARC_SIZE.y],
		SIGIL_REGION_NAME,
		"bounds:%d,%d,%d,%d" % [SPLIT_SIGIL_POS.x, SPLIT_SIGIL_POS.y, SPLIT_SIGIL_SIZE.x, SPLIT_SIGIL_SIZE.y],
		"",
		SPLIT_DEATH_PAGE,
		"size:%d,%d" % [SPLIT_DEATH_ATLAS_SIZE.x, SPLIT_DEATH_ATLAS_SIZE.y],
		"filter:Linear,Linear",
		"pma:false",
		"repeat:none",
		SPLIT_DEATH_REGION,
		"bounds:%d,%d,%d,%d" % [
			SPLIT_DEATH_REGION_POS.x,
			SPLIT_DEATH_REGION_POS.y,
			SPLIT_DEATH_REGION_SIZE.x,
			SPLIT_DEATH_REGION_SIZE.y,
		],
	])) + "\n"


func _build_split_tres() -> String:
	var lines := PackedStringArray([
		"[gd_resource type=\"SpineSkeletonDataResource\" load_steps=13 format=3]",
		"",
		"[ext_resource type=\"SpineAtlasResource\" path=\"%s/%s\" id=\"1_atlas\"]" % [SPLIT_MOUNT_ROOT, SPLIT_ATLAS],
		"[ext_resource type=\"SpineSkeletonFileResource\" path=\"%s/%s\" id=\"2_skeleton\"]" % [SPLIT_MOUNT_ROOT, SPLIT_JSON],
	])
	var mix_ids := PackedStringArray()
	for contract: Dictionary in SPLIT_ANIMATION_MIXES:
		var mix_id := str(contract["id"])
		mix_ids.append("SubResource(\"%s\")" % mix_id)
		lines.append("")
		lines.append("[sub_resource type=\"SpineAnimationMix\" id=\"%s\"]" % mix_id)
		lines.append("from = \"%s\"" % contract["from"])
		lines.append("to = \"%s\"" % contract["to"])
		var mix := float(contract["mix"])
		if not is_zero_approx(mix):
			lines.append("mix = %s" % str(mix))
	lines.append("")
	lines.append("[resource]")
	lines.append("atlas_res = ExtResource(\"1_atlas\")")
	lines.append("skeleton_file_res = ExtResource(\"2_skeleton\")")
	lines.append("default_mix = 0.05")
	lines.append("animation_mixes = [%s]" % ", ".join(mix_ids))
	return "\n".join(lines) + "\n"


func _build_candidate_manifest(
	body_path: String,
	arc_path: String,
	sigil_path: String,
	death_path: String,
	body: Image,
	death: Image,
) -> Dictionary:
	var part_contract := []
	for part: Dictionary in SPLIT_PARTS:
		var rect: Rect2 = part["rect"]
		part_contract.append({
			"id": part["name"],
			"bone": part["bone"],
			"normal_slot": "part_%s" % part["name"],
			"death_slot": "death_%s" % part["name"],
			"preview_source_rect_px": [rect.position.x, rect.position.y, rect.size.x, rect.size.y],
			"publishable_art_status": "requires_independent_evolink_redraw",
		})
	var bounds := _alpha_bounds(body)
	var death_bounds := _alpha_bounds(death)
	return {
		"schema": 1,
		"name": "split_mesh",
		"label": "拆件 + 层级骨链 + 整图落地（离线 Hybrid 候选）",
		"status": "preview_only_not_publishable",
		"mount_path": SPLIT_MOUNT_ROOT,
		"resource": SPLIT_DATA,
		"scene_scale_contract": SPLIT_SCENE_SCALE,
		"files": [SPLIT_JSON, SPLIT_ATLAS, SPLIT_PAGE, SPLIT_DEATH_PAGE, SPLIT_DATA],
		"source_contract": {
			"body_classification": "single_full_body_single_frame_rgba_not_a_sprite_sheet",
			"body": _repo_relative(body_path),
			"body_canvas_px": [body.get_width(), body.get_height()],
			"body_alpha_bounds_px": [bounds.position.x, bounds.position.y, bounds.size.x, bounds.size.y],
			"death_classification": "single_full_body_side_collapse_single_frame_rgba_not_a_sprite_sheet",
			"death": _repo_relative(death_path),
			"death_canvas_px": [death.get_width(), death.get_height()],
			"death_alpha_bounds_px": [
				death_bounds.position.x,
				death_bounds.position.y,
				death_bounds.size.x,
				death_bounds.size.y,
			],
			"arc": _repo_relative(arc_path),
			"sigil": _repo_relative(sigil_path),
		},
		"consumer_contract_evidence": [
			"Vivhite/VivhiteCode/Characters/IroncladReplacementAssets.cs",
			"Vivhite/Vivhite/skins/ironclad/scenes/combat.tscn",
			".work/ironclad-v0.111.0/combat/scene.tscn",
		],
		"required_animations": ANIMATION_DURATIONS.keys(),
		"required_slots": REQUIRED_SLOTS,
		"required_events": REQUIRED_EVENTS,
		"transition_mix_contract": {
			"source": ".work/ironclad-v0.111.0/combat/combat_skeleton_data.tres",
			"default_mix": 0.05,
			"overrides": SPLIT_ANIMATION_MIXES,
		},
		"animation_curve_contract": {
			"format": "Spine 4.2 absolute Bezier handles; rotate=4 values, translate=8 values",
			"loop_profile_normalized": [SPLIT_LOOP_EASING.x, SPLIT_LOOP_EASING.y, SPLIT_LOOP_EASING.z, SPLIT_LOOP_EASING.w],
			"action_profile_normalized": [SPLIT_ACTION_EASING.x, SPLIT_ACTION_EASING.y, SPLIT_ACTION_EASING.z, SPLIT_ACTION_EASING.w],
		},
		"motion_at_scene_scale_px": {
			"attack_root_lunge": 104.0 * SPLIT_SCENE_SCALE,
			"attack_heavy_root_lunge": 164.0 * SPLIT_SCENE_SCALE,
			"hurt_root_recoil": 120.0 * SPLIT_SCENE_SCALE,
		},
		"part_contract": part_contract,
		"required_evolink_redraws": SPLIT_REQUIRED_REDRAWS,
		"death_contract": {
			"dedicated_slot_prefix": "death_",
			"dedicated_attachment_prefix": "vivhite_death_",
			"preview_parts_use_same_unmodified_standing_master_uvs": true,
			"landing_slot": SPLIT_SLOT_DEATH,
			"landing_bone": SPLIT_BONE_DEATH,
			"landing_attachment": SPLIT_DEATH_REGION,
			"landing_source": _repo_relative(death_path),
			"landing_mode": "one rigid full-body side-collapse attachment on isolated atlas page",
			"publishable_version_requires_independent_death_art": false,
			"clear_vfx_time": 0.0,
			"atomic_swap_time": SPLIT_DEATH_SWAP_TIME,
			"impact_time": SPLIT_DEATH_IMPACT_TIME,
			"settle_end": 1.80,
			"animation_end": ANIMATION_DURATIONS["die"],
			"collapse_method": "staggered pelvis/torso/head/arm/hip/knee/ankle chains before landing; root rotation capped at 7 degrees; atomic rigid side-collapse swap, 120 ms fall, one rebound, then still",
		},
		"known_preview_artifacts": [
			"The source has a whole-body semi-transparent halo crossing every joint cut.",
			"Flattened joints have no hidden pixels; large rotations expose seams or duplicated overlap bands.",
			"Head, front hair, rear hair and butterfly remain one temporary attachment.",
			"The death-preview parts atomically disappear at landing so no split/whole double-image ghost remains; the accepted v2 side-collapse source owns the final silhouette.",
			"Preview candidate defect: die@1.04 remains a near-vertical curled silhouette (alpha bbox 237,445,242,250), while die@1.05 is the horizontal landing art (176,464,332,174). The atomic frame therefore jumps 61 px left, expands 90 px in width and loses 76 px in height. It fixes empty/double-image frames but not pose continuity, so this candidate must not be treated as final animation quality, published, or connected to the runtime skin.",
		],
		"safety": {
			"evolink_paid_calls": 0,
			"alpha_creation_threshold_mask_or_cleanup": false,
			"allowed_full_image_resize_resampled_pixels": true,
			"runtime_skin_modified": false,
			"deployable": false,
		},
	}


func _repo_relative(path: String) -> String:
	var repo := ProjectSettings.globalize_path("res://").path_join("../..").simplify_path().replace("\\", "/")
	var normalized := path.simplify_path().replace("\\", "/")
	if normalized.begins_with(repo + "/"):
		return normalized.trim_prefix(repo + "/")
	return normalized


func _validate_split_candidate(skeleton: Dictionary, atlas_data: String) -> bool:
	if str(skeleton["skeleton"].get("spine", "")) != SPINE_VERSION:
		return _set_error("Split candidate must target Spine %s" % SPINE_VERSION)
	if skeleton["skins"].size() != 1 or skeleton["skins"][0]["name"] != "default":
		return _set_error("Split candidate must have exactly one default skin")
	var bones := {}
	for bone: Dictionary in skeleton["bones"]:
		bones[str(bone["name"])] = bone
	var expected_parents := {
		"vivhite_shoulder_left": SPLIT_BONE_TORSO_UPPER,
		"vivhite_upper_arm_left": "vivhite_shoulder_left",
		"vivhite_forearm_left": "vivhite_upper_arm_left",
		"vivhite_hand_left": "vivhite_forearm_left",
		"vivhite_shoulder_right": SPLIT_BONE_TORSO_UPPER,
		"vivhite_upper_arm_right": "vivhite_shoulder_right",
		"vivhite_forearm_right": "vivhite_upper_arm_right",
		"vivhite_hand_right": "vivhite_forearm_right",
		"vivhite_knee_left": "vivhite_thigh_left",
		"vivhite_ankle_left": "vivhite_knee_left",
		"vivhite_foot_left": "vivhite_ankle_left",
		"vivhite_knee_right": "vivhite_thigh_right",
		"vivhite_ankle_right": "vivhite_knee_right",
		"vivhite_foot_right": "vivhite_ankle_right",
	}
	for bone_name: String in expected_parents:
		if not bones.has(bone_name) or str(bones[bone_name].get("parent", "")) != expected_parents[bone_name]:
			return _set_error("Hierarchical chain mismatch for %s" % bone_name)
	for side: String in ["left", "right"]:
		var shoulder_name := "vivhite_shoulder_%s" % side
		var upper_arm_name := "vivhite_upper_arm_%s" % side
		var upper_arm: Dictionary = bones[upper_arm_name]
		var bind_offset := Vector2(float(upper_arm.get("x", 0.0)), float(upper_arm.get("y", 0.0)))
		if bind_offset.length() < 1.0:
			return _set_error("%s -> %s bind segment must be non-zero" % [shoulder_name, upper_arm_name])
		if float(bones[shoulder_name].get("length", 0.0)) < 1.0:
			return _set_error("%s must declare a visible non-zero bind length" % shoulder_name)
	var slots := {}
	for slot: Dictionary in skeleton["slots"]:
		slots[str(slot["name"])] = str(slot["bone"])
	for required: String in REQUIRED_SLOTS:
		if not slots.has(required):
			return _set_error("Split candidate is missing required slot %s" % required)
	for part: Dictionary in SPLIT_PARTS:
		for prefix: String in ["part_", "death_"]:
			if not slots.has(prefix + str(part["name"])):
				return _set_error("Split candidate is missing %s%s" % [prefix, part["name"]])
	if str(slots.get(SPLIT_SLOT_DEATH, "<missing>")) != SPLIT_BONE_DEATH:
		return _set_error("Hybrid side-collapse slot must be bound to the isolated death-pose bone")
	var bone_names := {}
	for bone: Dictionary in skeleton["bones"]:
		bone_names[str(bone["name"])] = true
	if not bone_names.has(SPLIT_BONE_DEATH):
		return _set_error("Hybrid side-collapse bone is missing")
	var default_attachments: Dictionary = skeleton["skins"][0]["attachments"]
	var landing_attachments: Dictionary = default_attachments.get(SPLIT_SLOT_DEATH, {})
	if landing_attachments.size() != 1 or not landing_attachments.has(SPLIT_DEATH_REGION):
		return _set_error("Hybrid candidate must contain exactly one rigid side-collapse attachment")
	if str(landing_attachments[SPLIT_DEATH_REGION].get("type", "region")) != "region":
		return _set_error("Hybrid side-collapse attachment must remain a rigid region")
	for required: String in REQUIRED_EVENTS:
		if not skeleton["events"].has(required):
			return _set_error("Split candidate is missing required event %s" % required)
	if skeleton["animations"].size() != ANIMATION_DURATIONS.size():
		return _set_error("Split candidate must contain exactly eight animations")
	for animation_name: String in ANIMATION_DURATIONS:
		if not skeleton["animations"].has(animation_name):
			return _set_error("Split candidate is missing animation %s" % animation_name)
		var actual := _max_timeline_time(skeleton["animations"][animation_name])
		if absf(actual - float(ANIMATION_DURATIONS[animation_name])) > 0.00001:
			return _set_error("Animation %s duration is %.7f, expected %.7f" % [animation_name, actual, ANIMATION_DURATIONS[animation_name]])
	if not _validate_split_easing(skeleton):
		return false
	if not _validate_event_time(skeleton["animations"]["attack"], "attack_slash_start", EVENT_TIMES["attack_slash_start"]):
		return false
	if not _validate_event_time(skeleton["animations"]["attack_heavy"], "heavy_slash_start", EVENT_TIMES["heavy_slash_start"]):
		return false
	if not _validate_event_time(skeleton["animations"]["cast"], "cast_eyes_start", EVENT_TIMES["cast_eyes_start"]):
		return false
	if not _validate_event_time(skeleton["animations"]["die"], "clear_vfx", 0.0):
		return false
	if not _validate_split_hybrid_death(skeleton):
		return false
	var die_root_rotate: Array = skeleton["animations"]["die"]["bones"][BONE_RIG]["rotate"]
	for key: Dictionary in die_root_rotate:
		if absf(float(key.get("value", 0.0))) > 7.00001:
			return _set_error("Death candidate may not rotate the whole rig beyond seven degrees")
	for region_name: String in [SPLIT_REGION, ARC_REGION_NAME, SIGIL_REGION_NAME, SPLIT_DEATH_REGION]:
		if atlas_data.count("%s\n" % region_name) != 1:
			return _set_error("Split atlas must declare exactly one %s region" % region_name)
	if atlas_data.count("%s\n" % SPLIT_PAGE) != 1 or atlas_data.count("%s\n" % SPLIT_DEATH_PAGE) != 1:
		return _set_error("Split hybrid atlas must declare each of its two pages exactly once")
	return true


func _validate_split_hybrid_death(skeleton: Dictionary) -> bool:
	for animation_name: String in ANIMATION_DURATIONS:
		if animation_name == "die":
			continue
		var animation_slots: Dictionary = skeleton["animations"][animation_name].get("slots", {})
		if animation_slots.has(SPLIT_SLOT_DEATH):
			return _set_error("Only die may drive the hybrid side-collapse slot; found %s" % animation_name)

	var die: Dictionary = skeleton["animations"]["die"]
	var timelines: Dictionary = die.get("slots", {})
	if not timelines.has(SPLIT_SLOT_DEATH):
		return _set_error("die must drive the hybrid side-collapse slot")
	for part: Dictionary in SPLIT_PARTS:
		if not _validate_split_death_part_timelines(timelines, str(part["name"])):
			return false

	var landing: Dictionary = timelines[SPLIT_SLOT_DEATH]
	var landing_attachments: Array = landing.get("attachment", [])
	if (
		landing_attachments.size() != 2
		or landing_attachments[0].get("name", "sentinel") != null
		or absf(float(landing_attachments[1].get("time", -1.0)) - SPLIT_DEATH_SWAP_TIME) > 0.00001
		or str(landing_attachments[1].get("name", "")) != SPLIT_DEATH_REGION
	):
		return _set_error("die must atomically attach the side-collapse art at the hybrid swap time")
	if landing.has("rgba"):
		return _set_error("Hybrid death uses an atomic attachment swap; the landing slot may not crossfade")

	var settle: Array = die["bones"][SPLIT_BONE_DEATH].get("translate", [])
	if settle.size() < 8:
		return _set_error("Hybrid landing must contain entry, impact, rebound, settle and hold poses")
	var death_setup_y := NAN
	for bone: Dictionary in skeleton["bones"]:
		if str(bone["name"]) == SPLIT_BONE_DEATH:
			death_setup_y = float(bone.get("y", 0.0))
			break
	if (
		is_nan(death_setup_y)
		or absf(death_setup_y - SPLIT_DEATH_FINAL_CENTER.y) > 0.00001
		or absf((SPLIT_DEATH_ALPHA_EDGE_CENTER_Y - death_setup_y) - SPLIT_DEATH_SOLID_CONTACT_SHIFT) > 0.00001
	):
		return _set_error("Hybrid death-pose setup y must retain the v2 solid-contact calibration")
	var entry_y := NAN
	var impact_y := NAN
	for key: Dictionary in settle:
		var key_time := float(key.get("time", 0.0))
		if absf(key_time - SPLIT_DEATH_SWAP_TIME) <= 0.00001:
			entry_y = float(key.get("y", 0.0))
		if absf(key_time - SPLIT_DEATH_IMPACT_TIME) <= 0.00001:
			impact_y = float(key.get("y", 0.0))
	if (
		is_nan(entry_y) or is_nan(impact_y)
		or absf(entry_y - SPLIT_DEATH_ENTRY_OFFSET_Y) > 0.00001
		or absf(SPLIT_DEATH_FINAL_CENTER.y + entry_y - SPLIT_DEATH_ENTRY_WORLD_Y) > 0.00001
		or absf(impact_y) > 0.00001
	):
		return _set_error("Hybrid death landing must preserve the calibrated entry and impact endpoints")
	var hold_start: Dictionary = settle[settle.size() - 2]
	var hold_end: Dictionary = settle[settle.size() - 1]
	if (
		absf(float(hold_start.get("time", -1.0)) - 1.80) > 0.00001
		or absf(float(hold_start.get("x", INF))) > 0.00001
		or absf(float(hold_start.get("y", INF))) > 0.00001
		or absf(float(hold_end.get("time", -1.0)) - float(ANIMATION_DURATIONS["die"])) > 0.00001
		or absf(float(hold_end.get("x", INF))) > 0.00001
		or absf(float(hold_end.get("y", INF))) > 0.00001
	):
		return _set_error("Hybrid landing must be motionless from 1.80 seconds through the die endpoint")
	return true


func _validate_split_death_part_timelines(timelines: Dictionary, part_name: String) -> bool:
	var normal_slot := "part_%s" % part_name
	var preview_slot := "death_%s" % part_name
	if not timelines.has(normal_slot) or not timelines.has(preview_slot):
		return _set_error("die must drive both normal and death-preview slot for %s" % part_name)
	var normal_attachments: Array = timelines[normal_slot].get("attachment", [])
	if (
		normal_attachments.size() != 1
		or absf(float(normal_attachments[0].get("time", -1.0))) > 0.00001
		or normal_attachments[0].get("name", "sentinel") != null
	):
		return _set_error("die must hide normal part %s at time zero" % part_name)
	var preview: Dictionary = timelines[preview_slot]
	var preview_attachments: Array = preview.get("attachment", [])
	if (
		preview_attachments.size() != 2
		or str(preview_attachments[0].get("name", "")) != "vivhite_death_%s" % part_name
		or absf(float(preview_attachments[1].get("time", -1.0)) - SPLIT_DEATH_SWAP_TIME) > 0.00001
		or preview_attachments[1].get("name", "sentinel") != null
	):
		return _set_error("Death-preview part %s must detach at the atomic hybrid swap" % part_name)
	if preview.has("rgba"):
		return _set_error("Death-preview part %s may not remain as a crossfade ghost" % part_name)
	return true


func _validate_split_easing(skeleton: Dictionary) -> bool:
	var eased_segments := 0
	for animation_name: String in ANIMATION_DURATIONS:
		var bones: Dictionary = skeleton["animations"][animation_name].get("bones", {})
		for bone_name: String in bones:
			var timelines: Dictionary = bones[bone_name]
			for timeline_name: String in ["rotate", "translate"]:
				if not timelines.has(timeline_name):
					continue
				var frames: Array = timelines[timeline_name]
				for index in range(frames.size() - 1):
					var frame: Dictionary = frames[index]
					var finish: Dictionary = frames[index + 1]
					if not frame.has("curve") or not frame["curve"] is Array:
						return _set_error("%s/%s/%s frame %d is missing easing" % [animation_name, bone_name, timeline_name, index])
					var curve: Array = frame["curve"]
					var expected_size := 4 if timeline_name == "rotate" else 8
					if curve.size() != expected_size:
						return _set_error("%s/%s/%s frame %d curve has %d values, expected %d" % [animation_name, bone_name, timeline_name, index, curve.size(), expected_size])
					var start_time := float(frame.get("time", 0.0))
					var finish_time := float(finish.get("time", 0.0))
					var time_indices: Array = [0, 2] if timeline_name == "rotate" else [0, 2, 4, 6]
					for time_index: int in time_indices:
						var control_time := float(curve[time_index])
						if control_time < start_time or control_time > finish_time:
							return _set_error("%s/%s/%s frame %d has an out-of-segment Bezier handle" % [animation_name, bone_name, timeline_name, index])
					eased_segments += 1
	if eased_segments == 0:
		return _set_error("Split candidate must contain eased bone timeline segments")
	return true


func _validate_split_tres(tres_text: String) -> bool:
	if not tres_text.begins_with("[gd_resource type=\"SpineSkeletonDataResource\" load_steps=13 format=3]"):
		return _set_error("Split skeleton-data resource must declare 13 load steps")
	if tres_text.count("[sub_resource type=\"SpineAnimationMix\"") != SPLIT_ANIMATION_MIXES.size():
		return _set_error("Split skeleton-data resource must contain the ten vanilla transition mixes")
	var expected_refs := PackedStringArray()
	for contract: Dictionary in SPLIT_ANIMATION_MIXES:
		var mix_id := str(contract["id"])
		expected_refs.append("SubResource(\"%s\")" % mix_id)
		var header := "[sub_resource type=\"SpineAnimationMix\" id=\"%s\"]" % mix_id
		var block_start := tres_text.find(header)
		if block_start < 0:
			return _set_error("Split skeleton-data resource is missing mix resource %s" % mix_id)
		var block_end := tres_text.find("\n[sub_resource", block_start + header.length())
		if block_end < 0:
			block_end = tres_text.find("\n[resource]", block_start + header.length())
		var actual_block := tres_text.substr(block_start, block_end - block_start)
		var block := "%s\nfrom = \"%s\"\nto = \"%s\"" % [header, contract["from"], contract["to"]]
		var mix := float(contract["mix"])
		if not is_zero_approx(mix):
			block += "\nmix = %s" % str(mix)
		elif actual_block.contains("\nmix ="):
			return _set_error("Split transition %s -> %s must retain vanilla's implicit zero mix" % [contract["from"], contract["to"]])
		if not actual_block.contains(block):
			return _set_error("Split skeleton-data resource is missing exact transition %s -> %s" % [contract["from"], contract["to"]])
	var refs_line := "animation_mixes = [%s]" % ", ".join(expected_refs)
	if not tres_text.contains("default_mix = 0.05") or not tres_text.contains(refs_line):
		return _set_error("Split skeleton-data resource mix list/default mix is incomplete")
	return true


func _validate_split_written(output_root: String) -> bool:
	var page := Image.load_from_file(output_root.path_join(SPLIT_PAGE))
	if page == null or page.is_empty() or page.get_size() != SPLIT_ATLAS_SIZE or page.get_format() != Image.FORMAT_RGBA8:
		return _set_error("Written split atlas is not 3072x2304 RGBA8")
	var death_page := Image.load_from_file(output_root.path_join(SPLIT_DEATH_PAGE))
	if (
		death_page == null or death_page.is_empty()
		or death_page.get_size() != SPLIT_DEATH_ATLAS_SIZE
		or death_page.get_format() != Image.FORMAT_RGBA8
	):
		return _set_error("Written split death atlas is not 2048x1536 RGBA8")
	var skeleton = JSON.parse_string(FileAccess.get_file_as_string(output_root.path_join(SPLIT_JSON)))
	var atlas = JSON.parse_string(FileAccess.get_file_as_string(output_root.path_join(SPLIT_ATLAS)))
	var manifest = JSON.parse_string(FileAccess.get_file_as_string(output_root.path_join(SPLIT_MANIFEST)))
	if not skeleton is Dictionary or not atlas is Dictionary or not manifest is Dictionary:
		return _set_error("Written split candidate JSON could not be parsed")
	if str(manifest.get("status", "")) != "preview_only_not_publishable":
		return _set_error("Split candidate must remain explicitly non-publishable")
	if bool(manifest["safety"].get("runtime_skin_modified", true)):
		return _set_error("Split candidate safety manifest incorrectly claims a runtime modification")
	var expected_files := [SPLIT_JSON, SPLIT_ATLAS, SPLIT_PAGE, SPLIT_DEATH_PAGE, SPLIT_DATA]
	if manifest.get("files", []) != expected_files:
		return _set_error("Split hybrid manifest must list the exact five candidate artifacts")
	if not _validate_split_tres(FileAccess.get_file_as_string(output_root.path_join(SPLIT_DATA))):
		return false
	return _validate_split_candidate(skeleton, str(atlas.get("atlas_data", "")))
