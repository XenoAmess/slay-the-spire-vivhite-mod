extends SceneTree

## Loads and samples the isolated candidate with the real game-compatible
## Spine GDExtension. This is intentionally headless and never opens, focuses,
## deploys to, or controls Slay the Spire 2.

const DATA_PATH := "res://tools/candidates/whole_mesh/vivhite_combat_skeleton_data.tres"
const JSON_PATH := "res://tools/candidates/whole_mesh/vivhite_combat.spjson"
const ATLAS_PATH := "res://tools/candidates/whole_mesh/vivhite_combat.spatlas"
const DEATH_PAGE_PATH := "res://tools/candidates/whole_mesh/vivhite_combat_death.png"
const DEATH_SLOT := "vivhite_death_body"
const DEATH_BONE := "vivhite_death_pose"
const DEATH_REGION := "vivhite_combat_death_side"
const DEATH_PREP_TIME := 0.94
const DEATH_PRE_SWAP_TIME := 1.0499
const DEATH_SWAP_TIME := 1.05
const DEATH_CONTACT_TIME := 1.1666667
const DEATH_REBOUND_TIME := 1.30
const DEATH_SETTLE_TIME := 1.80
const DEATH_SETUP_Y := 188.0
const DEATH_SOLID_CONTACT_SHIFT := 224.8
const DEATH_SWAP_OFFSET_Y := 298.8
const DEATH_SWAP_WORLD_Y := 486.8
const EXPECTED_ANIMATIONS := {
	"attack": 1.1666667,
	"attack_heavy": 1.5333334,
	"cast": 1.5666667,
	"die": 2.3333335,
	"hurt": 1.0,
	"idle_loop": 2.0,
	"low_health_loop": 1.4666667,
	"relaxed_loop": 12.000001,
}
const REQUIRED_PARENTS := {
	"vivhite_torso_lower": "vivhite_pelvis",
	"vivhite_torso_upper": "vivhite_torso_lower",
	"vivhite_neck": "vivhite_torso_upper",
	"vivhite_head": "vivhite_neck",
	"vivhite_upper_arm_left": "vivhite_shoulder_left",
	"vivhite_forearm_left": "vivhite_upper_arm_left",
	"vivhite_hand_left": "vivhite_forearm_left",
	"vivhite_upper_arm_right": "vivhite_shoulder_right",
	"vivhite_forearm_right": "vivhite_upper_arm_right",
	"vivhite_hand_right": "vivhite_forearm_right",
	"vivhite_thigh_left": "vivhite_hip_left",
	"vivhite_shin_left": "vivhite_thigh_left",
	"vivhite_foot_left": "vivhite_shin_left",
	"vivhite_thigh_right": "vivhite_hip_right",
	"vivhite_shin_right": "vivhite_thigh_right",
	"vivhite_foot_right": "vivhite_shin_right",
}
const REQUIRED_SLOTS := ["slash_mesh", "eye_attach_slot", DEATH_SLOT]
const REQUIRED_EVENTS := ["attack_slash_start", "heavy_slash_start", "cast_eyes_start", "clear_vfx"]
const SCENE_SCALE := 0.28
const ATTACK_FORWARD_MIN := 95.0
const ATTACK_FORWARD_MAX := 105.0
const HEAVY_FORWARD_MIN := 150.0
const HEAVY_FORWARD_MAX := 165.0
const HURT_BACKWARD_MIN := 95.0

var _errors: Array[String] = []


func _initialize() -> void:
	call_deferred("_run")


func _run() -> void:
	for type_name: String in ["SpineSprite", "SpineSkeletonDataResource", "SpineSkeletonFileResource", "SpineAtlasResource"]:
		if not ClassDB.class_exists(type_name):
			_errors.append("Game-compatible Spine class is unavailable: %s" % type_name)
	if not _errors.is_empty():
		_finish({})
		return

	var parsed = JSON.parse_string(FileAccess.get_file_as_string(JSON_PATH))
	if not parsed is Dictionary:
		_errors.append("Candidate Spine JSON is unreadable: %s" % JSON_PATH)
		_finish({})
		return
	_validate_raw_contract(parsed)
	_validate_atlas_contract()

	var data: Resource = ResourceLoader.load(DATA_PATH)
	if data == null or not data.is_class("SpineSkeletonDataResource"):
		_errors.append("Spine runtime could not load candidate data: %s" % DATA_PATH)
		_finish({})
		return
	if str(data.call("get_version")) != "4.2.43":
		_errors.append("Spine runtime reported version %s, expected 4.2.43" % data.call("get_version"))
	for animation_name: String in EXPECTED_ANIMATIONS:
		var animation: Object = data.call("find_animation", animation_name)
		if animation == null:
			_errors.append("Spine runtime is missing animation %s" % animation_name)
			continue
		var duration := float(animation.call("get_duration"))
		if absf(duration - float(EXPECTED_ANIMATIONS[animation_name])) > 0.00001:
			_errors.append("Spine runtime duration mismatch for %s: %.7f" % [animation_name, duration])
	for slot_name: String in REQUIRED_SLOTS:
		if data.call("find_slot", slot_name) == null:
			_errors.append("Spine runtime is missing slot %s" % slot_name)
	for event_name: String in REQUIRED_EVENTS:
		if data.call("find_event", event_name) == null:
			_errors.append("Spine runtime is missing event %s" % event_name)

	var sampled := []
	for animation_name: String in EXPECTED_ANIMATIONS:
		if _sample_animation(data, animation_name, float(EXPECTED_ANIMATIONS[animation_name])):
			sampled.append(animation_name)

	var metrics := _motion_metrics(parsed)
	metrics["bone_count"] = data.call("get_bones").size()
	metrics["runtime_animation_count"] = data.call("get_animations").size()
	metrics["runtime_event_count"] = data.call("get_events").size()
	metrics["runtime_slot_count"] = data.call("get_slots").size()
	metrics["sampled_animations"] = sampled
	metrics["spine_version"] = str(data.call("get_version"))
	_finish(metrics)


func _validate_raw_contract(skeleton: Dictionary) -> void:
	var parents := {}
	var bones_by_name := {}
	var slot_bones := {}
	for bone: Dictionary in skeleton.get("bones", []):
		parents[str(bone.get("name", ""))] = str(bone.get("parent", ""))
		bones_by_name[str(bone.get("name", ""))] = bone
	for slot: Dictionary in skeleton.get("slots", []):
		slot_bones[str(slot.get("name", ""))] = str(slot.get("bone", ""))
	for child: String in REQUIRED_PARENTS:
		if str(parents.get(child, "<missing>")) != str(REQUIRED_PARENTS[child]):
			_errors.append("Hierarchy mismatch: %s must directly parent %s" % [REQUIRED_PARENTS[child], child])
	var body_attachments: Dictionary = skeleton["skins"][0]["attachments"]["vivhite_body"]
	if body_attachments.size() != 1 or not body_attachments.has("vivhite_combat_body"):
		_errors.append("Candidate does not retain exactly one standing full-body mesh attachment")
	var death_attachments: Dictionary = skeleton["skins"][0]["attachments"].get(DEATH_SLOT, {})
	if death_attachments.size() != 1 or not death_attachments.has(DEATH_REGION):
		_errors.append("Candidate does not contain exactly one isolated side-collapse attachment")
	elif str(death_attachments[DEATH_REGION].get("type", "region")) != "region":
		_errors.append("Side-collapse attachment is not a rigid region")
	if str(slot_bones.get(DEATH_SLOT, "<missing>")) != DEATH_BONE:
		_errors.append("Side-collapse slot is not bound to its isolated death-pose bone")
	if not bones_by_name.has(DEATH_BONE):
		_errors.append("Side-collapse death-pose bone is missing")
	elif absf(float(bones_by_name[DEATH_BONE].get("y", 0.0)) - DEATH_SETUP_Y) > 0.00001:
		_errors.append("Death-pose setup y no longer includes the -224.8-unit solid-contact shift")
	for animation_name: String in EXPECTED_ANIMATIONS:
		if animation_name == "die":
			continue
		var slots: Dictionary = skeleton["animations"][animation_name].get("slots", {})
		if slots.has("vivhite_body") or slots.has(DEATH_SLOT):
			_errors.append("Only die may drive the standing/death attachment swap; found %s" % animation_name)
	_validate_death_swap(skeleton["animations"]["die"])
	_validate_death_preswap_pose(skeleton["animations"]["die"])
	_validate_death_landing_alignment(skeleton["animations"]["die"])
	var die_events: Array = skeleton["animations"]["die"].get("events", [])
	var clear_at_zero := false
	for event: Dictionary in die_events:
		if str(event.get("name", "")) == "clear_vfx" and is_zero_approx(float(event.get("time", -1.0))):
			clear_at_zero = true
	if not clear_at_zero:
		_errors.append("die must emit clear_vfx at t=0")

	var attack_forward := _axis_directional_peak(skeleton["animations"]["attack"], "vivhite_rig", "x", true)
	if attack_forward < ATTACK_FORWARD_MIN or attack_forward > ATTACK_FORWARD_MAX:
		_errors.append("attack forward root peak %.3f is outside 95-105 Spine units" % attack_forward)
	var heavy_forward := _axis_directional_peak(skeleton["animations"]["attack_heavy"], "vivhite_rig", "x", true)
	if heavy_forward < HEAVY_FORWARD_MIN or heavy_forward > HEAVY_FORWARD_MAX:
		_errors.append("attack_heavy forward root peak %.3f is outside 150-165 Spine units" % heavy_forward)
	var hurt_backward := _axis_directional_peak(skeleton["animations"]["hurt"], "vivhite_rig", "x", false)
	if hurt_backward < HURT_BACKWARD_MIN:
		_errors.append("hurt backward root peak %.3f is below 95 Spine units" % hurt_backward)
	_validate_easing_contract(skeleton)


func _validate_death_swap(animation: Dictionary) -> void:
	var slots: Dictionary = animation.get("slots", {})
	if not slots.has("vivhite_body") or not slots.has(DEATH_SLOT):
		_errors.append("die does not drive both standing and side-collapse slots")
		return
	var standing: Dictionary = slots["vivhite_body"]
	var collapse: Dictionary = slots[DEATH_SLOT]
	var standing_attachments: Array = standing.get("attachment", [])
	var collapse_attachments: Array = collapse.get("attachment", [])
	if standing_attachments.size() != 2 or collapse_attachments.size() != 2:
		_errors.append("die attachment swap does not have exactly two keys per slot")
		return
	if absf(float(standing_attachments[0].get("time", 0.0))) > 0.00001:
		_errors.append("Standing mesh setup key is not at t=0")
	if str(standing_attachments[0].get("name", "")) != "vivhite_combat_body":
		_errors.append("Standing mesh setup key uses the wrong attachment")
	if absf(float(standing_attachments[1].get("time", -1.0)) - DEATH_SWAP_TIME) > 0.00001:
		_errors.append("Standing mesh does not detach atomically at %.2f" % DEATH_SWAP_TIME)
	if standing_attachments[1].get("name", "sentinel") != null:
		_errors.append("Standing mesh detach key is not null")
	if absf(float(collapse_attachments[0].get("time", 0.0))) > 0.00001:
		_errors.append("Side-collapse empty setup key is not at t=0")
	if collapse_attachments[0].get("name", "sentinel") != null:
		_errors.append("Side-collapse setup key must be null")
	if absf(float(collapse_attachments[1].get("time", -1.0)) - DEATH_SWAP_TIME) > 0.00001:
		_errors.append("Side-collapse art does not attach atomically at %.2f" % DEATH_SWAP_TIME)
	if str(collapse_attachments[1].get("name", "")) != DEATH_REGION:
		_errors.append("Side-collapse attachment key uses the wrong region")
	if standing.has("rgba") or collapse.has("rgba"):
		_errors.append("Atomic death swap must not contain RGBA crossfade timelines")


func _validate_death_preswap_pose(animation: Dictionary) -> void:
	var bones: Dictionary = animation.get("bones", {})
	if not bones.has("vivhite_rig"):
		_errors.append("die is missing the weighted-mesh root timeline")
		return
	var root_translate: Array = bones["vivhite_rig"].get("translate", [])
	var root_rotate: Array = bones["vivhite_rig"].get("rotate", [])
	var prep_x = _axis_value_at_time(root_translate, DEATH_PREP_TIME, "x")
	var prep_y = _axis_value_at_time(root_translate, DEATH_PREP_TIME, "y")
	var pre_swap_x = _axis_value_at_time(root_translate, DEATH_PRE_SWAP_TIME, "x")
	var pre_swap_y = _axis_value_at_time(root_translate, DEATH_PRE_SWAP_TIME, "y")
	var pre_swap_rotation = _value_at_time(root_rotate, DEATH_PRE_SWAP_TIME)
	if prep_x == null or prep_y == null:
		_errors.append("die is missing the 0.94-second articulated side-fall preparation key")
	if pre_swap_x == null or float(pre_swap_x) > -350.0:
		_errors.append("die pre-swap pose does not shift at least 350 units left")
	if pre_swap_y == null or absf(float(pre_swap_y) - 150.0) > 0.00001:
		_errors.append("die pre-swap pose lost its 150-unit floor-preserving offset")
	if pre_swap_rotation == null or float(pre_swap_rotation) > -45.0:
		_errors.append("die pre-swap pose does not reach at least -45 degrees of side tilt")
	for limb_bone: String in [
		"vivhite_upper_arm_left",
		"vivhite_forearm_left",
		"vivhite_upper_arm_right",
		"vivhite_forearm_right",
		"vivhite_thigh_left",
		"vivhite_shin_left",
		"vivhite_thigh_right",
		"vivhite_shin_right",
	]:
		if not bones.has(limb_bone):
			_errors.append("die is missing articulated limb timeline %s" % limb_bone)
			continue
		if _value_at_time(bones[limb_bone].get("rotate", []), DEATH_PRE_SWAP_TIME) == null:
			_errors.append("die limb %s is missing its 1.0499-second gather key" % limb_bone)


func _validate_death_landing_alignment(animation: Dictionary) -> void:
	var death_bones: Dictionary = animation.get("bones", {})
	if not death_bones.has(DEATH_BONE):
		_errors.append("die does not animate the isolated death-pose bone")
		return
	var translate: Array = death_bones[DEATH_BONE].get("translate", [])
	var swap_y = _axis_value_at_time(translate, DEATH_SWAP_TIME, "y")
	var contact_y = _axis_value_at_time(translate, DEATH_CONTACT_TIME, "y")
	var rebound_y = _axis_value_at_time(translate, DEATH_REBOUND_TIME, "y")
	var settle_y = _axis_value_at_time(translate, DEATH_SETTLE_TIME, "y")
	if swap_y == null or contact_y == null or rebound_y == null or settle_y == null:
		_errors.append("die landing timeline is missing an atomic-swap/contact/rebound/settle key")
		return
	if absf(float(swap_y) - DEATH_SWAP_OFFSET_Y) > 0.00001:
		_errors.append("die swap y no longer includes the +224.8-unit compensation")
	if absf(DEATH_SETUP_Y + float(swap_y) - DEATH_SWAP_WORLD_Y) > 0.00001:
		_errors.append("die swap world position changed during floor calibration")
	if absf(float(contact_y)) > 0.00001:
		_errors.append("die contact key does not land on the calibrated setup position")
	if absf(float(rebound_y) - 11.0) > 0.00001:
		_errors.append("die rebound peak is no longer 11 authored units")
	if absf(float(settle_y)) > 0.00001:
		_errors.append("die does not settle completely by 1.80 seconds")


func _validate_atlas_contract() -> void:
	var wrapper = JSON.parse_string(FileAccess.get_file_as_string(ATLAS_PATH))
	if not wrapper is Dictionary:
		_errors.append("Candidate atlas wrapper is unreadable: %s" % ATLAS_PATH)
		return
	var atlas_data := str(wrapper.get("atlas_data", ""))
	if atlas_data.count("vivhite_combat_death.png\n") != 1:
		_errors.append("Candidate atlas does not declare exactly one death page")
	if atlas_data.count("%s\n" % DEATH_REGION) != 1:
		_errors.append("Candidate atlas does not declare exactly one death region")
	var death_texture := ResourceLoader.load(DEATH_PAGE_PATH, "Texture2D") as Texture2D
	var death_page := death_texture.get_image() if death_texture != null else null
	if death_page == null or death_page.is_empty():
		_errors.append("Candidate death page could not be decoded")
	elif death_page.get_size() != Vector2i(2048, 1536) or death_page.get_format() != Image.FORMAT_RGBA8:
		_errors.append("Candidate death page is not 2048x1536 RGBA8")


func _validate_easing_contract(skeleton: Dictionary) -> void:
	for animation_name: String in EXPECTED_ANIMATIONS:
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
						_errors.append("%s/%s/%s frame %d is missing Bezier easing" % [animation_name, bone_name, timeline_name, index])
						continue
					var curve: Array = frame["curve"]
					var expected_size := 4 if timeline_name == "rotate" else 8
					if curve.size() != expected_size:
						_errors.append("%s/%s/%s frame %d curve has %d values, expected %d" % [animation_name, bone_name, timeline_name, index, curve.size(), expected_size])
						continue
					var start_time := float(frame.get("time", 0.0))
					var finish_time := float(finish.get("time", 0.0))
					for time_index: int in ([0, 2] if timeline_name == "rotate" else [0, 2, 4, 6]):
						var control_time := float(curve[time_index])
						if control_time < start_time or control_time > finish_time:
							_errors.append("%s/%s/%s frame %d has an out-of-segment Bezier handle" % [animation_name, bone_name, timeline_name, index])


func _sample_animation(data: Resource, animation_name: String, duration: float) -> bool:
	var sprite: Node2D = ClassDB.instantiate("SpineSprite") as Node2D
	if sprite == null:
		_errors.append("Could not instantiate SpineSprite for %s" % animation_name)
		return false
	root.add_child(sprite)
	sprite.set("skeleton_data_res", data)
	var state: Object = sprite.call("get_animation_state")
	var skeleton: Object = sprite.call("get_skeleton")
	if state == null or skeleton == null:
		_errors.append("SpineSprite did not initialize animation state for %s" % animation_name)
		sprite.queue_free()
		return false
	state.call("set_animation", animation_name, false, 0)
	var sample_times: Array[float] = [0.0, duration * 0.25, duration * 0.50, duration * 0.75, duration]
	if animation_name == "die":
		sample_times.append_array([
			DEATH_SWAP_TIME - 0.0001,
			DEATH_SWAP_TIME,
			DEATH_CONTACT_TIME,
			DEATH_REBOUND_TIME,
			DEATH_SETTLE_TIME,
		])
		sample_times.sort()
	var previous := 0.0
	for sample_time: float in sample_times:
		state.call("update", sample_time - previous)
		state.call("apply", skeleton)
		sprite.call("update_skeleton", 0.0)
		previous = sample_time
	sprite.queue_free()
	return true


func _motion_metrics(skeleton: Dictionary) -> Dictionary:
	var animations: Dictionary = skeleton["animations"]
	var death_translate: Array = animations["die"]["bones"][DEATH_BONE]["translate"]
	var landing_drop_units := (
		float(_axis_value_at_time(death_translate, DEATH_SWAP_TIME, "y"))
		- float(_axis_value_at_time(death_translate, DEATH_CONTACT_TIME, "y"))
	)
	return {
		"scene_scale": SCENE_SCALE,
		"attack_root_forward_peak_units": _axis_directional_peak(animations["attack"], "vivhite_rig", "x", true),
		"attack_root_forward_peak_px": _axis_directional_peak(animations["attack"], "vivhite_rig", "x", true) * SCENE_SCALE,
		"attack_heavy_root_forward_peak_units": _axis_directional_peak(animations["attack_heavy"], "vivhite_rig", "x", true),
		"attack_heavy_root_forward_peak_px": _axis_directional_peak(animations["attack_heavy"], "vivhite_rig", "x", true) * SCENE_SCALE,
		"hurt_root_backward_peak_units": _axis_directional_peak(animations["hurt"], "vivhite_rig", "x", false),
		"hurt_root_backward_peak_px": _axis_directional_peak(animations["hurt"], "vivhite_rig", "x", false) * SCENE_SCALE,
		"cast_root_y_range_px": _axis_range(animations["cast"], "vivhite_rig", "y") * SCENE_SCALE,
		"idle_root_y_range_px": _axis_range(animations["idle_loop"], "vivhite_rig", "y") * SCENE_SCALE,
		"bezier_segment_count": _count_bezier_segments(skeleton),
		"die_root_key_count": animations["die"]["bones"]["vivhite_rig"]["translate"].size(),
		"die_preparation_time": DEATH_PREP_TIME,
		"die_pre_swap_time": DEATH_PRE_SWAP_TIME,
		"die_pre_swap_root_x_units": _axis_value_at_time(animations["die"]["bones"]["vivhite_rig"]["translate"], DEATH_PRE_SWAP_TIME, "x"),
		"die_pre_swap_root_y_units": _axis_value_at_time(animations["die"]["bones"]["vivhite_rig"]["translate"], DEATH_PRE_SWAP_TIME, "y"),
		"die_pre_swap_root_rotation_degrees": _value_at_time(animations["die"]["bones"]["vivhite_rig"]["rotate"], DEATH_PRE_SWAP_TIME),
		"die_attachment_atomic_swap_time": DEATH_SWAP_TIME,
		"die_contact_time": DEATH_CONTACT_TIME,
		"die_rebound_time": DEATH_REBOUND_TIME,
		"die_settle_time": DEATH_SETTLE_TIME,
		"die_has_rgba_crossfade": false,
		"die_solid_contact_shift_units": DEATH_SOLID_CONTACT_SHIFT,
		"die_solid_contact_shift_px": DEATH_SOLID_CONTACT_SHIFT * SCENE_SCALE,
		"die_visible_landing_drop_units": landing_drop_units,
		"die_visible_landing_drop_px": landing_drop_units * SCENE_SCALE,
		"direct_parent_contract_count": REQUIRED_PARENTS.size(),
	}


func _axis_range(animation: Dictionary, bone_name: String, axis: String) -> float:
	var minimum := INF
	var maximum := -INF
	for key: Dictionary in animation["bones"][bone_name]["translate"]:
		var value := float(key.get(axis, 0.0))
		minimum = minf(minimum, value)
		maximum = maxf(maximum, value)
	return maximum - minimum


func _axis_directional_peak(
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


func _axis_value_at_time(frames: Array, time: float, axis: String) -> Variant:
	for frame: Dictionary in frames:
		if absf(float(frame.get("time", 0.0)) - time) <= 0.00001:
			return float(frame.get(axis, 0.0))
	return null


func _value_at_time(frames: Array, time: float) -> Variant:
	for frame: Dictionary in frames:
		if absf(float(frame.get("time", 0.0)) - time) <= 0.00001:
			return float(frame.get("value", 0.0))
	return null


func _count_bezier_segments(skeleton: Dictionary) -> int:
	var count := 0
	for animation_name: String in EXPECTED_ANIMATIONS:
		var bones: Dictionary = skeleton["animations"][animation_name].get("bones", {})
		for bone_name: String in bones:
			var timelines: Dictionary = bones[bone_name]
			for timeline_name: String in ["rotate", "translate"]:
				if not timelines.has(timeline_name):
					continue
				for frame: Dictionary in timelines[timeline_name]:
					if frame.has("curve") and frame["curve"] is Array:
						count += 1
	return count


func _finish(metrics: Dictionary) -> void:
	if _errors.is_empty():
		print("[whole-mesh-candidate] Spine load and animation sampling passed")
		print(JSON.stringify(metrics, "  ", false))
		quit(0)
		return
	for message: String in _errors:
		push_error("[whole-mesh-candidate] %s" % message)
	quit(1)
