extends SceneTree

## Builds a deliberately non-publishable torso/skirt consumer graybox.
##
## The candidate consumes the existing 0054 torso exactly as returned by
## EvoLink and samples neighbouring setup-pose regions from the unmodified
## 0018 full-body master. It never thresholds, masks, crops, repairs or creates
## subject Alpha. Its purpose is to make the current baked shoulder/sleeve and
## waist draw-order conflicts reproducible before another paid generation.

const COMMAND := "build-semantic-torso-skirt-candidate"
const OUTPUT_ROOT := "Vivhite/tools/candidates/semantic_torso_skirt"
const MOUNT_ROOT := "res://tools/candidates/semantic_torso_skirt"

const TORSO_SOURCE := (
	"assets/vivhite-ironclad/generated/evolink-paid/2026-08-28/"
	+ "0054-split-torso-attachment-attempt-07/output.png"
)
const TORSO_PROMPT := (
	"assets/vivhite-ironclad/generated/evolink-paid/2026-08-28/"
	+ "0054-split-torso-attachment-attempt-07/output.prompt.txt"
)
const TORSO_REQUEST := (
	"assets/vivhite-ironclad/generated/evolink-paid/2026-08-28/"
	+ "0054-split-torso-attachment-attempt-07/output.request.json"
)
const TORSO_LINEAGE_PROMPT := (
	"assets/vivhite-ironclad/generated/evolink-paid/2026-08-28/"
	+ "0048-split-torso-attachment-attempt-01/output.prompt.txt"
)
const CONSUMED_MASTER := (
	"assets/vivhite-ironclad/generated/evolink-paid/2026-08-28/"
	+ "0018-combat-body-master-attempt-01/output.png"
)
const VISUAL_DIRECTION_MASTER := (
	"assets/vivhite-ironclad/generated/evolink-paid/2026-08-28/"
	+ "0022-combat-body-master-attempt-05/output.png"
)
const SPLIT_SKELETON_EVIDENCE := (
	"assets/vivhite-ironclad/candidates/split_mesh/combat/"
	+ "vivhite_combat_split_mesh.spjson"
)
const VANILLA_ATLAS_EVIDENCE := "assets/ironclad-v0.111.0/combat/ironclad.atlas"
const REGISTRY_EVIDENCE := "Vivhite/VivhiteCode/Characters/IroncladReplacementAssets.cs"
const SCENE_EVIDENCE := "Vivhite/Vivhite/skins/ironclad/scenes/combat.tscn"

const JSON_FILE := "vivhite_semantic_torso_skirt.spjson"
const ATLAS_FILE := "vivhite_semantic_torso_skirt.spatlas"
const DATA_FILE := "vivhite_semantic_torso_skirt_skeleton_data.tres"
const TORSO_PAGE := "vivhite_semantic_torso_0054.png"
const CONTEXT_PAGE := "vivhite_semantic_context_0018.png"
const MANIFEST_FILE := "candidate.json"
const TORSO_REGION := "vivhite_semantic_torso_0054"
const CONTEXT_REGION := "vivhite_semantic_context_0018"

const SPINE_VERSION := "4.2.43"
const SCENE_SCALE := 0.28
const SOURCE_SIZE := Vector2(1680.0, 2512.0)
const WORLD_RECT := Rect2(-434.0, -61.0, 868.0, 1302.0)
const TORSO_TARGET_RECT := Rect2(505.0, 430.0, 485.0, 490.0)
const TORSO_SOLID_THRESHOLD := 127

const BONE_ROOT := "root"
const BONE_PELVIS := "vivhite_pelvis"
const BONE_TORSO_LOWER := "vivhite_torso_lower"
const BONE_TORSO_UPPER := "vivhite_torso_upper"
const BONE_SKIRT := "vivhite_skirt_center"
const BONE_FAR_SHOULDER := "vivhite_shoulder_left"
const BONE_FAR_ARM := "vivhite_upper_arm_left"
const BONE_NEAR_SHOULDER := "vivhite_shoulder_right"
const BONE_NEAR_ARM := "vivhite_upper_arm_right"
const BONE_LEFT_THIGH := "vivhite_thigh_left"
const BONE_RIGHT_THIGH := "vivhite_thigh_right"

# Current split consumer rectangles. These are GPU UV samples from the
# unchanged 0018 page, not newly cut production assets.
const FAR_ARM_RECT := Rect2(400.0, 590.0, 250.0, 310.0)
const NEAR_ARM_RECT := Rect2(745.0, 475.0, 340.0, 260.0)
const LEFT_THIGH_RECT := Rect2(445.0, 1140.0, 270.0, 330.0)
const RIGHT_THIGH_RECT := Rect2(675.0, 1120.0, 300.0, 390.0)
const SKIRT_RECT := Rect2(445.0, 825.0, 805.0, 470.0)

# The split-heavy peak rotates torso_lower and torso_upper by 23 degrees each;
# the skirt remains pelvis-relative. This 46-degree relative twist is the
# consumer extreme that a torso/skirt semantic group must survive.
const TWIST_PER_TORSO_BONE := 23.0
const MAX_RELATIVE_TORSO_TWIST := 46.0
const SKIRT_COUNTER_SWAY := 8.0
const FAR_ARM_LOCAL_TURN := 18.0
const NEAR_ARM_LOCAL_TURN := 46.0

var _repo_root := ""
var _last_error := ""


func _initialize() -> void:
	_repo_root = ProjectSettings.globalize_path("res://").path_join("../..").simplify_path()
	var args := OS.get_cmdline_user_args()
	if args.is_empty():
		args = PackedStringArray([COMMAND])
	if args[0] in ["-h", "--help", "help"]:
		print("Usage: godot --headless --path tools/art --script res://candidates/semantic_torso_skirt/build_semantic_torso_skirt_candidate.gd -- %s" % COMMAND)
		quit(0)
		return
	if args[0] != COMMAND:
		quit(_fail("Unknown command: %s" % args[0]))
		return
	if not _build():
		quit(_fail(_last_error))
		return
	quit(0)


func _build() -> bool:
	var torso_path := _path(TORSO_SOURCE)
	var consumed_path := _path(CONSUMED_MASTER)
	var visual_path := _path(VISUAL_DIRECTION_MASTER)
	var torso := _load_native_rgba(torso_path, "0054 torso")
	var consumed := _load_native_rgba(consumed_path, "0018 consumed combat master")
	var visual := _load_native_rgba(visual_path, "0022 direction master")
	if torso.is_empty() or consumed.is_empty() or visual.is_empty():
		return false
	if torso.get_size() != Vector2i(832, 1248):
		return _set_error("0054 canvas changed; expected 832x1248, got %s" % torso.get_size())
	if consumed.get_size() != Vector2i(1680, 2512) or visual.get_size() != Vector2i(1680, 2512):
		return _set_error("0018 and 0022 must both remain 1680x2512 single-frame masters")

	var solid_bounds := _alpha_bounds(torso, TORSO_SOLID_THRESHOLD)
	if solid_bounds.size.x <= 0 or solid_bounds.size.y <= 0:
		return _set_error("0054 has no A>127 physical core")
	var target_world_rect := _source_rect_world(TORSO_TARGET_RECT)
	var world_per_pixel := target_world_rect.size.y / float(solid_bounds.size.y)
	var torso_world_size := Vector2(torso.get_width(), torso.get_height()) * world_per_pixel
	var target_center := target_world_rect.get_center()
	var torso_bone_world := _bone_world_positions()[BONE_TORSO_UPPER] as Vector2
	var solid_center_px := Vector2(solid_bounds.get_center())
	var image_center_px := Vector2(torso.get_size()) * 0.5
	var solid_center_from_attachment := Vector2(
		(solid_center_px.x - image_center_px.x) * world_per_pixel,
		(image_center_px.y - solid_center_px.y) * world_per_pixel
	)
	var torso_attachment_offset := target_center - torso_bone_world - solid_center_from_attachment

	var split_evidence := _load_json(_path(SPLIT_SKELETON_EVIDENCE), "split skeleton evidence")
	if split_evidence.is_empty():
		return false
	var split_slot_audit := _audit_split_slots(split_evidence)
	if not bool(split_slot_audit.get("passed", false)):
		return _set_error(str(split_slot_audit.get("error", "split slot audit failed")))
	var vanilla_audit := _audit_vanilla_atlas(_path(VANILLA_ATLAS_EVIDENCE))
	if not bool(vanilla_audit.get("passed", false)):
		return _set_error(str(vanilla_audit.get("error", "vanilla atlas audit failed")))
	if not _audit_source_consumers():
		return false

	var skeleton := _build_skeleton(torso_world_size, torso_attachment_offset)
	var atlas_data := _build_atlas_data(torso.get_size(), consumed.get_size())
	var output_root := _path(OUTPUT_ROOT)
	if not _make_dir(output_root):
		return false
	if DirAccess.copy_absolute(torso_path, output_root.path_join(TORSO_PAGE)) != OK:
		return _set_error("Could not byte-copy 0054 into the isolated candidate")
	if DirAccess.copy_absolute(consumed_path, output_root.path_join(CONTEXT_PAGE)) != OK:
		return _set_error("Could not byte-copy 0018 into the isolated candidate")
	if not _write_text(output_root.path_join(JSON_FILE), JSON.stringify(skeleton, "  ", false) + "\n"):
		return false
	var atlas_wrapper := {
		"atlas_data": atlas_data,
		"normal_texture_prefix": "n",
		"source_path": "%s/%s" % [MOUNT_ROOT, ATLAS_FILE.replace(".spatlas", ".atlas")],
		"specular_texture_prefix": "s",
	}
	if not _write_text(output_root.path_join(ATLAS_FILE), JSON.stringify(atlas_wrapper, "", false) + "\n"):
		return false
	if not _write_text(output_root.path_join(DATA_FILE), _build_tres()):
		return false

	var manifest := _build_manifest(
		torso,
		consumed,
		visual,
		solid_bounds,
		target_world_rect,
		torso_world_size,
		torso_attachment_offset,
		split_slot_audit,
		vanilla_audit
	)
	if not _write_text(output_root.path_join(MANIFEST_FILE), JSON.stringify(manifest, "  ", false) + "\n"):
		return false

	print("Built semantic torso/skirt graybox (audit-only; not publishable):")
	print("  output: %s" % output_root)
	print("  0054 A>127 bbox: %s" % solid_bounds)
	print("  fitted solid world size: %.2fx%.2f" % [solid_bounds.size.x * world_per_pixel, solid_bounds.size.y * world_per_pixel])
	print("  target torso world rect: %s" % target_world_rect)
	print("  relative twist gate: +/-%.1f degrees" % MAX_RELATIVE_TORSO_TWIST)
	print("  result: freeze next semantic-group contract; do not promote 0054")
	return true


func _build_skeleton(torso_world_size: Vector2, torso_offset: Vector2) -> Dictionary:
	var world := _bone_world_positions()
	var bones := []
	var parent_map := {
		BONE_ROOT: "",
		BONE_PELVIS: BONE_ROOT,
		BONE_TORSO_LOWER: BONE_PELVIS,
		BONE_TORSO_UPPER: BONE_TORSO_LOWER,
		BONE_SKIRT: BONE_PELVIS,
		BONE_FAR_SHOULDER: BONE_TORSO_UPPER,
		BONE_FAR_ARM: BONE_FAR_SHOULDER,
		BONE_NEAR_SHOULDER: BONE_TORSO_UPPER,
		BONE_NEAR_ARM: BONE_NEAR_SHOULDER,
		BONE_LEFT_THIGH: BONE_PELVIS,
		BONE_RIGHT_THIGH: BONE_PELVIS,
	}
	var order := [
		BONE_ROOT, BONE_PELVIS, BONE_TORSO_LOWER, BONE_TORSO_UPPER,
		BONE_SKIRT, BONE_LEFT_THIGH, BONE_RIGHT_THIGH,
		BONE_FAR_SHOULDER, BONE_FAR_ARM, BONE_NEAR_SHOULDER, BONE_NEAR_ARM,
	]
	for bone_name: String in order:
		var bone := {"name": bone_name}
		var parent_name := str(parent_map[bone_name])
		if not parent_name.is_empty():
			var local := (world[bone_name] as Vector2) - (world[parent_name] as Vector2)
			bone["parent"] = parent_name
			bone["x"] = local.x
			bone["y"] = local.y
		bones.append(bone)

	var slot_specs := [
		{"name": "context_far_upper_arm", "bone": BONE_FAR_ARM, "attachment": "context_far_upper_arm"},
		{"name": "context_left_thigh", "bone": BONE_LEFT_THIGH, "attachment": "context_left_thigh"},
		{"name": "context_right_thigh", "bone": BONE_RIGHT_THIGH, "attachment": "context_right_thigh"},
		# This deliberately reproduces the current split ordering: torso before
		# skirt. It demonstrates why the white skirt covers the navy front hem.
		{"name": "semantic_torso", "bone": BONE_TORSO_UPPER, "attachment": TORSO_REGION},
		{"name": "context_skirt", "bone": BONE_SKIRT, "attachment": "context_skirt"},
		{"name": "context_near_upper_arm", "bone": BONE_NEAR_ARM, "attachment": "context_near_upper_arm"},
	]
	var attachments := {
		"context_far_upper_arm": {
			"context_far_upper_arm": _context_mesh(FAR_ARM_RECT, BONE_FAR_ARM, world),
		},
		"context_left_thigh": {
			"context_left_thigh": _context_mesh(LEFT_THIGH_RECT, BONE_LEFT_THIGH, world),
		},
		"context_right_thigh": {
			"context_right_thigh": _context_mesh(RIGHT_THIGH_RECT, BONE_RIGHT_THIGH, world),
		},
		"semantic_torso": {
			TORSO_REGION: {
				"path": TORSO_REGION,
				"x": torso_offset.x,
				"y": torso_offset.y,
				"width": torso_world_size.x,
				"height": torso_world_size.y,
			},
		},
		"context_skirt": {
			"context_skirt": _context_mesh(SKIRT_RECT, BONE_SKIRT, world),
		},
		"context_near_upper_arm": {
			"context_near_upper_arm": _context_mesh(NEAR_ARM_RECT, BONE_NEAR_ARM, world),
		},
	}
	return {
		"skeleton": {
			"hash": "vivhite-semantic-torso-skirt-graybox-v1",
			"spine": SPINE_VERSION,
			"x": -620.0,
			"y": -120.0,
			"width": 1240.0,
			"height": 1480.0,
			"images": "./",
		},
		"bones": bones,
		"slots": slot_specs,
		"skins": [{"name": "default", "attachments": attachments}],
		"animations": {
			"setup": _pose_animation(0.0),
			"max_twist_clockwise": _pose_animation(1.0),
			"max_twist_counter_clockwise": _pose_animation(-1.0),
		},
	}


func _pose_animation(direction: float) -> Dictionary:
	var end := 1.0
	return {"bones": {
		BONE_TORSO_LOWER: {"rotate": [{"time": 0.0, "value": 0.0}, {"time": end, "value": direction * TWIST_PER_TORSO_BONE}]},
		BONE_TORSO_UPPER: {"rotate": [{"time": 0.0, "value": 0.0}, {"time": end, "value": direction * TWIST_PER_TORSO_BONE}]},
		BONE_SKIRT: {"rotate": [{"time": 0.0, "value": 0.0}, {"time": end, "value": -direction * SKIRT_COUNTER_SWAY}]},
		BONE_FAR_ARM: {"rotate": [{"time": 0.0, "value": 0.0}, {"time": end, "value": -direction * FAR_ARM_LOCAL_TURN}]},
		BONE_NEAR_ARM: {"rotate": [{"time": 0.0, "value": 0.0}, {"time": end, "value": direction * NEAR_ARM_LOCAL_TURN}]},
	}}


func _bone_world_positions() -> Dictionary:
	return {
		BONE_ROOT: Vector2.ZERO,
		BONE_PELVIS: _source_point_world(Vector2(700, 1110)),
		BONE_TORSO_LOWER: _source_point_world(Vector2(700, 820)),
		BONE_TORSO_UPPER: _source_point_world(Vector2(700, 590)),
		BONE_SKIRT: _source_point_world(Vector2(700, 880)),
		BONE_FAR_SHOULDER: _source_point_world(Vector2(550, 565)),
		BONE_FAR_ARM: _source_point_world(Vector2(585, 585)),
		BONE_NEAR_SHOULDER: _source_point_world(Vector2(775, 525)),
		BONE_NEAR_ARM: _source_point_world(Vector2(810, 545)),
		BONE_LEFT_THIGH: _source_point_world(Vector2(575, 1190)),
		BONE_RIGHT_THIGH: _source_point_world(Vector2(790, 1190)),
	}


func _context_mesh(source_rect: Rect2, bone_name: String, bone_world: Dictionary) -> Dictionary:
	var u0 := source_rect.position.x / SOURCE_SIZE.x
	var v0 := source_rect.position.y / SOURCE_SIZE.y
	var u1 := source_rect.end.x / SOURCE_SIZE.x
	var v1 := source_rect.end.y / SOURCE_SIZE.y
	var origin := bone_world[bone_name] as Vector2
	var top_left := _source_point_world(source_rect.position) - origin
	var top_right := _source_point_world(Vector2(source_rect.end.x, source_rect.position.y)) - origin
	var bottom_right := _source_point_world(source_rect.end) - origin
	var bottom_left := _source_point_world(Vector2(source_rect.position.x, source_rect.end.y)) - origin
	return {
		"type": "mesh",
		"path": CONTEXT_REGION,
		"uvs": [u0, v0, u1, v0, u1, v1, u0, v1],
		"triangles": [0, 3, 1, 1, 3, 2],
		"vertices": [
			top_left.x, top_left.y,
			top_right.x, top_right.y,
			bottom_right.x, bottom_right.y,
			bottom_left.x, bottom_left.y,
		],
		"hull": 4,
		"width": source_rect.size.x / SOURCE_SIZE.x * WORLD_RECT.size.x,
		"height": source_rect.size.y / SOURCE_SIZE.y * WORLD_RECT.size.y,
	}


func _source_point_world(point: Vector2) -> Vector2:
	return Vector2(
		WORLD_RECT.position.x + WORLD_RECT.size.x * point.x / SOURCE_SIZE.x,
		WORLD_RECT.position.y + WORLD_RECT.size.y * (1.0 - point.y / SOURCE_SIZE.y)
	)


func _source_rect_world(rect: Rect2) -> Rect2:
	var bottom_left := _source_point_world(Vector2(rect.position.x, rect.end.y))
	return Rect2(
		bottom_left,
		Vector2(
			rect.size.x / SOURCE_SIZE.x * WORLD_RECT.size.x,
			rect.size.y / SOURCE_SIZE.y * WORLD_RECT.size.y
		)
	)


func _build_atlas_data(torso_size: Vector2i, context_size: Vector2i) -> String:
	return "\n".join(PackedStringArray([
		TORSO_PAGE,
		"size:%d,%d" % [torso_size.x, torso_size.y],
		"filter:Linear,Linear",
		"pma:false",
		"repeat:none",
		TORSO_REGION,
		"bounds:0,0,%d,%d" % [torso_size.x, torso_size.y],
		"",
		CONTEXT_PAGE,
		"size:%d,%d" % [context_size.x, context_size.y],
		"filter:Linear,Linear",
		"pma:false",
		"repeat:none",
		CONTEXT_REGION,
		"bounds:0,0,%d,%d" % [context_size.x, context_size.y],
	])) + "\n"


func _build_tres() -> String:
	return """[gd_resource type="SpineSkeletonDataResource" load_steps=3 format=3]

[ext_resource type="SpineAtlasResource" path="%s/%s" id="1_atlas"]
[ext_resource type="SpineSkeletonFileResource" path="%s/%s" id="2_skeleton"]

[resource]
atlas_res = ExtResource("1_atlas")
skeleton_file_res = ExtResource("2_skeleton")
""" % [MOUNT_ROOT, ATLAS_FILE, MOUNT_ROOT, JSON_FILE]


func _build_manifest(
	torso: Image,
	consumed: Image,
	visual: Image,
	solid_bounds: Rect2i,
	target_world_rect: Rect2,
	torso_world_size: Vector2,
	torso_offset: Vector2,
	split_slot_audit: Dictionary,
	vanilla_audit: Dictionary,
) -> Dictionary:
	var fitted_solid_size := Vector2(
		solid_bounds.size.x / float(torso.get_width()) * torso_world_size.x,
		solid_bounds.size.y / float(torso.get_height()) * torso_world_size.y
	)
	var chest_waist_audit := _chest_waist_audit(torso, consumed, visual, solid_bounds)
	return {
		"schema": 1,
		"name": "semantic_torso_skirt",
		"label": "躯干 + 裙摆语义组消费灰盒",
		"status": "contract_frozen_existing_art_rejected_not_publishable",
		"mount_path": MOUNT_ROOT,
		"resource": DATA_FILE,
		"classification": {
			"0054": "one_single_torso_like_object_not_a_sprite_sheet_or_atlas",
			"0018": "one_single_full_body_frame_not_a_sprite_sheet_or_atlas",
			"0022": "one_single_full_body_frame_not_a_sprite_sheet_or_atlas",
		},
		"source_contract": {
			"0054_torso": _source_record(TORSO_SOURCE, torso),
			"0018_actual_split_consumer": _source_record(CONSUMED_MASTER, consumed),
			"0022_visual_direction_reference_only": _source_record(VISUAL_DIRECTION_MASTER, visual),
			"0054_prompt": TORSO_PROMPT,
			"0054_request": TORSO_REQUEST,
			"0048_lineage_prompt": TORSO_LINEAGE_PROMPT,
		},
		"consumer_evidence": {
			"registry": REGISTRY_EVIDENCE,
			"scene": SCENE_EVIDENCE,
			"scene_scale": SCENE_SCALE,
			"split_slot_audit": split_slot_audit,
			"vanilla_atlas_audit": vanilla_audit,
			"source_code_finding": "C# replaces the complete combat Spine resource; internal part layering is owned exclusively by Spine slot order.",
		},
		"graybox": {
			"animations": ["setup", "max_twist_clockwise", "max_twist_counter_clockwise"],
			"relative_torso_to_skirt_twist_degrees": MAX_RELATIVE_TORSO_TWIST,
			"slot_order_reproduced": [
				"context_far_upper_arm",
				"context_left_thigh",
				"context_right_thigh",
				"semantic_torso",
				"context_skirt",
				"context_near_upper_arm",
			],
			"0054_A_gt_127_bbox_px": _rect_array(solid_bounds),
			"0018_target_rect_px": _rect_array(TORSO_TARGET_RECT),
			"0018_target_world_rect": _rect_array(target_world_rect),
			"fitted_0054_solid_world_size": [fitted_solid_size.x, fitted_solid_size.y],
			"torso_region_world_size": [torso_world_size.x, torso_world_size.y],
			"torso_attachment_offset": [torso_offset.x, torso_offset.y],
			"chest_to_waist_width_audit": chest_waist_audit,
		},
		"audit_verdict": {
			"0054_production_eligible": false,
			"0054_alpha_status": "static_alpha_previously_passed; not the blocking issue",
			"blocking_findings": [
				"0054 lineage intentionally bakes both white shoulder caps/sleeves into the connected torso.",
				"0054 lineage also bakes the screen-left blue/gold shoulder ornament into the torso, preventing an independent far-arm crossing order.",
				(
					"At equal solid height, 0054 fits to %.2f world width versus the frozen 0018 target %.2f; its chest/waist span ratio is %.3f versus 0018 %.3f and 0022 %.3f. This is a proportion mismatch, not one uniform-scale error."
					% [
						fitted_solid_size.x,
						target_world_rect.size.x,
						float(chest_waist_audit["0054"]["chest_to_waist_ratio"]),
						float(chest_waist_audit["0018"]["chest_to_waist_ratio"]),
						float(chest_waist_audit["0022"]["chest_to_waist_ratio"]),
					]
				),
				"0054 includes a white lower waist/skirt-like layer despite the requested short insert, so it duplicates a separate skirt consumer.",
				"Current split slot order places skirt after torso and therefore above the navy bodice hem; no drawOrder animation repairs this during the +/-46 degree relative twist.",
			],
			"graybox_visual_findings": [
				"At setup, the 0054 shoulder caps overlap the independent 0018 arm samples instead of forming one clean sleeve-to-arm joint.",
				"At the clockwise 46-degree torso-to-skirt extreme, the near arm and baked near sleeve visibly separate while the torso waist rotates away from the skirt root.",
				"At the counter-clockwise extreme, the fixed torso/then/skirt order produces bodice/skirt intersections and exposes the lack of hidden waist overlap.",
				"The same defects remain legible at the real 0.28 scene scale, so they are not inspection-zoom-only artifacts.",
			],
		},
		"next_generation_consumer_contract": {
			"paid_call_performed_by_this_task": false,
			"semantic_group_outputs": [
				"torso_core",
				"skirt_back",
				"skirt_center_front",
				"skirt_side_near",
				"skirt_side_far",
				"screen_left_shoulder_ornament_back",
				"screen_left_shoulder_ornament_front",
			],
			"torso_core": {
				"includes": "collar, chest cutout/crystal, white bodice, navy corset and visible navy pointed hem",
				"excludes": "both white upper-arm sleeves/caps, both arms, blue/gold shoulder ornament and every white skirt layer",
				"pivot": "waist center inherited from frozen neutral setup pose",
				"layer": "above all skirt panels; far arm behind; near arm in front",
			},
			"skirt": {
				"attachments": "one back/under panel plus three front/side panels; all generated as one coordinated costume group but stored as separate attachments",
				"hidden_overlap": "each panel extends upward behind torso and laterally behind its neighbour; no glow is baked into joint cuts",
				"layer": "both thighs behind all skirt panels; all skirt panels behind the torso's visible navy pointed hem",
				"bones": "pelvis root plus center/near/far inertial child bones",
			},
			"shoulder_and_sleeve": {
				"white_sleeves": "belong to the left/right arm semantic groups and rotate with their upper-arm chains",
				"blue_gold_ornament": "separate back/front attachments around the far shoulder so the far arm can cross between them without duplicating the torso",
			},
			"required_gate": "setup plus both +/-46 degree torso-to-skirt extremes, near/far upper-arm extremes, SourceOver adjacency, and fixed slot order must pass before any asset is promoted",
		},
		"recommended_draw_order_back_to_front": [
			"far_shoulder_ornament_back",
			"far_upper_arm_and_sleeve",
			"left_and_right_thighs",
			"skirt_back",
			"skirt_side_far",
			"skirt_center_front",
			"skirt_side_near",
			"torso_core_with_visible_navy_front_hem",
			"far_shoulder_ornament_front",
			"near_upper_arm_and_sleeve",
		],
		"safety": {
			"evolink_paid_calls": 0,
			"source_images_modified": false,
			"alpha_threshold_mask_or_cleanup": false,
			"runtime_skin_modified": false,
			"game_or_stream_touched": false,
			"deployable": false,
		},
	}


func _audit_split_slots(document: Dictionary) -> Dictionary:
	var names := []
	var indices := {}
	for index in document.get("slots", []).size():
		var name := str(document["slots"][index].get("name", ""))
		names.append(name)
		indices[name] = index
	var required := ["part_arm_left_upper", "part_torso", "part_skirt", "part_arm_right_upper"]
	for name: String in required:
		if not indices.has(name):
			return {"passed": false, "error": "Missing split slot evidence: %s" % name}
	var draw_order_animations := []
	for animation_name: String in document.get("animations", {}):
		var animation: Dictionary = document["animations"][animation_name]
		if animation.has("drawOrder") or animation.has("draworder"):
			draw_order_animations.append(animation_name)
	return {
		"passed": draw_order_animations.is_empty(),
		"slot_indices": {
			"far_arm": indices["part_arm_left_upper"],
			"torso": indices["part_torso"],
			"skirt": indices["part_skirt"],
			"near_arm": indices["part_arm_right_upper"],
		},
		"back_to_front_relation": "far_arm < torso < skirt < near_arm",
		"draw_order_animation_names": draw_order_animations,
		"all_slot_names": names,
	}


func _audit_vanilla_atlas(path: String) -> Dictionary:
	if not FileAccess.file_exists(path):
		return {"passed": false, "error": "Missing original Ironclad atlas evidence"}
	var text := FileAccess.get_file_as_string(path)
	var required := [
		"bod", "hips", "belt", "bottom upper arm", "top upper arm",
		"l shoulder armor top", "l shoulder armor bottom",
		"r shoulder armor top", "r shoulder armor bottom",
	]
	var missing := []
	for region_name: String in required:
		if not ("\n%s\n" % region_name) in ("\n%s\n" % text):
			missing.append(region_name)
	return {
		"passed": missing.is_empty(),
		"required_separate_regions": required,
		"missing": missing,
		"finding": "Vanilla separates body/hips/belt/upper arms/shoulder armor; one baked torso is not required by the game consumer.",
	}


func _audit_source_consumers() -> bool:
	var registry_path := _path(REGISTRY_EVIDENCE)
	var scene_path := _path(SCENE_EVIDENCE)
	var lineage_path := _path(TORSO_LINEAGE_PROMPT)
	var request_path := _path(TORSO_REQUEST)
	for required_path: String in [registry_path, scene_path, lineage_path, request_path]:
		if not FileAccess.file_exists(required_path):
			return _set_error("Missing consumer/lineage evidence: %s" % required_path)
	var registry := FileAccess.get_file_as_string(registry_path)
	var scene := FileAccess.get_file_as_string(scene_path)
	var lineage := FileAccess.get_file_as_string(lineage_path)
	var request := FileAccess.get_file_as_string(request_path)
	if not "CombatSkeletonDataPath" in registry or not "RegisterCharacterAssetReplacement" in registry:
		return _set_error("Registry no longer proves complete combat Spine replacement")
	if not "scale = Vector2(0.28, 0.28)" in scene:
		return _set_error("Combat scene no longer preserves the 0.28 scale contract")
	if not "white shoulder-cap fabric" in lineage or not "screen-left shoulder" in lineage:
		return _set_error("0052 lineage no longer proves baked sleeve/ornament intent")
	if not "0052-split-torso-attachment-attempt-05" in request:
		return _set_error("0054 request no longer points to the audited 0052 lineage")
	return true


func _source_record(relative_path: String, image: Image) -> Dictionary:
	return {
		"path": relative_path,
		"sha256": FileAccess.get_sha256(_path(relative_path)),
		"canvas_px": [image.get_width(), image.get_height()],
		"alpha": _alpha_stats(image),
	}


func _alpha_stats(image: Image) -> Dictionary:
	var thresholds := [0, 15, 63, 127]
	var width := image.get_width()
	var height := image.get_height()
	var mins_x := [width, width, width, width]
	var mins_y := [height, height, height, height]
	var maxs_x := [-1, -1, -1, -1]
	var maxs_y := [-1, -1, -1, -1]
	var counts := [0, 0, 0, 0]
	var bytes := image.get_data()
	for y in height:
		var row := y * width * 4
		for x in width:
			var alpha := int(bytes[row + x * 4 + 3])
			for threshold_index in thresholds.size():
				if alpha <= int(thresholds[threshold_index]):
					continue
				counts[threshold_index] += 1
				mins_x[threshold_index] = mini(mins_x[threshold_index], x)
				mins_y[threshold_index] = mini(mins_y[threshold_index], y)
				maxs_x[threshold_index] = maxi(maxs_x[threshold_index], x)
				maxs_y[threshold_index] = maxi(maxs_y[threshold_index], y)
	var result := {}
	for threshold_index in thresholds.size():
		var bounds := Rect2i()
		if maxs_x[threshold_index] >= mins_x[threshold_index]:
			bounds = Rect2i(
				mins_x[threshold_index], mins_y[threshold_index],
				maxs_x[threshold_index] - mins_x[threshold_index] + 1,
				maxs_y[threshold_index] - mins_y[threshold_index] + 1
			)
		result["A_gt_%d" % thresholds[threshold_index]] = {
			"bbox": _rect_array(bounds),
			"count": counts[threshold_index],
		}
	return result


func _alpha_bounds(image: Image, threshold: int) -> Rect2i:
	var width := image.get_width()
	var height := image.get_height()
	var bytes := image.get_data()
	var min_x := width
	var min_y := height
	var max_x := -1
	var max_y := -1
	for y in height:
		var row := y * width * 4
		for x in width:
			if int(bytes[row + x * 4 + 3]) <= threshold:
				continue
			min_x = mini(min_x, x)
			min_y = mini(min_y, y)
			max_x = maxi(max_x, x)
			max_y = maxi(max_y, y)
	if max_x < min_x:
		return Rect2i()
	return Rect2i(min_x, min_y, max_x - min_x + 1, max_y - min_y + 1)


func _chest_waist_audit(
	torso: Image,
	consumed: Image,
	visual: Image,
	torso_bounds: Rect2i,
) -> Dictionary:
	var torso_chest_y := torso_bounds.position.y + int(round(torso_bounds.size.y * 0.45))
	var torso_waist_y := torso_bounds.position.y + int(round(torso_bounds.size.y * 0.78))
	var master_chest_y := int(round(TORSO_TARGET_RECT.position.y + TORSO_TARGET_RECT.size.y * 0.42))
	var master_waist_y := int(round(TORSO_TARGET_RECT.position.y + TORSO_TARGET_RECT.size.y * 0.78))
	var x_start := int(TORSO_TARGET_RECT.position.x)
	var x_end := int(TORSO_TARGET_RECT.end.x) - 1
	var torso_chest := _row_span(torso, torso_chest_y, 0, torso.get_width() - 1, TORSO_SOLID_THRESHOLD)
	var torso_waist := _row_span(torso, torso_waist_y, 0, torso.get_width() - 1, TORSO_SOLID_THRESHOLD)
	var consumed_chest := _row_span(consumed, master_chest_y, x_start, x_end, TORSO_SOLID_THRESHOLD)
	var consumed_waist := _row_span(consumed, master_waist_y, x_start, x_end, TORSO_SOLID_THRESHOLD)
	var visual_chest := _row_span(visual, master_chest_y, x_start, x_end, TORSO_SOLID_THRESHOLD)
	var visual_waist := _row_span(visual, master_waist_y, x_start, x_end, TORSO_SOLID_THRESHOLD)
	return {
		"method": "A>127 horizontal span at fixed normalized chest/waist rows; 0018/0022 are restricted to the frozen torso target rect",
		"0054": _span_pair(torso_chest_y, torso_waist_y, torso_chest, torso_waist),
		"0018": _span_pair(master_chest_y, master_waist_y, consumed_chest, consumed_waist),
		"0022": _span_pair(master_chest_y, master_waist_y, visual_chest, visual_waist),
		"limitation": "This is a reproducible silhouette diagnostic, not a substitute for landmarked chest/shoulder art direction.",
	}


func _span_pair(chest_y: int, waist_y: int, chest: Vector2i, waist: Vector2i) -> Dictionary:
	var chest_width := maxi(0, chest.y - chest.x + 1)
	var waist_width := maxi(0, waist.y - waist.x + 1)
	return {
		"chest_y": chest_y,
		"waist_y": waist_y,
		"chest_span": [chest.x, chest.y, chest_width],
		"waist_span": [waist.x, waist.y, waist_width],
		"chest_to_waist_ratio": float(chest_width) / float(maxi(1, waist_width)),
	}


func _row_span(image: Image, y: int, x_start: int, x_end: int, threshold: int) -> Vector2i:
	var bytes := image.get_data()
	var width := image.get_width()
	var min_x := width
	var max_x := -1
	var clamped_y := clampi(y, 0, image.get_height() - 1)
	for x in range(clampi(x_start, 0, width - 1), clampi(x_end, 0, width - 1) + 1):
		if int(bytes[(clamped_y * width + x) * 4 + 3]) <= threshold:
			continue
		min_x = mini(min_x, x)
		max_x = maxi(max_x, x)
	return Vector2i(min_x, max_x) if max_x >= min_x else Vector2i(0, -1)


func _load_native_rgba(path: String, label: String) -> Image:
	if not FileAccess.file_exists(path):
		_set_error("Missing %s: %s" % [label, path])
		return Image.new()
	var image := Image.load_from_file(path)
	if image == null or image.is_empty():
		_set_error("Could not decode %s: %s" % [label, path])
		return Image.new()
	if image.get_format() != Image.FORMAT_RGBA8:
		_set_error("%s must decode directly as RGBA8" % label)
		return Image.new()
	var corners := [
		image.get_pixel(0, 0).a8,
		image.get_pixel(image.get_width() - 1, 0).a8,
		image.get_pixel(0, image.get_height() - 1).a8,
		image.get_pixel(image.get_width() - 1, image.get_height() - 1).a8,
	]
	if corners != [0, 0, 0, 0]:
		_set_error("%s corners must remain zero Alpha; no repair is permitted" % label)
		return Image.new()
	return image


func _load_json(path: String, label: String) -> Dictionary:
	if not FileAccess.file_exists(path):
		_set_error("Missing %s: %s" % [label, path])
		return {}
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(path))
	if not parsed is Dictionary:
		_set_error("Invalid JSON for %s: %s" % [label, path])
		return {}
	return parsed as Dictionary


func _rect_array(rect: Variant) -> Array:
	return [rect.position.x, rect.position.y, rect.size.x, rect.size.y]


func _make_dir(path: String) -> bool:
	var error := DirAccess.make_dir_recursive_absolute(path)
	if error != OK and error != ERR_ALREADY_EXISTS:
		return _set_error("Could not create output directory: %s" % path)
	return true


func _write_text(path: String, value: String) -> bool:
	var file := FileAccess.open(path, FileAccess.WRITE)
	if file == null:
		return _set_error("Could not write: %s" % path)
	file.store_string(value)
	file.close()
	return true


func _path(relative_path: String) -> String:
	return _repo_root.path_join(relative_path).simplify_path()


func _set_error(message: String) -> bool:
	_last_error = message
	push_error(message)
	return false


func _fail(message: String) -> int:
	push_error(message)
	return 2
