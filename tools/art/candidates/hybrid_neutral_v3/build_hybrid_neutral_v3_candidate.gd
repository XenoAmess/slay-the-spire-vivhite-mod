extends SceneTree

## Isolated V3 neutral milestone. It snapshots the frozen Hybrid action-set
## candidate, changes no atlas pixels or neutral deformation keys, and adds
## explicit loop-boundary resets for every person/VFX slot. This makes direct
## merchant random seeks and interrupted loop entry deterministic.

const COMMAND := "build-neutral-v3"
const UPSTREAM_ROOT := "res://tools/candidates/hybrid_action_set"
const OUTPUT_ROOT := "res://tools/candidates/hybrid_neutral_v3"
const OUTPUT_RESOURCE_ROOT := "res://tools/candidates/hybrid_neutral_v3"

const EXPECTED_FILES := [
	"vivhite_combat.png",
	"vivhite_combat.spatlas",
	"vivhite_combat.spjson",
	"vivhite_combat_attack.png",
	"vivhite_combat_attack_heavy.png",
	"vivhite_combat_death.png",
	"vivhite_combat_skeleton_data.tres",
]
const BINARY_FILES := [
	"vivhite_combat.png",
	"vivhite_combat_attack.png",
	"vivhite_combat_attack_heavy.png",
	"vivhite_combat_death.png",
]
const LOOP_DURATIONS := {
	"idle_loop": 2.0,
	"low_health_loop": 1.4666667,
	"relaxed_loop": 12.000001,
}
const LOOP_RESET_SLOTS := {
	"vivhite_body": "vivhite_combat_body",
	"vivhite_action_pose": null,
	"vivhite_death_body": null,
	"slash_mesh": null,
	"vivhite_magic_sigil": null,
	"eye_attach_slot": null,
}

var _errors: Array[String] = []


func _initialize() -> void:
	var args := OS.get_cmdline_user_args()
	if args.is_empty():
		args = PackedStringArray([COMMAND])
	if args.size() != 1 or args[0] != COMMAND:
		push_error("Usage: --script res://candidates/hybrid_neutral_v3/build_hybrid_neutral_v3_candidate.gd -- %s" % COMMAND)
		quit(2)
		return
	_build()
	if not _errors.is_empty():
		for message: String in _errors:
			push_error("[hybrid-neutral-v3] %s" % message)
		quit(1)
		return
	print("[hybrid-neutral-v3] Built isolated neutral reset candidate from frozen Hybrid action-set")
	print("  atlas pages: byte-identical; neutral mesh/weights/bones/deformation: unchanged")
	print("  loops: idle_loop, low_health_loop, relaxed_loop reset body/action/death/slash/sigil/eye at both boundaries")
	print("  output: %s" % OUTPUT_ROOT)
	quit(0)


func _build() -> void:
	for file_name: String in EXPECTED_FILES:
		if not FileAccess.file_exists(UPSTREAM_ROOT + "/" + file_name):
			_errors.append("Frozen upstream file is missing: %s" % file_name)
	if not _errors.is_empty():
		return
	var output_absolute := ProjectSettings.globalize_path(OUTPUT_ROOT)
	var mkdir_error := DirAccess.make_dir_recursive_absolute(output_absolute)
	if mkdir_error != OK:
		_errors.append("Could not create candidate output: %s" % error_string(mkdir_error))
		return

	for file_name: String in BINARY_FILES:
		_copy_binary(UPSTREAM_ROOT + "/" + file_name, OUTPUT_ROOT + "/" + file_name)

	var skeleton_value: Variant = JSON.parse_string(
		FileAccess.get_file_as_string(UPSTREAM_ROOT + "/vivhite_combat.spjson")
	)
	if not skeleton_value is Dictionary:
		_errors.append("Frozen upstream Spine JSON is invalid")
		return
	var skeleton: Dictionary = skeleton_value
	skeleton["skeleton"]["hash"] = "vivhite-hybrid-v3-neutral-reset-v1"
	_patch_neutral_loops(skeleton)
	_write_text(
		OUTPUT_ROOT + "/vivhite_combat.spjson",
		JSON.stringify(skeleton, "  ", false) + "\n"
	)

	var atlas_value: Variant = JSON.parse_string(
		FileAccess.get_file_as_string(UPSTREAM_ROOT + "/vivhite_combat.spatlas")
	)
	if not atlas_value is Dictionary:
		_errors.append("Frozen upstream atlas wrapper is invalid")
		return
	var atlas: Dictionary = atlas_value
	atlas["source_path"] = OUTPUT_RESOURCE_ROOT + "/vivhite_combat.atlas"
	_write_text(
		OUTPUT_ROOT + "/vivhite_combat.spatlas",
		JSON.stringify(atlas, "", false) + "\n"
	)

	var tres := FileAccess.get_file_as_string(
		UPSTREAM_ROOT + "/vivhite_combat_skeleton_data.tres"
	).replace(UPSTREAM_ROOT, OUTPUT_RESOURCE_ROOT)
	_write_text(OUTPUT_ROOT + "/vivhite_combat_skeleton_data.tres", tres)

	for file_name: String in BINARY_FILES:
		var upstream := UPSTREAM_ROOT + "/" + file_name
		var output := OUTPUT_ROOT + "/" + file_name
		if FileAccess.get_sha256(upstream) != FileAccess.get_sha256(output):
			_errors.append("Atlas page changed while snapshotting: %s" % file_name)


func _patch_neutral_loops(skeleton: Dictionary) -> void:
	var animations: Dictionary = skeleton.get("animations", {})
	for animation_name: String in LOOP_DURATIONS:
		if not animations.has(animation_name):
			_errors.append("Upstream is missing neutral loop: %s" % animation_name)
			continue
		var animation: Dictionary = animations[animation_name]
		var slots: Dictionary = animation.get("slots", {})
		animation["slots"] = slots
		var duration := float(LOOP_DURATIONS[animation_name])
		for slot_name: String in LOOP_RESET_SLOTS:
			var attachment_name: Variant = LOOP_RESET_SLOTS[slot_name]
			slots[slot_name] = {"attachment": [
				{"time": 0.0, "name": attachment_name},
				{"time": duration, "name": attachment_name},
			]}


func _copy_binary(source_path: String, output_path: String) -> void:
	var bytes := FileAccess.get_file_as_bytes(source_path)
	if bytes.is_empty():
		_errors.append("Could not read binary input: %s" % source_path)
		return
	var file := FileAccess.open(output_path, FileAccess.WRITE)
	if file == null:
		_errors.append("Could not open binary output: %s" % output_path)
		return
	file.store_buffer(bytes)
	file.close()


func _write_text(path: String, content: String) -> void:
	var file := FileAccess.open(path, FileAccess.WRITE)
	if file == null:
		_errors.append("Could not open text output: %s" % path)
		return
	file.store_string(content)
	file.close()
