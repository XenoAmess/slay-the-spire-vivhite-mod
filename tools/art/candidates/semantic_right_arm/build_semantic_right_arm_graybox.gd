extends SceneTree

## Builds a no-art, isolated consumer contract for Vivhite's screen-right,
## camera-near arm.  The legacy split candidate calls this side "right" only
## because it is on screen-right; the character-facing anatomical side is left.
## No image is generated, cropped, masked, packed, or copied by this tool.

const COMMAND := "build-semantic-right-arm-graybox"
const SPINE_VERSION := "4.2.43"
const OUTPUT_ROOT := "Vivhite/tools/candidates/semantic_right_arm"
const CONTRACT_FILE := "consumer-contract.json"
const SKELETON_FILE := "vivhite_semantic_right_arm_graybox.spjson"

const MASTER_0018 := (
	"assets/vivhite-ironclad/generated/evolink-paid/2026-08-28/"
	+ "0018-combat-body-master-attempt-01/output.png"
)
const RUNTIME_MASTER := (
	"assets/vivhite-ironclad/custom/combat/sources/"
	+ "vivhite-combat-body-master-v1.png"
)
const VISUAL_0022 := (
	"assets/vivhite-ironclad/generated/evolink-paid/2026-08-28/"
	+ "0022-combat-body-master-attempt-05/output.png"
)
const TORSO_0054 := (
	"assets/vivhite-ironclad/generated/evolink-paid/2026-08-28/"
	+ "0054-split-torso-attachment-attempt-07/output.png"
)

const EXPECTED_MASTER_SHA256 := "86ffd64a637d170e213879e72d986b707ee181d4812c8e3fb1eda4abfab98bd1"
const EXPECTED_VISUAL_SHA256 := "488e74758164dab0702ec6f943e02d23d9561caef29320275f698cb0000e232e"

const SOURCE_SIZE := Vector2(1680.0, 2512.0)
const CHARACTER_SCALE := 0.70
const SCENE_SCALE := 0.28
const WORLD_RECT := Rect2(
	-620.0 * CHARACTER_SCALE,
	-61.0,
	1240.0 * CHARACTER_SCALE,
	1860.0 * CHARACTER_SCALE
)

# These points come from build_vivhite_combat_split_mesh_candidate.gd and the
# 0018 source actually consumed by that builder.  They are consumer pivots,
# not landmarks inferred from a newly generated fragment.
const LANDMARK_SOURCE_PX := {
	"clavicle_bind": Vector2(775.0, 525.0),
	"shoulder_pivot": Vector2(810.0, 545.0),
	"elbow_pivot": Vector2(1040.0, 650.0),
	"palm_deform_pivot": Vector2(1430.0, 555.0),
	"magic_arc_anchor": Vector2(1500.0, 530.0),
}

# Spine-local rotations copied from the current split candidate's authored
# extrema.  The hand remains part of one forearm+hand attachment; palm rotation
# is an internal weighted-deform control, not a separate wrist seam.
const POSES := {
	"setup": {"upper": 0.0, "forearm": 0.0, "palm": 0.0},
	"low_health_extreme": {"upper": -10.0, "forearm": 0.0, "palm": 0.0},
	"attack_anticipation": {"upper": -28.0, "forearm": -35.0, "palm": -18.0},
	"attack_peak": {"upper": 32.0, "forearm": 43.0, "palm": 20.0},
	"heavy_peak": {"upper": 46.0, "forearm": 62.0, "palm": 28.0},
	"cast_anticipation": {"upper": -12.0, "forearm": -15.0, "palm": -8.0},
	"cast_peak": {"upper": 32.0, "forearm": 44.0, "palm": 22.0},
	"hurt_peak": {"upper": 0.0, "forearm": -22.0, "palm": 0.0},
	"death_terminal": {"upper": -77.0, "forearm": -54.0, "palm": -21.0},
}


func _initialize() -> void:
	var args := OS.get_cmdline_user_args()
	if args.is_empty():
		args = PackedStringArray([COMMAND])
	if args[0] in ["-h", "--help", "help"]:
		print("Usage: godot --headless --path tools/art --script res://candidates/semantic_right_arm/build_semantic_right_arm_graybox.gd -- %s" % COMMAND)
		quit(0)
		return
	if args[0] != COMMAND:
		push_error("Unknown command: %s" % args[0])
		quit(2)
		return

	var repo_root := ProjectSettings.globalize_path("res://").path_join("../..").simplify_path()
	var output_root := repo_root.path_join(OUTPUT_ROOT)
	DirAccess.make_dir_recursive_absolute(output_root)
	var source_paths := [MASTER_0018, RUNTIME_MASTER, VISUAL_0022, TORSO_0054]
	for relative_path: String in source_paths:
		if not FileAccess.file_exists(repo_root.path_join(relative_path)):
			push_error("Missing evidence source: %s" % relative_path)
			quit(2)
			return

	var master_sha := FileAccess.get_sha256(repo_root.path_join(MASTER_0018)).to_lower()
	var runtime_sha := FileAccess.get_sha256(repo_root.path_join(RUNTIME_MASTER)).to_lower()
	var visual_sha := FileAccess.get_sha256(repo_root.path_join(VISUAL_0022)).to_lower()
	if master_sha != EXPECTED_MASTER_SHA256 or runtime_sha != master_sha:
		push_error("0018/runtime master drifted; refuse to freeze a different arm consumer")
		quit(2)
		return
	if visual_sha != EXPECTED_VISUAL_SHA256:
		push_error("0022 comparison source drifted")
		quit(2)
		return

	var contract := _build_contract(master_sha, runtime_sha, visual_sha, FileAccess.get_sha256(repo_root.path_join(TORSO_0054)).to_lower())
	var skeleton := _build_skeleton()
	if not _write_json(output_root.path_join(CONTRACT_FILE), contract):
		quit(2)
		return
	if not _write_json(output_root.path_join(SKELETON_FILE), skeleton):
		quit(2)
		return

	print("Built isolated semantic near-arm graybox contract:")
	print("  side: screen-right / camera-near / anatomical-left")
	print("  art:  none (0 paid calls, 0 candidate raster files)")
	print("  out:  %s" % output_root)
	quit(0)


func _build_contract(master_sha: String, runtime_sha: String, visual_sha: String, torso_sha: String) -> Dictionary:
	var landmarks := {}
	for name: String in LANDMARK_SOURCE_PX:
		var source_point: Vector2 = LANDMARK_SOURCE_PX[name]
		var world_point := _source_to_world(source_point)
		landmarks[name] = {
			"source_px": [source_point.x, source_point.y],
			"world_units": [world_point.x, world_point.y],
		}

	var pose_rows := []
	for pose_name: String in POSES:
		var pose: Dictionary = POSES[pose_name]
		pose_rows.append({
			"name": pose_name,
			"upper_arm_rotation_deg": pose["upper"],
			"forearm_hand_rotation_deg": pose["forearm"],
			"palm_internal_rotation_deg": pose["palm"],
		})

	return {
		"schema_version": 1,
		"status": "executable-graybox-consumer-no-art",
		"asset_classification": {
			"requested_group": "semantic body-part group",
			"production_delivery": "two independent single-frame attachments: upper_arm and continuous forearm_hand",
			"not_a_sprite_sheet": true,
			"not_an_atlas_page": true,
			"packed_atlas_redraw_forbidden": true,
		},
		"side_identity": {
			"screen_side": "right",
			"camera_depth": "near",
			"anatomical_side": "left",
			"legacy_builder_suffix": "right",
			"legacy_suffix_semantics": "screen side only; never use it as an anatomical label",
			"canonical_id": "near_screen_right_anatomical_left_arm",
			"evidence": [
				"0018 prompt calls the screen-right raised casting arm the near arm",
				"the front-facing identity reference places the character-left butterfly on screen-right",
				"the current split builder names x-positive pivots *_right, proving its suffix is screen-space",
			],
		},
		"consumer": {
			"combat_scene": "Vivhite/Vivhite/skins/ironclad/scenes/combat.tscn",
			"spine_scale": SCENE_SCALE,
			"authored_character_scale": CHARACTER_SCALE,
			"world_rect": [WORLD_RECT.position.x, WORLD_RECT.position.y, WORLD_RECT.size.x, WORLD_RECT.size.y],
			"source_size_px": [SOURCE_SIZE.x, SOURCE_SIZE.y],
			"current_split_builder": "tools/art/build_vivhite_combat_split_mesh_candidate.gd",
			"runtime_vfx_type": "MegaCrit.Sts2.Core.Nodes.Vfx.NIroncladVfx",
			"runtime_vfx_contract": {
				"slash_slot": "slash_mesh",
				"attack_event": "attack_slash_start",
				"heavy_event": "heavy_slash_start",
				"arc_follows": "magic_arc_anchor is screen-right and above palm_deform_pivot",
				"slash_draws_behind_character": true,
			},
		},
		"evidence_sources": [
			{"path": MASTER_0018, "sha256": master_sha, "role": "actual current split/runtime body source; full-body single frame; pivot authority only"},
			{"path": RUNTIME_MASTER, "sha256": runtime_sha, "role": "byte-identical registered runtime master"},
			{"path": VISUAL_0022, "sha256": visual_sha, "role": "visual direction/silhouette comparison only; not pivot authority"},
			{"path": TORSO_0054, "sha256": torso_sha, "role": "adjacent shoulder-sleeve/armhole candidate only; not an arm source"},
		],
		"landmarks": landmarks,
		"attachments": {
			"upper_arm": {
				"bone": "near_upper_arm",
				"slot": "near_upper_arm_back",
				"pivot": "shoulder_pivot",
				"axis": "shoulder_pivot -> elbow_pivot; screen-right and down in source pixels",
				"source_axis_length_px": LANDMARK_SOURCE_PX["shoulder_pivot"].distance_to(LANDMARK_SOURCE_PX["elbow_pivot"]),
				"hidden_shoulder_root_overlap_px": 48.0,
				"hidden_elbow_extension_px": 32.0,
				"joint_cap_radius_px": 44.0,
				"layer": "behind torso shoulder sleeve/occluder; behind forearm_hand",
			},
			"forearm_hand": {
				"bone": "near_forearm_hand",
				"slot": "near_forearm_hand_front",
				"pivot": "elbow_pivot",
				"axis": "elbow_pivot -> palm_deform_pivot; screen-right and up in source pixels",
				"source_axis_length_px": LANDMARK_SOURCE_PX["elbow_pivot"].distance_to(LANDMARK_SOURCE_PX["palm_deform_pivot"]),
				"hidden_elbow_root_overlap_px": 64.0,
				"joint_cap_radius_px": 44.0,
				"wrist_seam": "none; hand is continuous with forearm",
				"palm_internal_bone": "near_palm_deform",
				"layer": "in front of upper arm, torso/head, and behind slash VFX consumer",
			},
			"shoulder_occluder_requirement": {
				"owner": "torso semantic group",
				"graybox_slot": "near_shoulder_occluder_reference",
				"center": "shoulder_pivot",
				"minimum_coverage_radius_px": 96.0,
				"fallback": "if the torso does not supply the sleeve/armhole foreground, add a separate shoulder-front attachment; never move upper_arm in front merely to hide a gap",
			},
		},
		"required_slot_order": [
			"near_upper_arm_back",
			"near_shoulder_occluder_reference",
			"near_forearm_hand_front",
			"slash_mesh",
		],
		"extreme_pose_gates": pose_rows,
		"rotation_envelope_deg": {
			"upper_arm": [-77.0, 46.0],
			"forearm_hand": [-54.0, 62.0],
			"palm_internal": [-21.0, 28.0],
		},
		"source_availability": {
			"dedicated_production_upper_arm": null,
			"dedicated_production_forearm_hand": null,
			"usable_existing_arm_sources": [],
			"reason": "0018/0022 are flattened whole figures with no hidden shoulder/elbow pixels; 0054 is only the adjacent torso sleeve candidate",
		},
		"safety": {
			"paid_generation_calls": 0,
			"candidate_raster_files": 0,
			"alpha_created_or_modified": false,
			"runtime_modified": false,
			"deployable": false,
		},
	}


func _build_skeleton() -> Dictionary:
	var world := {}
	for name: String in LANDMARK_SOURCE_PX:
		world[name] = _source_to_world(LANDMARK_SOURCE_PX[name])
	var bones := [
		{"name": "root"},
		{"name": "near_clavicle_bind", "parent": "root", "x": world["clavicle_bind"].x, "y": world["clavicle_bind"].y},
		_bone_from_world("near_upper_arm", "near_clavicle_bind", world["shoulder_pivot"], world["clavicle_bind"], world["elbow_pivot"]),
		_bone_from_world("near_forearm_hand", "near_upper_arm", world["elbow_pivot"], world["shoulder_pivot"], world["palm_deform_pivot"]),
		_bone_from_world("near_palm_deform", "near_forearm_hand", world["palm_deform_pivot"], world["elbow_pivot"], world["magic_arc_anchor"]),
		{"name": "near_magic_arc_anchor", "parent": "near_palm_deform", "x": world["magic_arc_anchor"].x - world["palm_deform_pivot"].x, "y": world["magic_arc_anchor"].y - world["palm_deform_pivot"].y},
	]
	var animations := {}
	for pose_name: String in POSES:
		var pose: Dictionary = POSES[pose_name]
		animations[pose_name] = {"bones": {
			"near_upper_arm": {"rotate": [{"time": 0.0, "value": 0.0}, {"time": 1.0, "value": pose["upper"]}]},
			"near_forearm_hand": {"rotate": [{"time": 0.0, "value": 0.0}, {"time": 1.0, "value": pose["forearm"]}]},
			"near_palm_deform": {"rotate": [{"time": 0.0, "value": 0.0}, {"time": 1.0, "value": pose["palm"]}]},
		}}
	return {
		"skeleton": {
			"hash": "vivhite-semantic-near-arm-graybox-v1",
			"spine": SPINE_VERSION,
			"x": -900.0,
			"y": -260.0,
			"width": 3260.0,
			"height": 2220.0,
			"images": "./",
		},
		"bones": bones,
		"slots": [
			{"name": "near_upper_arm_back", "bone": "near_upper_arm"},
			{"name": "near_shoulder_occluder_reference", "bone": "near_clavicle_bind"},
			{"name": "near_forearm_hand_front", "bone": "near_forearm_hand"},
			{"name": "slash_mesh", "bone": "near_magic_arc_anchor"},
		],
		"skins": [{"name": "default", "attachments": {}}],
		"animations": animations,
	}


func _bone_from_world(name: String, parent: String, point: Vector2, parent_point: Vector2, child_point: Vector2) -> Dictionary:
	return {
		"name": name,
		"parent": parent,
		"x": point.x - parent_point.x,
		"y": point.y - parent_point.y,
		"length": point.distance_to(child_point),
	}


func _source_to_world(point: Vector2) -> Vector2:
	return Vector2(
		WORLD_RECT.position.x + WORLD_RECT.size.x * point.x / SOURCE_SIZE.x,
		WORLD_RECT.position.y + WORLD_RECT.size.y * (1.0 - point.y / SOURCE_SIZE.y)
	)


func _write_json(path: String, value: Variant) -> bool:
	var file := FileAccess.open(path, FileAccess.WRITE)
	if file == null:
		push_error("Could not write %s: %s" % [path, error_string(FileAccess.get_open_error())])
		return false
	file.store_string(JSON.stringify(value, "  ", false) + "\n")
	return true
