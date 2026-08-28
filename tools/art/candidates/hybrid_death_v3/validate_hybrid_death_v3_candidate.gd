extends SceneTree

## Static/runtime contract gate for the isolated V3 death candidate. This does
## not render or deploy; it parses the authored JSON/atlas, verifies the frozen
## 0029 source lineage, and samples all eight animations with the real Spine
## 4.2 runtime.

const ROOT := "res://tools/candidates/hybrid_death_v3"
const DATA_PATH := ROOT + "/vivhite_combat_skeleton_data.tres"
const JSON_PATH := ROOT + "/vivhite_combat.spjson"
const ATLAS_PATH := ROOT + "/vivhite_combat.spatlas"
const BODY_PAGE_PATH := ROOT + "/vivhite_combat.png"
const DEATH_PAGE_PATH := ROOT + "/vivhite_combat_death.png"
const SOURCE_RELATIVE_PATH := "assets/vivhite-ironclad/custom/combat/sources/vivhite-combat-death-side-collapse-v2.png"
const SOURCE_SHA256 := "9b391e6dae9ac1e85d05d77b3b0e7e286bf2f0b613e164c714a99054ec12a17b"
const BODY_SLOT := "vivhite_body"
const BODY_ATTACHMENT := "vivhite_combat_body"
const DEATH_SLOT := "vivhite_death_body"
const DEATH_BONE := "vivhite_death_pose"
const DEATH_ATTACHMENT := "vivhite_combat_death_side"
const SWAP_TIME := 1.05
const PRE_SWAP_TIME := 1.0499
const IMPACT_TIME := 1.1666667
const REBOUND_TIME := 1.30
const DAMP_TIME := 1.55
const SETTLE_TIME := 1.80
const PRE_SWAP_X := -396.0
const PRE_SWAP_Y := 150.0
const PRE_SWAP_ROTATION := -50.0
const EXPECTED_FILES: Array[String] = [
	"vivhite_combat.png",
	"vivhite_combat.spatlas",
	"vivhite_combat.spjson",
	"vivhite_combat_death.png",
	"vivhite_combat_skeleton_data.tres",
]
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
const REQUIRED_SLOTS: Array[String] = [BODY_SLOT, DEATH_SLOT, "slash_mesh", "eye_attach_slot"]
const REQUIRED_EVENTS: Array[String] = ["attack_slash_start", "heavy_slash_start", "cast_eyes_start", "clear_vfx"]
const EPSILON := 0.00001

var _errors: Array[String] = []


func _initialize() -> void:
	call_deferred("_run")


func _run() -> void:
	_validate_files_and_lineage()
	var parsed = JSON.parse_string(FileAccess.get_file_as_string(JSON_PATH))
	if not parsed is Dictionary:
		_errors.append("Candidate Spine JSON is unreadable: %s" % JSON_PATH)
		_finish({})
		return
	_validate_raw_contract(parsed)
	_validate_atlas_contract()

	for type_name: String in ["SpineSprite", "SpineSkeletonDataResource", "SpineSkeletonFileResource", "SpineAtlasResource"]:
		if not ClassDB.class_exists(type_name):
			_errors.append("Game-compatible Spine class is unavailable: %s" % type_name)
	if not _errors.is_empty():
		_finish({})
		return
	var data: Resource = ResourceLoader.load(DATA_PATH)
	if data == null or not data.is_class("SpineSkeletonDataResource"):
		_errors.append("Spine runtime could not load V3 death candidate: %s" % DATA_PATH)
		_finish({})
		return
	if str(data.call("get_version")) != "4.2.43":
		_errors.append("Spine runtime reported version %s, expected 4.2.43" % data.call("get_version"))
	for animation_name: String in EXPECTED_ANIMATIONS:
		var animation: Object = data.call("find_animation", animation_name)
		if animation == null:
			_errors.append("Spine runtime is missing animation %s" % animation_name)
			continue
		if absf(float(animation.call("get_duration")) - float(EXPECTED_ANIMATIONS[animation_name])) > EPSILON:
			_errors.append("Runtime duration mismatch for %s" % animation_name)
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
	_finish({
		"animation_count": data.call("get_animations").size(),
		"bone_count": data.call("get_bones").size(),
		"death_source_sha256": SOURCE_SHA256,
		"event_count": data.call("get_events").size(),
		"sampled_animations": sampled,
		"slot_count": data.call("get_slots").size(),
		"spine_version": str(data.call("get_version")),
		"swap_time": SWAP_TIME,
	})


func _validate_files_and_lineage() -> void:
	var files := PackedStringArray()
	for file_name: String in DirAccess.get_files_at(ROOT):
		if file_name.ends_with(".uid") or file_name.ends_with(".import"):
			continue
		files.append(file_name)
	var expected := PackedStringArray(EXPECTED_FILES)
	files.sort()
	expected.sort()
	if files != expected:
		_errors.append("V3 death candidate must contain exactly five logical files; got %s" % files)
	var repo_root := ProjectSettings.globalize_path("res://").path_join("..").simplify_path()
	var source_path := repo_root.path_join(SOURCE_RELATIVE_PATH)
	if not FileAccess.file_exists(source_path):
		_errors.append("Frozen 0029 source is missing: %s" % source_path)
	elif FileAccess.get_sha256(source_path).to_lower() != SOURCE_SHA256:
		_errors.append("Frozen 0029 source hash changed")
	else:
		var source := Image.load_from_file(source_path)
		if source == null or source.is_empty() or source.get_size() != Vector2i(2512, 1680):
			_errors.append("Frozen 0029 source must remain the native 2512x1680 image")
		elif source.get_format() != Image.FORMAT_RGBA8:
			_errors.append("Frozen 0029 source must decode directly as RGBA8")
		else:
			for corner: Vector2i in [Vector2i.ZERO, Vector2i(2511, 0), Vector2i(0, 1679), Vector2i(2511, 1679)]:
				if source.get_pixelv(corner).a > 0.0:
					_errors.append("Frozen 0029 source corner is not transparent: %s" % corner)
	for text_path: String in [JSON_PATH, ATLAS_PATH, DATA_PATH]:
		var text := FileAccess.get_file_as_string(text_path)
		if text.contains("res://Vivhite/skins/ironclad/spine/combat"):
			_errors.append("Candidate leaked a live runtime path in %s" % text_path)
		if text.contains("res://tools/candidates/whole_mesh"):
			_errors.append("Candidate leaked its parent candidate path in %s" % text_path)


func _validate_raw_contract(skeleton: Dictionary) -> void:
	if str(skeleton.get("skeleton", {}).get("spine", "")) != "4.2.43":
		_errors.append("Authored Spine version is not 4.2.43")
	var bones := {}
	for bone: Dictionary in skeleton.get("bones", []):
		bones[str(bone.get("name", ""))] = bone
	if not bones.has(DEATH_BONE):
		_errors.append("Dedicated death bone is missing")
	var slots := {}
	for slot: Dictionary in skeleton.get("slots", []):
		slots[str(slot.get("name", ""))] = slot
	if str(slots.get(BODY_SLOT, {}).get("attachment", "")) != BODY_ATTACHMENT:
		_errors.append("Setup pose must show the neutral weighted mesh")
	if slots.get(DEATH_SLOT, {}).has("attachment"):
		_errors.append("Setup pose must keep the dedicated death slot empty")
	var skins: Array = skeleton.get("skins", [])
	if skins.size() != 1 or str(skins[0].get("name", "")) != "default":
		_errors.append("Candidate must retain one default skin")
	else:
		var attachments: Dictionary = skins[0].get("attachments", {})
		var body_attachments: Dictionary = attachments.get(BODY_SLOT, {})
		var death_attachments: Dictionary = attachments.get(DEATH_SLOT, {})
		if body_attachments.size() != 1 or not body_attachments.has(BODY_ATTACHMENT):
			_errors.append("Default skin must contain exactly one neutral body mesh")
		if death_attachments.size() != 1 or not death_attachments.has(DEATH_ATTACHMENT):
			_errors.append("Default skin must contain exactly one death region")
		elif str(death_attachments[DEATH_ATTACHMENT].get("type", "region")) != "region":
			_errors.append("Dedicated death attachment must remain a rigid region")
	var animations: Dictionary = skeleton.get("animations", {})
	if animations.size() != EXPECTED_ANIMATIONS.size():
		_errors.append("Candidate must contain exactly eight animations")
	for animation_name: String in EXPECTED_ANIMATIONS:
		if not animations.has(animation_name):
			_errors.append("Authored animation is missing: %s" % animation_name)
			continue
		if absf(_max_timeline_time(animations[animation_name]) - float(EXPECTED_ANIMATIONS[animation_name])) > EPSILON:
			_errors.append("Authored duration mismatch for %s" % animation_name)
		if animation_name != "die":
			var animation_slots: Dictionary = animations[animation_name].get("slots", {})
			if animation_slots.has(BODY_SLOT) or animation_slots.has(DEATH_SLOT):
				_errors.append("Only die may drive character attachment visibility: %s" % animation_name)
	if animations.has("die"):
		_validate_die_contract(animations["die"])


func _validate_die_contract(animation: Dictionary) -> void:
	var slots: Dictionary = animation.get("slots", {})
	var body_keys: Array = slots.get(BODY_SLOT, {}).get("attachment", [])
	var death_keys: Array = slots.get(DEATH_SLOT, {}).get("attachment", [])
	if body_keys.size() != 2 or death_keys.size() != 2:
		_errors.append("die must use exactly two atomic attachment keys per character slot")
	else:
		if (
			str(body_keys[0].get("name", "")) != BODY_ATTACHMENT
			or absf(float(body_keys[1].get("time", -1.0)) - SWAP_TIME) > EPSILON
			or body_keys[1].get("name", "sentinel") != null
			or death_keys[0].get("name", "sentinel") != null
			or absf(float(death_keys[1].get("time", -1.0)) - SWAP_TIME) > EPSILON
			or str(death_keys[1].get("name", "")) != DEATH_ATTACHMENT
		):
			_errors.append("die body/death slots do not switch atomically at 1.05")
	if slots.get(BODY_SLOT, {}).has("rgba") or slots.get(DEATH_SLOT, {}).has("rgba"):
		_errors.append("Full-body death handoff may not use RGBA crossfade")
	var bones: Dictionary = animation.get("bones", {})
	var root_translate: Array = bones.get("vivhite_rig", {}).get("translate", [])
	var root_rotate: Array = bones.get("vivhite_rig", {}).get("rotate", [])
	for contract: Array in [
		[root_translate, PRE_SWAP_TIME, "x", PRE_SWAP_X],
		[root_translate, PRE_SWAP_TIME, "y", PRE_SWAP_Y],
		[root_rotate, PRE_SWAP_TIME, "value", PRE_SWAP_ROTATION],
	]:
		if not _timeline_matches(contract[0], float(contract[1]), str(contract[2]), float(contract[3])):
			_errors.append("Low pre-swap contraction contract changed: %s" % contract)
	var landing: Array = bones.get(DEATH_BONE, {}).get("translate", [])
	for contract: Array in [
		[SWAP_TIME, 0.0, 0.0],
		[IMPACT_TIME, -4.0, -7.0],
		[REBOUND_TIME, 5.0, 14.0],
		[DAMP_TIME, 1.5, 3.0],
		[SETTLE_TIME, 0.0, 0.0],
		[float(EXPECTED_ANIMATIONS["die"]), 0.0, 0.0],
	]:
		if (
			not _timeline_matches(landing, float(contract[0]), "x", float(contract[1]))
			or not _timeline_matches(landing, float(contract[0]), "y", float(contract[2]))
		):
			_errors.append("Ground/contact/rebound timeline changed at %.7f" % float(contract[0]))
	var clear_at_zero := false
	for event: Dictionary in animation.get("events", []):
		if str(event.get("name", "")) == "clear_vfx" and absf(float(event.get("time", 0.0))) <= EPSILON:
			clear_at_zero = true
	if not clear_at_zero:
		_errors.append("die must clear VFX at t=0")


func _validate_atlas_contract() -> void:
	var wrapper = JSON.parse_string(FileAccess.get_file_as_string(ATLAS_PATH))
	if not wrapper is Dictionary:
		_errors.append("Candidate atlas wrapper is unreadable")
		return
	if str(wrapper.get("source_path", "")) != ROOT + "/vivhite_combat.atlas":
		_errors.append("Atlas wrapper is not isolated to hybrid_death_v3")
	var atlas_data := str(wrapper.get("atlas_data", ""))
	if atlas_data.count("vivhite_combat.png\n") != 1 or atlas_data.count("vivhite_combat_death.png\n") != 1:
		_errors.append("Atlas must declare exactly one neutral/VFX page and one death page")
	if atlas_data.count("%s\n" % DEATH_ATTACHMENT) != 1:
		_errors.append("Atlas must declare exactly one death region")
	for spec: Dictionary in [
		{"path": BODY_PAGE_PATH, "size": Vector2i(3072, 2304)},
		{"path": DEATH_PAGE_PATH, "size": Vector2i(2048, 1536)},
	]:
		var texture := ResourceLoader.load(str(spec.path), "Texture2D") as Texture2D
		var image := texture.get_image() if texture != null else null
		if image == null or image.is_empty() or image.get_size() != spec.size or image.get_format() != Image.FORMAT_RGBA8:
			_errors.append("Atlas page failed RGBA8/size contract: %s" % spec.path)


func _sample_animation(data: Resource, animation_name: String, duration: float) -> bool:
	var sprite: Node2D = ClassDB.instantiate("SpineSprite") as Node2D
	if sprite == null:
		_errors.append("Could not instantiate SpineSprite for %s" % animation_name)
		return false
	root.add_child(sprite)
	sprite.call("set_update_mode", 2)
	sprite.set("skeleton_data_res", data)
	var state: Object = sprite.call("get_animation_state")
	var skeleton: Object = sprite.call("get_skeleton")
	if state == null or skeleton == null:
		_errors.append("Spine runtime did not initialize for %s" % animation_name)
		sprite.queue_free()
		return false
	state.call("set_animation", animation_name, false, 0)
	var times: Array[float] = [0.0, duration * 0.25, duration * 0.5, duration * 0.75, duration]
	if animation_name == "die":
		times.append_array([PRE_SWAP_TIME, SWAP_TIME, SWAP_TIME + 0.0001, IMPACT_TIME, REBOUND_TIME, SETTLE_TIME])
		times.sort()
	var previous := 0.0
	for time: float in times:
		state.call("update", time - previous)
		state.call("apply", skeleton)
		sprite.call("update_skeleton", 0.0)
		if animation_name == "die":
			var body_name = _attachment_name(skeleton, BODY_SLOT)
			var death_name = _attachment_name(skeleton, DEATH_SLOT)
			var expected_death := time >= SWAP_TIME - EPSILON
			if (
				(expected_death and (body_name != null or death_name != DEATH_ATTACHMENT))
				or (not expected_death and (body_name != BODY_ATTACHMENT or death_name != null))
			):
				_errors.append("Runtime die visibility is not atomic at %.7f" % time)
		previous = time
	sprite.queue_free()
	return true


func _attachment_name(skeleton: Object, slot_name: String) -> Variant:
	var slot: Variant = skeleton.call("find_slot", slot_name)
	if slot == null:
		return "<missing>"
	var attachment: Variant = (slot as Object).call("get_attachment")
	if attachment == null:
		return null
	return str((attachment as Object).call("get_attachment_name"))


func _timeline_matches(keys: Array, time: float, axis: String, expected: float) -> bool:
	for key: Dictionary in keys:
		if absf(float(key.get("time", 0.0)) - time) <= EPSILON:
			return absf(float(key.get(axis, 0.0)) - expected) <= EPSILON
	return false


func _max_timeline_time(value: Variant) -> float:
	var result := 0.0
	if value is Dictionary:
		for child: Variant in (value as Dictionary).values():
			result = maxf(result, _max_timeline_time(child))
	elif value is Array:
		for child: Variant in value:
			if child is Dictionary and (child as Dictionary).has("time"):
				result = maxf(result, float((child as Dictionary).get("time", 0.0)))
			result = maxf(result, _max_timeline_time(child))
	return result


func _finish(metrics: Dictionary) -> void:
	if _errors.is_empty():
		print("[hybrid-death-v3] Static and Spine runtime validation passed")
		print(JSON.stringify(metrics, "  ", false))
		quit(0)
		return
	for message: String in _errors:
		push_error("[hybrid-death-v3] %s" % message)
	quit(1)
