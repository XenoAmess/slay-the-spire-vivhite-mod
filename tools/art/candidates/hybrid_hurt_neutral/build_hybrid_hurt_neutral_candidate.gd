extends SceneTree

## Isolated V3 experiment: keep the complete Hybrid action-set bundle intact
## and replace only `hurt` with a neutral-whole-mesh protective contraction.
##
## The upstream action-set may be produced concurrently by another offline
## builder.  Every copy therefore records all seven authored SHA-256 values
## before and after the snapshot.  One changed snapshot is retried once; a
## second change fails instead of publishing a torn candidate.

const COMMAND := "build-hurt-neutral"
const UPSTREAM_ROOT := "Vivhite/tools/candidates/hybrid_action_set"
const OUTPUT_ROOT := "Vivhite/tools/candidates/hybrid_hurt_neutral"
const UPSTREAM_RESOURCE_ROOT := "res://tools/candidates/hybrid_action_set"
const OUTPUT_RESOURCE_ROOT := "res://tools/candidates/hybrid_hurt_neutral"
const SNAPSHOT_FILE := "upstream_snapshot.json"
const AUTHORED_FILES := [
	"vivhite_combat.png",
	"vivhite_combat.spatlas",
	"vivhite_combat.spjson",
	"vivhite_combat_attack.png",
	"vivhite_combat_attack_heavy.png",
	"vivhite_combat_death.png",
	"vivhite_combat_skeleton_data.tres",
]

const HURT_TIMES := [0.0, 0.10, 0.16, 0.28, 0.46, 0.70, 1.0]
const ACTION_EASING := Vector4(0.20, 0.0, 0.68, 1.0)

var _last_error := ""


func _initialize() -> void:
	call_deferred("_run")


func _run() -> void:
	var args := OS.get_cmdline_user_args()
	if args.is_empty():
		args = PackedStringArray([COMMAND])
	if args[0] in ["-h", "--help", "help"]:
		print("Build the isolated Hybrid neutral-mesh hurt candidate:")
		print("  godot --headless --path tools/art --script res://candidates/hybrid_hurt_neutral/build_hybrid_hurt_neutral_candidate.gd -- build-hurt-neutral")
		quit(0)
		return
	if args[0] != COMMAND:
		quit(_fail("Unknown command: %s" % args[0]))
		return
	var upstream := _absolute_path(UPSTREAM_ROOT)
	var output := _absolute_path(OUTPUT_ROOT)
	if not _build_consistent_snapshot(upstream, output):
		quit(_fail(_last_error))
		return
	quit(0)


func _build_consistent_snapshot(upstream: String, output: String) -> bool:
	if not DirAccess.dir_exists_absolute(upstream):
		return _set_error("Upstream action-set directory does not exist: %s" % upstream)
	var mkdir_error := DirAccess.make_dir_recursive_absolute(output)
	if mkdir_error != OK:
		return _set_error("Could not create candidate output (%s): %s" % [error_string(mkdir_error), output])

	for attempt in 2:
		var before := _snapshot_hashes(upstream)
		if before.is_empty():
			return false
		if not _copy_authored_bundle(upstream, output):
			return false
		if not _rewrite_candidate(output):
			return false
		var after := _snapshot_hashes(upstream)
		if after.is_empty():
			return false
		if before == after:
			var snapshot := {
				"schema": "vivhite.hybrid-hurt-neutral-upstream-snapshot/v1",
				"source_root": UPSTREAM_ROOT,
				"attempts": attempt + 1,
				"sha256": before,
			}
			if not _write_text(output.path_join(SNAPSHOT_FILE), JSON.stringify(snapshot, "\t", false) + "\n"):
				return false
			print("Built isolated neutral-mesh protective hurt candidate:")
			print("  upstream snapshot: %d files, stable on attempt %d" % [before.size(), attempt + 1])
			print("  hurt: guard contraction 0.10s -> recoil 0.28s -> rebound 0.46s -> settle 1.00s")
			print("  output: %s" % output)
			return true
		if attempt == 0:
			print("Upstream changed during copy; rebuilding one clean snapshot...")
	return _set_error("Upstream action-set changed during both snapshot attempts")


func _snapshot_hashes(root_path: String) -> Dictionary:
	var hashes := {}
	for file_name: String in AUTHORED_FILES:
		var path := root_path.path_join(file_name)
		if not FileAccess.file_exists(path):
			_set_error("Upstream action-set is missing authored file: %s" % path)
			return {}
		var digest := FileAccess.get_sha256(path)
		if digest.is_empty():
			_set_error("Could not hash upstream authored file: %s" % path)
			return {}
		hashes[file_name] = digest
	return hashes


func _copy_authored_bundle(source_root: String, output_root: String) -> bool:
	for file_name: String in AUTHORED_FILES:
		var bytes := FileAccess.get_file_as_bytes(source_root.path_join(file_name))
		var output := FileAccess.open(output_root.path_join(file_name), FileAccess.WRITE)
		if output == null:
			return _set_error("Could not open candidate output: %s" % output_root.path_join(file_name))
		output.store_buffer(bytes)
	return true


func _rewrite_candidate(output_root: String) -> bool:
	var json_path := output_root.path_join("vivhite_combat.spjson")
	var decoded: Variant = JSON.parse_string(FileAccess.get_file_as_string(json_path))
	if not decoded is Dictionary:
		return _set_error("Copied Spine JSON could not be parsed")
	var skeleton: Dictionary = decoded
	if not skeleton.get("animations", {}).has("hurt"):
		return _set_error("Copied action-set has no hurt animation")
	skeleton["skeleton"]["hash"] = "vivhite-hybrid-v3-hurt-neutral-v1"
	var original_hurt: Dictionary = skeleton["animations"]["hurt"]
	skeleton["animations"]["hurt"] = _protective_hurt(original_hurt)
	if not _write_text(json_path, JSON.stringify(skeleton, "\t", false) + "\n"):
		return false

	var atlas_path := output_root.path_join("vivhite_combat.spatlas")
	var atlas_decoded: Variant = JSON.parse_string(FileAccess.get_file_as_string(atlas_path))
	if not atlas_decoded is Dictionary:
		return _set_error("Copied Spine atlas wrapper could not be parsed")
	var atlas: Dictionary = atlas_decoded
	atlas["source_path"] = OUTPUT_RESOURCE_ROOT + "/vivhite_combat.atlas"
	if not _write_text(atlas_path, JSON.stringify(atlas, "", false) + "\n"):
		return false

	var tres_path := output_root.path_join("vivhite_combat_skeleton_data.tres")
	var tres := FileAccess.get_file_as_string(tres_path)
	if not tres.contains(UPSTREAM_RESOURCE_ROOT):
		return _set_error("Copied skeleton-data wrapper does not reference the upstream candidate root")
	tres = tres.replace(UPSTREAM_RESOURCE_ROOT, OUTPUT_RESOURCE_ROOT)
	return _write_text(tres_path, tres)


func _protective_hurt(original: Dictionary) -> Dictionary:
	# Preserve consumer-visible slots and events byte-for-byte in structure.  The
	# only authored change is the neutral weighted mesh's bone performance.
	return {
		"bones": {
			"vivhite_rig": {"translate": _translate_track([
				Vector2(0, 0), Vector2(-118, 8), Vector2(-110, 12),
				Vector2(-55, 10), Vector2(24, -4), Vector2(7, 0), Vector2(0, 0),
			])},
			"vivhite_pelvis": {"rotate": _rotate_track([0, -6, -5.5, -2.5, 3, 0.8, 0])},
			"vivhite_torso_lower": {"rotate": _rotate_track([0, -12, -11, -5, 5, 1.2, 0])},
			"vivhite_torso_upper": {"rotate": _rotate_track([0, -17, -16, -7, 7, 1.8, 0])},
			"vivhite_neck": {"rotate": _rotate_track([0, 11, 10, 5, -4, -1, 0])},
			"vivhite_head": {"rotate": _rotate_track([0, 16, 15, 7, -6, -1.5, 0])},

			# Fold both open neutral arms inward.  The screen-left hand guards the
			# abdomen while the screen-right hand covers the chest; this is a short
			# protective recoil, not a new large-angle action silhouette.
			"vivhite_shoulder_left": {"rotate": _rotate_track([0, 10, 9, 4, -4, -1, 0])},
			"vivhite_upper_arm_left": {"rotate": _rotate_track([0, 60, 56, 25, -8, -2, 0])},
			"vivhite_forearm_left": {"rotate": _rotate_track([0, 100, 94, 42, -14, -3, 0])},
			"vivhite_hand_left": {"rotate": _rotate_track([0, -80, -75, -34, 11, 2, 0])},
			"vivhite_shoulder_right": {"rotate": _rotate_track([0, -10, -9, -4, 4, 1, 0])},
			"vivhite_upper_arm_right": {"rotate": _rotate_track([0, 75, 71, 32, -11, -2.5, 0])},
			"vivhite_forearm_right": {"rotate": _rotate_track([0, 75, 71, 32, -11, -2.5, 0])},
			"vivhite_hand_right": {"rotate": _rotate_track([0, -70, -66, -29, 10, 2, 0])},

			# Small knee compression and secondary-motion lag keep the response
			# distinct from low-health breathing without asking the flattened mesh
			# for a new large-angle silhouette.
			"vivhite_hip_left": {"rotate": _rotate_track([0, -4, -4, -2, 2, 0.5, 0])},
			"vivhite_thigh_left": {"rotate": _rotate_track([0, 6, 6, 3, -3, -0.8, 0])},
			"vivhite_shin_left": {"rotate": _rotate_track([0, -9, -9, -4, 4, 1, 0])},
			"vivhite_foot_left": {"rotate": _rotate_track([0, 3, 3, 1, -1, -0.3, 0])},
			"vivhite_hip_right": {"rotate": _rotate_track([0, 4, 4, 2, -2, -0.5, 0])},
			"vivhite_thigh_right": {"rotate": _rotate_track([0, -6, -6, -3, 3, 0.8, 0])},
			"vivhite_shin_right": {"rotate": _rotate_track([0, 9, 9, 4, -4, -1, 0])},
			"vivhite_foot_right": {"rotate": _rotate_track([0, -3, -3, -1, 1, 0.3, 0])},
			"vivhite_hair_crown": {"rotate": _rotate_track([0, 8, 11, 8, -7, -2, 0])},
			"vivhite_hair_left": {"rotate": _rotate_track([0, 18, 24, 17, -10, -3, 0])},
			"vivhite_hair_right": {"rotate": _rotate_track([0, 22, 29, 20, -12, -3, 0])},
			"vivhite_butterfly": {"rotate": _rotate_track([0, 16, 24, 18, -12, -3, 0])},
			"vivhite_skirt_left": {"rotate": _rotate_track([0, 6, 8, 6, -5, -1, 0])},
			"vivhite_skirt_right": {"rotate": _rotate_track([0, -6, -8, -6, 5, 1, 0])},
		},
		"events": original.get("events", []).duplicate(true),
		"slots": original.get("slots", {}).duplicate(true),
	}


func _rotate_track(values: Array) -> Array:
	var keys := []
	for index in HURT_TIMES.size():
		keys.append({"time": HURT_TIMES[index], "value": float(values[index])})
	_add_easing(keys, "rotate")
	return keys


func _translate_track(values: Array) -> Array:
	var keys := []
	for index in HURT_TIMES.size():
		var value: Vector2 = values[index]
		keys.append({"time": HURT_TIMES[index], "x": value.x, "y": value.y})
	_add_easing(keys, "translate")
	return keys


func _add_easing(keys: Array, timeline_name: String) -> void:
	for index in range(keys.size() - 1):
		var start: Dictionary = keys[index]
		var finish: Dictionary = keys[index + 1]
		var start_time := float(start["time"])
		var finish_time := float(finish["time"])
		var control_time_1 := lerpf(start_time, finish_time, ACTION_EASING.x)
		var control_time_2 := lerpf(start_time, finish_time, ACTION_EASING.z)
		if timeline_name == "rotate":
			start["curve"] = [
				control_time_1,
				lerpf(float(start["value"]), float(finish["value"]), ACTION_EASING.y),
				control_time_2,
				lerpf(float(start["value"]), float(finish["value"]), ACTION_EASING.w),
			]
		else:
			start["curve"] = [
				control_time_1, lerpf(float(start["x"]), float(finish["x"]), ACTION_EASING.y),
				control_time_2, lerpf(float(start["x"]), float(finish["x"]), ACTION_EASING.w),
				control_time_1, lerpf(float(start["y"]), float(finish["y"]), ACTION_EASING.y),
				control_time_2, lerpf(float(start["y"]), float(finish["y"]), ACTION_EASING.w),
			]


func _write_text(path: String, content: String) -> bool:
	var output := FileAccess.open(path, FileAccess.WRITE)
	if output == null:
		return _set_error("Could not open text output: %s" % path)
	output.store_string(content)
	return true


func _absolute_path(path: String) -> String:
	if path.is_absolute_path():
		return path.simplify_path()
	var repo_root := ProjectSettings.globalize_path("res://").path_join("../..").simplify_path()
	return repo_root.path_join(path).simplify_path()


func _set_error(message: String) -> bool:
	_last_error = message
	return false


func _fail(message: String) -> int:
	push_error(message)
	return 1
