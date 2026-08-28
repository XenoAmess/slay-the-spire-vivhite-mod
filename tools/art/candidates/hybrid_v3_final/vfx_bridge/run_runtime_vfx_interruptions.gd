extends SceneTree

## Acceptance-only interruption matrix for the real v0.111.0 NIroncladVfx.
## The PowerShell wrapper stages this script, the C# bridge, the final candidate
## and the Spine extension under .work; nothing here enters the runtime Mod.

const DATA_PATH := "res://tools/candidates/hybrid_v3_final/vivhite_combat_skeleton_data.tres"
const JSON_PATH := "res://tools/candidates/hybrid_v3_final/vivhite_combat.spjson"
const BRIDGE_PATH := "res://RuntimeVfxHarness.cs"
const MANUAL_UPDATE_MODE := 2
const CANVAS := Vector2i(1280, 900)
const ORIGIN := Vector2(325, 681)
const SCENE_SCALE := 0.28
const SETTLE_TIME := 0.06
const GAME_BG := Color(0.075, 0.125, 0.105, 1.0)
const CHARACTER_SLOTS: Array[String] = [
	"vivhite_body",
	"vivhite_action_pose",
	"vivhite_death_body",
]
const OBSERVED_SLOTS: Array[String] = [
	"vivhite_body",
	"vivhite_action_pose",
	"vivhite_death_body",
	"slash_mesh",
	"vivhite_magic_sigil",
	"eye_attach_slot",
]
const SOURCE_EVENT_TIME := {
	"attack": 0.08,
	"attack_heavy": 0.12,
	"cast": 0.25,
}
const SOURCE_EVENT_NAME := {
	"attack": "attack_slash_start",
	"attack_heavy": "heavy_slash_start",
	"cast": "cast_eyes_start",
}
const SCENARIOS := [
	{"name": "cast_030_to_cast_000", "source": "cast", "source_time": 0.30, "destination": "cast"},
	{"name": "cast_030_to_hurt_000", "source": "cast", "source_time": 0.30, "destination": "hurt"},
	{"name": "cast_030_to_die_000", "source": "cast", "source_time": 0.30, "destination": "die"},
	{"name": "cast_030_to_idle_000", "source": "cast", "source_time": 0.30, "destination": "idle_loop"},
	{"name": "attack_010_to_hurt_000", "source": "attack", "source_time": 0.10, "destination": "hurt"},
	{"name": "attack_010_to_die_000", "source": "attack", "source_time": 0.10, "destination": "die"},
	{"name": "heavy_014_to_hurt_000", "source": "attack_heavy", "source_time": 0.14, "destination": "hurt"},
	{"name": "heavy_014_to_die_000", "source": "attack_heavy", "source_time": 0.14, "destination": "die"},
]

var _output_root := ""
var _errors: Array[String] = []


func _initialize() -> void:
	if DisplayServer.get_name() != "headless":
		DisplayServer.window_set_flag(DisplayServer.WINDOW_FLAG_NO_FOCUS, true)
		DisplayServer.window_set_position(Vector2i(-32000, -32000))
	call_deferred("_run")


func _run() -> void:
	var options := _parse_options()
	_output_root = str(options.get("output", ""))
	if _output_root.is_empty():
		_fail("--output is required")
	if DisplayServer.get_name() == "headless":
		_fail("Windows display is required; headless cannot provide Vulkan visual evidence")
	if RenderingServer.get_current_rendering_driver_name().to_lower() != "vulkan":
		_fail("Vulkan is required, got %s" % RenderingServer.get_current_rendering_driver_name())
	if not ProjectSettings.load_resource_pack(str(options.get("pck", "")), false):
		_fail("base PCK mount failed")
	var data: Resource = load(DATA_PATH)
	var bridge_script: Script = load(BRIDGE_PATH)
	if data == null or not data.is_class("SpineSkeletonDataResource"):
		_fail("final candidate SpineSkeletonDataResource failed to load")
	if bridge_script == null or not bridge_script.can_instantiate():
		_fail("compiled RuntimeVfxHarness is unavailable")
	if not _errors.is_empty():
		_write_summary({"success": false, "errors": _errors})
		quit(2)
		return

	DirAccess.make_dir_recursive_absolute(_output_root)
	var report := {
		"schema_version": 1,
		"success": false,
		"consumer_executed": false,
		"matrix_passed": false,
		"display_server": DisplayServer.get_name(),
		"rendering_driver": RenderingServer.get_current_rendering_driver_name(),
		"candidate": DATA_PATH,
		"candidate_skeleton_sha256": FileAccess.get_sha256(DATA_PATH),
		"candidate_json_sha256": FileAccess.get_sha256(JSON_PATH),
		"base_pck_sha256": FileAccess.get_sha256(str(options.get("pck", ""))),
		"input_sts2_dll_sha256": FileAccess.get_sha256(str(options.get("sts2-dll", ""))),
		"consumer": {},
		"contract": {
			"destination_t0": "EyeFire hidden and slash/sigil attachments absent",
			"settle_time": SETTLE_TIME,
			"known_consumer_boundary": "non-cast animation_started hides EyeFire only; clear_vfx hides EyeFire only",
		},
		"scenarios": [],
		"errors": [],
	}
	var consumer_metadata := {}
	for scenario_value: Variant in SCENARIOS:
		var scenario: Dictionary = scenario_value
		var result: Dictionary = await _run_scenario(data, bridge_script, scenario)
		(report.scenarios as Array).append(result)
		if consumer_metadata.is_empty() and result.has("consumer"):
			consumer_metadata = (result.consumer as Dictionary).duplicate(true)
	report.consumer = consumer_metadata
	report.consumer_executed = (
		str(consumer_metadata.get("type", "")) == "MegaCrit.Sts2.Core.Nodes.Vfx.NIroncladVfx"
		and not str(consumer_metadata.get("module_version_id", "")).is_empty()
		and _all_consumer_signals_observed(report.scenarios as Array)
	)
	report.matrix_passed = _all_scenarios_passed(report.scenarios as Array)
	report.errors = _errors.duplicate()
	report.success = (
		bool(report.consumer_executed)
		and bool(report.matrix_passed)
		and _errors.is_empty()
	)
	_write_summary(report)
	Engine.time_scale = 1.0
	if bool(report.success):
		print("[runtime-vfx-bridge] real NIroncladVfx interruption matrix passed: ", _output_root)
		quit(0)
		return
	push_error("[runtime-vfx-bridge] interruption isolation failed; see summary.json")
	quit(1)


func _run_scenario(data: Resource, bridge_script: Script, scenario: Dictionary) -> Dictionary:
	Engine.time_scale = 1.0
	var viewport := SubViewport.new()
	viewport.name = "%sViewport" % str(scenario.name)
	viewport.size = CANVAS
	viewport.transparent_bg = true
	viewport.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	viewport.render_target_clear_mode = SubViewport.CLEAR_MODE_ALWAYS
	root.add_child(viewport)
	var stage := Node2D.new()
	viewport.add_child(stage)
	var runtime: Dictionary = await _make_runtime(stage, data, bridge_script)
	if runtime.is_empty():
		viewport.queue_free()
		return {"name": str(scenario.name), "passed": false, "errors": ["runtime creation failed"]}
	Engine.time_scale = 0.0

	var state: Object = runtime.state
	var skeleton: Object = runtime.skeleton
	var visuals: Node2D = runtime.visuals
	var harness: RefCounted = runtime.harness
	harness.call("SetProbeTime", -0.5)
	state.call("set_animation", "idle_loop", true, 0)
	state.call("update", 0.5)
	state.call("apply", skeleton)
	visuals.call("update_skeleton", 0.0)
	harness.call("ClearSignalLog")

	var source := str(scenario.source)
	var source_time := float(scenario.source_time)
	_set_animation(runtime, source, false, 0.0)
	var event_time := float(SOURCE_EVENT_TIME[source])
	_advance(runtime, event_time, event_time)
	if source_time > event_time:
		_advance(runtime, source_time - event_time, source_time)
	var before: Dictionary = await _snapshot(runtime, viewport, str(scenario.name), "source-active")

	var destination := str(scenario.destination)
	_set_animation(runtime, destination, destination == "idle_loop", source_time)
	var after_zero: Dictionary = await _snapshot(runtime, viewport, str(scenario.name), "destination-t0")
	_advance(runtime, SETTLE_TIME, source_time + SETTLE_TIME)
	var after_settle: Dictionary = await _snapshot(runtime, viewport, str(scenario.name), "destination-settled")
	var destination_lifecycle := {}
	if destination == "cast":
		_advance(runtime, 0.25 - SETTLE_TIME, source_time + 0.25)
		var after_reopen: Dictionary = await _snapshot(
			runtime, viewport, str(scenario.name), "destination-cast-eyes-start"
		)
		_advance(runtime, 1.222000026 - 0.25, source_time + 1.222000026)
		var after_clear: Dictionary = await _snapshot(
			runtime, viewport, str(scenario.name), "destination-cast-clear-vfx"
		)
		destination_lifecycle = {
			"after_cast_eyes_start_025": after_reopen,
			"after_clear_vfx_1222000026": after_clear,
			"reopened_at_025": bool(after_reopen.eye_fire_visible),
			"cleared_at_1222000026": not bool(after_clear.eye_fire_visible),
		}
	var signals: Array = (harness.call("GetSignalLog") as Array).duplicate(true)
	var source_active := _source_is_active(source, before)
	var signal_contract := (
		_has_signal(signals, "animation_started", source)
		and _has_signal(signals, "animation_event", str(SOURCE_EVENT_NAME[source]))
		and _has_signal(signals, "animation_started", destination)
	)
	var after_zero_isolated := not bool(after_zero.visible_vfx_active)
	var after_settle_isolated := not bool(after_settle.visible_vfx_active)
	var destination_lifecycle_passed := (
		destination != "cast"
		or (
			bool(destination_lifecycle.get("reopened_at_025", false))
			and bool(destination_lifecycle.get("cleared_at_1222000026", false))
		)
	)
	var passed := (
		source_active
		and signal_contract
		and after_zero_isolated
		and after_settle_isolated
		and destination_lifecycle_passed
	)
	var result := {
		"name": str(scenario.name),
		"source": source,
		"source_time": source_time,
		"destination": destination,
		"destination_time": 0.0,
		"source_active_contract_passed": source_active,
		"signal_contract_passed": signal_contract,
		"destination_t0_isolated": after_zero_isolated,
		"destination_settled_isolated": after_settle_isolated,
		"destination_lifecycle_passed": destination_lifecycle_passed,
		"passed": passed,
		"consumer": _consumer_metadata(harness),
		"before": before,
		"after_t0": after_zero,
		"after_settle": after_settle,
		"destination_lifecycle": destination_lifecycle,
		"signals": signals,
	}
	Engine.time_scale = 1.0
	viewport.queue_free()
	await process_frame
	return result


func _make_runtime(stage: Node2D, data: Resource, bridge_script: Script) -> Dictionary:
	var visuals: Node2D = ClassDB.instantiate("SpineSprite") as Node2D
	if visuals == null:
		_fail("SpineSprite class unavailable")
		return {}
	visuals.name = "Visuals"
	visuals.position = ORIGIN
	visuals.scale = Vector2(SCENE_SCALE, SCENE_SCALE)
	visuals.set("skeleton_data_res", data)
	visuals.call("set_update_mode", MANUAL_UPDATE_MODE)

	var slash: Node2D = ClassDB.instantiate("SpineSlotNode") as Node2D
	slash.name = "SlashVfxSlot"
	slash.set("normal_material", _make_slash_material())
	slash.set("slot_name", "slash_mesh")
	slash.set("show_behind_parent", true)
	slash.position = Vector2(863.2593, -1558.245)
	visuals.add_child(slash)

	var eye_slot: Node2D = ClassDB.instantiate("SpineSlotNode") as Node2D
	eye_slot.name = "EyeSlot"
	eye_slot.set("slot_name", "eye_attach_slot")
	eye_slot.set("show_behind_parent", true)
	eye_slot.position = Vector2(349.7109, -659.5685)
	eye_slot.rotation = -0.14384604
	eye_slot.scale = Vector2(1.0095462, 1.0182862)
	eye_slot.skew = 0.0025269985
	visuals.add_child(eye_slot)
	var eye_fire := TextureRect.new()
	eye_fire.name = "EyeFire"
	eye_fire.material = _make_eye_material()
	eye_fire.offset_left = -205.07704
	eye_fire.offset_top = -450.1532
	eye_fire.offset_right = 294.92322
	eye_fire.offset_bottom = 49.846893
	eye_fire.scale = Vector2(0.22, 0.28)
	eye_fire.texture = load("res://images/vfx/characters/ironclad_eye_fire_base.png")
	eye_slot.add_child(eye_fire)

	var harness: RefCounted = bridge_script.new()
	harness.call("AttachSignalProbe", visuals)
	var runtime_vfx := harness.call("CreateRuntimeVfx") as Node
	if runtime_vfx == null:
		_fail("RuntimeVfxHarness did not create NIroncladVfx")
		return {}
	runtime_vfx.name = "NIroncladVfx"
	visuals.add_child(runtime_vfx)
	stage.add_child(visuals)
	await process_frame
	await process_frame
	var state: Object = visuals.call("get_animation_state")
	var skeleton: Object = visuals.call("get_skeleton")
	if state == null or skeleton == null:
		_fail("Spine animation state/skeleton unavailable")
		return {}
	return {
		"visuals": visuals,
		"state": state,
		"skeleton": skeleton,
		"slash_material": slash.get("normal_material"),
		"eye_fire": eye_fire,
		"harness": harness,
		"runtime_vfx": runtime_vfx,
	}


func _set_animation(runtime: Dictionary, name: String, loop: bool, logical_time: float) -> void:
	(runtime.harness as RefCounted).call("SetProbeTime", logical_time)
	(runtime.state as Object).call("set_animation", name, loop, 0)
	(runtime.state as Object).call("update", 0.0)
	(runtime.state as Object).call("apply", runtime.skeleton)
	(runtime.visuals as Node2D).call("update_skeleton", 0.0)


func _advance(runtime: Dictionary, delta: float, logical_time: float) -> void:
	(runtime.harness as RefCounted).call("CustomStepRuntimeVfx", runtime.runtime_vfx, delta)
	(runtime.harness as RefCounted).call("SetProbeTime", logical_time)
	(runtime.state as Object).call("update", delta)
	(runtime.state as Object).call("apply", runtime.skeleton)
	(runtime.visuals as Node2D).call("update_skeleton", 0.0)


func _snapshot(runtime: Dictionary, viewport: SubViewport, scenario_name: String, phase: String) -> Dictionary:
	await process_frame
	RenderingServer.force_draw(false)
	await RenderingServer.frame_post_draw
	var image: Image = viewport.get_texture().get_image()
	if image.get_format() != Image.FORMAT_RGBA8:
		image.convert(Image.FORMAT_RGBA8)
	var relative := "frames/%s/%s.png" % [scenario_name, phase]
	var raw_path := _output_root.path_join(relative)
	DirAccess.make_dir_recursive_absolute(raw_path.get_base_dir())
	if image.save_png(raw_path) != OK:
		_fail("could not save %s" % raw_path)
	var background := Image.create(CANVAS.x, CANVAS.y, false, Image.FORMAT_RGBA8)
	background.fill(GAME_BG)
	background.blend_rect(image, Rect2i(Vector2i.ZERO, CANVAS), Vector2i.ZERO)
	var game_bg_path := raw_path.trim_suffix(".png") + "-game-bg.png"
	if background.save_png(game_bg_path) != OK:
		_fail("could not save %s" % game_bg_path)
	var material: ShaderMaterial = runtime.slash_material
	var step: Vector2 = material.get_shader_parameter("step")
	var attachments := _attachments(runtime.skeleton)
	var eye_visible := bool((runtime.eye_fire as TextureRect).visible)
	var slash_visible := attachments.slash_mesh != null and step.x < 0.999
	var sigil_visible := attachments.vivhite_magic_sigil != null
	return {
		"eye_fire_visible": eye_visible,
		"slot_attachments": attachments,
		"slash_step": [step.x, step.y],
		"runtime_tween": (runtime.harness as RefCounted).call(
			"GetRuntimeTweenSnapshot", runtime.runtime_vfx
		),
		"visible_vfx_active": eye_visible or slash_visible or sigil_visible,
		"visible_vfx_reasons": {
			"external_eye_fire": eye_visible,
			"slash_attachment_and_shader": slash_visible,
			"sigil_attachment": sigil_visible,
		},
		"render": {
			"raw_path": relative,
			"game_bg_path": relative.trim_suffix(".png") + "-game-bg.png",
			"alpha_bbox": _rect_array(image.get_used_rect()),
			"non_empty": image.get_used_rect().has_area(),
		},
	}


func _attachments(skeleton: Object) -> Dictionary:
	var result := {}
	for slot_name: String in OBSERVED_SLOTS:
		var slot: Object = skeleton.call("find_slot", slot_name)
		var attachment: Variant = slot.call("get_attachment") if slot != null else null
		result[slot_name] = (
			null
			if attachment == null
			else str((attachment as Object).call("get_attachment_name"))
		)
	return result


func _source_is_active(source: String, snapshot: Dictionary) -> bool:
	var attachments: Dictionary = snapshot.slot_attachments
	match source:
		"cast":
			return bool(snapshot.eye_fire_visible) and attachments.vivhite_magic_sigil != null
		"attack", "attack_heavy":
			return (
				attachments.slash_mesh != null
				and bool((snapshot.runtime_tween as Dictionary).get("exists", false))
			)
	return false


func _consumer_metadata(harness: RefCounted) -> Dictionary:
	return {
		"type": str(harness.call("GetConsumerTypeName")),
		"assembly_identity": str(harness.call("GetConsumerAssemblyIdentity")),
		"assembly_location": str(harness.call("GetConsumerAssemblyPath")),
		"assembly_location_sha256": str(harness.call("GetConsumerAssemblySha256")),
		"module_version_id": str(harness.call("GetConsumerModuleVersionId")),
	}


func _all_consumer_signals_observed(scenarios: Array) -> bool:
	if scenarios.size() != SCENARIOS.size():
		return false
	for value: Variant in scenarios:
		if not bool((value as Dictionary).get("signal_contract_passed", false)):
			return false
	return true


func _all_scenarios_passed(scenarios: Array) -> bool:
	if scenarios.size() != SCENARIOS.size():
		return false
	for value: Variant in scenarios:
		if not bool((value as Dictionary).get("passed", false)):
			return false
	return true


func _has_signal(signals: Array, kind: String, name: String) -> bool:
	for value: Variant in signals:
		var item: Dictionary = value
		if str(item.get("kind", "")) == kind and str(item.get("name", "")) == name:
			return true
	return false


func _make_slash_material() -> ShaderMaterial:
	var shader := Shader.new()
	shader.code = """shader_type canvas_item;
render_mode blend_mix, unshaded;
uniform vec4 ColorParameter : source_color = vec4(1.0);
uniform vec2 step = vec2(0.0, 0.02);
uniform float master_step : hint_range(0.0, 1.0) = 1.0;
uniform float opacity : hint_range(0.0, 1.0) = 1.0;
void fragment() {
	vec4 base = texture(TEXTURE, UV) * ColorParameter * COLOR;
	float runtime_fade = 1.0 - clamp(step.x, 0.0, 1.0);
	base.a *= runtime_fade * clamp(master_step, 0.0, 1.0) * clamp(opacity, 0.0, 1.0);
	COLOR = base;
}
"""
	var material := ShaderMaterial.new()
	material.shader = shader
	material.set_shader_parameter("ColorParameter", Color.WHITE)
	material.set_shader_parameter("step", Vector2(0.0, 0.02))
	material.set_shader_parameter("master_step", 1.0)
	material.set_shader_parameter("opacity", 1.0)
	return material


func _make_eye_material() -> ShaderMaterial:
	var material := ShaderMaterial.new()
	material.shader = load("res://shaders/vfx/vfx_stepped_shader_fire_flat.tres")
	material.set_shader_parameter("OuterColor", Color(0.46, 0.1, 0.96, 1))
	material.set_shader_parameter("InnerColorStep", Vector2(0.24, 0.49))
	material.set_shader_parameter("Noise2Strength", 1.085)
	material.set_shader_parameter("Noise2Scaling", Vector2(1, 1))
	material.set_shader_parameter("Noise2Panning", Vector2(0.4, 0.8))
	material.set_shader_parameter("Noise2Texture", load("res://images/vfx/tileable_noise_1.png"))
	material.set_shader_parameter("Noise1Strength", 0.435)
	material.set_shader_parameter("Noise1Scaling", Vector2(0.8, 0.8))
	material.set_shader_parameter("Noise1Panning", Vector2(0.2, 1))
	material.set_shader_parameter("Noise1Texture", load("res://images/vfx/fire/triangle_noise_tile.png"))
	material.set_shader_parameter("InvertNoiseMask", false)
	material.set_shader_parameter("NoiseMaskScale", Vector2(1, 1.305))
	material.set_shader_parameter("NoiseMaskOffset", Vector2(0, -0.77))
	material.set_shader_parameter("NoiseMask", load("res://images/vfx/environment/fire/basic_fire_gradient.png"))
	material.set_shader_parameter("Distortion2Scale", Vector2(1, 1))
	material.set_shader_parameter("Distortion2Panning", Vector2(0.4, 0.4))
	material.set_shader_parameter("Distortion2Texture", load("res://images/vfx/tileable_noise_1.png"))
	material.set_shader_parameter("Distortion2Strength", 0.17)
	material.set_shader_parameter("Distortion1Scale", Vector2(1, 1))
	material.set_shader_parameter("Distortion1Panning", Vector2(0, 1.5))
	material.set_shader_parameter("Distortion1Texture", load("res://images/vfx/fire/zigzag_fire_distortion.png"))
	material.set_shader_parameter("Distortion1Strength", -0.075)
	material.set_shader_parameter("DistortionMaskScale", Vector2(1, 2))
	material.set_shader_parameter("DistortionMaskOffset", Vector2(0, -0.72))
	material.set_shader_parameter("DistortionMask", load("res://images/vfx/fire/fire_bottom_mask.png"))
	material.set_shader_parameter("InnerColor", Color(0.32, 0.94, 1, 1))
	material.set_shader_parameter("OuterStep", Vector2(0.07, 0.17))
	return material


func _rect_array(rect: Rect2i) -> Array[int]:
	return [rect.position.x, rect.position.y, rect.size.x, rect.size.y]


func _parse_options() -> Dictionary:
	var options := {"pck": "", "sts2-dll": "", "output": ""}
	var args := OS.get_cmdline_user_args()
	var index := 0
	while index < args.size():
		if not str(args[index]).begins_with("--") or index + 1 >= args.size():
			_fail("expected --name value")
			return options
		var key := str(args[index]).trim_prefix("--")
		if not options.has(key):
			_fail("unknown option --%s" % key)
			return options
		options[key] = str(args[index + 1])
		index += 2
	return options


func _write_summary(value: Dictionary) -> void:
	var path := _output_root.path_join("summary.json")
	DirAccess.make_dir_recursive_absolute(path.get_base_dir())
	var file := FileAccess.open(path, FileAccess.WRITE)
	if file == null:
		push_error("could not write %s" % path)
		return
	file.store_string(JSON.stringify(value, "  ", false) + "\n")
	file.close()


func _fail(message: String) -> void:
	_errors.append(message)
	push_error(message)
