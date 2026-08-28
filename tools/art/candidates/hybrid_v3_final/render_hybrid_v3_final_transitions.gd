extends SceneTree

## Continuous Windows/Vulkan interruption acceptance for hybrid_v3_final.
##
## Unlike the exact single-animation samplers, every sequence below keeps one
## SpineSprite, SpineAnimationState and TrackEntry alive while time advances in
## bounded increments. It never seeks a fresh sprite for an individual frame.
## The preferred path instantiates the production combat.tscn and lets the real
## NIroncladVfx consume Spine signals. If the standalone editor cannot activate
## the game's C# script, the same production node/material topology is retained
## and only NIroncladVfx's decompiled event lifecycle is simulated explicitly.

const CANDIDATE_DATA_PATH := "res://tools/candidates/hybrid_v3_final/vivhite_combat_skeleton_data.tres"
const CANDIDATE_JSON_PATH := "res://tools/candidates/hybrid_v3_final/vivhite_combat.spjson"
const FORMAL_COMBAT_SCENE_PATH := "res://Vivhite/skins/ironclad/scenes/combat.tscn"
const FORMAL_VISUALS_SCRIPT_PATH := "res://src/Core/Nodes/Combat/NCreatureVisuals.cs"
const FORMAL_VFX_SCRIPT_PATH := "res://src/Core/Nodes/Vfx/NIroncladVfx.cs"
const DEFAULT_OUTPUT := ".work/combat-rig-compare-preview/hybrid-v3-final-transitions"
const DEFAULT_CANVAS := Vector2i(1280, 900)
const DEFAULT_ORIGIN := Vector2(320.0, 700.0)
const DEFAULT_SCENE_OFFSET := Vector2(5.0, -19.0)
const DEFAULT_SCENE_SCALE := 0.28
const SPINE_UPDATE_MODE_MANUAL := 2
const STEP_SECONDS := 1.0 / 120.0
const MIX_EPSILON_SECONDS := 0.001
const FLOAT_EPSILON := 0.00002
const ALPHA_THRESHOLD := 1
const ALPHA_METRIC_MAX_DIMENSION := 256
const CONTACT_TILE := Vector2i(256, 180)
const CONTACT_GAP := 8
const CONTACT_PADDING := 12

const BODY_SLOT := "vivhite_body"
const ACTION_SLOT := "vivhite_action_pose"
const DEATH_SLOT := "vivhite_death_body"
const SLASH_SLOT := "slash_mesh"
const SIGIL_SLOT := "vivhite_magic_sigil"
const EYE_SLOT := "eye_attach_slot"
const SIX_SLOTS: Array[String] = [
	BODY_SLOT,
	ACTION_SLOT,
	DEATH_SLOT,
	SLASH_SLOT,
	SIGIL_SLOT,
	EYE_SLOT,
]
const CHARACTER_SLOTS: Array[String] = [BODY_SLOT, ACTION_SLOT, DEATH_SLOT]

const BODY_ATTACHMENT := "vivhite_combat_body"
const ATTACK_ATTACHMENT := "vivhite_combat_attack_peak"
const HEAVY_ATTACHMENT := "vivhite_combat_attack_heavy_peak"
const CAST_ATTACHMENT := "vivhite_combat_cast_peak"
const DEATH_ATTACHMENT := "vivhite_combat_death_side"
const SLASH_ATTACHMENT := "vivhite_combat_magic_arc"
const SIGIL_ATTACHMENT := "vivhite_combat_magic_sigil"

const ATTACK_ENTER := 0.08
const ATTACK_EXIT := 0.20
const ATTACK_CLEAR := 0.886666692
const HEAVY_ENTER := 0.12
const HEAVY_EXIT := 0.32
const HEAVY_CLEAR := 1.165333384
const CAST_SIGIL_ENTER := 0.10
const CAST_ENTER := 0.25
const CAST_EXIT := 0.60
const CAST_CLEAR := 1.222000026
const DEATH_SWAP := 1.05

const EYE_FIRE_TEXTURE := "res://images/vfx/characters/ironclad_eye_fire_base.png"
const EYE_FIRE_SHADER := "res://shaders/vfx/vfx_stepped_shader_fire_flat.tres"
const FIRE_ZIGZAG := "res://images/vfx/fire/zigzag_fire_distortion.png"
const FIRE_TILE_NOISE := "res://images/vfx/tileable_noise_1.png"
const FIRE_GRADIENT := "res://images/vfx/environment/fire/basic_fire_gradient.png"
const FIRE_BOTTOM_MASK := "res://images/vfx/fire/fire_bottom_mask.png"
const FIRE_TRIANGLE_NOISE := "res://images/vfx/fire/triangle_noise_tile.png"

const SEQUENCES: Array[Dictionary] = [
	{"name": "attack_to_attack", "source": "attack", "source_active": 0.10, "target": "attack", "target_active": 0.10, "target_mix": 0.0},
	{"name": "attack_to_heavy", "source": "attack", "source_active": 0.10, "target": "attack_heavy", "target_active": 0.14, "target_mix": 0.0},
	{"name": "attack_to_cast", "source": "attack", "source_active": 0.10, "target": "cast", "target_active": 0.30, "target_mix": 0.05},
	{"name": "attack_to_hurt", "source": "attack", "source_active": 0.10, "target": "hurt", "target_active": 0.28, "target_mix": 0.05},
	{"name": "attack_to_die", "source": "attack", "source_active": 0.10, "target": "die", "target_active": 0.20, "target_mix": 0.05},
	{"name": "attack_to_idle", "source": "attack", "source_active": 0.10, "target": "idle_loop", "target_active": 0.12, "target_mix": 0.05},
	{"name": "heavy_to_attack", "source": "attack_heavy", "source_active": 0.14, "target": "attack", "target_active": 0.10, "target_mix": 0.0},
	{"name": "heavy_to_heavy", "source": "attack_heavy", "source_active": 0.14, "target": "attack_heavy", "target_active": 0.14, "target_mix": 0.0},
	{"name": "heavy_to_cast", "source": "attack_heavy", "source_active": 0.14, "target": "cast", "target_active": 0.30, "target_mix": 0.05},
	{"name": "heavy_to_hurt", "source": "attack_heavy", "source_active": 0.14, "target": "hurt", "target_active": 0.28, "target_mix": 0.05},
	{"name": "heavy_to_die", "source": "attack_heavy", "source_active": 0.14, "target": "die", "target_active": 0.20, "target_mix": 0.05},
	{"name": "heavy_to_idle", "source": "attack_heavy", "source_active": 0.14, "target": "idle_loop", "target_active": 0.12, "target_mix": 0.05},
	{"name": "cast_to_attack", "source": "cast", "source_active": 0.30, "target": "attack", "target_active": 0.10, "target_mix": 0.05},
	{"name": "cast_to_heavy", "source": "cast", "source_active": 0.30, "target": "attack_heavy", "target_active": 0.14, "target_mix": 0.05},
	{"name": "cast_to_cast", "source": "cast", "source_active": 0.30, "target": "cast", "target_active": 0.30, "target_mix": 0.05},
	{"name": "cast_to_hurt", "source": "cast", "source_active": 0.30, "target": "hurt", "target_active": 0.28, "target_mix": 0.05},
	{"name": "cast_to_die", "source": "cast", "source_active": 0.30, "target": "die", "target_active": 0.20, "target_mix": 0.05},
	{"name": "cast_to_idle", "source": "cast", "source_active": 0.30, "target": "idle_loop", "target_active": 0.12, "target_mix": 0.05},
	{"name": "hurt_to_attack", "source": "hurt", "source_active": 0.28, "target": "attack", "target_active": 0.10, "target_mix": 0.05},
	{"name": "hurt_to_heavy", "source": "hurt", "source_active": 0.28, "target": "attack_heavy", "target_active": 0.14, "target_mix": 0.05},
	{"name": "hurt_to_cast", "source": "hurt", "source_active": 0.28, "target": "cast", "target_active": 0.30, "target_mix": 0.05},
	{"name": "hurt_to_hurt", "source": "hurt", "source_active": 0.28, "target": "hurt", "target_active": 0.28, "target_mix": 0.0},
	{"name": "hurt_to_die", "source": "hurt", "source_active": 0.28, "target": "die", "target_active": 0.20, "target_mix": 0.0},
	{"name": "hurt_to_idle", "source": "hurt", "source_active": 0.28, "target": "idle_loop", "target_active": 0.12, "target_mix": 0.10},
	{"name": "die_to_idle", "source": "die", "source_active": 1.10, "target": "idle_loop", "target_active": 0.12, "target_mix": 0.05},
]

var _errors: Array[String] = []
var _output_root := ""
var _canvas := DEFAULT_CANVAS
var _origin := DEFAULT_ORIGIN
var _scene_offset := DEFAULT_SCENE_OFFSET
var _scene_scale := DEFAULT_SCENE_SCALE
var _sequence_clock := 0.0
var _pending_event_clock := 0.0
var _active_context: Dictionary = {}
var _active_event_log: Array = []
var _contact_images: Array[Image] = []
var _contact_validity: Array[bool] = []
var _sample_serial := 0


func _initialize() -> void:
	if DisplayServer.get_name() != "headless":
		DisplayServer.window_set_flag(DisplayServer.WINDOW_FLAG_NO_FOCUS, true)
		DisplayServer.window_set_position(Vector2i(-32000, -32000))
	call_deferred("_run")


func _run() -> void:
	var options := _parse_args()
	if options.is_empty():
		quit(2)
		return
	_output_root = _safe_output_root(str(options["output"]))
	if _output_root.is_empty():
		quit(2)
		return
	_canvas = Vector2i(int(options["width"]), int(options["height"]))
	_origin = Vector2(float(options["origin-x"]), float(options["origin-y"]))
	_scene_offset = Vector2(float(options["scene-offset-x"]), float(options["scene-offset-y"]))
	_scene_scale = float(options["scene-scale"])
	if DirAccess.dir_exists_absolute(_output_root) and not _directory_is_empty(_output_root):
		_fail("Output must be new or empty so earlier evidence is never overwritten: %s" % _output_root)
		quit(2)
		return
	DirAccess.make_dir_recursive_absolute(_output_root)

	var report := {
		"base_pck": str(options["pck"]).replace("\\", "/"),
		"base_pck_sha256": FileAccess.get_sha256(str(options["pck"])) if FileAccess.file_exists(str(options["pck"])) else "",
		"candidate": CANDIDATE_DATA_PATH,
		"candidate_sha256": FileAccess.get_sha256(CANDIDATE_DATA_PATH) if FileAccess.file_exists(CANDIDATE_DATA_PATH) else "",
		"candidate_spjson": CANDIDATE_JSON_PATH,
		"candidate_spjson_sha256": FileAccess.get_sha256(CANDIDATE_JSON_PATH) if FileAccess.file_exists(CANDIDATE_JSON_PATH) else "",
		"canvas": [_canvas.x, _canvas.y],
		"consumer_fidelity": {},
		"continuous_contract": {
			"fresh_seek_count": 0,
			"max_update_step_seconds": STEP_SECONDS,
			"one_animation_state_per_sequence": true,
			"same_track_entry_between_segment_samples": true,
			"target_gate_samples": ["target_t0", "target_mix_epsilon"],
		},
		"display_server": DisplayServer.get_name(),
		"errors": [],
		"formal_scene": FORMAL_COMBAT_SCENE_PATH,
		"generated_utc": Time.get_datetime_string_from_system(true),
		"origin": [_origin.x, _origin.y],
		"pass": false,
		"rendering_driver": RenderingServer.get_current_rendering_driver_name(),
		"required_slots": SIX_SLOTS,
		"scene_offset": [_scene_offset.x, _scene_offset.y],
		"scene_scale": _scene_scale,
		"schema_version": 1,
		"sequence_count": 0,
		"sequences": [],
		"success": false,
	}

	if not _prepare_runtime(str(options["pck"])):
		report.errors = _errors.duplicate()
		_write_reports(report)
		quit(2)
		return
	var skeleton_data: Resource = ResourceLoader.load(CANDIDATE_DATA_PATH)
	if skeleton_data == null or not skeleton_data.is_class("SpineSkeletonDataResource"):
		_fail("Could not load final candidate SpineSkeletonDataResource: %s" % CANDIDATE_DATA_PATH)
		report.errors = _errors.duplicate()
		_write_reports(report)
		quit(2)
		return

	var viewport := SubViewport.new()
	viewport.name = "VivhiteHybridV3FinalTransitionViewport"
	viewport.size = _canvas
	viewport.transparent_bg = true
	viewport.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	viewport.render_target_clear_mode = SubViewport.CLEAR_MODE_ALWAYS
	root.add_child(viewport)
	var stage := Node2D.new()
	stage.name = "TransitionStage"
	viewport.add_child(stage)

	var actual_consumer_count := 0
	var simulated_consumer_count := 0
	var formal_topology_count := 0
	var first_fidelity: Dictionary = {}
	for definition: Dictionary in SEQUENCES:
		var sequence_report: Dictionary = await _run_sequence(stage, viewport, skeleton_data, definition)
		report.sequences.append(sequence_report)
		var fidelity: Dictionary = sequence_report.get("consumer_fidelity", {})
		if first_fidelity.is_empty():
			first_fidelity = fidelity.duplicate(true)
		if bool(fidelity.get("actual_nironclad_vfx_active", false)):
			actual_consumer_count += 1
		else:
			simulated_consumer_count += 1
		if bool(fidelity.get("formal_scene_topology_used", false)):
			formal_topology_count += 1

	var sequence_count := int(report.sequences.size())
	var sample_count := 0
	var all_sequences_passed := sequence_count == SEQUENCES.size()
	for sequence_value: Variant in report.sequences:
		var sequence: Dictionary = sequence_value
		sample_count += int((sequence.get("samples", []) as Array).size())
		if not bool(sequence.get("passed", false)):
			all_sequences_passed = false
	var coverage := _validate_coverage(report.sequences)
	if not bool(coverage.get("passed", false)):
		all_sequences_passed = false

	var sheet_path := _output_root.path_join("contact-sheets/all-transition-checkpoints.png")
	var sheet_ok := _write_contact_sheet(_contact_images, _contact_validity, sheet_path, 6)
	if not sheet_ok:
		_fail("Could not write the aggregate transition contact sheet.")
		all_sequences_passed = false
	report["contact_sheet"] = _relative_to_output(sheet_path) if sheet_ok else ""
	report["consumer_fidelity"] = {
		"actual_nironclad_sequence_count": actual_consumer_count,
		"decompiled_contract_sha256": _decompiled_consumer_sha256(),
		"first_sequence_probe": first_fidelity,
		"formal_scene_topology_sequence_count": formal_topology_count,
		"simulation_sequence_count": simulated_consumer_count,
		"simulation_is_not_claimed_as_real_csharp": simulated_consumer_count > 0,
	}
	report["coverage"] = coverage
	report["sample_count"] = sample_count
	report["sequence_count"] = sequence_count
	report.errors = _errors.duplicate()
	report["pass"] = all_sequences_passed and sheet_ok and _errors.is_empty()
	report["success"] = bool(report["pass"])
	_write_reports(report)
	if bool(report["pass"]):
		print("[hybrid-v3-final-transitions] Passed %d continuous sequences / %d Vulkan checkpoints." % [sequence_count, sample_count])
		quit(0)
		return
	push_error("[hybrid-v3-final-transitions] Continuous transition acceptance failed; see transition_summary.json.")
	quit(1)


func _parse_args() -> Dictionary:
	var options := {
		"height": DEFAULT_CANVAS.y,
		"origin-x": DEFAULT_ORIGIN.x,
		"origin-y": DEFAULT_ORIGIN.y,
		"output": DEFAULT_OUTPUT,
		"pck": OS.get_environment("VIVHITE_STS2_PCK_PATH"),
		"scene-offset-x": DEFAULT_SCENE_OFFSET.x,
		"scene-offset-y": DEFAULT_SCENE_OFFSET.y,
		"scene-scale": DEFAULT_SCENE_SCALE,
		"width": DEFAULT_CANVAS.x,
	}
	var args := OS.get_cmdline_user_args()
	var index := 0
	if index < args.size() and str(args[index]) == "render-transitions":
		index += 1
	if index < args.size() and not str(args[index]).begins_with("--"):
		options["output"] = str(args[index])
		index += 1
	while index < args.size():
		var key := str(args[index])
		if not key.begins_with("--") or index + 1 >= args.size():
			_fail("Expected '--name value', got '%s'." % key)
			return {}
		var name := key.trim_prefix("--")
		if not options.has(name):
			_fail("Unknown option '%s'." % key)
			return {}
		index += 1
		var value := str(args[index])
		match name:
			"width", "height":
				options[name] = value.to_int()
			"scene-scale", "origin-x", "origin-y", "scene-offset-x", "scene-offset-y":
				options[name] = value.to_float()
			_:
				options[name] = value
		index += 1
	if int(options["width"]) < 64 or int(options["height"]) < 64:
		_fail("Canvas dimensions must both be at least 64 pixels.")
	if float(options["scene-scale"]) <= 0.0:
		_fail("Scene scale must be positive.")
	return options if _errors.is_empty() else {}


func _prepare_runtime(pck_path: String) -> bool:
	if DisplayServer.get_name() == "headless":
		_fail("A Windows display with Vulkan is required; headless uses the dummy rasterizer.")
	var driver := RenderingServer.get_current_rendering_driver_name()
	if driver.to_lower() != "vulkan":
		_fail("Expected Vulkan, but Godot selected '%s'." % driver)
	if pck_path.is_empty() or not FileAccess.file_exists(pck_path):
		_fail("A valid base-game PCK is required via --pck or VIVHITE_STS2_PCK_PATH.")
	elif not ProjectSettings.load_resource_pack(pck_path, false):
		_fail("Could not mount base-game PCK '%s'." % pck_path)
	for type_name: String in ["SpineSprite", "SpineSkeletonDataResource", "SpineSlotNode"]:
		if not ClassDB.class_exists(type_name):
			_fail("The game's Spine GDExtension class '%s' is unavailable." % type_name)
	if not ResourceLoader.exists(CANDIDATE_DATA_PATH):
		_fail("Final candidate resource is missing: %s" % CANDIDATE_DATA_PATH)
	return _errors.is_empty()


func _run_sequence(
	stage: Node2D,
	viewport: SubViewport,
	skeleton_data: Resource,
	definition: Dictionary,
) -> Dictionary:
	var sequence_name := str(definition["name"])
	var context: Dictionary = await _create_context(stage, skeleton_data)
	var report := {
		"consumer_fidelity": context.get("fidelity", {}),
		"definition": definition,
		"errors": [],
		"events": [],
		"name": sequence_name,
		"passed": false,
		"samples": [],
		"state_instance_id": 0,
		"track_entries": [],
	}
	if context.is_empty():
		report.errors = ["Could not create a Spine consumer context."]
		return report
	_active_context = context
	_active_event_log = []
	_sequence_clock = 0.0
	_pending_event_clock = 0.0
	var state: Object = context["state"]
	var skeleton: Object = context["skeleton"]
	report["state_instance_id"] = state.get_instance_id()
	if not _connect_observers(context):
		report.errors = ["Could not connect Spine lifecycle observers."]
		await _dispose_context(context)
		_active_context = {}
		return report

	var idle_entry: Variant = _set_segment(context, "idle_loop", true)
	report.track_entries.append(_entry_report("initial_idle", idle_entry, 0.0, -1.0))
	await _advance_to(context, 0.25)

	var source_name := str(definition["source"])
	var source_entry: Variant = _set_segment(context, source_name, false)
	var source_mix := _track_entry_mix_duration(source_entry)
	report.track_entries.append(_entry_report("source", source_entry, source_mix, _expected_idle_mix(source_name)))
	await _advance_to(context, float(definition["source_active"]))
	var source_sample := await _capture_checkpoint(
		viewport, context, sequence_name, "source_active", source_name,
		float(definition["source_active"]), source_entry,
		_expected_external_eye(source_name, float(definition["source_active"]))
	)
	report.samples.append(source_sample)

	var target_name := str(definition["target"])
	var target_entry: Variant = _set_segment(context, target_name, target_name == "idle_loop")
	var target_mix := _track_entry_mix_duration(target_entry)
	var expected_target_mix := float(definition["target_mix"])
	var target_entry_report := _entry_report("target", target_entry, target_mix, expected_target_mix)
	report.track_entries.append(target_entry_report)
	if not bool(target_entry_report["mix_passed"]):
		_fail("[%s] %s -> %s mix was %.7f, expected %.7f." % [sequence_name, source_name, target_name, target_mix, expected_target_mix])
	await _apply_zero(context)
	var target_t0 := await _capture_checkpoint(
		viewport, context, sequence_name, "target_t0", target_name, 0.0,
		target_entry, _expected_external_eye(target_name, 0.0)
	)
	report.samples.append(target_t0)

	var mix_gate_time := maxf(0.0, target_mix) + MIX_EPSILON_SECONDS
	await _advance_to(context, mix_gate_time)
	var target_mix_sample := await _capture_checkpoint(
		viewport, context, sequence_name, "target_mix_epsilon", target_name,
		mix_gate_time, target_entry,
		_expected_external_eye(target_name, mix_gate_time)
	)
	report.samples.append(target_mix_sample)

	var target_active_time := maxf(float(definition["target_active"]), mix_gate_time)
	await _advance_to(context, target_active_time)
	var target_active := await _capture_checkpoint(
		viewport, context, sequence_name, "target_active", target_name,
		target_active_time, target_entry,
		_expected_external_eye(target_name, target_active_time)
	)
	report.samples.append(target_active)

	if target_name == "die":
		var death_landed_time := DEATH_SWAP + MIX_EPSILON_SECONDS
		await _advance_to(context, death_landed_time)
		var death_landed := await _capture_checkpoint(
			viewport, context, sequence_name, "death_attachment", target_name,
			death_landed_time, target_entry, false
		)
		report.samples.append(death_landed)
	elif bool(definition.get("return_idle", false)):
		var return_entry: Variant = _set_segment(context, "idle_loop", true)
		var return_mix := _track_entry_mix_duration(return_entry)
		var expected_return_mix := _expected_return_idle_mix(target_name)
		var return_entry_report := _entry_report("return_idle", return_entry, return_mix, expected_return_mix)
		report.track_entries.append(return_entry_report)
		if not bool(return_entry_report["mix_passed"]):
			_fail("[%s] %s -> idle_loop mix was %.7f, expected %.7f." % [sequence_name, target_name, return_mix, expected_return_mix])
		await _apply_zero(context)
		var return_t0 := await _capture_checkpoint(
			viewport, context, sequence_name, "return_idle_t0", "idle_loop", 0.0,
			return_entry, false
		)
		report.samples.append(return_t0)
		var return_gate_time := maxf(0.0, return_mix) + MIX_EPSILON_SECONDS
		await _advance_to(context, return_gate_time)
		var return_settled := await _capture_checkpoint(
			viewport, context, sequence_name, "return_idle_mix_epsilon", "idle_loop",
			return_gate_time, return_entry, false
		)
		report.samples.append(return_settled)

	report["events"] = _active_event_log.duplicate(true)
	var sequence_passed := true
	var sequence_errors: Array[String] = []
	for entry_value: Variant in report.track_entries:
		var entry_data: Dictionary = entry_value
		if not bool(entry_data.get("entry_valid", false)) or not bool(entry_data.get("mix_passed", true)):
			sequence_passed = false
			sequence_errors.append("TrackEntry gate failed for %s." % str(entry_data.get("role", "unknown")))
	for sample_value: Variant in report.samples:
		var sample: Dictionary = sample_value
		if not bool(sample.get("passed", false)):
			sequence_passed = false
			sequence_errors.append("Checkpoint failed: %s." % str(sample.get("checkpoint", "unknown")))
	report["errors"] = sequence_errors
	report["passed"] = sequence_passed
	await _dispose_context(context)
	_active_context = {}
	return report


func _create_context(stage: Node2D, skeleton_data: Resource) -> Dictionary:
	var scene_root: Node2D = null
	var sprite: Node2D = null
	var formal_scene_loaded := false
	var formal_scene_instantiated := false
	var formal_topology_used := false
	var project_assembly := str(ProjectSettings.get_setting("dotnet/project/assembly_name", ""))
	# The v0.111.0 game classes are registered by the sts2 project assembly.
	# Calling CSharpScript.can_instantiate() for them from the Vivhite editor
	# project itself emits an engine ERROR, so use the owning assembly as the
	# non-destructive preflight. The earlier direct probe established the same
	# class-not-found result; the summary pins both script resource paths.
	var owns_game_scripts := project_assembly.to_lower() == "sts2"
	var visuals_script_instantiable := owns_game_scripts and ResourceLoader.exists(FORMAL_VISUALS_SCRIPT_PATH)
	var vfx_script_instantiable := owns_game_scripts and ResourceLoader.exists(FORMAL_VFX_SCRIPT_PATH)
	var formal_scripts_instantiable := visuals_script_instantiable and vfx_script_instantiable
	var scene_resource: Resource = null
	if ResourceLoader.exists(FORMAL_COMBAT_SCENE_PATH):
		scene_resource = ResourceLoader.load(FORMAL_COMBAT_SCENE_PATH)
		formal_scene_loaded = scene_resource is PackedScene
	# PackedScene.instantiate() emits engine-level errors when these C# classes
	# are absent from the standalone editor's loaded assembly. Preflight avoids
	# repeating that known failure eleven times while still recording the exact
	# evidence gap. A real game process remains the final C# consumer gate.
	if scene_resource is PackedScene and formal_scripts_instantiable:
		var instance: Node = (scene_resource as PackedScene).instantiate()
		if instance is Node2D:
			scene_root = instance as Node2D
			formal_scene_instantiated = true
			sprite = scene_root.get_node_or_null("Visuals") as Node2D
			formal_topology_used = sprite != null
	if sprite == null:
		if scene_root != null:
			scene_root.queue_free()
		var fallback := _create_programmatic_scene(skeleton_data)
		if fallback.is_empty():
			_fail("Could not instantiate either formal combat.tscn or the programmatic production-topology fallback.")
			return {}
		scene_root = fallback["root"] as Node2D
		sprite = fallback["sprite"] as Node2D
	else:
		sprite.call("set_update_mode", SPINE_UPDATE_MODE_MANUAL)
		sprite.set("skeleton_data_res", skeleton_data)
		scene_root.position = _origin
	stage.add_child(scene_root)
	await process_frame

	var state: Object = sprite.call("get_animation_state")
	var skeleton: Object = sprite.call("get_skeleton")
	var eye_fire: CanvasItem = scene_root.get_node_or_null("Visuals/EyeSlot/EyeFire") as CanvasItem
	var slash_slot_node: Node = scene_root.get_node_or_null("Visuals/SlashVfxSlot")
	var vfx_node: Node = scene_root.get_node_or_null("Visuals/NIroncladVfx")
	if state == null or skeleton == null or eye_fire == null:
		_fail("Combat consumer did not initialize Spine state/skeleton/EyeFire.")
		scene_root.queue_free()
		await process_frame
		return {}
	var vfx_script_path := ""
	if vfx_node != null and vfx_node.get_script() != null:
		vfx_script_path = str((vfx_node.get_script() as Script).resource_path)
	var method_available := vfx_node != null and vfx_node.has_method("OnClearVfx")
	var initial_eye_hidden := not eye_fire.visible
	var actual_consumer_active := formal_topology_used and method_available and initial_eye_hidden
	if not actual_consumer_active:
		eye_fire.visible = false
		eye_fire.modulate = Color.WHITE
	_reset_slash_material(slash_slot_node)
	var fidelity := {
		"actual_nironclad_vfx_active": actual_consumer_active,
		"consumer_mode": "formal_combat_scene_with_NIroncladVfx" if actual_consumer_active else ("formal_combat_scene_topology_with_lifecycle_simulation" if formal_topology_used else "programmatic_production_topology_with_lifecycle_simulation"),
		"formal_scene_exists_after_pck_mount": ResourceLoader.exists(FORMAL_COMBAT_SCENE_PATH),
		"formal_scene_instantiated": formal_scene_instantiated,
		"formal_scene_loaded": formal_scene_loaded,
		"formal_scene_topology_used": formal_topology_used,
		"formal_instantiation_skipped_reason": "" if formal_scripts_instantiable else "The standalone project's dotnet/project/assembly_name is not sts2, so the game-owned NCreatureVisuals/NIroncladVfx C# classes are not registered here; a direct probe produced the matching class-not-found result.",
		"initial_eye_fire_hidden_after_ready": initial_eye_hidden,
		"limitation": "" if actual_consumer_active else "Standalone Godot did not expose a live NIroncladVfx method/Ready side effect; event visibility and slash tween are simulated from the pinned v0.111.0 decompile, while the production Spine state, six slots, scene transforms/material parameters and Vulkan renderer remain real.",
		"nironclad_method_available": method_available,
		"nironclad_script_path": vfx_script_path,
		"nironclad_script_resource_instantiable": vfx_script_instantiable,
		"project_assembly_name": project_assembly,
		"visuals_script_resource_instantiable": visuals_script_instantiable,
	}
	return {
		"actual_consumer": actual_consumer_active,
		"active_entry": null,
		"eye_fire": eye_fire,
		"fidelity": fidelity,
		"root": scene_root,
		"segment_elapsed": 0.0,
		"sim_slash_elapsed": 0.0,
		"sim_slash_kind": "",
		"sim_slash_material": _slash_material(slash_slot_node),
		"skeleton": skeleton,
		"sprite": sprite,
		"state": state,
	}


func _create_programmatic_scene(skeleton_data: Resource) -> Dictionary:
	var scene_root := Node2D.new()
	scene_root.name = "VivhiteIroncladFallback"
	scene_root.position = _origin
	var sprite: Node2D = ClassDB.instantiate("SpineSprite") as Node2D
	if sprite == null:
		return {}
	sprite.name = "Visuals"
	sprite.call("set_update_mode", SPINE_UPDATE_MODE_MANUAL)
	sprite.set("skeleton_data_res", skeleton_data)
	sprite.position = _scene_offset
	sprite.scale = Vector2(_scene_scale, _scene_scale)
	scene_root.add_child(sprite)

	var slash_slot: Node2D = ClassDB.instantiate("SpineSlotNode") as Node2D
	var eye_slot: Node2D = ClassDB.instantiate("SpineSlotNode") as Node2D
	if slash_slot == null or eye_slot == null:
		return {}
	slash_slot.name = "SlashVfxSlot"
	slash_slot.set("slot_name", SLASH_SLOT)
	slash_slot.set("show_behind_parent", true)
	slash_slot.position = Vector2(863.2593, -1558.245)
	slash_slot.set("normal_material", _create_slash_material())
	sprite.add_child(slash_slot)
	eye_slot.name = "EyeSlot"
	eye_slot.set("slot_name", EYE_SLOT)
	eye_slot.set("show_behind_parent", true)
	eye_slot.position = Vector2(349.7109, -659.5685)
	eye_slot.rotation = -0.14384604
	eye_slot.scale = Vector2(1.0095462, 1.0182862)
	eye_slot.skew = 0.0025269985
	sprite.add_child(eye_slot)
	var eye_fire := _create_eye_fire()
	if eye_fire == null:
		return {}
	eye_slot.add_child(eye_fire)
	return {"root": scene_root, "sprite": sprite}


func _connect_observers(context: Dictionary) -> bool:
	var sprite: Node2D = context["sprite"]
	if not sprite.has_signal("animation_started") or not sprite.has_signal("animation_event"):
		_fail("SpineSprite lacks animation_started or animation_event signals.")
		return false
	var start_error := sprite.connect("animation_started", Callable(self, "_on_animation_started"))
	var event_error := sprite.connect("animation_event", Callable(self, "_on_animation_event"))
	if start_error != OK or event_error != OK:
		_fail("Could not connect Spine lifecycle observers (%s / %s)." % [start_error, event_error])
		return false
	return true


func _on_animation_started(_sprite: Object, _state: Object, entry: Object) -> void:
	var animation_name := _track_entry_animation_name(entry)
	_active_event_log.append({
		"animation": animation_name,
		"kind": "animation_started",
		"sequence_clock": _pending_event_clock,
	})
	if _active_context.is_empty() or bool(_active_context.get("actual_consumer", false)):
		return
	if animation_name != "cast":
		var eye_fire: CanvasItem = _active_context["eye_fire"]
		eye_fire.visible = false


func _on_animation_event(_sprite: Object, _state: Object, _entry: Object, spine_event: Object) -> void:
	var event_name := _spine_event_name(spine_event)
	_active_event_log.append({
		"event": event_name,
		"kind": "animation_event",
		"sequence_clock": _pending_event_clock,
	})
	if _active_context.is_empty() or bool(_active_context.get("actual_consumer", false)):
		return
	var eye_fire: CanvasItem = _active_context["eye_fire"]
	match event_name:
		"cast_eyes_start":
			eye_fire.visible = true
		"clear_vfx":
			eye_fire.visible = false
		"attack_slash_start":
			_active_context["sim_slash_kind"] = "attack"
			_active_context["sim_slash_elapsed"] = 0.0
			_set_slash_step(_active_context.get("sim_slash_material"), Vector2(0.0, 0.02))
		"heavy_slash_start":
			_active_context["sim_slash_kind"] = "heavy"
			_active_context["sim_slash_elapsed"] = 0.0
			_set_slash_step(_active_context.get("sim_slash_material"), Vector2(0.0, 0.02))


func _set_segment(context: Dictionary, animation_name: String, loop: bool) -> Variant:
	context["segment_elapsed"] = 0.0
	_pending_event_clock = _sequence_clock
	var state: Object = context["state"]
	var entry: Variant = state.call("set_animation", animation_name, loop, 0)
	context["active_entry"] = entry
	return entry


func _apply_zero(context: Dictionary) -> void:
	_pending_event_clock = _sequence_clock
	var state: Object = context["state"]
	var skeleton: Object = context["skeleton"]
	var sprite: Node2D = context["sprite"]
	state.call("update", 0.0)
	state.call("apply", skeleton)
	sprite.call("update_skeleton", 0.0)


func _advance_to(context: Dictionary, target_elapsed: float) -> void:
	var elapsed := float(context["segment_elapsed"])
	if target_elapsed + FLOAT_EPSILON < elapsed:
		_fail("Harness attempted to seek backwards from %.7f to %.7f." % [elapsed, target_elapsed])
		return
	var state: Object = context["state"]
	var skeleton: Object = context["skeleton"]
	var sprite: Node2D = context["sprite"]
	while elapsed + FLOAT_EPSILON < target_elapsed:
		var delta := minf(STEP_SECONDS, target_elapsed - elapsed)
		_pending_event_clock = _sequence_clock + delta
		state.call("update", delta)
		state.call("apply", skeleton)
		sprite.call("update_skeleton", 0.0)
		if bool(context.get("actual_consumer", false)):
			_step_active_tweens(delta)
		else:
			_advance_simulated_slash(context, delta)
		elapsed += delta
		_sequence_clock += delta
	context["segment_elapsed"] = target_elapsed


func _capture_checkpoint(
	viewport: SubViewport,
	context: Dictionary,
	sequence_name: String,
	checkpoint: String,
	animation_name: String,
	animation_elapsed: float,
	entry: Variant,
	expected_external_eye: bool,
) -> Dictionary:
	await process_frame
	RenderingServer.force_draw(false)
	await RenderingServer.frame_post_draw
	var image: Image = viewport.get_texture().get_image()
	if image == null or image.is_empty():
		_fail("[%s/%s] Vulkan returned an empty image." % [sequence_name, checkpoint])
		return {"checkpoint": checkpoint, "passed": false}
	if image.get_format() != Image.FORMAT_RGBA8:
		image.convert(Image.FORMAT_RGBA8)
	var alpha := _alpha_metrics(image)
	var expected_slots := _expected_slots(animation_name, animation_elapsed)
	var observed_slots := _slot_snapshot(context["skeleton"] as Object)
	var slot_contract := _compare_slot_contract(observed_slots, expected_slots)
	var visible_characters := _visible_character_attachments(observed_slots)
	var one_character := visible_characters.size() == 1
	var eye_fire: CanvasItem = context["eye_fire"]
	var eye_visible := eye_fire.visible
	var eye_contract := eye_visible == expected_external_eye
	var entry_name := _track_entry_animation_name(entry as Object) if entry is Object else ""
	var entry_time := _track_entry_time(entry)
	var entry_contract := entry_name == animation_name and absf(entry_time - animation_elapsed) <= 0.0025
	var relative_path := "frames/%s/%02d-%s.png" % [sequence_name, _sample_serial, _safe_component(checkpoint)]
	var absolute_path := _output_root.path_join(relative_path)
	DirAccess.make_dir_recursive_absolute(absolute_path.get_base_dir())
	var save_error := image.save_png(absolute_path)
	var render_passed := int(alpha["pixel_count"]) > 0 and not bool(alpha["touches_canvas_edge"]) and save_error == OK
	var passed := slot_contract and one_character and eye_contract and entry_contract and render_passed
	if not slot_contract:
		_fail("[%s/%s] six-slot contract failed: expected %s, observed %s." % [sequence_name, checkpoint, JSON.stringify(expected_slots), JSON.stringify(observed_slots)])
	if not one_character:
		_fail("[%s/%s] expected one visible character attachment, observed %s." % [sequence_name, checkpoint, JSON.stringify(visible_characters)])
	if not eye_contract:
		_fail("[%s/%s] external EyeFire visible=%s, expected %s." % [sequence_name, checkpoint, eye_visible, expected_external_eye])
	if not entry_contract:
		_fail("[%s/%s] retained TrackEntry was %s@%.7f, expected %s@%.7f." % [sequence_name, checkpoint, entry_name, entry_time, animation_name, animation_elapsed])
	if not render_passed:
		_fail("[%s/%s] composite was empty, clipped, or could not be saved." % [sequence_name, checkpoint])
	var thumbnail := image.duplicate()
	thumbnail.resize(320, 225, Image.INTERPOLATE_LANCZOS)
	_contact_images.append(thumbnail)
	_contact_validity.append(passed)
	_sample_serial += 1
	return {
		"alpha_bbox": alpha["bbox"],
		"alpha_centroid": alpha["centroid"],
		"animation": animation_name,
		"animation_elapsed": animation_elapsed,
		"checkpoint": checkpoint,
		"expected_external_eye_fire_visible": expected_external_eye,
		"expected_slots": expected_slots,
		"external_eye_fire_modulate_alpha": eye_fire.modulate.a,
		"external_eye_fire_visible": eye_visible,
		"external_eye_fire_visible_in_tree": eye_fire.is_visible_in_tree(),
		"one_character_contract_passed": one_character,
		"passed": passed,
		"path": relative_path,
		"render_contract_passed": render_passed,
		"sha256": _image_sha256(image),
		"six_slot_contract_passed": slot_contract,
		"slots": observed_slots,
		"touches_canvas_edge": alpha["touches_canvas_edge"],
		"track_entry_animation": entry_name,
		"track_entry_contract_passed": entry_contract,
		"track_entry_instance_id": (entry as Object).get_instance_id() if entry is Object else 0,
		"track_entry_time": entry_time,
		"visible_character_attachment_count": visible_characters.size(),
		"visible_character_attachments": visible_characters,
	}


func _expected_slots(animation_name: String, elapsed: float) -> Dictionary:
	var values := {
		BODY_SLOT: BODY_ATTACHMENT,
		ACTION_SLOT: null,
		DEATH_SLOT: null,
		SLASH_SLOT: null,
		SIGIL_SLOT: null,
		EYE_SLOT: null,
	}
	match animation_name:
		"attack":
			if elapsed + FLOAT_EPSILON >= ATTACK_ENTER and elapsed < ATTACK_EXIT - FLOAT_EPSILON:
				values[BODY_SLOT] = null
				values[ACTION_SLOT] = ATTACK_ATTACHMENT
			if elapsed + FLOAT_EPSILON >= ATTACK_ENTER and elapsed < ATTACK_CLEAR - FLOAT_EPSILON:
				values[SLASH_SLOT] = SLASH_ATTACHMENT
		"attack_heavy":
			if elapsed + FLOAT_EPSILON >= HEAVY_ENTER and elapsed < HEAVY_EXIT - FLOAT_EPSILON:
				values[BODY_SLOT] = null
				values[ACTION_SLOT] = HEAVY_ATTACHMENT
			if elapsed + FLOAT_EPSILON >= HEAVY_ENTER and elapsed < HEAVY_CLEAR - FLOAT_EPSILON:
				values[SLASH_SLOT] = SLASH_ATTACHMENT
		"cast":
			if elapsed + FLOAT_EPSILON >= CAST_ENTER and elapsed < CAST_EXIT - FLOAT_EPSILON:
				values[BODY_SLOT] = null
				values[ACTION_SLOT] = CAST_ATTACHMENT
			if elapsed + FLOAT_EPSILON >= CAST_SIGIL_ENTER and elapsed < CAST_CLEAR - FLOAT_EPSILON:
				values[SIGIL_SLOT] = SIGIL_ATTACHMENT
		"die":
			if elapsed + FLOAT_EPSILON >= DEATH_SWAP:
				values[BODY_SLOT] = null
				values[DEATH_SLOT] = DEATH_ATTACHMENT
	return values


func _expected_external_eye(animation_name: String, elapsed: float) -> bool:
	if animation_name != "cast":
		return false
	if elapsed + FLOAT_EPSILON >= CAST_CLEAR:
		return false
	if elapsed + FLOAT_EPSILON >= CAST_ENTER:
		return true
	# The unified final candidate emits clear_vfx at cast t=0. This deliberately
	# prevents cast -> cast from carrying the previous external EyeFire through
	# the new cast's anticipation/mix window.
	return false


func _slot_snapshot(skeleton: Object) -> Dictionary:
	var result := {}
	for slot_name: String in SIX_SLOTS:
		var slot_value: Variant = skeleton.call("find_slot", slot_name)
		if slot_value == null or not slot_value is Object:
			result[slot_name] = {"attachment": "<missing>", "color": [], "color_alpha": 0.0}
			continue
		var slot := slot_value as Object
		var attachment_name: Variant = null
		if slot.has_method("get_attachment"):
			var attachment: Variant = slot.call("get_attachment")
			if attachment != null and attachment is Object and (attachment as Object).has_method("get_attachment_name"):
				attachment_name = str((attachment as Object).call("get_attachment_name"))
		var color := Color.WHITE
		if slot.has_method("get_color"):
			color = slot.call("get_color") as Color
		result[slot_name] = {
			"attachment": attachment_name,
			"color": [color.r, color.g, color.b, color.a],
			"color_alpha": color.a,
		}
	return result


func _compare_slot_contract(observed: Dictionary, expected: Dictionary) -> bool:
	for slot_name: String in SIX_SLOTS:
		if not observed.has(slot_name):
			return false
		if observed[slot_name].get("attachment") != expected.get(slot_name):
			return false
	return true


func _visible_character_attachments(slots: Dictionary) -> Array:
	var result := []
	for slot_name: String in CHARACTER_SLOTS:
		var slot: Dictionary = slots.get(slot_name, {})
		if slot.get("attachment") != null and float(slot.get("color_alpha", 0.0)) > FLOAT_EPSILON:
			result.append({"attachment": slot["attachment"], "slot": slot_name})
	return result


func _entry_report(role: String, entry: Variant, actual_mix: float, expected_mix: float) -> Dictionary:
	var valid := entry != null and entry is Object
	return {
		"animation": _track_entry_animation_name(entry as Object) if valid else "",
		"entry_instance_id": (entry as Object).get_instance_id() if valid else 0,
		"entry_valid": valid,
		"expected_mix_duration": expected_mix,
		"mix_duration": actual_mix,
		"mix_passed": valid and (expected_mix < 0.0 or absf(actual_mix - expected_mix) <= FLOAT_EPSILON),
		"role": role,
	}


func _track_entry_animation_name(entry: Object) -> String:
	if entry == null or not entry.has_method("get_animation"):
		return ""
	var animation: Variant = entry.call("get_animation")
	if animation == null or not animation is Object or not (animation as Object).has_method("get_name"):
		return ""
	return str((animation as Object).call("get_name"))


func _track_entry_time(entry: Variant) -> float:
	if entry == null or not entry is Object or not (entry as Object).has_method("get_track_time"):
		return -1.0
	return float((entry as Object).call("get_track_time"))


func _track_entry_mix_duration(entry: Variant) -> float:
	if entry == null or not entry is Object:
		return -1.0
	var object := entry as Object
	for method_name: String in ["get_mix_duration", "get_mix_duration_seconds"]:
		if object.has_method(method_name):
			return float(object.call(method_name))
	return -1.0


func _spine_event_name(spine_event: Object) -> String:
	if spine_event == null or not spine_event.has_method("get_data"):
		return "<unavailable>"
	var data: Variant = spine_event.call("get_data")
	if data == null or not data is Object or not (data as Object).has_method("get_event_name"):
		return "<unavailable>"
	return str((data as Object).call("get_event_name"))


func _expected_idle_mix(animation_name: String) -> float:
	match animation_name:
		"attack": return 0.10
		"attack_heavy": return 0.02
		"hurt": return 0.03
		_: return 0.05


func _expected_return_idle_mix(from_animation: String) -> float:
	return 0.10 if from_animation == "hurt" else 0.05


func _step_active_tweens(delta: float) -> void:
	if not has_method("get_processed_tweens"):
		return
	for tween_value: Variant in get_processed_tweens():
		if tween_value is Tween:
			(tween_value as Tween).custom_step(delta)


func _advance_simulated_slash(context: Dictionary, delta: float) -> void:
	var kind := str(context.get("sim_slash_kind", ""))
	if kind.is_empty():
		return
	var elapsed := float(context.get("sim_slash_elapsed", 0.0)) + delta
	context["sim_slash_elapsed"] = elapsed
	var progress := 0.0
	if kind == "attack":
		progress = clampf((elapsed - 0.150000006) / 0.200000003, 0.0, 1.0)
		progress *= progress
	else:
		progress = clampf(elapsed / 0.349999994, 0.0, 1.0)
		progress = progress * progress * progress
	_set_slash_step(context.get("sim_slash_material"), Vector2(progress, lerpf(0.02, 1.02, progress)))
	if progress >= 1.0:
		context["sim_slash_kind"] = ""


func _slash_material(slot_node: Node) -> ShaderMaterial:
	if slot_node == null:
		return null
	var material: Variant = slot_node.get("normal_material")
	return material as ShaderMaterial if material is ShaderMaterial else null


func _reset_slash_material(slot_node: Node) -> void:
	_set_slash_step(_slash_material(slot_node), Vector2(0.0, 0.02))


func _set_slash_step(material_value: Variant, value: Vector2) -> void:
	if material_value is ShaderMaterial:
		(material_value as ShaderMaterial).set_shader_parameter("step", value)


func _create_slash_material() -> ShaderMaterial:
	var shader := Shader.new()
	shader.code = "shader_type canvas_item;\nrender_mode blend_mix, unshaded;\nuniform vec4 ColorParameter : source_color = vec4(1.0);\nuniform vec2 step = vec2(0.0, 0.02);\nuniform float master_step : hint_range(0.0, 1.0) = 1.0;\nuniform float opacity : hint_range(0.0, 1.0) = 1.0;\nvoid fragment(){ vec4 base=texture(TEXTURE,UV)*ColorParameter*COLOR; base.a*=1.0-clamp(step.x,0.0,1.0); base.a*=clamp(master_step,0.0,1.0)*clamp(opacity,0.0,1.0); COLOR=base; }"
	var material := ShaderMaterial.new()
	material.shader = shader
	material.set_shader_parameter("ColorParameter", Color.WHITE)
	material.set_shader_parameter("step", Vector2(0.0, 0.02))
	material.set_shader_parameter("master_step", 1.0)
	material.set_shader_parameter("opacity", 1.0)
	return material


func _create_eye_fire() -> TextureRect:
	var shader: Shader = ResourceLoader.load(EYE_FIRE_SHADER) as Shader
	var texture: Texture2D = ResourceLoader.load(EYE_FIRE_TEXTURE) as Texture2D
	if shader == null or texture == null:
		_fail("Could not load production EyeFire shader or texture for fallback topology.")
		return null
	var material := ShaderMaterial.new()
	material.shader = shader
	material.set_shader_parameter("OuterColor", Color(0.46, 0.1, 0.96, 1))
	material.set_shader_parameter("InnerColorStep", Vector2(0.24, 0.49))
	material.set_shader_parameter("Noise2Strength", 1.085)
	material.set_shader_parameter("Noise2Scaling", Vector2.ONE)
	material.set_shader_parameter("Noise2Panning", Vector2(0.4, 0.8))
	material.set_shader_parameter("Noise2Texture", ResourceLoader.load(FIRE_TILE_NOISE))
	material.set_shader_parameter("Noise1Strength", 0.435)
	material.set_shader_parameter("Noise1Scaling", Vector2(0.8, 0.8))
	material.set_shader_parameter("Noise1Panning", Vector2(0.2, 1.0))
	material.set_shader_parameter("Noise1Texture", ResourceLoader.load(FIRE_TRIANGLE_NOISE))
	material.set_shader_parameter("InvertNoiseMask", false)
	material.set_shader_parameter("NoiseMaskScale", Vector2(1.0, 1.305))
	material.set_shader_parameter("NoiseMaskOffset", Vector2(0.0, -0.77))
	material.set_shader_parameter("NoiseMask", ResourceLoader.load(FIRE_GRADIENT))
	material.set_shader_parameter("Distortion2Scale", Vector2.ONE)
	material.set_shader_parameter("Distortion2Panning", Vector2(0.4, 0.4))
	material.set_shader_parameter("Distortion2Texture", ResourceLoader.load(FIRE_TILE_NOISE))
	material.set_shader_parameter("Distortion2Strength", 0.17)
	material.set_shader_parameter("Distortion1Scale", Vector2.ONE)
	material.set_shader_parameter("Distortion1Panning", Vector2(0.0, 1.5))
	material.set_shader_parameter("Distortion1Texture", ResourceLoader.load(FIRE_ZIGZAG))
	material.set_shader_parameter("Distortion1Strength", -0.075)
	material.set_shader_parameter("DistortionMaskScale", Vector2(1.0, 2.0))
	material.set_shader_parameter("DistortionMaskOffset", Vector2(0.0, -0.72))
	material.set_shader_parameter("DistortionMask", ResourceLoader.load(FIRE_BOTTOM_MASK))
	material.set_shader_parameter("InnerColor", Color(0.32, 0.94, 1, 1))
	material.set_shader_parameter("OuterStep", Vector2(0.07, 0.17))
	var eye_fire := TextureRect.new()
	eye_fire.name = "EyeFire"
	eye_fire.material = material
	eye_fire.offset_left = -205.07704
	eye_fire.offset_top = -450.1532
	eye_fire.offset_right = 294.92322
	eye_fire.offset_bottom = 49.846893
	eye_fire.scale = Vector2(0.22, 0.28)
	eye_fire.texture = texture
	eye_fire.visible = false
	return eye_fire


func _dispose_context(context: Dictionary) -> void:
	var scene_root: Node = context.get("root") as Node
	if scene_root != null:
		scene_root.queue_free()
	await process_frame


func _validate_coverage(sequence_values: Array) -> Dictionary:
	var observed := {}
	for value: Variant in sequence_values:
		var sequence: Dictionary = value
		observed[str(sequence.get("name", ""))] = true
	var required := []
	for source_name: String in ["attack", "heavy", "cast", "hurt"]:
		for target_name: String in ["attack", "heavy", "cast", "hurt", "die", "idle"]:
			required.append("%s_to_%s" % [source_name, target_name])
	required.append("die_to_idle")
	var missing := []
	for name: String in required:
		if not observed.has(name):
			missing.append(name)
	return {"missing": missing, "passed": missing.is_empty(), "required": required}


func _alpha_metrics(image: Image) -> Dictionary:
	var source_width := image.get_width()
	var source_height := image.get_height()
	var exact_bbox := image.get_used_rect()
	var metric_image := image.duplicate()
	var metric_width := source_width
	var metric_height := source_height
	var longest := maxi(metric_width, metric_height)
	if longest > ALPHA_METRIC_MAX_DIMENSION:
		var metric_scale := float(ALPHA_METRIC_MAX_DIMENSION) / float(longest)
		metric_width = maxi(1, int(round(float(metric_width) * metric_scale)))
		metric_height = maxi(1, int(round(float(metric_height) * metric_scale)))
		metric_image.resize(metric_width, metric_height, Image.INTERPOLATE_BILINEAR)
	metric_image.convert(Image.FORMAT_RGBA8)
	var data: PackedByteArray = metric_image.get_data()
	var pixel_count := 0
	var alpha_weight := 0.0
	var weighted_x := 0.0
	var weighted_y := 0.0
	for pixel_index in metric_width * metric_height:
		var alpha := int(data[pixel_index * 4 + 3])
		if alpha <= ALPHA_THRESHOLD:
			continue
		var x := pixel_index % metric_width
		var y := pixel_index / metric_width
		var weight := float(alpha) / 255.0
		pixel_count += 1
		alpha_weight += weight
		weighted_x += float(x) * weight
		weighted_y += float(y) * weight
	var bbox := [exact_bbox.position.x, exact_bbox.position.y, exact_bbox.size.x, exact_bbox.size.y]
	var centroid := [null, null]
	if pixel_count > 0:
		var source_per_metric_x := float(source_width) / float(metric_width)
		var source_per_metric_y := float(source_height) / float(metric_height)
		centroid = [
			(weighted_x / maxf(alpha_weight, 0.000001) + 0.5) * source_per_metric_x - 0.5,
			(weighted_y / maxf(alpha_weight, 0.000001) + 0.5) * source_per_metric_y - 0.5,
		]
	var touches := exact_bbox.has_area() and (
		exact_bbox.position.x <= 0 or exact_bbox.position.y <= 0
		or exact_bbox.end.x >= source_width or exact_bbox.end.y >= source_height
	)
	return {"bbox": bbox, "centroid": centroid, "pixel_count": pixel_count, "touches_canvas_edge": touches}


func _write_contact_sheet(images: Array[Image], validity: Array[bool], path: String, columns: int) -> bool:
	if images.is_empty() or columns <= 0 or images.size() != validity.size():
		return false
	var actual_columns := mini(columns, images.size())
	var rows := int(ceil(float(images.size()) / float(actual_columns)))
	var sheet_size := Vector2i(
		CONTACT_PADDING * 2 + actual_columns * CONTACT_TILE.x + (actual_columns - 1) * CONTACT_GAP,
		CONTACT_PADDING * 2 + rows * CONTACT_TILE.y + (rows - 1) * CONTACT_GAP,
	)
	var sheet := Image.create(sheet_size.x, sheet_size.y, false, Image.FORMAT_RGBA8)
	sheet.fill(Color("11131c"))
	for index in images.size():
		var column := index % actual_columns
		var row := index / actual_columns
		var tile_origin := Vector2i(
			CONTACT_PADDING + column * (CONTACT_TILE.x + CONTACT_GAP),
			CONTACT_PADDING + row * (CONTACT_TILE.y + CONTACT_GAP),
		)
		sheet.fill_rect(Rect2i(tile_origin, CONTACT_TILE), Color("35d0d0") if validity[index] else Color("ef476f"))
		var interior := Rect2i(tile_origin + Vector2i(3, 3), CONTACT_TILE - Vector2i(6, 6))
		sheet.fill_rect(interior, Color("202432"))
		var source: Image = images[index]
		var scale := minf(float(interior.size.x) / float(source.get_width()), float(interior.size.y) / float(source.get_height()))
		var target_size := Vector2i(maxi(1, int(round(source.get_width() * scale))), maxi(1, int(round(source.get_height() * scale))))
		var thumbnail := source.duplicate()
		thumbnail.resize(target_size.x, target_size.y, Image.INTERPOLATE_LANCZOS)
		var destination := interior.position + (interior.size - target_size) / 2
		sheet.blend_rect(thumbnail, Rect2i(Vector2i.ZERO, target_size), destination)
	DirAccess.make_dir_recursive_absolute(path.get_base_dir())
	return sheet.save_png(path) == OK


func _safe_output_root(requested: String) -> String:
	var repo_dir := _repository_root()
	var work_dir := repo_dir.path_join(".work").simplify_path()
	var output := requested
	if output.is_empty():
		output = repo_dir.path_join(DEFAULT_OUTPUT)
	elif not output.is_absolute_path():
		output = repo_dir.path_join(output)
	output = output.simplify_path()
	var required_prefix := work_dir.replace("\\", "/").trim_suffix("/") + "/"
	if not output.replace("\\", "/").begins_with(required_prefix):
		_fail("Output must stay below '%s', got '%s'." % [work_dir, output])
		return ""
	return output


func _repository_root() -> String:
	var current := ProjectSettings.globalize_path("res://").replace("\\", "/").trim_suffix("/").simplify_path()
	if current.get_file().to_lower() == "vivhite":
		return current.get_base_dir()
	for _depth in 10:
		if DirAccess.dir_exists_absolute(current.path_join("Vivhite")) and DirAccess.dir_exists_absolute(current.path_join("tools")):
			return current
		var parent := current.get_base_dir()
		if parent == current:
			break
		current = parent
	return ProjectSettings.globalize_path("res://").path_join("..").simplify_path()


func _directory_is_empty(path: String) -> bool:
	var directory := DirAccess.open(path)
	if directory == null:
		return true
	directory.list_dir_begin()
	var name := directory.get_next()
	directory.list_dir_end()
	return name.is_empty()


func _write_reports(report: Dictionary) -> void:
	_write_json(_output_root.path_join("transition_summary.json"), report)
	_write_json(_output_root.path_join("summary.json"), report)


func _write_json(path: String, value: Variant) -> bool:
	DirAccess.make_dir_recursive_absolute(path.get_base_dir())
	var file := FileAccess.open(path, FileAccess.WRITE)
	if file == null:
		_fail("Could not open JSON output '%s'." % path)
		return false
	file.store_string(JSON.stringify(value, "  ", true) + "\n")
	return true


func _relative_to_output(path: String) -> String:
	var root_path := _output_root.replace("\\", "/").trim_suffix("/")
	var normalized := path.replace("\\", "/")
	return normalized.trim_prefix(root_path + "/") if normalized.begins_with(root_path + "/") else normalized


func _safe_component(value: String) -> String:
	var result := value.to_lower()
	for character: String in ["/", "\\", ":", "*", "?", "\"", "<", ">", "|", " ", "="]:
		result = result.replace(character, "-")
	return result


func _image_sha256(image: Image) -> String:
	var context := HashingContext.new()
	if context.start(HashingContext.HASH_SHA256) != OK:
		return ""
	if context.update(image.get_data()) != OK:
		return ""
	return context.finish().hex_encode()


func _decompiled_consumer_sha256() -> String:
	var path := _repository_root().path_join(".work/sts2-decompiled-v0.111.0/MegaCrit/sts2/Core/Nodes/Vfx/NIroncladVfx.cs")
	return FileAccess.get_sha256(path) if FileAccess.file_exists(path) else ""


func _fail(message: String) -> void:
	_errors.append(message)
	push_error("[hybrid-v3-final-transitions] %s" % message)
