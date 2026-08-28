extends "res://build_vivhite_combat_rig.gd"

## Offline comparison candidate: one weighted full-body mesh driven by a
## genuinely hierarchical Vivhite skeleton. It deliberately writes below the
## Mod project's excluded tools/ tree and never touches the live skin path.

const CANDIDATE_OUTPUT_ROOT := "Vivhite/tools/candidates/whole_mesh"
const CANDIDATE_RESOURCE_ROOT := "res://tools/candidates/whole_mesh"

const PELVIS := "vivhite_pelvis"
const TORSO_LOWER := "vivhite_torso_lower"
const TORSO_UPPER := "vivhite_torso_upper"
const NECK := "vivhite_neck"
const HEAD := "vivhite_head"
const HAIR_CROWN := "vivhite_hair_crown"
const HAIR_LEFT := "vivhite_hair_left"
const HAIR_RIGHT := "vivhite_hair_right"
const BUTTERFLY := "vivhite_butterfly"
const SHOULDER_LEFT := "vivhite_shoulder_left"
const UPPER_ARM_LEFT := "vivhite_upper_arm_left"
const FOREARM_LEFT := "vivhite_forearm_left"
const HAND_LEFT := "vivhite_hand_left"
const SHOULDER_RIGHT := "vivhite_shoulder_right"
const UPPER_ARM_RIGHT := "vivhite_upper_arm_right"
const FOREARM_RIGHT := "vivhite_forearm_right"
const HAND_RIGHT := "vivhite_hand_right"
const SKIRT_LEFT := "vivhite_skirt_left"
const SKIRT_CENTER := "vivhite_skirt_center"
const SKIRT_RIGHT := "vivhite_skirt_right"
const HIP_LEFT := "vivhite_hip_left"
const THIGH_LEFT := "vivhite_thigh_left"
const SHIN_LEFT := "vivhite_shin_left"
const FOOT_LEFT := "vivhite_foot_left"
const HIP_RIGHT := "vivhite_hip_right"
const THIGH_RIGHT := "vivhite_thigh_right"
const SHIN_RIGHT := "vivhite_shin_right"
const FOOT_RIGHT := "vivhite_foot_right"

# Normalized locations remain authored against the clean EvoLink body master.
# Parent relationships are defined separately in _build_bones; these points
# are also the bind-pose controls used by the single weighted mesh.
const CHAIN_INFLUENCES := [
	{"name": HAIR_CROWN, "p": Vector2(0.50, 0.055)},
	{"name": HAIR_LEFT, "p": Vector2(0.38, 0.12)},
	{"name": HAIR_RIGHT, "p": Vector2(0.62, 0.12)},
	{"name": BUTTERFLY, "p": Vector2(0.67, 0.10)},
	{"name": HEAD, "p": Vector2(0.51, 0.16)},
	{"name": NECK, "p": Vector2(0.50, 0.245)},
	{"name": SHOULDER_LEFT, "p": Vector2(0.35, 0.28)},
	{"name": UPPER_ARM_LEFT, "p": Vector2(0.24, 0.35)},
	{"name": FOREARM_LEFT, "p": Vector2(0.14, 0.43)},
	{"name": HAND_LEFT, "p": Vector2(0.06, 0.49)},
	{"name": SHOULDER_RIGHT, "p": Vector2(0.65, 0.28)},
	{"name": UPPER_ARM_RIGHT, "p": Vector2(0.76, 0.31)},
	{"name": FOREARM_RIGHT, "p": Vector2(0.87, 0.27)},
	{"name": HAND_RIGHT, "p": Vector2(0.96, 0.22)},
	{"name": TORSO_UPPER, "p": Vector2(0.50, 0.32)},
	{"name": TORSO_LOWER, "p": Vector2(0.50, 0.43)},
	{"name": PELVIS, "p": Vector2(0.50, 0.55)},
	{"name": SKIRT_LEFT, "p": Vector2(0.39, 0.54)},
	{"name": SKIRT_CENTER, "p": Vector2(0.50, 0.56)},
	{"name": SKIRT_RIGHT, "p": Vector2(0.61, 0.54)},
	{"name": HIP_LEFT, "p": Vector2(0.44, 0.59)},
	{"name": THIGH_LEFT, "p": Vector2(0.43, 0.66)},
	{"name": SHIN_LEFT, "p": Vector2(0.41, 0.78)},
	{"name": FOOT_LEFT, "p": Vector2(0.39, 0.93)},
	{"name": HIP_RIGHT, "p": Vector2(0.56, 0.59)},
	{"name": THIGH_RIGHT, "p": Vector2(0.57, 0.66)},
	{"name": SHIN_RIGHT, "p": Vector2(0.62, 0.78)},
	{"name": FOOT_RIGHT, "p": Vector2(0.69, 0.93)},
]

const REQUIRED_PARENT_LINKS := {
	TORSO_LOWER: PELVIS,
	TORSO_UPPER: TORSO_LOWER,
	NECK: TORSO_UPPER,
	HEAD: NECK,
	SHOULDER_LEFT: TORSO_UPPER,
	UPPER_ARM_LEFT: SHOULDER_LEFT,
	FOREARM_LEFT: UPPER_ARM_LEFT,
	HAND_LEFT: FOREARM_LEFT,
	SHOULDER_RIGHT: TORSO_UPPER,
	UPPER_ARM_RIGHT: SHOULDER_RIGHT,
	FOREARM_RIGHT: UPPER_ARM_RIGHT,
	HAND_RIGHT: FOREARM_RIGHT,
	THIGH_LEFT: HIP_LEFT,
	SHIN_LEFT: THIGH_LEFT,
	FOOT_LEFT: SHIN_LEFT,
	THIGH_RIGHT: HIP_RIGHT,
	SHIN_RIGHT: THIGH_RIGHT,
	FOOT_RIGHT: SHIN_RIGHT,
}

# Spine 4.2 stores Bezier handles in absolute timeline coordinates. These
# normalized profiles are converted per keyframe segment before serialization.
# Both profiles leave each authored pose exactly where it is while removing the
# constant-speed, hard-corner motion produced by the default linear timeline.
const LOOP_EASING := Vector4(0.25, 0.0, 0.75, 1.0)
const ACTION_EASING := Vector4(0.20, 0.0, 0.68, 1.0)


func _initialize() -> void:
	var args := OS.get_cmdline_user_args()
	if args.is_empty():
		args = PackedStringArray([COMMAND])
	if args[0] in ["-h", "--help", "help"]:
		_print_candidate_help()
		quit(0)
		return
	if args[0] != COMMAND:
		quit(_fail("Unknown command: %s" % args[0]))
		return
	var options := _parse_options(args)
	if options.is_empty() and args.size() > 1:
		quit(2)
		return
	var body_path := _absolute_path(str(options.get("body-source", DEFAULT_BODY_SOURCE)))
	var arc_path := _absolute_path(str(options.get("arc-source", DEFAULT_ARC_SOURCE)))
	var sigil_path := _absolute_path(str(options.get("sigil-source", DEFAULT_SIGIL_SOURCE)))
	var output_root := _absolute_path(str(options.get("output-root", CANDIDATE_OUTPUT_ROOT)))
	if not _build(body_path, arc_path, sigil_path, output_root):
		quit(_fail(_last_error))
		return
	quit(0)


func _print_candidate_help() -> void:
	print("Build the isolated Vivhite whole-mesh hierarchical-bone candidate:")
	print("  godot --headless --path tools/art --script res://candidates/whole_mesh/build_whole_mesh_candidate.gd -- build-combat")
	print("    [--body-source PATH] [--arc-source PATH] [--sigil-source PATH]")
	print("    [--output-root PATH]")


func _build(body_path: String, arc_path: String, sigil_path: String, output_root: String) -> bool:
	if not super._build(body_path, arc_path, sigil_path, output_root):
		return false
	var atlas_path := output_root.path_join(OUTPUT_ATLAS)
	var wrapper = JSON.parse_string(FileAccess.get_file_as_string(atlas_path))
	if not wrapper is Dictionary:
		return _set_error("Candidate atlas wrapper could not be parsed for isolation rewrite")
	wrapper["source_path"] = "%s/vivhite_combat.atlas" % CANDIDATE_RESOURCE_ROOT
	if not _write_text(atlas_path, JSON.stringify(wrapper, "", false) + "\n"):
		return false
	if not _validate_candidate_isolation(output_root):
		return false
	print("  candidate: %s" % output_root)
	print("  hierarchy: torso->neck->head; shoulder->upperarm->forearm->hand; hip->thigh->shin->foot")
	return true


func _build_skeleton_json() -> Dictionary:
	var bones := _build_bones()
	var indices := {}
	var world_positions := _bind_world_positions(bones)
	for index in bones.size():
		indices[str(bones[index]["name"])] = index
	var events := {}
	for event_name: String in REQUIRED_EVENTS:
		events[event_name] = {}
	return {
		"skeleton": {
			"hash": "vivhite-whole-mesh-hierarchical-candidate-v2-motion-eased",
			"spine": SPINE_VERSION,
			"x": SKELETON_BOUNDS.position.x,
			"y": SKELETON_BOUNDS.position.y,
			"width": SKELETON_BOUNDS.size.x,
			"height": SKELETON_BOUNDS.size.y,
			"images": "./",
		},
		"bones": bones,
		"slots": [
			{"name": "vivhite_magic_sigil", "bone": BONE_SIGIL},
			{"name": "vivhite_body", "bone": BONE_RIG, "attachment": BODY_REGION_NAME},
			{"name": "slash_mesh", "bone": BONE_ARC},
			{"name": "eye_attach_slot", "bone": BONE_EYES},
		],
		"skins": [{
			"name": "default",
			"attachments": {
				"vivhite_magic_sigil": {SIGIL_REGION_NAME: _region_attachment(SIGIL_REGION_NAME, 1420.0, 1420.0)},
				"vivhite_body": {BODY_REGION_NAME: _build_weighted_mesh(indices, world_positions)},
				"slash_mesh": {ARC_REGION_NAME: _region_attachment(ARC_REGION_NAME, 1340.0, 900.0)},
			},
		}],
		"events": events,
		"animations": _build_animations(),
	}


func _build_bones() -> Array:
	var worlds := {}
	var result := []
	_append_world_bone(result, worlds, BONE_ROOT, "", Vector2.ZERO)
	_append_world_bone(result, worlds, BONE_SIGIL, BONE_ROOT, _scaled_character_anchor(Vector2(80.0, 960.0)))
	_append_world_bone(result, worlds, BONE_RIG, BONE_ROOT, Vector2.ZERO)

	_append_normalized_bone(result, worlds, PELVIS, BONE_RIG, Vector2(0.50, 0.55))
	_append_normalized_bone(result, worlds, TORSO_LOWER, PELVIS, Vector2(0.50, 0.43))
	_append_normalized_bone(result, worlds, TORSO_UPPER, TORSO_LOWER, Vector2(0.50, 0.32))
	_append_normalized_bone(result, worlds, NECK, TORSO_UPPER, Vector2(0.50, 0.245))
	_append_normalized_bone(result, worlds, HEAD, NECK, Vector2(0.51, 0.16))
	_append_normalized_bone(result, worlds, HAIR_CROWN, HEAD, Vector2(0.50, 0.055))
	_append_normalized_bone(result, worlds, HAIR_LEFT, HEAD, Vector2(0.38, 0.12))
	_append_normalized_bone(result, worlds, HAIR_RIGHT, HEAD, Vector2(0.62, 0.12))
	_append_normalized_bone(result, worlds, BUTTERFLY, HEAD, Vector2(0.67, 0.10))

	_append_normalized_bone(result, worlds, SHOULDER_LEFT, TORSO_UPPER, Vector2(0.35, 0.28))
	_append_normalized_bone(result, worlds, UPPER_ARM_LEFT, SHOULDER_LEFT, Vector2(0.24, 0.35))
	_append_normalized_bone(result, worlds, FOREARM_LEFT, UPPER_ARM_LEFT, Vector2(0.14, 0.43))
	_append_normalized_bone(result, worlds, HAND_LEFT, FOREARM_LEFT, Vector2(0.06, 0.49))
	_append_normalized_bone(result, worlds, SHOULDER_RIGHT, TORSO_UPPER, Vector2(0.65, 0.28))
	_append_normalized_bone(result, worlds, UPPER_ARM_RIGHT, SHOULDER_RIGHT, Vector2(0.76, 0.31))
	_append_normalized_bone(result, worlds, FOREARM_RIGHT, UPPER_ARM_RIGHT, Vector2(0.87, 0.27))
	_append_normalized_bone(result, worlds, HAND_RIGHT, FOREARM_RIGHT, Vector2(0.96, 0.22))

	_append_normalized_bone(result, worlds, SKIRT_LEFT, PELVIS, Vector2(0.39, 0.54))
	_append_normalized_bone(result, worlds, SKIRT_CENTER, PELVIS, Vector2(0.50, 0.56))
	_append_normalized_bone(result, worlds, SKIRT_RIGHT, PELVIS, Vector2(0.61, 0.54))
	_append_normalized_bone(result, worlds, HIP_LEFT, PELVIS, Vector2(0.44, 0.59))
	_append_normalized_bone(result, worlds, THIGH_LEFT, HIP_LEFT, Vector2(0.43, 0.66))
	_append_normalized_bone(result, worlds, SHIN_LEFT, THIGH_LEFT, Vector2(0.41, 0.78))
	_append_normalized_bone(result, worlds, FOOT_LEFT, SHIN_LEFT, Vector2(0.39, 0.93))
	_append_normalized_bone(result, worlds, HIP_RIGHT, PELVIS, Vector2(0.56, 0.59))
	_append_normalized_bone(result, worlds, THIGH_RIGHT, HIP_RIGHT, Vector2(0.57, 0.66))
	_append_normalized_bone(result, worlds, SHIN_RIGHT, THIGH_RIGHT, Vector2(0.62, 0.78))
	_append_normalized_bone(result, worlds, FOOT_RIGHT, SHIN_RIGHT, Vector2(0.69, 0.93))

	# VFX anchors follow the articulated anatomy instead of remaining detached.
	_append_world_bone(result, worlds, BONE_ARC, HAND_RIGHT, _scaled_character_anchor(Vector2(840.0, 1750.0)), -5.0)
	_append_world_bone(result, worlds, BONE_EYES, HEAD, _scaled_character_anchor(Vector2(20.0, 1555.0)))
	return result


func _append_normalized_bone(
	result: Array,
	worlds: Dictionary,
	name: String,
	parent: String,
	normalized: Vector2,
) -> void:
	_append_world_bone(result, worlds, name, parent, _normalized_world_position(normalized))


func _append_world_bone(
	result: Array,
	worlds: Dictionary,
	name: String,
	parent: String,
	world: Vector2,
	rotation := 0.0,
) -> void:
	var bone := {"name": name}
	if not parent.is_empty():
		bone["parent"] = parent
		var parent_world: Vector2 = worlds[parent]
		bone["x"] = world.x - parent_world.x
		bone["y"] = world.y - parent_world.y
	else:
		bone["x"] = world.x
		bone["y"] = world.y
	if not is_zero_approx(rotation):
		bone["rotation"] = rotation
	worlds[name] = world
	result.append(bone)


func _bind_world_positions(bones: Array) -> Dictionary:
	var result := {}
	for bone: Dictionary in bones:
		var local := Vector2(float(bone.get("x", 0.0)), float(bone.get("y", 0.0)))
		var parent := str(bone.get("parent", ""))
		result[str(bone["name"])] = local if parent.is_empty() else (result[parent] as Vector2) + local
	return result


func _nearest_influences(point: Vector2) -> Array:
	var candidates := []
	for spec: Dictionary in CHAIN_INFLUENCES:
		var delta: Vector2 = point - (spec["p"] as Vector2)
		candidates.append({"bone": spec["name"], "distance": delta.length_squared()})
	candidates.sort_custom(func(a: Dictionary, b: Dictionary) -> bool: return a["distance"] < b["distance"])
	var raw := []
	var total := 0.0
	for index in 4:
		var value := 1.0 / maxf(0.00035, float(candidates[index]["distance"]))
		raw.append(value)
		total += value
	var result := []
	for index in 4:
		result.append({"bone": candidates[index]["bone"], "weight": raw[index] / total})
	return result


func _build_animations() -> Dictionary:
	var animations := {
		"idle_loop": _whole_mesh_loop(1.0, 2.0),
		"low_health_loop": _whole_mesh_low_health(),
		"relaxed_loop": _whole_mesh_loop(0.72, 12.000001),
		"attack": _whole_mesh_attack(false),
		"attack_heavy": _whole_mesh_attack(true),
		"cast": _whole_mesh_cast(),
		"hurt": _whole_mesh_hurt(),
		"die": _whole_mesh_die(),
	}
	_apply_natural_easing(animations)
	return animations


func _apply_natural_easing(animations: Dictionary) -> void:
	for animation_name: String in animations:
		var animation: Dictionary = animations[animation_name]
		var profile := LOOP_EASING if animation_name.ends_with("_loop") else ACTION_EASING
		var bones: Dictionary = animation.get("bones", {})
		for bone_name: String in bones:
			var timelines: Dictionary = bones[bone_name]
			for timeline_name: String in ["rotate", "translate"]:
				if timelines.has(timeline_name):
					_add_timeline_easing(timelines[timeline_name], timeline_name, profile)


func _add_timeline_easing(keys: Array, timeline_name: String, profile: Vector4) -> void:
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


func _whole_mesh_loop(strength: float, duration: float) -> Dictionary:
	return {"bones": {
		BONE_RIG: {"translate": _translate_loop(duration, Vector2(0, 0), Vector2(-3, 12 * strength), Vector2(0, 1), Vector2(3, -7 * strength))},
		PELVIS: {"rotate": _rotate_loop(duration, 0, -1.2 * strength, 0, 1.0 * strength)},
		TORSO_LOWER: {"rotate": _rotate_loop(duration, 0, 1.5 * strength, 0, -1.1 * strength)},
		TORSO_UPPER: {"rotate": _rotate_loop(duration, 0, 1.8 * strength, 0, -1.3 * strength)},
		NECK: {"rotate": _rotate_loop(duration, 0, -1.0 * strength, 0, 0.8 * strength)},
		HEAD: {"rotate": _rotate_loop(duration, 0, -1.4 * strength, 0, 1.0 * strength)},
		SHOULDER_LEFT: {"rotate": _rotate_loop(duration, 0, -1.1 * strength, 0, 0.8 * strength)},
		SHOULDER_RIGHT: {"rotate": _rotate_loop(duration, 0, 1.2 * strength, 0, -0.9 * strength)},
		HAIR_LEFT: {"rotate": _rotate_loop(duration, 0, 3.4 * strength, 0, -2.4 * strength)},
		HAIR_RIGHT: {"rotate": _rotate_loop(duration, 0, -3.1 * strength, 0, 2.2 * strength)},
		BUTTERFLY: {"rotate": _rotate_loop(duration, 0, -4.0 * strength, 0, 2.8 * strength)},
		SKIRT_LEFT: {"rotate": _rotate_loop(duration, 0, -2.0 * strength, 0, 1.4 * strength)},
		SKIRT_RIGHT: {"rotate": _rotate_loop(duration, 0, 2.0 * strength, 0, -1.4 * strength)},
	}}


func _whole_mesh_low_health() -> Dictionary:
	var duration := float(ANIMATION_DURATIONS["low_health_loop"])
	return {"bones": {
		BONE_RIG: {"translate": _translate_loop(duration, Vector2(0, -18), Vector2(-5, -31), Vector2(0, -20), Vector2(4, -28))},
		PELVIS: {"rotate": _rotate_loop(duration, -3, -4.5, -3, -4.0)},
		TORSO_LOWER: {"rotate": _rotate_loop(duration, -5, -7.5, -5, -6.8)},
		TORSO_UPPER: {"rotate": _rotate_loop(duration, -7, -10.0, -7, -9.0)},
		NECK: {"rotate": _rotate_loop(duration, 3, 5.0, 3, 4.2)},
		HEAD: {"rotate": _rotate_loop(duration, 5, 7.5, 5, 6.4)},
		SHOULDER_LEFT: {"rotate": _rotate_loop(duration, 5, 8, 5, 7)},
		SHOULDER_RIGHT: {"rotate": _rotate_loop(duration, -5, -8, -5, -7)},
		HAIR_LEFT: {"rotate": _rotate_loop(duration, 0, 2.6, 0, -1.8)},
		HAIR_RIGHT: {"rotate": _rotate_loop(duration, 0, -2.4, 0, 1.7)},
	}}


func _whole_mesh_attack(heavy: bool) -> Dictionary:
	var name := "attack_heavy" if heavy else "attack"
	var duration := float(ANIMATION_DURATIONS[name])
	var strike := float(EVENT_TIMES["heavy_slash_start" if heavy else "attack_slash_start"])
	var anticipation := strike * 0.45
	var recoil := duration * (0.43 if heavy else 0.38)
	var recover := duration * 0.76
	var power := 1.55 if heavy else 1.0
	# Directional forward peaks are authored directly instead of inferred from
	# anticipation-to-strike range: 100/158 units become 28.0/44.24 px at the
	# unchanged 0.28 combat-scene scale.
	var root_anticipation_x := -34.0 if heavy else -22.0
	var root_strike_x := 158.0 if heavy else 100.0
	var root_recoil_x := 88.0 if heavy else 55.0
	return {
		"slots": {"slash_mesh": {"attachment": [
			{"time": 0.0, "name": null},
			{"time": strike, "name": ARC_REGION_NAME},
			{"time": recover, "name": null},
		]}},
		"bones": {
			BONE_RIG: {"translate": [
				{"time": 0.0, "x": 0.0, "y": 0.0},
				{"time": anticipation, "x": root_anticipation_x, "y": -9.0 * power},
				{"time": strike, "x": root_strike_x, "y": 27.0 * power},
				{"time": recoil, "x": root_recoil_x, "y": 10.0 * power},
				{"time": recover, "x": 12.0, "y": 2.0},
				{"time": duration, "x": 0.0, "y": 0.0},
			]},
			PELVIS: {"rotate": _action_pose(duration, anticipation, strike, recoil, recover, -5 * power, 8 * power, 3 * power)},
			TORSO_LOWER: {"rotate": _action_pose(duration, anticipation, strike, recoil, recover, -8 * power, 14 * power, 6 * power)},
			TORSO_UPPER: {"rotate": _action_pose(duration, anticipation, strike, recoil, recover, -11 * power, 21 * power, 8 * power)},
			NECK: {"rotate": _action_pose(duration, anticipation, strike, recoil, recover, 5 * power, -10 * power, -3 * power)},
			HEAD: {"rotate": _action_pose(duration, anticipation, strike, recoil, recover, 7 * power, -13 * power, -4 * power)},
			SHOULDER_RIGHT: {"rotate": _action_pose(duration, anticipation, strike, recoil, recover, -14 * power, 29 * power, 11 * power)},
			UPPER_ARM_RIGHT: {"rotate": _action_pose(duration, anticipation, strike, recoil, recover, -18 * power, 39 * power, 15 * power)},
			FOREARM_RIGHT: {"rotate": _action_pose(duration, anticipation, strike, recoil, recover, -24 * power, 52 * power, 18 * power)},
			HAND_RIGHT: {"rotate": _action_pose(duration, anticipation, strike, recoil, recover, -13 * power, 28 * power, 9 * power)},
			SHOULDER_LEFT: {"rotate": _action_pose(duration, anticipation, strike, recoil, recover, 7 * power, -15 * power, -5 * power)},
			HIP_LEFT: {"rotate": _action_pose(duration, anticipation, strike, recoil, recover, 3 * power, -7 * power, -2 * power)},
			HIP_RIGHT: {"rotate": _action_pose(duration, anticipation, strike, recoil, recover, -3 * power, 8 * power, 3 * power)},
			SHIN_LEFT: {"rotate": _action_pose(duration, anticipation, strike, recoil, recover, -2 * power, 6 * power, 2 * power)},
			HAIR_LEFT: {"rotate": _action_pose(duration, anticipation, strike, recoil, recover, 3 * power, -12 * power, -7 * power)},
			HAIR_RIGHT: {"rotate": _action_pose(duration, anticipation, strike, recoil, recover, -3 * power, 14 * power, 8 * power)},
			SKIRT_LEFT: {"rotate": _action_pose(duration, anticipation, strike, recoil, recover, 2 * power, -9 * power, -5 * power)},
			SKIRT_RIGHT: {"rotate": _action_pose(duration, anticipation, strike, recoil, recover, -2 * power, 11 * power, 6 * power)},
			BONE_ARC: {"rotate": _action_pose(duration, anticipation, strike, recoil, recover, -20 * power, 42 * power, 15 * power)},
		},
		"events": [
			{"time": strike, "name": "heavy_slash_start" if heavy else "attack_slash_start"},
			{"time": recover, "name": "clear_vfx"},
		],
	}


func _whole_mesh_cast() -> Dictionary:
	var duration := float(ANIMATION_DURATIONS["cast"])
	var start := float(EVENT_TIMES["cast_eyes_start"])
	var anticipation := 0.11
	var crest := 0.48
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
				{"time": anticipation, "x": -5.0, "y": -9.0},
				{"time": start, "x": 6.0, "y": 38.0},
				{"time": crest, "x": 10.0, "y": 53.0},
				{"time": clear, "x": 3.0, "y": 17.0},
				{"time": duration, "x": 0.0, "y": 0.0},
			]},
			PELVIS: {"rotate": _cast_pose(duration, anticipation, start, crest, clear, -3, 5, 3)},
			TORSO_LOWER: {"rotate": _cast_pose(duration, anticipation, start, crest, clear, -5, 8, 5)},
			TORSO_UPPER: {"rotate": _cast_pose(duration, anticipation, start, crest, clear, -7, 12, 8)},
			NECK: {"rotate": _cast_pose(duration, anticipation, start, crest, clear, 3, -6, -4)},
			HEAD: {"rotate": _cast_pose(duration, anticipation, start, crest, clear, 5, -9, -6)},
			SHOULDER_LEFT: {"rotate": _cast_pose(duration, anticipation, start, crest, clear, 4, -25, -19)},
			UPPER_ARM_LEFT: {"rotate": _cast_pose(duration, anticipation, start, crest, clear, 7, -39, -30)},
			FOREARM_LEFT: {"rotate": _cast_pose(duration, anticipation, start, crest, clear, 9, -48, -36)},
			HAND_LEFT: {"rotate": _cast_pose(duration, anticipation, start, crest, clear, 3, -22, -14)},
			SHOULDER_RIGHT: {"rotate": _cast_pose(duration, anticipation, start, crest, clear, -4, 25, 19)},
			UPPER_ARM_RIGHT: {"rotate": _cast_pose(duration, anticipation, start, crest, clear, -7, 39, 30)},
			FOREARM_RIGHT: {"rotate": _cast_pose(duration, anticipation, start, crest, clear, -9, 48, 36)},
			HAND_RIGHT: {"rotate": _cast_pose(duration, anticipation, start, crest, clear, -3, 22, 14)},
			HAIR_LEFT: {"rotate": _cast_pose(duration, anticipation, start, crest, clear, 0, 10, 15)},
			HAIR_RIGHT: {"rotate": _cast_pose(duration, anticipation, start, crest, clear, 0, -10, -15)},
			SKIRT_LEFT: {"rotate": _cast_pose(duration, anticipation, start, crest, clear, 0, 8, 12)},
			SKIRT_RIGHT: {"rotate": _cast_pose(duration, anticipation, start, crest, clear, 0, -8, -12)},
			BONE_SIGIL: {"rotate": [
				{"time": 0.0, "value": -12.0},
				{"time": start, "value": 6.0},
				{"time": crest, "value": 31.0},
				{"time": clear, "value": 52.0},
				{"time": duration, "value": -12.0},
			]},
		},
		"events": [
			{"time": start, "name": "cast_eyes_start"},
			{"time": clear, "name": "clear_vfx"},
		],
	}


func _whole_mesh_hurt() -> Dictionary:
	var duration := float(ANIMATION_DURATIONS["hurt"])
	return {"bones": {
		BONE_RIG: {"translate": [
			{"time": 0.0, "x": 0.0, "y": 0.0},
			{"time": 0.10, "x": -100.0, "y": -28.0},
			{"time": 0.24, "x": -63.0, "y": -15.0},
			{"time": 0.48, "x": 24.0, "y": 8.0},
			{"time": 0.72, "x": 8.0, "y": 2.0},
			{"time": duration, "x": 0.0, "y": 0.0},
		]},
		PELVIS: {"rotate": _hurt_pose(duration, -9, 4)},
		TORSO_LOWER: {"rotate": _hurt_pose(duration, -16, 7)},
		TORSO_UPPER: {"rotate": _hurt_pose(duration, -23, 10)},
		NECK: {"rotate": _hurt_pose(duration, 9, -4)},
		HEAD: {"rotate": _hurt_pose(duration, 17, -7)},
		SHOULDER_LEFT: {"rotate": _hurt_pose(duration, 15, -6)},
		SHOULDER_RIGHT: {"rotate": _hurt_pose(duration, -15, 6)},
		UPPER_ARM_LEFT: {"rotate": _hurt_pose(duration, 18, -7)},
		UPPER_ARM_RIGHT: {"rotate": _hurt_pose(duration, -18, 7)},
		HAIR_LEFT: {"rotate": _hurt_pose(duration, 22, -9)},
		HAIR_RIGHT: {"rotate": _hurt_pose(duration, 25, -10)},
	}, "events": [{"time": 0.72, "name": "clear_vfx"}]}


func _whole_mesh_die() -> Dictionary:
	var duration := float(ANIMATION_DURATIONS["die"])
	return {"bones": {
		BONE_RIG: {
			"translate": [
				{"time": 0.0, "x": 0.0, "y": 0.0},
				{"time": 0.18, "x": -17.0, "y": 10.0},
				{"time": 0.46, "x": -30.0, "y": -28.0},
				{"time": 0.82, "x": -13.0, "y": -86.0},
				{"time": 1.24, "x": 14.0, "y": -151.0},
				{"time": 1.78, "x": 48.0, "y": -218.0},
				{"time": 2.08, "x": 79.0, "y": -253.0},
				{"time": duration, "x": 72.0, "y": -244.0},
			],
			"rotate": _death_pose(duration, 0, -2, -6, -11, -17, -23, -26),
		},
		PELVIS: {"rotate": _death_pose(duration, 0, -3, -8, -13, -18, -22, -24)},
		TORSO_LOWER: {"rotate": _death_pose(duration, 0, -5, -13, -22, -30, -37, -41)},
		TORSO_UPPER: {"rotate": _death_pose(duration, 0, -7, -18, -31, -43, -50, -54)},
		NECK: {"rotate": _death_pose(duration, 0, 3, 8, 14, 19, 22, 24)},
		HEAD: {"rotate": _death_pose(duration, 0, 6, 15, 25, 34, 39, 42)},
		SHOULDER_LEFT: {"rotate": _death_pose(duration, 0, 5, 14, 23, 31, 36, 39)},
		UPPER_ARM_LEFT: {"rotate": _death_pose(duration, 0, 8, 21, 35, 48, 56, 60)},
		FOREARM_LEFT: {"rotate": _death_pose(duration, 0, 11, 28, 45, 59, 67, 71)},
		SHOULDER_RIGHT: {"rotate": _death_pose(duration, 0, -5, -13, -22, -30, -35, -38)},
		UPPER_ARM_RIGHT: {"rotate": _death_pose(duration, 0, -8, -20, -34, -46, -54, -58)},
		FOREARM_RIGHT: {"rotate": _death_pose(duration, 0, -10, -26, -42, -56, -64, -68)},
		HIP_LEFT: {"rotate": _death_pose(duration, 0, -3, -9, -17, -27, -36, -40)},
		THIGH_LEFT: {"rotate": _death_pose(duration, 0, 5, 14, 26, 39, 49, 54)},
		SHIN_LEFT: {"rotate": _death_pose(duration, 0, -8, -21, -36, -51, -62, -67)},
		FOOT_LEFT: {"rotate": _death_pose(duration, 0, 3, 8, 14, 20, 24, 26)},
		HIP_RIGHT: {"rotate": _death_pose(duration, 0, 4, 11, 20, 31, 39, 43)},
		THIGH_RIGHT: {"rotate": _death_pose(duration, 0, -5, -14, -26, -39, -49, -54)},
		SHIN_RIGHT: {"rotate": _death_pose(duration, 0, 8, 21, 36, 51, 62, 67)},
		FOOT_RIGHT: {"rotate": _death_pose(duration, 0, -3, -8, -14, -20, -24, -26)},
		HAIR_LEFT: {"rotate": _death_pose(duration, 0, 4, 12, 24, 38, 51, 58)},
		HAIR_RIGHT: {"rotate": _death_pose(duration, 0, 5, 15, 29, 45, 59, 66)},
		SKIRT_LEFT: {"rotate": _death_pose(duration, 0, 3, 10, 19, 30, 40, 45)},
		SKIRT_RIGHT: {"rotate": _death_pose(duration, 0, -3, -10, -19, -30, -40, -45)},
	}, "events": [{"time": 0.0, "name": "clear_vfx"}]}


func _action_pose(
	duration: float,
	anticipation_time: float,
	strike_time: float,
	recoil_time: float,
	recover_time: float,
	anticipation: float,
	strike: float,
	recoil: float,
) -> Array:
	return [
		{"time": 0.0, "value": 0.0},
		{"time": anticipation_time, "value": anticipation},
		{"time": strike_time, "value": strike},
		{"time": recoil_time, "value": recoil},
		{"time": recover_time, "value": strike * 0.12},
		{"time": duration, "value": 0.0},
	]


func _cast_pose(
	duration: float,
	anticipation_time: float,
	start_time: float,
	crest_time: float,
	clear_time: float,
	anticipation: float,
	start: float,
	crest: float,
) -> Array:
	return [
		{"time": 0.0, "value": 0.0},
		{"time": anticipation_time, "value": anticipation},
		{"time": start_time, "value": start},
		{"time": crest_time, "value": crest},
		{"time": clear_time, "value": crest * 0.24},
		{"time": duration, "value": 0.0},
	]


func _hurt_pose(duration: float, impact: float, rebound: float) -> Array:
	return [
		{"time": 0.0, "value": 0.0},
		{"time": 0.10, "value": impact},
		{"time": 0.24, "value": impact * 0.72},
		{"time": 0.48, "value": rebound},
		{"time": 0.72, "value": rebound * 0.30},
		{"time": duration, "value": 0.0},
	]


func _death_pose(
	duration: float,
	start: float,
	recoil: float,
	buckle: float,
	kneel: float,
	fall: float,
	settle: float,
	end: float,
) -> Array:
	return [
		{"time": 0.0, "value": start},
		{"time": 0.18, "value": recoil},
		{"time": 0.46, "value": buckle},
		{"time": 0.82, "value": kneel},
		{"time": 1.24, "value": fall},
		{"time": 1.78, "value": settle},
		{"time": 2.08, "value": end + (end - settle) * 0.35},
		{"time": duration, "value": end},
	]


func _build_skeleton_data_tres() -> String:
	return """[gd_resource type="SpineSkeletonDataResource" load_steps=13 format=3]

[ext_resource type="SpineAtlasResource" path="res://tools/candidates/whole_mesh/vivhite_combat.spatlas" id="1_atlas"]
[ext_resource type="SpineSkeletonFileResource" path="res://tools/candidates/whole_mesh/vivhite_combat.spjson" id="2_skeleton"]

[sub_resource type="SpineAnimationMix" id="Mix_idle_attack"]
from = "idle_loop"
to = "attack"
mix = 0.1

[sub_resource type="SpineAnimationMix" id="Mix_attack_attack"]
from = "attack"
to = "attack"

[sub_resource type="SpineAnimationMix" id="Mix_hurt_hurt"]
from = "hurt"
to = "hurt"

[sub_resource type="SpineAnimationMix" id="Mix_hurt_die"]
from = "hurt"
to = "die"

[sub_resource type="SpineAnimationMix" id="Mix_idle_hurt"]
from = "idle_loop"
to = "hurt"
mix = 0.03

[sub_resource type="SpineAnimationMix" id="Mix_hurt_idle"]
from = "hurt"
to = "idle_loop"
mix = 0.1

[sub_resource type="SpineAnimationMix" id="Mix_idle_heavy"]
from = "idle_loop"
to = "attack_heavy"
mix = 0.02

[sub_resource type="SpineAnimationMix" id="Mix_heavy_heavy"]
from = "attack_heavy"
to = "attack_heavy"

[sub_resource type="SpineAnimationMix" id="Mix_attack_heavy"]
from = "attack"
to = "attack_heavy"

[sub_resource type="SpineAnimationMix" id="Mix_heavy_attack"]
from = "attack_heavy"
to = "attack"

[resource]
atlas_res = ExtResource("1_atlas")
skeleton_file_res = ExtResource("2_skeleton")
default_mix = 0.05
animation_mixes = [SubResource("Mix_idle_attack"), SubResource("Mix_attack_attack"), SubResource("Mix_hurt_hurt"), SubResource("Mix_hurt_die"), SubResource("Mix_idle_hurt"), SubResource("Mix_hurt_idle"), SubResource("Mix_idle_heavy"), SubResource("Mix_heavy_heavy"), SubResource("Mix_attack_heavy"), SubResource("Mix_heavy_attack")]
"""


func _validate_rig(skeleton: Dictionary, atlas_data: String) -> bool:
	if not super._validate_rig(skeleton, atlas_data):
		return false
	var parents := {}
	var bone_names := {}
	for bone: Dictionary in skeleton["bones"]:
		var name := str(bone["name"])
		bone_names[name] = true
		parents[name] = str(bone.get("parent", ""))
	for child: String in REQUIRED_PARENT_LINKS:
		if str(parents.get(child, "<missing>")) != str(REQUIRED_PARENT_LINKS[child]):
			return _set_error("Whole-mesh candidate hierarchy requires %s -> %s" % [REQUIRED_PARENT_LINKS[child], child])
	for spec: Dictionary in CHAIN_INFLUENCES:
		if not bone_names.has(str(spec["name"])):
			return _set_error("Whole-mesh influence bone is missing: %s" % spec["name"])
	var body_attachments: Dictionary = skeleton["skins"][0]["attachments"]["vivhite_body"]
	if body_attachments.size() != 1 or not body_attachments.has(BODY_REGION_NAME):
		return _set_error("Whole-mesh candidate must contain exactly one body attachment")
	for animation_name: String in ANIMATION_DURATIONS:
		if skeleton["animations"][animation_name].get("slots", {}).has("vivhite_body"):
			return _set_error("Whole-mesh candidate may not switch body attachments in %s" % animation_name)
	if _translation_axis_range(skeleton["animations"]["idle_loop"], BONE_RIG, "y") < 18.0:
		return _set_error("Whole-mesh idle amplitude regressed below 18 authored units")
	var attack_forward := _translation_axis_directional_peak(skeleton["animations"]["attack"], BONE_RIG, "x", true)
	if attack_forward < 95.0 or attack_forward > 105.0:
		return _set_error("Whole-mesh attack forward peak must remain within 95-105 authored units")
	var heavy_forward := _translation_axis_directional_peak(skeleton["animations"]["attack_heavy"], BONE_RIG, "x", true)
	if heavy_forward < 150.0 or heavy_forward > 165.0:
		return _set_error("Whole-mesh heavy forward peak must remain within 150-165 authored units")
	if _translation_axis_range(skeleton["animations"]["cast"], BONE_RIG, "y") < 60.0:
		return _set_error("Whole-mesh cast amplitude regressed below 60 authored units")
	if _translation_axis_directional_peak(skeleton["animations"]["hurt"], BONE_RIG, "x", false) < 95.0:
		return _set_error("Whole-mesh hurt backward peak regressed below 95 authored units")
	if skeleton["animations"]["die"]["bones"][BONE_RIG]["translate"].size() < 7:
		return _set_error("Whole-mesh die must retain at least seven staged root poses")
	return true


func _translation_axis_range(animation: Dictionary, bone_name: String, axis: String) -> float:
	var minimum := INF
	var maximum := -INF
	for key: Dictionary in animation["bones"][bone_name]["translate"]:
		var value := float(key.get(axis, 0.0))
		minimum = minf(minimum, value)
		maximum = maxf(maximum, value)
	return maximum - minimum


func _translation_axis_directional_peak(
	animation: Dictionary,
	bone_name: String,
	axis: String,
	positive: bool,
) -> float:
	var peak := 0.0
	for key: Dictionary in animation["bones"][bone_name]["translate"]:
		var value := float(key.get(axis, 0.0))
		peak = maxf(peak, value if positive else -value)
	return peak


func _validate_written(output_root: String) -> bool:
	var page := Image.load_from_file(output_root.path_join(OUTPUT_PAGE))
	if page == null or page.is_empty() or page.get_size() != ATLAS_SIZE or page.get_format() != Image.FORMAT_RGBA8:
		return _set_error("Written whole-mesh atlas is not 3072x2304 RGBA8")
	var decoded = JSON.parse_string(FileAccess.get_file_as_string(output_root.path_join(OUTPUT_JSON)))
	if not decoded is Dictionary:
		return _set_error("Written whole-mesh Spine JSON could not be parsed")
	var atlas_decoded = JSON.parse_string(FileAccess.get_file_as_string(output_root.path_join(OUTPUT_ATLAS)))
	if not atlas_decoded is Dictionary:
		return _set_error("Written whole-mesh atlas wrapper could not be parsed")
	if not _validate_rig(decoded, str(atlas_decoded.get("atlas_data", ""))):
		return false
	var tres := FileAccess.get_file_as_string(output_root.path_join(OUTPUT_DATA))
	for required: String in [
		"res://tools/candidates/whole_mesh/vivhite_combat.spatlas",
		"res://tools/candidates/whole_mesh/vivhite_combat.spjson",
	]:
		if not tres.contains(required):
			return _set_error("Written whole-mesh skeleton-data wrapper is missing %s" % required)
	return true


func _validate_candidate_isolation(output_root: String) -> bool:
	var files := PackedStringArray()
	for file_name: String in DirAccess.get_files_at(output_root):
		# Godot may create ignored import metadata after the runtime-loading
		# validator runs. It is cache, not part of the candidate's logical bundle.
		if file_name.ends_with(".uid") or file_name.ends_with(".import"):
			continue
		files.append(file_name)
	var expected := PackedStringArray([OUTPUT_JSON, OUTPUT_ATLAS, OUTPUT_PAGE, OUTPUT_DATA])
	files.sort()
	expected.sort()
	if files != expected:
		return _set_error("Whole-mesh output must be a self-contained four-file directory; got %s" % files)
	for file_name: String in expected:
		var path := output_root.path_join(file_name)
		if not FileAccess.file_exists(path):
			return _set_error("Whole-mesh output is missing %s" % path)
	for text_name: String in [OUTPUT_JSON, OUTPUT_ATLAS, OUTPUT_DATA]:
		var text := FileAccess.get_file_as_string(output_root.path_join(text_name))
		if text.contains("res://Vivhite/skins/ironclad/spine/combat"):
			return _set_error("Whole-mesh candidate leaked a runtime combat path in %s" % text_name)
	var wrapper = JSON.parse_string(FileAccess.get_file_as_string(output_root.path_join(OUTPUT_ATLAS)))
	if str(wrapper.get("source_path", "")) != "%s/vivhite_combat.atlas" % CANDIDATE_RESOURCE_ROOT:
		return _set_error("Whole-mesh atlas wrapper is not candidate-local")
	return true
