extends SceneTree

## Read-only static + Spine-runtime gate for the assembled Hybrid V3 final
## candidate. It proves the five frozen semantic pages, exact atlas layout,
## reviewed four-donor JSON merge, animation windows and mix table without
## rebuilding, publishing, deploying, or controlling the game.

const ROOT := "res://tools/candidates/hybrid_v3_final"
const CAST_ROOT := "res://tools/candidates/hybrid_cast_set"
const NEUTRAL_ROOT := "res://tools/candidates/hybrid_neutral_v3"
const HURT_ROOT := "res://tools/candidates/hybrid_hurt_neutral"
const DEATH_ROOT := "res://tools/candidates/hybrid_death_v3"
const JSON_PATH := ROOT + "/vivhite_combat.spjson"
const ATLAS_PATH := ROOT + "/vivhite_combat.spatlas"
const DATA_PATH := ROOT + "/vivhite_combat_skeleton_data.tres"

const EXPECTED_FILES: Array[String] = [
	"vivhite_combat.png",
	"vivhite_combat.spatlas",
	"vivhite_combat.spjson",
	"vivhite_combat_attack.png",
	"vivhite_combat_attack_heavy.png",
	"vivhite_combat_cast.png",
	"vivhite_combat_death.png",
	"vivhite_combat_skeleton_data.tres",
]
const PAGE_SIZES := {
	"vivhite_combat.png": Vector2i(3072, 2304),
	"vivhite_combat_attack.png": Vector2i(2048, 2304),
	"vivhite_combat_attack_heavy.png": Vector2i(2048, 2304),
	"vivhite_combat_cast.png": Vector2i(2048, 2304),
	"vivhite_combat_death.png": Vector2i(2048, 1536),
}
const PAGE_SHA256 := {
	"vivhite_combat.png": "fabdb49900d01af55ef8ff193824149a504019630e1f39afe692481ae52f6f5b",
	"vivhite_combat_attack.png": "17bfee690fbc7401487cba0d4e14ba311cdee8b9a03f1ada9144fbf4c7114dfb",
	"vivhite_combat_attack_heavy.png": "e245f4a17d506e97cd34abd19f55b6c8b884832d01396ecaa837beaf0a07720e",
	"vivhite_combat_cast.png": "65458604f022f0fd98d64737d130f7fc89e621032bf0677d24ccddef108b2b5e",
	"vivhite_combat_death.png": "7c89552c69bb50eb94a3d5a10d4ca408a0546156ed72aa7a289f1cf25a9af33d",
}
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
const EXPECTED_EVENTS: Array[String] = [
	"attack_slash_start", "heavy_slash_start", "cast_eyes_start", "clear_vfx",
]
const LOOP_DURATIONS := {
	"idle_loop": 2.0,
	"low_health_loop": 1.4666667,
	"relaxed_loop": 12.000001,
}
const SOURCE_HASHES := {
	"cast": "vivhite-hybrid-v3-cast-set-v1",
	"neutral": "vivhite-hybrid-v3-neutral-reset-v1",
	"hurt": "vivhite-hybrid-v3-hurt-neutral-v1",
	"death": "vivhite-hybrid-death-v3-grounded-atomic-v1",
}

const BODY_BONE := "vivhite_rig"
const BODY_SLOT := "vivhite_body"
const BODY_REGION := "vivhite_combat_body"
const ACTION_BONE := "vivhite_action_pose_root"
const ACTION_SLOT := "vivhite_action_pose"
const ATTACK_REGION := "vivhite_combat_attack_peak"
const HEAVY_REGION := "vivhite_combat_attack_heavy_peak"
const CAST_REGION := "vivhite_combat_cast_peak"
const DEATH_BONE := "vivhite_death_pose"
const DEATH_SLOT := "vivhite_death_body"
const DEATH_REGION := "vivhite_combat_death_side"
const ARC_BONE := "vivhite_magic_arc"
const SLASH_SLOT := "slash_mesh"
const ARC_REGION := "vivhite_combat_magic_arc"
const SIGIL_BONE := "vivhite_magic_sigil"
const SIGIL_SLOT := "vivhite_magic_sigil"
const SIGIL_REGION := "vivhite_combat_magic_sigil"
const EYE_BONE := "vivhite_eye_anchor"
const EYE_SLOT := "eye_attach_slot"
const ALL_SLOTS: Array[String] = [
	BODY_SLOT, ACTION_SLOT, DEATH_SLOT, SLASH_SLOT, SIGIL_SLOT, EYE_SLOT,
]
const CHARACTER_SLOTS: Array[String] = [BODY_SLOT, ACTION_SLOT, DEATH_SLOT]

const ATTACK_ENTER := 0.08
const ATTACK_EXIT := 0.20
const ATTACK_PRE_EXIT := 0.1999
const ATTACK_CLEAR := 0.886666692
const HEAVY_ENTER := 0.12
const HEAVY_EXIT := 0.32
const HEAVY_PRE_EXIT := 0.3199
const HEAVY_CLEAR := 1.165333384
const CAST_ENTER := 0.25
const CAST_EXIT := 0.60
const CAST_PRE_EXIT := 0.5999
const CAST_SIGIL_ENTER := 0.10
const CAST_CLEAR := 1.222000026
const CAST_EYE_PRE_CLEAR := 1.2219
const CAST_EYE_PEAK := Vector2(194.0, -292.0)
const CAST_EYE_NEUTRAL := Vector2(72.0, -282.0)
const ARC_PEAK := Vector2(210.0, 30.0)
const ACTION_WORLD_SIZE := Vector2(868.0, 1302.0)

const DEATH_SWAP := 1.05
const DEATH_PRE_SWAP := 1.0499
const DEATH_IMPACT := 1.1666667
const DEATH_REBOUND := 1.30
const DEATH_DAMP := 1.55
const DEATH_SETTLE := 1.80

const HURT_TIMES := [0.0, 0.10, 0.16, 0.28, 0.46, 0.70, 1.0]
const HURT_IMPACT := {
	"vivhite_rig": Vector2(-118.0, 8.0),
	"vivhite_pelvis": -6.0,
	"vivhite_torso_lower": -12.0,
	"vivhite_torso_upper": -17.0,
	"vivhite_neck": 11.0,
	"vivhite_head": 16.0,
	"vivhite_upper_arm_left": 60.0,
	"vivhite_forearm_left": 100.0,
	"vivhite_hand_left": -80.0,
	"vivhite_upper_arm_right": 75.0,
	"vivhite_forearm_right": 75.0,
	"vivhite_hand_right": -70.0,
}

const MIXES := [
	{"from": "idle_loop", "to": "attack", "mix": 0.10},
	{"from": "attack", "to": "attack", "mix": 0.0},
	{"from": "hurt", "to": "hurt", "mix": 0.0},
	{"from": "hurt", "to": "die", "mix": 0.0},
	{"from": "idle_loop", "to": "hurt", "mix": 0.03},
	{"from": "hurt", "to": "idle_loop", "mix": 0.10},
	{"from": "idle_loop", "to": "attack_heavy", "mix": 0.02},
	{"from": "attack_heavy", "to": "attack_heavy", "mix": 0.0},
	{"from": "attack", "to": "attack_heavy", "mix": 0.0},
	{"from": "attack_heavy", "to": "attack", "mix": 0.0},
]
const EPSILON := 0.00002

var _errors: Array[String] = []
var _runtime_animation_samples := 0
var _runtime_loop_reset_samples := 0
var _runtime_mix_samples := 0
var _visibility_samples := 0


func _initialize() -> void:
	call_deferred("_run")


func _run() -> void:
	_validate_file_set_and_pages()
	var skeleton := _load_dictionary(JSON_PATH, "final Spine JSON")
	var cast := _load_dictionary(CAST_ROOT + "/vivhite_combat.spjson", "cast donor Spine JSON")
	var neutral := _load_dictionary(NEUTRAL_ROOT + "/vivhite_combat.spjson", "neutral donor Spine JSON")
	var hurt := _load_dictionary(HURT_ROOT + "/vivhite_combat.spjson", "hurt donor Spine JSON")
	var death := _load_dictionary(DEATH_ROOT + "/vivhite_combat.spjson", "death donor Spine JSON")
	var atlas := _load_dictionary(ATLAS_PATH, "final atlas wrapper")
	if not skeleton.is_empty() and not cast.is_empty() and not neutral.is_empty() and not hurt.is_empty() and not death.is_empty():
		_validate_donor_provenance(skeleton, cast, neutral, hurt, death)
		_validate_skeleton_contract(skeleton)
		_validate_animation_contracts(skeleton)
	if not atlas.is_empty():
		_validate_atlas_contract(atlas)
	_validate_tres_contract()
	_validate_runtime()
	_finish()


func _validate_file_set_and_pages() -> void:
	var actual := PackedStringArray()
	for file_name: String in DirAccess.get_files_at(ROOT):
		if file_name.ends_with(".uid") or file_name.ends_with(".import"):
			continue
		actual.append(file_name)
	actual.sort()
	var expected := PackedStringArray()
	for file_name: String in EXPECTED_FILES:
		expected.append(file_name)
	expected.sort()
	if actual != expected:
		_errors.append("Final candidate must contain exactly eight authored files; got %s" % actual)
	if FileAccess.file_exists(ROOT + "/vivhite_combat.atlas"):
		_errors.append("Final candidate must not contain a physical .atlas sidecar")
	for page_name: String in PAGE_SIZES:
		var page_path := ROOT + "/" + page_name
		if not FileAccess.file_exists(page_path):
			_errors.append("Frozen atlas page is missing: %s" % page_name)
			continue
		var actual_hash := FileAccess.get_sha256(page_path).to_lower()
		if actual_hash != str(PAGE_SHA256[page_name]):
			_errors.append("Frozen atlas page SHA-256 changed for %s: %s" % [page_name, actual_hash])
		var image := Image.load_from_file(page_path)
		if image == null or image.is_empty():
			_errors.append("Atlas page could not be decoded: %s" % page_name)
			continue
		if image.get_format() != Image.FORMAT_RGBA8:
			_errors.append("Atlas page must decode natively as RGBA8: %s" % page_name)
		if image.get_size() != PAGE_SIZES[page_name]:
			_errors.append("Atlas page size changed for %s: %s" % [page_name, image.get_size()])
		for corner: Vector2i in [
			Vector2i.ZERO,
			Vector2i(image.get_width() - 1, 0),
			Vector2i(0, image.get_height() - 1),
			Vector2i(image.get_width() - 1, image.get_height() - 1),
		]:
			if image.get_pixelv(corner).a > 0.0:
				_errors.append("Atlas page corner is not Alpha 0: %s @ %s" % [page_name, corner])
		if not image.get_used_rect().has_area():
			_errors.append("Atlas page has no non-zero Alpha subject: %s" % page_name)


func _validate_donor_provenance(
	skeleton: Dictionary,
	cast: Dictionary,
	neutral: Dictionary,
	hurt: Dictionary,
	death: Dictionary,
) -> void:
	var donors := {"cast": cast, "neutral": neutral, "hurt": hurt, "death": death}
	for label: String in donors:
		var donor: Dictionary = donors[label]
		if str(donor.get("skeleton", {}).get("hash", "")) != str(SOURCE_HASHES[label]):
			_errors.append("%s donor no longer carries the accepted milestone marker" % label)
		if str(donor.get("skeleton", {}).get("spine", "")) != "4.2.43":
			_errors.append("%s donor is not Spine 4.2.43" % label)

	var final_animations: Dictionary = skeleton.get("animations", {})
	var cast_animations: Dictionary = cast.get("animations", {})
	var neutral_animations: Dictionary = neutral.get("animations", {})
	var hurt_animations: Dictionary = hurt.get("animations", {})
	var death_animations: Dictionary = death.get("animations", {})
	for animation_name: String in LOOP_DURATIONS:
		if not _same_variant(
			final_animations.get(animation_name, {}).get("slots", null),
			neutral_animations.get(animation_name, {}).get("slots", null)
		):
			_errors.append("%s slots differ from the accepted neutral-reset donor" % animation_name)
	if not _same_variant(
		final_animations.get("hurt", {}).get("bones", null),
		hurt_animations.get("hurt", {}).get("bones", null)
	):
		_errors.append("Final hurt bones differ from the accepted protective-hurt donor")
	for section_name: String in ["slots", "events"]:
		if not _same_variant(
			final_animations.get("hurt", {}).get(section_name, null),
			cast_animations.get("hurt", {}).get(section_name, null)
		):
			_errors.append("Final hurt/%s differs from the cast-set base" % section_name)
		if not _same_variant(
			final_animations.get("die", {}).get(section_name, null),
			cast_animations.get("die", {}).get(section_name, null)
		):
			_errors.append("Final die/%s differs from the cast-set base" % section_name)
	for bone_name: String in [BODY_BONE, DEATH_BONE]:
		if not _same_variant(
			final_animations.get("die", {}).get("bones", {}).get(bone_name, null),
			death_animations.get("die", {}).get("bones", {}).get(bone_name, null)
		):
			_errors.append("Final die/%s differs from the accepted grounded-death donor" % bone_name)
	for animation_name: String in ["attack", "attack_heavy", "cast"]:
		if not _same_variant(final_animations.get(animation_name, null), cast_animations.get(animation_name, null)):
			_errors.append("Final %s animation differs from the accepted cast-set base" % animation_name)

	# Revert only the four reviewed merge deltas. The result must be the cast
	# donor byte-for-byte at the decoded JSON level, which catches any hidden
	# edit outside neutral slots, hurt bones, and the two death bone tracks.
	var normalized: Dictionary = skeleton.duplicate(true)
	normalized["skeleton"]["hash"] = cast.get("skeleton", {}).get("hash", "")
	for animation_name: String in LOOP_DURATIONS:
		normalized["animations"][animation_name]["slots"] = (
			cast_animations.get(animation_name, {}).get("slots", {}).duplicate(true)
		)
	normalized["animations"]["hurt"]["bones"] = (
		cast_animations.get("hurt", {}).get("bones", {}).duplicate(true)
	)
	for bone_name: String in [BODY_BONE, DEATH_BONE]:
		normalized["animations"]["die"]["bones"][bone_name] = (
			cast_animations.get("die", {}).get("bones", {}).get(bone_name, {}).duplicate(true)
		)
	if not _same_variant(normalized, cast):
		_errors.append("Final Spine JSON contains a change outside the four reviewed merge deltas")


func _validate_skeleton_contract(skeleton: Dictionary) -> void:
	var header: Dictionary = skeleton.get("skeleton", {})
	if str(header.get("hash", "")) != "vivhite-hybrid-v3-final-v1":
		_errors.append("Skeleton hash does not identify the Hybrid V3 final contract")
	if str(header.get("spine", "")) != "4.2.43":
		_errors.append("Final skeleton must remain Spine 4.2.43")
	var bones: Dictionary = _named_dictionaries(skeleton.get("bones", []))
	var slots: Dictionary = _named_dictionaries(skeleton.get("slots", []))
	if bones.size() != 35:
		_errors.append("Final skeleton must contain exactly 35 bones, got %d" % bones.size())
	if slots.size() != 6 or _sorted_keys(slots) != _sorted_strings(ALL_SLOTS):
		_errors.append("Final skeleton must contain exactly the six runtime slots; got %s" % _sorted_keys(slots))
	var slot_bones := {
		BODY_SLOT: BODY_BONE,
		ACTION_SLOT: ACTION_BONE,
		DEATH_SLOT: DEATH_BONE,
		SLASH_SLOT: ARC_BONE,
		SIGIL_SLOT: SIGIL_BONE,
		EYE_SLOT: EYE_BONE,
	}
	for slot_name: String in slot_bones:
		if str(slots.get(slot_name, {}).get("bone", "")) != str(slot_bones[slot_name]):
			_errors.append("Slot %s is bound to the wrong bone" % slot_name)
	if str(slots.get(BODY_SLOT, {}).get("attachment", "")) != BODY_REGION:
		_errors.append("Setup pose must show the neutral body")
	for hidden_slot: String in [ACTION_SLOT, DEATH_SLOT, SLASH_SLOT, SIGIL_SLOT, EYE_SLOT]:
		if slots.get(hidden_slot, {}).has("attachment"):
			_errors.append("Setup pose must keep %s empty" % hidden_slot)

	var animations: Dictionary = skeleton.get("animations", {})
	if animations.size() != 8 or _sorted_keys(animations) != _sorted_keys(EXPECTED_ANIMATIONS):
		_errors.append("Final skeleton must expose exactly the eight animation names")
	var events: Dictionary = skeleton.get("events", {})
	if events.size() != 4 or _sorted_keys(events) != _sorted_strings(EXPECTED_EVENTS):
		_errors.append("Final skeleton must expose exactly the four event definitions")

	var skins: Array = skeleton.get("skins", [])
	if skins.size() != 1 or str(skins[0].get("name", "")) != "default":
		_errors.append("Final skeleton must expose exactly one default skin")
		return
	var attachments: Dictionary = skins[0].get("attachments", {})
	var actions: Dictionary = attachments.get(ACTION_SLOT, {})
	var expected_actions := [ATTACK_REGION, HEAVY_REGION, CAST_REGION]
	if actions.size() != 3 or _sorted_keys(actions) != _sorted_strings(expected_actions):
		_errors.append("Action slot must contain exactly attack, heavy, and cast attachments")
	for region_name: String in expected_actions:
		var attachment: Dictionary = actions.get(region_name, {})
		if str(attachment.get("type", "region")) != "region" or str(attachment.get("path", "")) != region_name:
			_errors.append("Action attachment must remain one rigid region: %s" % region_name)
		if (
			not _near(float(attachment.get("width", NAN)), ACTION_WORLD_SIZE.x)
			or not _near(float(attachment.get("height", NAN)), ACTION_WORLD_SIZE.y)
		):
			_errors.append("Action attachment lost its fixed world size: %s" % region_name)
	for spec: Dictionary in [
		{"slot": BODY_SLOT, "region": BODY_REGION},
		{"slot": DEATH_SLOT, "region": DEATH_REGION},
		{"slot": SLASH_SLOT, "region": ARC_REGION},
		{"slot": SIGIL_SLOT, "region": SIGIL_REGION},
	]:
		var slot_attachments: Dictionary = attachments.get(str(spec.slot), {})
		if slot_attachments.size() != 1 or not slot_attachments.has(str(spec.region)):
			_errors.append("Skin slot %s must contain exactly %s" % [spec.slot, spec.region])
	if attachments.has(EYE_SLOT):
		_errors.append("eye_attach_slot must remain an external runtime VFX slot without a skin attachment")


func _validate_animation_contracts(skeleton: Dictionary) -> void:
	var animations: Dictionary = skeleton.get("animations", {})
	var setup_slots := _named_dictionaries(skeleton.get("slots", []))
	for animation_name: String in EXPECTED_ANIMATIONS:
		if not animations.has(animation_name):
			continue
		var animation: Dictionary = animations[animation_name]
		var actual_duration := _max_timeline_time(animation)
		if not _near(actual_duration, float(EXPECTED_ANIMATIONS[animation_name])):
			_errors.append("Authored duration mismatch for %s: %.7f" % [animation_name, actual_duration])
		_validate_no_person_crossfade(animation_name, animation)
		_validate_exactly_one_person(
			animation_name,
			animation,
			float(EXPECTED_ANIMATIONS[animation_name]),
			setup_slots
		)
	_validate_neutral_loops(animations)
	_validate_attack_action(animations.get("attack", {}), "attack", ATTACK_REGION, ATTACK_ENTER, ATTACK_PRE_EXIT, ATTACK_EXIT, "attack_slash_start", ATTACK_CLEAR)
	_validate_attack_action(animations.get("attack_heavy", {}), "attack_heavy", HEAVY_REGION, HEAVY_ENTER, HEAVY_PRE_EXIT, HEAVY_EXIT, "heavy_slash_start", HEAVY_CLEAR)
	_validate_cast_action(animations.get("cast", {}))
	_validate_hurt_action(animations.get("hurt", {}))
	_validate_die_action(animations.get("die", {}))


func _validate_neutral_loops(animations: Dictionary) -> void:
	var expected_names := {
		BODY_SLOT: BODY_REGION,
		ACTION_SLOT: null,
		DEATH_SLOT: null,
		SLASH_SLOT: null,
		SIGIL_SLOT: null,
		EYE_SLOT: null,
	}
	for animation_name: String in LOOP_DURATIONS:
		var duration := float(LOOP_DURATIONS[animation_name])
		var animation: Dictionary = animations.get(animation_name, {})
		var slots: Dictionary = animation.get("slots", {})
		if slots.size() != ALL_SLOTS.size() or _sorted_keys(slots) != _sorted_strings(ALL_SLOTS):
			_errors.append("%s must contain exactly six attachment-reset slot timelines" % animation_name)
		for slot_name: String in ALL_SLOTS:
			var keys: Array = slots.get(slot_name, {}).get("attachment", [])
			if keys.size() != 2:
				_errors.append("%s must reset %s at both boundaries" % [animation_name, slot_name])
				continue
			for index in 2:
				var expected_time := 0.0 if index == 0 else duration
				if (
					not _near(float(keys[index].get("time", -1.0)), expected_time)
					or keys[index].get("name", "sentinel") != expected_names[slot_name]
				):
					_errors.append("%s has an invalid %s reset at %.7f" % [animation_name, slot_name, expected_time])


func _validate_attack_action(
	animation: Dictionary,
	label: String,
	region_name: String,
	enter_time: float,
	pre_exit_time: float,
	exit_time: float,
	start_event: String,
	clear_time: float,
) -> void:
	_validate_atomic_person_swap(animation, label, region_name, enter_time, exit_time)
	_validate_exact_events(animation, label, [
		{"name": start_event, "time": enter_time},
		{"name": "clear_vfx", "time": clear_time},
	])
	var slash_keys: Array = animation.get("slots", {}).get(SLASH_SLOT, {}).get("attachment", [])
	var slash_times := [0.0, enter_time, clear_time]
	var slash_names := [null, ARC_REGION, null]
	if slash_keys.size() != slash_times.size():
		_errors.append("%s slash must contain exactly null/show/null keys" % label)
	else:
		for index in slash_times.size():
			if not _key_matches(slash_keys[index], float(slash_times[index]), slash_names[index]):
				_errors.append("%s slash lifecycle changed at index %d" % [label, index])
	var duration := float(EXPECTED_ANIMATIONS[label])
	var times := [0.0, enter_time, pre_exit_time, exit_time, duration]
	for bone_name: String in [ARC_BONE, EYE_BONE]:
		var keys: Array = animation.get("bones", {}).get(bone_name, {}).get("translate", [])
		if keys.size() != times.size():
			_errors.append("%s/%s must contain exactly five action-anchor keys" % [label, bone_name])
			continue
		for index in times.size():
			var expected_offset := ARC_PEAK if bone_name == ARC_BONE and index in [1, 2] else Vector2.ZERO
			if not _translation_key_matches(keys[index], float(times[index]), expected_offset):
				_errors.append("%s/%s anchor changed at index %d" % [label, bone_name, index])


func _validate_cast_action(animation: Dictionary) -> void:
	_validate_atomic_person_swap(animation, "cast", CAST_REGION, CAST_ENTER, CAST_EXIT)
	_validate_exact_events(animation, "cast", [
		{"name": "cast_eyes_start", "time": CAST_ENTER},
		{"name": "clear_vfx", "time": CAST_CLEAR},
	])
	var slots: Dictionary = animation.get("slots", {})
	var slash_keys: Array = slots.get(SLASH_SLOT, {}).get("attachment", [])
	if slash_keys.size() != 1 or not _key_matches(slash_keys[0], 0.0, null):
		_errors.append("cast must explicitly clear slash_mesh at t=0")
	var sigil_keys: Array = slots.get(SIGIL_SLOT, {}).get("attachment", [])
	var sigil_times := [0.0, CAST_SIGIL_ENTER, CAST_CLEAR]
	var sigil_names := [null, SIGIL_REGION, null]
	if sigil_keys.size() != sigil_times.size():
		_errors.append("cast sigil must contain exactly null/show/null keys")
	else:
		for index in sigil_times.size():
			if not _key_matches(sigil_keys[index], float(sigil_times[index]), sigil_names[index]):
				_errors.append("cast sigil lifecycle changed at index %d" % index)
	var eye_keys: Array = animation.get("bones", {}).get(EYE_BONE, {}).get("translate", [])
	var eye_times := [
		0.0, CAST_ENTER, CAST_PRE_EXIT, CAST_EXIT,
		CAST_EYE_PRE_CLEAR, CAST_CLEAR, float(EXPECTED_ANIMATIONS["cast"]),
	]
	if eye_keys.size() != eye_times.size():
		_errors.append("cast eye anchor must contain exactly seven lifecycle keys")
	else:
		for index in eye_times.size():
			var expected_offset := Vector2.ZERO
			if index in [1, 2]:
				expected_offset = CAST_EYE_PEAK
			elif index in [3, 4]:
				expected_offset = CAST_EYE_NEUTRAL
			if not _translation_key_matches(eye_keys[index], float(eye_times[index]), expected_offset):
				_errors.append("cast eye anchor changed at index %d" % index)


func _validate_hurt_action(animation: Dictionary) -> void:
	var bones: Dictionary = animation.get("bones", {})
	for bone_name: String in HURT_IMPACT:
		if not bones.has(bone_name):
			_errors.append("Protective hurt is missing required bone %s" % bone_name)
			continue
		var keys: Array = bones[bone_name].get("translate", []) if bone_name == BODY_BONE else bones[bone_name].get("rotate", [])
		if keys.size() != HURT_TIMES.size():
			_errors.append("Protective hurt %s must contain seven performance keys" % bone_name)
			continue
		for index in HURT_TIMES.size():
			if not _near(float(keys[index].get("time", -1.0)), float(HURT_TIMES[index])):
				_errors.append("Protective hurt %s time changed at index %d" % [bone_name, index])
			if index < HURT_TIMES.size() - 1 and not keys[index].has("curve"):
				_errors.append("Protective hurt %s lost easing before key %d" % [bone_name, index + 1])
		if bone_name == BODY_BONE:
			var expected: Vector2 = HURT_IMPACT[bone_name]
			if not _near(float(keys[1].get("x", NAN)), expected.x) or not _near(float(keys[1].get("y", NAN)), expected.y):
				_errors.append("Protective hurt lost its root impact")
		elif not _near(float(keys[1].get("value", NAN)), float(HURT_IMPACT[bone_name])):
			_errors.append("Protective hurt impact changed for %s" % bone_name)
	var action_keys: Array = animation.get("slots", {}).get(ACTION_SLOT, {}).get("attachment", [])
	if action_keys.size() != 1 or not _key_matches(action_keys[0], 0.0, null):
		_errors.append("hurt must retain the cast-set action-slot reset")
	_validate_exact_events(animation, "hurt", [{"name": "clear_vfx", "time": 0.72}])


func _validate_die_action(animation: Dictionary) -> void:
	var slots: Dictionary = animation.get("slots", {})
	var body_keys: Array = slots.get(BODY_SLOT, {}).get("attachment", [])
	var death_keys: Array = slots.get(DEATH_SLOT, {}).get("attachment", [])
	if body_keys.size() != 2 or death_keys.size() != 2:
		_errors.append("die must contain exactly two atomic keys per body/death slot")
	else:
		if not _key_matches(body_keys[0], 0.0, BODY_REGION) or not _key_matches(body_keys[1], DEATH_SWAP, null):
			_errors.append("die body slot no longer hands off at 1.05")
		if not _key_matches(death_keys[0], 0.0, null) or not _key_matches(death_keys[1], DEATH_SWAP, DEATH_REGION):
			_errors.append("die death slot no longer appears atomically at 1.05")
	var action_keys: Array = slots.get(ACTION_SLOT, {}).get("attachment", [])
	if action_keys.size() != 1 or not _key_matches(action_keys[0], 0.0, null):
		_errors.append("die must retain the cast-set action-slot reset")
	_validate_exact_events(animation, "die", [{"name": "clear_vfx", "time": 0.0}])

	var bones: Dictionary = animation.get("bones", {})
	var root_translate: Array = bones.get(BODY_BONE, {}).get("translate", [])
	var root_rotate: Array = bones.get(BODY_BONE, {}).get("rotate", [])
	for spec: Dictionary in [
		{"keys": root_translate, "time": DEATH_PRE_SWAP, "axis": "x", "value": -396.0},
		{"keys": root_translate, "time": DEATH_PRE_SWAP, "axis": "y", "value": 150.0},
		{"keys": root_rotate, "time": DEATH_PRE_SWAP, "axis": "value", "value": -50.0},
	]:
		if not _timeline_has_value(spec.keys, float(spec.time), str(spec.axis), float(spec.value)):
			_errors.append("Grounded death pre-swap contraction changed: %s" % spec)
	var landing: Array = bones.get(DEATH_BONE, {}).get("translate", [])
	for contact: Array in [
		[DEATH_SWAP, 0.0, 0.0],
		[DEATH_IMPACT, -4.0, -7.0],
		[DEATH_REBOUND, 5.0, 14.0],
		[DEATH_DAMP, 1.5, 3.0],
		[DEATH_SETTLE, 0.0, 0.0],
		[float(EXPECTED_ANIMATIONS["die"]), 0.0, 0.0],
	]:
		if (
			not _timeline_has_value(landing, float(contact[0]), "x", float(contact[1]))
			or not _timeline_has_value(landing, float(contact[0]), "y", float(contact[2]))
		):
			_errors.append("Grounded death contact/rebound track changed at %.7f" % float(contact[0]))


func _validate_atomic_person_swap(animation: Dictionary, label: String, region_name: String, enter_time: float, exit_time: float) -> void:
	var slots: Dictionary = animation.get("slots", {})
	var body_keys: Array = slots.get(BODY_SLOT, {}).get("attachment", [])
	var action_keys: Array = slots.get(ACTION_SLOT, {}).get("attachment", [])
	var times := [0.0, enter_time, exit_time]
	var body_names := [BODY_REGION, null, BODY_REGION]
	var action_names := [null, region_name, null]
	if body_keys.size() != 3 or action_keys.size() != 3:
		_errors.append("%s must contain exactly three atomic person keys per slot" % label)
		return
	for index in 3:
		if not _key_matches(body_keys[index], float(times[index]), body_names[index]) or not _key_matches(action_keys[index], float(times[index]), action_names[index]):
			_errors.append("%s no longer switches neutral/action/neutral atomically" % label)
			return


func _validate_exact_events(animation: Dictionary, label: String, expected: Array) -> void:
	var events: Array = animation.get("events", [])
	if events.size() != expected.size():
		_errors.append("%s event count changed; got %d expected %d" % [label, events.size(), expected.size()])
		return
	for index in expected.size():
		if (
			str(events[index].get("name", "")) != str(expected[index].name)
			or not _near(float(events[index].get("time", 0.0)), float(expected[index].time))
		):
			_errors.append("%s event timeline changed at index %d" % [label, index])


func _validate_no_person_crossfade(animation_name: String, animation: Dictionary) -> void:
	for slot_name: String in CHARACTER_SLOTS:
		var timelines: Dictionary = animation.get("slots", {}).get(slot_name, {})
		for forbidden: String in ["rgba", "rgb", "alpha", "color", "twoColor"]:
			if timelines.has(forbidden):
				_errors.append("%s/%s uses forbidden full-person crossfade %s" % [animation_name, slot_name, forbidden])


func _validate_exactly_one_person(animation_name: String, animation: Dictionary, duration: float, setup_slots: Dictionary) -> void:
	var key_times: Array[float] = [0.0, duration]
	for slot_name: String in CHARACTER_SLOTS:
		for key: Dictionary in animation.get("slots", {}).get(slot_name, {}).get("attachment", []):
			key_times.append(clampf(float(key.get("time", 0.0)), 0.0, duration))
	key_times.sort()
	var unique: Array[float] = []
	for time: float in key_times:
		if unique.is_empty() or not _near(unique[-1], time):
			unique.append(time)
	var samples := unique.duplicate()
	for index in range(unique.size() - 1):
		if unique[index + 1] - unique[index] > EPSILON:
			samples.append((unique[index] + unique[index + 1]) * 0.5)
	for sample_time: float in samples:
		var visible := 0
		for slot_name: String in CHARACTER_SLOTS:
			var setup_name: Variant = setup_slots.get(slot_name, {}).get("attachment", null)
			var current: Variant = _attachment_at_time(
				setup_name,
				animation.get("slots", {}).get(slot_name, {}).get("attachment", []),
				sample_time
			)
			if current != null:
				visible += 1
		_visibility_samples += 1
		if visible != 1:
			_errors.append("%s at %.7f has %d visible character layers" % [animation_name, sample_time, visible])


func _validate_atlas_contract(wrapper: Dictionary) -> void:
	if str(wrapper.get("source_path", "")) != ROOT + "/vivhite_combat.atlas":
		_errors.append("Atlas wrapper is not final-candidate-local")
	if str(wrapper.get("normal_texture_prefix", "")) != "n" or str(wrapper.get("specular_texture_prefix", "")) != "s":
		_errors.append("Atlas wrapper texture prefixes changed")
	var atlas_data := str(wrapper.get("atlas_data", ""))
	var expected_data := _expected_atlas_data()
	if atlas_data != expected_data:
		_errors.append("Embedded atlas_data differs from the exact five-page/seven-region layout contract")
	for page_name: String in PAGE_SIZES:
		if atlas_data.count(page_name + "\n") != 1:
			_errors.append("Atlas must declare page exactly once: %s" % page_name)
	for region_name: String in [BODY_REGION, ARC_REGION, SIGIL_REGION, DEATH_REGION, ATTACK_REGION, HEAVY_REGION, CAST_REGION]:
		if atlas_data.count(region_name + "\n") != 1:
			_errors.append("Atlas must declare region exactly once: %s" % region_name)


func _expected_atlas_data() -> String:
	return "\n".join(PackedStringArray([
		"vivhite_combat.png",
		"size:3072,2304",
		"filter:Linear,Linear",
		"pma:false",
		"repeat:none",
		BODY_REGION,
		"bounds:16,16,1536,2272",
		ARC_REGION,
		"bounds:1568,16,1488,1104",
		SIGIL_REGION,
		"bounds:1808,1152,1248,1136",
		"",
		"vivhite_combat_death.png",
		"size:2048,1536",
		"filter:Linear,Linear",
		"pma:false",
		"repeat:none",
		DEATH_REGION,
		"bounds:16,16,2016,1504",
		"",
		"vivhite_combat_attack.png",
		"size:2048,2304",
		"filter:Linear,Linear",
		"pma:false",
		"repeat:none",
		ATTACK_REGION,
		"bounds:16,16,1536,2272",
		"",
		"vivhite_combat_attack_heavy.png",
		"size:2048,2304",
		"filter:Linear,Linear",
		"pma:false",
		"repeat:none",
		HEAVY_REGION,
		"bounds:16,16,1536,2272",
		"",
		"vivhite_combat_cast.png",
		"size:2048,2304",
		"filter:Linear,Linear",
		"pma:false",
		"repeat:none",
		CAST_REGION,
		"bounds:16,16,1536,2272",
		"",
	]))


func _validate_tres_contract() -> void:
	if not FileAccess.file_exists(DATA_PATH):
		_errors.append("Final skeleton-data wrapper is missing")
		return
	var final_tres := FileAccess.get_file_as_string(DATA_PATH)
	var cast_tres := FileAccess.get_file_as_string(CAST_ROOT + "/vivhite_combat_skeleton_data.tres")
	if final_tres != cast_tres.replace(CAST_ROOT, ROOT):
		_errors.append("Final skeleton-data wrapper differs from the accepted mix table plus local path rewrite")
	for required_path: String in [ATLAS_PATH, JSON_PATH]:
		if not final_tres.contains(required_path):
			_errors.append("Final skeleton-data wrapper is missing %s" % required_path)
	if final_tres.count("[sub_resource type=\"SpineAnimationMix\"") != MIXES.size():
		_errors.append("Final skeleton-data wrapper must contain exactly ten animation mixes")
	if not final_tres.contains("default_mix = 0.05"):
		_errors.append("Final skeleton-data wrapper lost default_mix = 0.05")
	for spec: Dictionary in MIXES:
		var required := "from = \"%s\"\nto = \"%s\"" % [spec.from, spec.to]
		if not _near(float(spec.mix), 0.0):
			required += "\nmix = %s" % _mix_text(float(spec.mix))
		if not final_tres.contains(required):
			_errors.append("Missing exact mix block %s -> %s = %.2f" % [spec.from, spec.to, spec.mix])


func _mix_text(value: float) -> String:
	if _near(value, 0.10):
		return "0.1"
	if _near(value, 0.03):
		return "0.03"
	if _near(value, 0.02):
		return "0.02"
	return str(value)


func _validate_runtime() -> void:
	for type_name: String in ["SpineSprite", "SpineSkeletonDataResource", "SpineSkeletonFileResource", "SpineAtlasResource"]:
		if not ClassDB.class_exists(type_name):
			_errors.append("Game-compatible Spine class is unavailable: %s" % type_name)
	if not _errors.filter(func(message: String) -> bool: return message.contains("Spine class")).is_empty():
		return
	var data: Resource = ResourceLoader.load(DATA_PATH)
	if data == null or not data.is_class("SpineSkeletonDataResource"):
		_errors.append("Spine runtime could not load Hybrid V3 final skeleton data")
		return
	if str(data.call("get_version")) != "4.2.43":
		_errors.append("Spine runtime must report version 4.2.43")
	if data.call("get_bones").size() != 35:
		_errors.append("Spine runtime must expose exactly 35 bones")
	if data.call("get_slots").size() != 6:
		_errors.append("Spine runtime must expose exactly six slots")
	if data.call("get_animations").size() != 8:
		_errors.append("Spine runtime must expose exactly eight animations")
	if data.call("get_events").size() != 4:
		_errors.append("Spine runtime must expose exactly four events")
	for slot_name: String in ALL_SLOTS:
		if data.call("find_slot", slot_name) == null:
			_errors.append("Spine runtime is missing slot %s" % slot_name)
	for event_name: String in EXPECTED_EVENTS:
		if data.call("find_event", event_name) == null:
			_errors.append("Spine runtime is missing event %s" % event_name)
	for animation_name: String in EXPECTED_ANIMATIONS:
		var animation: Object = data.call("find_animation", animation_name)
		if animation == null:
			_errors.append("Spine runtime is missing animation %s" % animation_name)
			continue
		var duration := float(animation.call("get_duration"))
		if not _near(duration, float(EXPECTED_ANIMATIONS[animation_name])):
			_errors.append("Runtime duration mismatch for %s: %.7f" % [animation_name, duration])
		_sample_runtime_animation(data, animation_name, duration)
	for animation_name: String in LOOP_DURATIONS:
		for sample_time: float in [0.0, float(LOOP_DURATIONS[animation_name]) * 0.5, float(LOOP_DURATIONS[animation_name])]:
			_sample_dirty_loop(data, animation_name, sample_time)
	_validate_runtime_mixes(data)


func _sample_runtime_animation(data: Resource, animation_name: String, duration: float) -> void:
	var sprite: Node2D = ClassDB.instantiate("SpineSprite") as Node2D
	if sprite == null:
		_errors.append("Could not instantiate SpineSprite for %s" % animation_name)
		return
	root.add_child(sprite)
	sprite.set("skeleton_data_res", data)
	var state: Object = sprite.call("get_animation_state")
	var skeleton: Object = sprite.call("get_skeleton")
	if state == null or skeleton == null:
		_errors.append("SpineSprite did not initialize for %s" % animation_name)
		sprite.queue_free()
		return
	state.call("set_animation", animation_name, false, 0)
	var samples: Array[float] = [0.0, duration * 0.5, duration]
	if animation_name == "attack":
		samples.append_array([ATTACK_ENTER - 0.0001, ATTACK_ENTER, ATTACK_PRE_EXIT, ATTACK_EXIT, ATTACK_EXIT + 0.0001, ATTACK_CLEAR, ATTACK_CLEAR + 0.0001])
	elif animation_name == "attack_heavy":
		samples.append_array([HEAVY_ENTER - 0.0001, HEAVY_ENTER, HEAVY_PRE_EXIT, HEAVY_EXIT, HEAVY_EXIT + 0.0001, HEAVY_CLEAR, HEAVY_CLEAR + 0.0001])
	elif animation_name == "cast":
		samples.append_array([CAST_SIGIL_ENTER - 0.0001, CAST_SIGIL_ENTER, CAST_ENTER - 0.0001, CAST_ENTER, CAST_PRE_EXIT, CAST_EXIT, CAST_EXIT + 0.0001, CAST_CLEAR, CAST_CLEAR + 0.0001])
	elif animation_name == "die":
		samples.append_array([DEATH_PRE_SWAP, DEATH_SWAP, DEATH_SWAP + 0.0001, DEATH_IMPACT, DEATH_REBOUND, DEATH_SETTLE])
	samples.sort()
	var previous := 0.0
	for sample_time: float in samples:
		state.call("update", sample_time - previous)
		state.call("apply", skeleton)
		sprite.call("update_skeleton", 0.0)
		_validate_runtime_visibility(skeleton, animation_name, sample_time)
		_runtime_animation_samples += 1
		previous = sample_time
	sprite.queue_free()


func _validate_runtime_visibility(skeleton: Object, animation_name: String, sample_time: float) -> void:
	var expected_body: Variant = BODY_REGION
	var expected_action: Variant = null
	var expected_death: Variant = null
	if animation_name == "attack" and sample_time >= ATTACK_ENTER - EPSILON and sample_time < ATTACK_EXIT - EPSILON:
		expected_body = null
		expected_action = ATTACK_REGION
	elif animation_name == "attack_heavy" and sample_time >= HEAVY_ENTER - EPSILON and sample_time < HEAVY_EXIT - EPSILON:
		expected_body = null
		expected_action = HEAVY_REGION
	elif animation_name == "cast" and sample_time >= CAST_ENTER - EPSILON and sample_time < CAST_EXIT - EPSILON:
		expected_body = null
		expected_action = CAST_REGION
	elif animation_name == "die" and sample_time >= DEATH_SWAP - EPSILON:
		expected_body = null
		expected_death = DEATH_REGION
	var actual := {
		BODY_SLOT: _runtime_attachment_name(skeleton, BODY_SLOT),
		ACTION_SLOT: _runtime_attachment_name(skeleton, ACTION_SLOT),
		DEATH_SLOT: _runtime_attachment_name(skeleton, DEATH_SLOT),
	}
	var expected := {BODY_SLOT: expected_body, ACTION_SLOT: expected_action, DEATH_SLOT: expected_death}
	for slot_name: String in CHARACTER_SLOTS:
		if actual[slot_name] != expected[slot_name]:
			_errors.append("Runtime %s@%.7f has %s=%s, expected %s" % [animation_name, sample_time, slot_name, actual[slot_name], expected[slot_name]])
	if animation_name in ["attack", "attack_heavy"]:
		var slash_enter := ATTACK_ENTER if animation_name == "attack" else HEAVY_ENTER
		var slash_clear := ATTACK_CLEAR if animation_name == "attack" else HEAVY_CLEAR
		# Spine stores event/attachment times as float32. The authored clear key is
		# checked exactly above; sample immediately after it for runtime state and
		# avoid interpreting one-ULP boundary rounding as a lifecycle failure.
		if not _near(sample_time, slash_clear):
			var expected_slash: Variant = ARC_REGION if sample_time >= slash_enter - EPSILON and sample_time < slash_clear else null
			if _runtime_attachment_name(skeleton, SLASH_SLOT) != expected_slash:
				_errors.append("Runtime %s slash lifecycle mismatch at %.7f" % [animation_name, sample_time])
	elif animation_name == "cast":
		var expected_sigil: Variant = SIGIL_REGION if sample_time >= CAST_SIGIL_ENTER - EPSILON and sample_time < CAST_CLEAR - EPSILON else null
		if _runtime_attachment_name(skeleton, SIGIL_SLOT) != expected_sigil:
			_errors.append("Runtime cast sigil lifecycle mismatch at %.7f" % sample_time)
		if _runtime_attachment_name(skeleton, SLASH_SLOT) != null:
			_errors.append("Runtime cast retained slash_mesh at %.7f" % sample_time)


func _sample_dirty_loop(data: Resource, animation_name: String, sample_time: float) -> void:
	var sprite: Node2D = ClassDB.instantiate("SpineSprite") as Node2D
	if sprite == null:
		_errors.append("Could not instantiate SpineSprite for dirty %s sample" % animation_name)
		return
	root.add_child(sprite)
	sprite.set("skeleton_data_res", data)
	var state: Object = sprite.call("get_animation_state")
	var skeleton: Object = sprite.call("get_skeleton")
	if state == null or skeleton == null:
		_errors.append("SpineSprite did not initialize for dirty %s sample" % animation_name)
		sprite.queue_free()
		return
	_set_slot_attachment(skeleton, BODY_SLOT, null)
	_set_slot_attachment(skeleton, ACTION_SLOT, ATTACK_REGION)
	_set_slot_attachment(skeleton, DEATH_SLOT, DEATH_REGION)
	_set_slot_attachment(skeleton, SLASH_SLOT, ARC_REGION)
	_set_slot_attachment(skeleton, SIGIL_SLOT, SIGIL_REGION)
	_set_slot_attachment(skeleton, EYE_SLOT, null)
	var entry: Object = state.call("set_animation", animation_name, true, 0)
	entry.call("set_track_time", sample_time)
	state.call("update", 0.0)
	state.call("apply", skeleton)
	sprite.call("update_skeleton", 0.0)
	var expected := {
		BODY_SLOT: BODY_REGION,
		ACTION_SLOT: null,
		DEATH_SLOT: null,
		SLASH_SLOT: null,
		SIGIL_SLOT: null,
		EYE_SLOT: null,
	}
	for slot_name: String in ALL_SLOTS:
		var actual: Variant = _runtime_attachment_name(skeleton, slot_name)
		if actual != expected[slot_name]:
			_errors.append("Dirty runtime %s@%.7f left %s=%s" % [animation_name, sample_time, slot_name, actual])
	_runtime_loop_reset_samples += 1
	sprite.queue_free()


func _validate_runtime_mixes(data: Resource) -> void:
	var sprite: Node2D = ClassDB.instantiate("SpineSprite") as Node2D
	if sprite == null:
		_errors.append("Could not instantiate SpineSprite for transition validation")
		return
	root.add_child(sprite)
	sprite.set("skeleton_data_res", data)
	var state: Object = sprite.call("get_animation_state")
	var skeleton: Object = sprite.call("get_skeleton")
	if state == null or skeleton == null:
		_errors.append("SpineSprite did not initialize for transition validation")
		sprite.queue_free()
		return
	for spec: Dictionary in MIXES:
		_validate_runtime_mix(sprite, state, skeleton, str(spec.from), str(spec.to), float(spec.mix))
	_validate_runtime_mix(sprite, state, skeleton, "low_health_loop", "relaxed_loop", 0.05)
	sprite.queue_free()


func _validate_runtime_mix(sprite: Node2D, state: Object, skeleton: Object, from_animation: String, to_animation: String, expected: float) -> void:
	if state.has_method("clear_tracks"):
		state.call("clear_tracks")
	state.call("set_animation", from_animation, true, 0)
	state.call("update", 0.05)
	state.call("apply", skeleton)
	sprite.call("update_skeleton", 0.0)
	var entry: Variant = state.call("set_animation", to_animation, false, 0)
	if entry == null or not entry is Object:
		_errors.append("Runtime returned no track entry for %s -> %s" % [from_animation, to_animation])
		return
	var entry_object := entry as Object
	var actual := -1.0
	for method_name: String in ["get_mix_duration", "get_mix_duration_seconds"]:
		if entry_object.has_method(method_name):
			actual = float(entry_object.call(method_name))
			break
	if actual < 0.0:
		_errors.append("Runtime exposes no mix-duration getter for %s -> %s" % [from_animation, to_animation])
		return
	_runtime_mix_samples += 1
	if not _near(actual, expected):
		_errors.append("Runtime mix %s -> %s was %.5f, expected %.5f" % [from_animation, to_animation, actual, expected])


func _set_slot_attachment(skeleton: Object, slot_name: String, attachment_name: Variant) -> void:
	var slot: Variant = skeleton.call("find_slot", slot_name)
	if slot == null:
		_errors.append("Runtime is missing slot %s" % slot_name)
		return
	if attachment_name == null:
		(slot as Object).call("set_attachment", null)
		return
	var attachment: Variant = skeleton.call("get_attachment_by_slot_name", slot_name, attachment_name)
	if attachment == null:
		_errors.append("Runtime cannot resolve %s/%s" % [slot_name, attachment_name])
		return
	(slot as Object).call("set_attachment", attachment)


func _runtime_attachment_name(skeleton: Object, slot_name: String) -> Variant:
	var slot: Variant = skeleton.call("find_slot", slot_name)
	if slot == null:
		return "<missing>"
	var attachment: Variant = (slot as Object).call("get_attachment")
	if attachment == null:
		return null
	return str((attachment as Object).call("get_attachment_name"))


func _key_matches(key: Dictionary, time: float, name: Variant) -> bool:
	return _near(float(key.get("time", 0.0)), time) and key.get("name", null) == name


func _translation_key_matches(key: Dictionary, time: float, position: Vector2) -> bool:
	return (
		_near(float(key.get("time", 0.0)), time)
		and _near(float(key.get("x", 0.0)), position.x)
		and _near(float(key.get("y", 0.0)), position.y)
	)


func _timeline_has_value(keys: Array, time: float, axis: String, expected: float) -> bool:
	for key: Dictionary in keys:
		if _near(float(key.get("time", 0.0)), time):
			return _near(float(key.get(axis, 0.0)), expected)
	return false


func _attachment_at_time(setup_name: Variant, keys: Array, time: float) -> Variant:
	var result: Variant = setup_name
	for key: Dictionary in keys:
		if float(key.get("time", 0.0)) <= time + EPSILON:
			result = key.get("name", null)
		else:
			break
	return result


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


func _named_dictionaries(items: Array) -> Dictionary:
	var result := {}
	for item: Dictionary in items:
		result[str(item.get("name", ""))] = item
	return result


func _load_dictionary(path: String, label: String) -> Dictionary:
	if not FileAccess.file_exists(path):
		_errors.append("Missing %s: %s" % [label, path])
		return {}
	var decoded: Variant = JSON.parse_string(FileAccess.get_file_as_string(path))
	if not decoded is Dictionary:
		_errors.append("Could not parse %s: %s" % [label, path])
		return {}
	return decoded


func _same_variant(left: Variant, right: Variant) -> bool:
	if (left is int or left is float) and (right is int or right is float):
		return _near(float(left), float(right))
	if typeof(left) != typeof(right):
		return false
	if left is Dictionary:
		if left.size() != right.size():
			return false
		for key: Variant in left:
			if not right.has(key) or not _same_variant(left[key], right[key]):
				return false
		return true
	if left is Array:
		if left.size() != right.size():
			return false
		for index in left.size():
			if not _same_variant(left[index], right[index]):
				return false
		return true
	return left == right


func _sorted_keys(dictionary: Dictionary) -> Array[String]:
	var result: Array[String] = []
	for key: Variant in dictionary:
		result.append(str(key))
	result.sort()
	return result


func _sorted_strings(values: Array) -> Array[String]:
	var result: Array[String] = []
	for value: Variant in values:
		result.append(str(value))
	result.sort()
	return result


func _near(left: float, right: float) -> bool:
	return absf(left - right) <= EPSILON


func _finish() -> void:
	if _errors.is_empty():
		print("[hybrid-v3-final] Static, donor-merge, atlas, mix and Spine runtime validation passed")
		print(JSON.stringify({
			"animation_count": EXPECTED_ANIMATIONS.size(),
			"authored_file_count": EXPECTED_FILES.size(),
			"bone_count": 35,
			"event_count": EXPECTED_EVENTS.size(),
			"page_count": PAGE_SIZES.size(),
			"runtime_animation_samples": _runtime_animation_samples,
			"runtime_loop_reset_samples": _runtime_loop_reset_samples,
			"runtime_mix_samples": _runtime_mix_samples,
			"slot_count": ALL_SLOTS.size(),
			"spine_version": "4.2.43",
			"visibility_samples": _visibility_samples,
		}, "  ", false))
		quit(0)
		return
	for message: String in _errors:
		push_error("[hybrid-v3-final] %s" % message)
	quit(1)
