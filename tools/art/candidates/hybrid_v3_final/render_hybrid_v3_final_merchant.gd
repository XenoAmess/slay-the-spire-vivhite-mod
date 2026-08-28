extends SceneTree

## Offline Windows/Vulkan gate for the assembled V3 merchant consumer.  The
## renderer instantiates the production merchant PackedScene, preserves its
## Node2D/SpineSprite layout, replaces only the skeleton-data resource with the
## isolated final candidate, dirties every person/VFX slot, and then performs
## the exact random-seek phases used to prove relaxed_loop is phase-safe.

const MERCHANT_SCENE_PATH := "res://Vivhite/skins/ironclad/scenes/merchant.tscn"
const MERCHANT_SCRIPT_PATH := "res://src/Core/Nodes/Screens/Shops/NMerchantCharacter.cs"
const CANDIDATE_DATA_PATH := "res://tools/candidates/hybrid_v3_final/vivhite_combat_skeleton_data.tres"
const CANDIDATE_JSON_PATH := "res://tools/candidates/hybrid_v3_final/vivhite_combat.spjson"
const CANDIDATE_ATLAS_PATH := "res://tools/candidates/hybrid_v3_final/vivhite_combat.spatlas"
const ANIMATION := "relaxed_loop"
const LOOP_DURATION := 12.000001
const LOOP_EPSILON := 0.00002
const EXPECTED_PREVIEW_TIME := 5.4
const EXPECTED_SCALE := 0.28
const SPINE_UPDATE_MODE_MANUAL := 2

const BODY_SLOT := "vivhite_body"
const BODY_ATTACHMENT := "vivhite_combat_body"
const ACTION_SLOT := "vivhite_action_pose"
const ACTION_ATTACHMENT := "vivhite_combat_attack_peak"
const DEATH_SLOT := "vivhite_death_body"
const DEATH_ATTACHMENT := "vivhite_combat_death_side"
const SLASH_SLOT := "slash_mesh"
const SLASH_ATTACHMENT := "vivhite_combat_magic_arc"
const SIGIL_SLOT := "vivhite_magic_sigil"
const SIGIL_ATTACHMENT := "vivhite_combat_magic_sigil"
const EYE_SLOT := "eye_attach_slot"
const SLOT_NAMES: Array[String] = [
	BODY_SLOT,
	ACTION_SLOT,
	DEATH_SLOT,
	SLASH_SLOT,
	SIGIL_SLOT,
	EYE_SLOT,
]
const CHARACTER_SLOTS: Array[String] = [BODY_SLOT, ACTION_SLOT, DEATH_SLOT]

const SAMPLES := [
	{"label": "loop-start", "time": 0.0},
	{"label": "random-1p37", "time": 1.37},
	{"label": "quarter", "time": 3.00000025},
	{"label": "scene-preview-5p4", "time": 5.4},
	{"label": "half", "time": 6.0000005},
	{"label": "three-quarter", "time": 9.00000075},
	{"label": "random-9p9", "time": 9.9},
	{"label": "pre-end", "time": 11.9999},
	{"label": "loop-end", "time": 12.000001},
	{"label": "loop-plus-epsilon", "time": 12.000021},
]

const DEFAULT_CANVAS := Vector2i(1280, 900)
const DEFAULT_ORIGIN := Vector2(325.0, 681.0)
const PROXY_MAX_DIMENSION := 512
const CORE_MINIMUM := Vector2i(170, 300)
const CORE_MAXIMUM := Vector2i(260, 390)
const ALPHA_THRESHOLDS: Array[int] = [1, 16, 128, 240]

var _output_root := ""
var _canvas := DEFAULT_CANVAS
var _origin := DEFAULT_ORIGIN
var _errors: Array[String] = []


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
	_output_root = _absolute_path(str(options["output"]))
	_canvas = Vector2i(int(options["width"]), int(options["height"]))
	_origin = Vector2(float(options["origin-x"]), float(options["origin-y"]))
	if not _validate_output_root(_output_root):
		quit(2)
		return
	DirAccess.make_dir_recursive_absolute(_output_root)

	var summary := _base_summary(options)
	if not _prepare_runtime(str(options["pck"])):
		summary["errors"] = _errors.duplicate()
		_write_json(_output_root.path_join("merchant_summary.json"), summary)
		quit(2)
		return

	var candidate_data: Resource = ResourceLoader.load(
		CANDIDATE_DATA_PATH, "SpineSkeletonDataResource", ResourceLoader.CACHE_MODE_REPLACE
	)
	if candidate_data == null or not candidate_data.is_class("SpineSkeletonDataResource"):
		_fail("Could not load the final candidate SpineSkeletonDataResource.")
		summary["errors"] = _errors.duplicate()
		_write_json(_output_root.path_join("merchant_summary.json"), summary)
		quit(2)
		return
	var relaxed: Variant = candidate_data.call("find_animation", ANIMATION)
	if relaxed == null:
		_fail("Final candidate has no relaxed_loop animation.")
	else:
		summary["runtime_animation_duration"] = float((relaxed as Object).call("get_duration"))
		if absf(float(summary["runtime_animation_duration"]) - LOOP_DURATION) > LOOP_EPSILON:
			_fail(
				"relaxed_loop duration %.9f does not match %.9f."
				% [float(summary["runtime_animation_duration"]), LOOP_DURATION]
			)
	if not _errors.is_empty():
		summary["errors"] = _errors.duplicate()
		_write_json(_output_root.path_join("merchant_summary.json"), summary)
		quit(2)
		return

	var viewport := SubViewport.new()
	viewport.name = "HybridV3FinalMerchantViewport"
	viewport.size = _canvas
	viewport.transparent_bg = true
	viewport.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	viewport.render_target_clear_mode = SubViewport.CLEAR_MODE_ALWAYS
	root.add_child(viewport)
	var stage := Node2D.new()
	stage.name = "MerchantStage"
	viewport.add_child(stage)

	var reports: Array = []
	var images: Array[Image] = []
	var validity: Array[bool] = []
	var scene_probe: Dictionary = {}
	for index in SAMPLES.size():
		var capture := await _capture_sample(
			stage, viewport, candidate_data, SAMPLES[index], index
		)
		if capture.is_empty():
			continue
		var report: Dictionary = capture["report"]
		reports.append(report)
		images.append(capture["image"] as Image)
		validity.append(bool(report["passed"]))
		if scene_probe.is_empty():
			scene_probe = report["scene_consumer"]

	var contact_sheets := _write_contact_sheets(images, validity)
	var frame_count_ok := reports.size() == SAMPLES.size()
	var frames_ok := frame_count_ok and validity.all(func(value: bool) -> bool: return value)
	var scene_layout_ok := (
		not scene_probe.is_empty()
		and bool(scene_probe.get("packed_scene_loaded", false))
		and bool(scene_probe.get("layout_contract_passed", false))
		and bool(scene_probe.get("candidate_override_applied", false))
	)
	var consumer_fidelity := _consumer_fidelity(scene_probe)
	summary["consumer_fidelity"] = consumer_fidelity
	summary["contact_sheets"] = contact_sheets
	summary["frame_count_passed"] = frame_count_ok
	summary["frames"] = reports
	summary["frames_passed"] = frames_ok
	summary["real_scene_layout_passed"] = scene_layout_ok
	summary["resource_graph"] = scene_probe
	summary["errors"] = _errors.duplicate()
	summary["success"] = (
		frame_count_ok
		and frames_ok
		and scene_layout_ok
		and contact_sheets.size() == 4
		and _errors.is_empty()
	)
	_write_json(_output_root.path_join("merchant_summary.json"), summary)
	if bool(summary["success"]):
		print(
			"[hybrid-v3-final-merchant] Vulkan PASS: %d/%d dirty relaxed_loop seeks; C# fidelity=%s."
			% [reports.size(), SAMPLES.size(), str(consumer_fidelity.get("status", "unknown"))]
		)
		quit(0)
		return
	push_error("[hybrid-v3-final-merchant] Offline merchant gate failed.")
	quit(1)


func _parse_args() -> Dictionary:
	var options := {
		"height": DEFAULT_CANVAS.y,
		"origin-x": DEFAULT_ORIGIN.x,
		"origin-y": DEFAULT_ORIGIN.y,
		"output": ".work/hybrid-v3-final-merchant",
		"pck": OS.get_environment("VIVHITE_STS2_PCK_PATH"),
		"width": DEFAULT_CANVAS.x,
	}
	var args := OS.get_cmdline_user_args()
	var index := 0
	while index < args.size():
		var token := str(args[index])
		if token == "render-merchant":
			index += 1
			if index < args.size() and not str(args[index]).begins_with("--"):
				options["output"] = str(args[index])
				index += 1
			continue
		if not token.begins_with("--") or index + 1 >= args.size():
			_fail("Expected '--name value', got '%s'." % token)
			return {}
		var name := token.trim_prefix("--")
		if not options.has(name):
			_fail("Unknown option '%s'." % token)
			return {}
		index += 1
		var value := str(args[index])
		if name in ["width", "height"]:
			options[name] = value.to_int()
		elif name in ["origin-x", "origin-y"]:
			options[name] = value.to_float()
		else:
			options[name] = value
		index += 1
	if int(options["width"]) < 64 or int(options["height"]) < 64:
		_fail("Merchant render canvas must be at least 64x64.")
		return {}
	return options


func _prepare_runtime(pck_path: String) -> bool:
	if DisplayServer.get_name() == "headless":
		_fail("A Windows display is required; headless uses the dummy rasterizer.")
	var driver := RenderingServer.get_current_rendering_driver_name().to_lower()
	if driver != "vulkan":
		_fail("Expected Vulkan, got '%s'." % driver)
	if pck_path.is_empty() or not FileAccess.file_exists(pck_path):
		_fail("A valid base-game PCK is required via --pck or VIVHITE_STS2_PCK_PATH.")
	elif not ProjectSettings.load_resource_pack(pck_path, false):
		_fail("Could not mount base-game PCK '%s'." % pck_path)
	for type_name: String in ["SpineSprite", "SpineSkeletonDataResource"]:
		if not ClassDB.class_exists(type_name):
			_fail("Missing game-compatible Spine class '%s'." % type_name)
	for path: String in [
		MERCHANT_SCENE_PATH,
		CANDIDATE_DATA_PATH,
		CANDIDATE_JSON_PATH,
		CANDIDATE_ATLAS_PATH,
	]:
		if not ResourceLoader.exists(path):
			_fail("Required merchant gate resource is missing: %s" % path)
	return _errors.is_empty()


func _capture_sample(
	stage: Node2D,
	viewport: SubViewport,
	candidate_data: Resource,
	sample: Dictionary,
	index: int,
) -> Dictionary:
	var scene_result := _instantiate_real_merchant(candidate_data)
	if scene_result.is_empty():
		return {}
	var merchant: Node2D = scene_result["merchant"]
	var sprite: Node2D = scene_result["sprite"]
	merchant.position = _origin
	stage.add_child(merchant)
	# _Ready may have performed the real consumer's chaotic initial seek.  The
	# acceptance sample deliberately overrides that state only after the real
	# scene has entered the tree.
	sprite.call("set_update_mode", SPINE_UPDATE_MODE_MANUAL)
	var state: Object = sprite.call("get_animation_state")
	var skeleton: Object = sprite.call("get_skeleton")
	if state == null or skeleton == null:
		_fail("Spine runtime did not initialize for merchant sample %s." % sample["label"])
		merchant.queue_free()
		await process_frame
		return {}

	var dirty_before := _dirty_all_slots(skeleton)
	var entry: Variant = state.call("set_animation", ANIMATION, true, 0)
	if entry == null or not (entry as Object).has_method("set_track_time"):
		_fail("relaxed_loop track entry cannot be seeked for %s." % sample["label"])
		merchant.queue_free()
		await process_frame
		return {}
	(entry as Object).call("set_track_time", float(sample["time"]))
	state.call("update", 0.0)
	state.call("apply", skeleton)
	sprite.call("update_skeleton", 0.0)

	var attachments := _observe_attachments(skeleton)
	var expected := {
		BODY_SLOT: BODY_ATTACHMENT,
		ACTION_SLOT: null,
		DEATH_SLOT: null,
		SLASH_SLOT: null,
		SIGIL_SLOT: null,
		EYE_SLOT: null,
	}
	var body_only_ok := attachments == expected
	var visible_character_count := 0
	var visible_total := 0
	for slot_name: String in SLOT_NAMES:
		if attachments[slot_name] != null:
			visible_total += 1
			if CHARACTER_SLOTS.has(slot_name):
				visible_character_count += 1
	var single_character_ok := visible_character_count == 1 and visible_total == 1

	await process_frame
	RenderingServer.force_draw(false)
	await RenderingServer.frame_post_draw
	var image: Image = viewport.get_texture().get_image()
	if image == null or image.is_empty():
		_fail("Vulkan returned an empty merchant frame for %s." % sample["label"])
		merchant.queue_free()
		await process_frame
		return {}
	if image.get_format() != Image.FORMAT_RGBA8:
		image.convert(Image.FORMAT_RGBA8)
	var alpha := _alpha_metrics(image)
	var core_bbox: Array = alpha["thresholds"]["128"]["bbox"]
	var size_ok := _bbox_size_in_range(core_bbox, CORE_MINIMUM, CORE_MAXIMUM)
	var alpha_ok := (
		int(alpha["thresholds"]["1"]["pixel_count_proxy"]) > 0
		and int(alpha["thresholds"]["240"]["pixel_count_proxy"]) > 0
		and bool(alpha["four_corners_clear"])
		and not bool(alpha["touches_canvas_edge"])
		and size_ok
	)
	var relative_path := "frames/%02d-%s-t%.7f.png" % [
		index, _safe_component(str(sample["label"])), float(sample["time"])
	]
	var absolute_path := _output_root.path_join(relative_path)
	DirAccess.make_dir_recursive_absolute(absolute_path.get_base_dir())
	var save_ok := image.save_png(absolute_path) == OK
	var passed := (
		bool(dirty_before["passed"])
		and body_only_ok
		and single_character_ok
		and alpha_ok
		and save_ok
		and bool(scene_result["probe"]["layout_contract_passed"])
	)
	if not passed:
		_fail(
			"Merchant sample %s failed: dirty=%s body-only=%s single=%s alpha=%s save=%s."
			% [
				sample["label"], dirty_before["passed"], body_only_ok,
				single_character_ok, alpha_ok, save_ok,
			]
		)
	var entry_object := entry as Object
	var report := {
		"alpha": alpha,
		"body_only_contract_passed": body_only_ok,
		"dirty_before_seek": dirty_before,
		"expected_attachments": expected,
		"label": sample["label"],
		"observed_attachments_after_seek": attachments,
		"passed": passed,
		"path": relative_path,
		"requested_track_time": float(sample["time"]),
		"runtime_animation_time": float(entry_object.call("get_animation_time")),
		"runtime_track_time": float(entry_object.call("get_track_time")),
		"scene_consumer": scene_result["probe"],
		"sha256": _image_sha256(image),
		"single_character_contract_passed": single_character_ok,
		"size_contract_passed": size_ok,
		"visible_character_attachment_count": visible_character_count,
		"visible_total_attachment_count": visible_total,
	}
	merchant.queue_free()
	await process_frame
	return {"image": image, "report": report}


func _instantiate_real_merchant(candidate_data: Resource) -> Dictionary:
	var loaded: Resource = ResourceLoader.load(
		MERCHANT_SCENE_PATH, "PackedScene", ResourceLoader.CACHE_MODE_REPLACE
	)
	if not loaded is PackedScene:
		_fail("Could not load the production merchant PackedScene '%s'." % MERCHANT_SCENE_PATH)
		return {}
	var merchant_value: Node = (loaded as PackedScene).instantiate()
	if not merchant_value is Node2D:
		_fail("Production merchant PackedScene did not instantiate a Node2D root.")
		if merchant_value != null:
			merchant_value.queue_free()
		return {}
	var merchant := merchant_value as Node2D
	var sprite_value: Node = merchant.get_node_or_null("SpineSprite")
	if sprite_value == null or not sprite_value.is_class("SpineSprite"):
		_fail("Production merchant scene has no SpineSprite child at 'SpineSprite'.")
		merchant.queue_free()
		return {}
	var sprite := sprite_value as Node2D
	var template_data: Variant = sprite.get("skeleton_data_res")
	var template_path := (
		str((template_data as Resource).resource_path)
		if template_data is Resource else ""
	)
	var original_scale := sprite.scale
	var preview_skin: Variant = sprite.get("preview_skin")
	var preview_animation: Variant = sprite.get("preview_animation")
	var preview_time: Variant = sprite.get("preview_time")
	var root_script: Variant = merchant.get_script()
	var script_path := str((root_script as Resource).resource_path) if root_script is Resource else ""
	var script_resource_attached: bool = (
		root_script != null and merchant.get_script() == root_script
	)
	var has_pascal_method := merchant.has_method("PlayAnimation")
	var has_snake_method := merchant.has_method("play_animation")
	# A CSharpScript resource may remain attached to the deserialized node even
	# when the standalone process cannot resolve its compiled class.  Presence
	# of the consumer method, rather than resource attachment alone, is the
	# accurate signal that a live NMerchantCharacter instance was bound.
	var bound_to_instance: bool = (
		script_resource_attached and (has_pascal_method or has_snake_method)
	)
	var layout_ok := (
		merchant.name == &"IroncladMerchant"
		and sprite.name == &"SpineSprite"
		and absf(original_scale.x - EXPECTED_SCALE) <= 0.000001
		and absf(original_scale.y - EXPECTED_SCALE) <= 0.000001
		and str(preview_skin) == "default"
		and str(preview_animation) == ANIMATION
		and absf(float(preview_time) - EXPECTED_PREVIEW_TIME) <= 0.000001
	)
	sprite.set("skeleton_data_res", candidate_data)
	var effective_data: Variant = sprite.get("skeleton_data_res")
	var candidate_override: bool = (
		effective_data == candidate_data
		and effective_data is Resource
		and str((effective_data as Resource).resource_path) == CANDIDATE_DATA_PATH
	)
	var probe := {
		"bound_instance_has_pascal_play_animation": has_pascal_method,
		"bound_instance_has_snake_play_animation": has_snake_method,
		"candidate_override_applied": candidate_override,
		"csharp_script_bound_to_instance": bound_to_instance,
		"csharp_script_resource_attached_to_scene_node": script_resource_attached,
		"effective_skeleton_data_path": (
			str((effective_data as Resource).resource_path) if effective_data is Resource else ""
		),
		"expected_consumer_script_path": MERCHANT_SCRIPT_PATH,
		"layout_contract_passed": layout_ok,
		"packed_scene_loaded": true,
		"preview_animation": str(preview_animation),
		"preview_skin": str(preview_skin),
		"preview_time": float(preview_time),
		"root_class": merchant.get_class(),
		"root_name": str(merchant.name),
		"root_script_class": (root_script as Object).get_class() if root_script is Object else "",
		"root_script_path": script_path,
		"scene_path": MERCHANT_SCENE_PATH,
		"spine_child_class": sprite.get_class(),
		"spine_child_name": str(sprite.name),
		"spine_scale": [original_scale.x, original_scale.y],
		"template_skeleton_data_path": template_path,
	}
	return {"merchant": merchant, "probe": probe, "sprite": sprite}


func _consumer_fidelity(probe: Dictionary) -> Dictionary:
	if probe.is_empty():
		return {
			"status": "unavailable",
			"csharp_consumer_executed": false,
			"limitation": "The production merchant PackedScene could not be instantiated.",
		}
	var script_path_matches := str(probe.get("root_script_path", "")) == MERCHANT_SCRIPT_PATH
	var bound := bool(probe.get("csharp_script_bound_to_instance", false))
	var resource_attached := bool(probe.get("csharp_script_resource_attached_to_scene_node", false))
	if script_path_matches and bound:
		return {
			"status": "production_csharp_bound",
			"csharp_consumer_executed": true,
			"deterministic_override": "After _Ready, each sample dirties all slots and replaces the chaotic preview seek with an exact relaxed_loop seek.",
			"limitation": "No limitation for scene binding; exact phase selection intentionally replaces Rng.Chaotic for reproducibility.",
		}
	return {
		"status": "production_layout_csharp_unbound",
		"csharp_consumer_executed": false,
		"observed_root_script_path": str(probe.get("root_script_path", "")),
		"script_resource_attached_to_scene_node": resource_attached,
		"script_bound_to_instance": bound,
		"limitation": "The standalone Godot process could not bind NMerchantCharacter; the gate uses the real PackedScene layout/resource graph and mirrors PlayAnimation by set_animation(loop=true) plus exact track seek.",
	}


func _dirty_all_slots(skeleton: Object) -> Dictionary:
	_set_named_attachment(skeleton, BODY_SLOT, null)
	_set_named_attachment(skeleton, ACTION_SLOT, ACTION_ATTACHMENT)
	_set_named_attachment(skeleton, DEATH_SLOT, DEATH_ATTACHMENT)
	_set_named_attachment(skeleton, SLASH_SLOT, SLASH_ATTACHMENT)
	_set_named_attachment(skeleton, SIGIL_SLOT, SIGIL_ATTACHMENT)
	# eye_attach_slot intentionally has no authored skin attachment.  Use a
	# foreign, valid attachment object to prove relaxed_loop clears inherited
	# runtime state instead of merely preserving an already-empty eye slot.
	var foreign_eye_attachment: Variant = skeleton.call(
		"get_attachment_by_slot_name", SLASH_SLOT, SLASH_ATTACHMENT
	)
	var eye_slot: Variant = skeleton.call("find_slot", EYE_SLOT)
	if eye_slot == null or foreign_eye_attachment == null:
		_fail("Could not inject a foreign dirty attachment into eye_attach_slot.")
	else:
		(eye_slot as Object).call("set_attachment", foreign_eye_attachment)
	var observed := _observe_attachments(skeleton)
	var expected := {
		BODY_SLOT: null,
		ACTION_SLOT: ACTION_ATTACHMENT,
		DEATH_SLOT: DEATH_ATTACHMENT,
		SLASH_SLOT: SLASH_ATTACHMENT,
		SIGIL_SLOT: SIGIL_ATTACHMENT,
		EYE_SLOT: SLASH_ATTACHMENT,
	}
	return {
		"attachments": observed,
		"eye_dirty_strategy": "foreign valid slash attachment object; eye slot has no authored skin attachment",
		"expected": expected,
		"passed": observed == expected,
	}


func _set_named_attachment(
	skeleton: Object, slot_name: String, attachment_name: Variant
) -> void:
	var slot: Variant = skeleton.call("find_slot", slot_name)
	if slot == null:
		_fail("Runtime skeleton is missing slot '%s'." % slot_name)
		return
	if attachment_name == null:
		(slot as Object).call("set_attachment", null)
		return
	var attachment: Variant = skeleton.call(
		"get_attachment_by_slot_name", slot_name, str(attachment_name)
	)
	if attachment == null:
		_fail("Runtime cannot resolve %s/%s." % [slot_name, attachment_name])
		return
	(slot as Object).call("set_attachment", attachment)


func _observe_attachments(skeleton: Object) -> Dictionary:
	var result := {}
	for slot_name: String in SLOT_NAMES:
		var slot: Variant = skeleton.call("find_slot", slot_name)
		if slot == null:
			_fail("Runtime skeleton is missing slot '%s'." % slot_name)
			result[slot_name] = "<missing>"
			continue
		var attachment: Variant = (slot as Object).call("get_attachment")
		result[slot_name] = (
			null
			if attachment == null
			else str((attachment as Object).call("get_attachment_name"))
		)
	return result


func _alpha_metrics(source: Image) -> Dictionary:
	var corners := [
		source.get_pixel(0, 0).a,
		source.get_pixel(source.get_width() - 1, 0).a,
		source.get_pixel(0, source.get_height() - 1).a,
		source.get_pixel(source.get_width() - 1, source.get_height() - 1).a,
	]
	var image := source.duplicate()
	var source_size := source.get_size()
	var longest := maxi(source_size.x, source_size.y)
	if longest > PROXY_MAX_DIMENSION:
		var factor := float(PROXY_MAX_DIMENSION) / float(longest)
		image.resize(
			maxi(1, int(round(source_size.x * factor))),
			maxi(1, int(round(source_size.y * factor))),
			Image.INTERPOLATE_BILINEAR
		)
	if image.get_format() != Image.FORMAT_RGBA8:
		image.convert(Image.FORMAT_RGBA8)
	var size: Vector2i = image.get_size()
	var bytes: PackedByteArray = image.get_data()
	var mins := {}
	var maxs := {}
	var counts := {}
	for threshold: int in ALPHA_THRESHOLDS:
		mins[threshold] = Vector2i(size.x, size.y)
		maxs[threshold] = Vector2i(-1, -1)
		counts[threshold] = 0
	var edge_count := 0
	for y in size.y:
		var row: int = y * size.x * 4
		for x in size.x:
			var alpha := int(bytes[row + x * 4 + 3])
			if alpha > 0 and (x == 0 or y == 0 or x == size.x - 1 or y == size.y - 1):
				edge_count += 1
			for threshold: int in ALPHA_THRESHOLDS:
				if alpha < threshold:
					continue
				counts[threshold] = int(counts[threshold]) + 1
				var minimum: Vector2i = mins[threshold]
				var maximum: Vector2i = maxs[threshold]
				mins[threshold] = Vector2i(mini(minimum.x, x), mini(minimum.y, y))
				maxs[threshold] = Vector2i(maxi(maximum.x, x), maxi(maximum.y, y))
	var scale := Vector2(float(source_size.x) / float(size.x), float(source_size.y) / float(size.y))
	var thresholds := {}
	for threshold: int in ALPHA_THRESHOLDS:
		var minimum: Vector2i = mins[threshold]
		var maximum: Vector2i = maxs[threshold]
		var bbox := []
		if maximum.x >= minimum.x:
			var begin := Vector2(floor(minimum.x * scale.x), floor(minimum.y * scale.y))
			var end := Vector2(
				ceil((maximum.x + 1) * scale.x), ceil((maximum.y + 1) * scale.y)
			)
			bbox = [int(begin.x), int(begin.y), int(end.x - begin.x), int(end.y - begin.y)]
		thresholds[str(threshold)] = {
			"bbox": bbox,
			"pixel_count_proxy": counts[threshold],
		}
	return {
		"corner_alpha": corners,
		"edge_alpha_pixels_proxy": edge_count,
		"four_corners_clear": corners.all(func(value: float) -> bool: return value <= 0.0),
		"format": "RGBA8",
		"proxy_size": [size.x, size.y],
		"thresholds": thresholds,
		"touches_canvas_edge": edge_count > 0,
	}


func _bbox_size_in_range(bbox: Array, minimum: Vector2i, maximum: Vector2i) -> bool:
	return (
		bbox.size() == 4
		and int(bbox[2]) >= minimum.x
		and int(bbox[2]) <= maximum.x
		and int(bbox[3]) >= minimum.y
		and int(bbox[3]) <= maximum.y
	)


func _write_contact_sheets(images: Array[Image], validity: Array[bool]) -> Dictionary:
	if images.is_empty() or images.size() != validity.size():
		_fail("Cannot create merchant contact sheets from incomplete frames.")
		return {}
	var result := {}
	var backgrounds := {
		"transparent_on_dark": Color("101318"),
		"sourceover_black": Color.BLACK,
		"sourceover_white": Color.WHITE,
		"sourceover_game_green": Color("243a32"),
	}
	for label: String in backgrounds:
		var path := _output_root.path_join("contact-sheets/%s.png" % label)
		DirAccess.make_dir_recursive_absolute(path.get_base_dir())
		if not _write_contact_sheet(images, validity, path, backgrounds[label]):
			_fail("Could not save merchant contact sheet '%s'." % label)
			continue
		result[label] = _relative_to_output(path)
	return result


func _write_contact_sheet(
	images: Array[Image], validity: Array[bool], path: String, background: Color
) -> bool:
	const COLUMNS := 5
	const CELL_SIZE := Vector2i(320, 225)
	var rows := ceili(float(images.size()) / float(COLUMNS))
	var sheet := Image.create(CELL_SIZE.x * COLUMNS, CELL_SIZE.y * rows, false, Image.FORMAT_RGBA8)
	sheet.fill(background)
	for index in images.size():
		var frame := images[index].duplicate()
		frame.resize(CELL_SIZE.x, CELL_SIZE.y, Image.INTERPOLATE_LANCZOS)
		var cell := Vector2i((index % COLUMNS) * CELL_SIZE.x, (index / COLUMNS) * CELL_SIZE.y)
		sheet.blend_rect(frame, Rect2i(Vector2i.ZERO, frame.get_size()), cell)
		var border := Color("36d27a") if validity[index] else Color("ef476f")
		_draw_border(sheet, Rect2i(cell, CELL_SIZE), border, 3)
	return sheet.save_png(path) == OK


func _draw_border(image: Image, rect: Rect2i, color: Color, width: int) -> void:
	for inset in width:
		var left := rect.position.x + inset
		var top := rect.position.y + inset
		var right := rect.end.x - inset - 1
		var bottom := rect.end.y - inset - 1
		for x in range(left, right + 1):
			image.set_pixel(x, top, color)
			image.set_pixel(x, bottom, color)
		for y in range(top, bottom + 1):
			image.set_pixel(left, y, color)
			image.set_pixel(right, y, color)


func _base_summary(options: Dictionary) -> Dictionary:
	var pck_path := str(options["pck"])
	return {
		"base_pck": pck_path.replace("\\", "/"),
		"base_pck_sha256": FileAccess.get_sha256(pck_path) if FileAccess.file_exists(pck_path) else "",
		"candidate_atlas": CANDIDATE_ATLAS_PATH,
		"candidate_atlas_sha256": FileAccess.get_sha256(ProjectSettings.globalize_path(CANDIDATE_ATLAS_PATH)),
		"candidate_json": CANDIDATE_JSON_PATH,
		"candidate_json_sha256": FileAccess.get_sha256(ProjectSettings.globalize_path(CANDIDATE_JSON_PATH)),
		"candidate_skeleton_data": CANDIDATE_DATA_PATH,
		"canvas": [_canvas.x, _canvas.y],
		"consumer_fidelity": {},
		"contact_sheets": {},
		"display_server": DisplayServer.get_name(),
		"errors": [],
		"frame_count_passed": false,
		"frames": [],
		"frames_passed": false,
		"generated_utc": Time.get_datetime_string_from_system(true),
		"merchant_scene": MERCHANT_SCENE_PATH,
		"origin": [_origin.x, _origin.y],
		"real_scene_layout_passed": false,
		"rendering_driver": RenderingServer.get_current_rendering_driver_name(),
		"requested_samples": SAMPLES,
		"resource_graph": {},
		"runtime_animation_duration": 0.0,
		"schema_version": 1,
		"success": false,
	}


func _validate_output_root(path: String) -> bool:
	if path.is_empty():
		_fail("Output path is empty.")
		return false
	var normalized := path.replace("\\", "/").to_lower()
	if normalized.find("/.work/") < 0 and not normalized.ends_with("/.work"):
		_fail("Merchant evidence output must stay under a .work directory: %s" % path)
		return false
	if DirAccess.dir_exists_absolute(path):
		var directory := DirAccess.open(path)
		if directory != null:
			directory.list_dir_begin()
			var first := directory.get_next()
			directory.list_dir_end()
			if not first.is_empty():
				_fail("Merchant evidence output must be new or empty: %s" % path)
				return false
	return true


func _absolute_path(path: String) -> String:
	if path.is_absolute_path():
		return path.simplify_path()
	return ProjectSettings.globalize_path(path).simplify_path()


func _relative_to_output(path: String) -> String:
	return path.trim_prefix(_output_root.trim_suffix("/") + "/").replace("\\", "/")


func _safe_component(value: String) -> String:
	var result := ""
	for character in value.to_lower():
		if character in "abcdefghijklmnopqrstuvwxyz0123456789-_.":
			result += character
		else:
			result += "-"
	return result


func _image_sha256(image: Image) -> String:
	var context := HashingContext.new()
	context.start(HashingContext.HASH_SHA256)
	context.update(image.get_data())
	return context.finish().hex_encode()


func _write_json(path: String, value: Variant) -> bool:
	DirAccess.make_dir_recursive_absolute(path.get_base_dir())
	var file := FileAccess.open(path, FileAccess.WRITE)
	if file == null:
		_fail("Could not write JSON report '%s'." % path)
		return false
	file.store_string(JSON.stringify(value, "  ", false) + "\n")
	file.close()
	return true


func _fail(message: String) -> void:
	_errors.append(message)
	push_error(message)
