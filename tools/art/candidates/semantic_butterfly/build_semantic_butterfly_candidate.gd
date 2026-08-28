extends SceneTree

## Isolated, non-deployable semantic-component probe for the native-transparent
## 0030 blue-butterfly ornament. Runtime pages are byte-for-byte copies of the
## archived EvoLink outputs; this builder never thresholds, masks, crops, or
## otherwise edits their Alpha. The only resampling below is for the explicitly
## opaque SourceOver preview strip, which is not referenced by the Spine atlas.

const COMMAND := "build-semantic-butterfly"
const OUTPUT_ROOT := "Vivhite/tools/candidates/semantic_butterfly"
const RESOURCE_ROOT := "res://tools/candidates/semantic_butterfly"

const SOURCE_BACK_HAIR := "assets/vivhite-ironclad/generated/evolink-paid/2026-08-28/0031-split-back-hair-attachment-attempt-01/output.png"
const SOURCE_HEAD_FACE := "assets/vivhite-ironclad/generated/evolink-paid/2026-08-28/0044-split-head-face-attachment-attempt-05/output.png"
const SOURCE_FRONT_HAIR := "assets/vivhite-ironclad/generated/evolink-paid/2026-08-28/0033-split-front-hair-attachment-attempt-02/output.png"
const SOURCE_BUTTERFLY := "assets/vivhite-ironclad/generated/evolink-paid/2026-08-28/0030-split-butterfly-attachment-attempt-01/output.png"

const PAGE_BACK_HAIR := "semantic_back_hair.png"
const PAGE_HEAD_FACE := "semantic_head_face.png"
const PAGE_FRONT_HAIR := "semantic_front_hair.png"
const PAGE_BUTTERFLY := "semantic_butterfly.png"
const PAGE_SOURCEOVER := "semantic_butterfly_sourceover_triptych.png"
const PAGE_SETUP_LAYER_PROBE := "semantic_butterfly_setup_layer_probe.png"
const ATLAS_FILE := "semantic_butterfly.spatlas"
const JSON_FILE := "semantic_butterfly.spjson"
const DATA_FILE := "semantic_butterfly_skeleton_data.tres"
const ANALYSIS_FILE := "semantic_butterfly_analysis.json"

const REGION_BACK_HAIR := "semantic_back_hair"
const REGION_HEAD_FACE := "semantic_head_face"
const REGION_FRONT_HAIR := "semantic_front_hair"
const REGION_BUTTERFLY := "semantic_butterfly"

const SLOT_BACK_HAIR := "semantic_back_hair"
const SLOT_HEAD_FACE := "semantic_head_face"
const SLOT_BUTTERFLY_UNDER := "semantic_butterfly_under_front_hair_probe"
const SLOT_FRONT_HAIR := "semantic_front_hair"
const SLOT_BUTTERFLY_FRONT := "semantic_butterfly_front"

const BONE_ROOT := "semantic_root"
const BONE_HEAD := "vivhite_head"
const BONE_BUTTERFLY := "vivhite_butterfly"

const IMAGE_SIZE := Vector2i(1024, 1024)
const HEAD_CANVAS_WORLD := 500.0
const BUTTERFLY_CANVAS_WORLD := 190.0
const BUTTERFLY_SOURCE_PIVOT := Vector2(176.0, 650.0)
const BUTTERFLY_HEAD_MOUNT := Vector2(100.0, 110.0)
const DEATH_DETACH_TIME := 1.05
const HEAD_NEGATIVE_EXTREME := -20.15
const HEAD_POSITIVE_VISIBLE_EXTREME := 29.5
const BUTTERFLY_NEGATIVE_EXTREME := -4.0
const BUTTERFLY_POSITIVE_EXTREME := 2.8

const ANIMATION_DURATIONS := {
	"idle_loop": 2.0,
	"low_health_loop": 1.4666667,
	"relaxed_loop": 12.000001,
	"attack": 1.1666667,
	"attack_heavy": 1.5333334,
	"cast": 1.5666667,
	"hurt": 1.0,
	"die": 2.3333335,
}

var _errors: Array[String] = []


func _initialize() -> void:
	var args := OS.get_cmdline_user_args()
	if args.is_empty():
		args = PackedStringArray([COMMAND])
	if args[0] in ["-h", "--help", "help"]:
		print("godot --headless --path tools/art --script res://candidates/semantic_butterfly/build_semantic_butterfly_candidate.gd -- build-semantic-butterfly")
		quit(0)
		return
	if args[0] != COMMAND:
		push_error("Unknown command: %s" % args[0])
		quit(2)
		return
	var ok := _build()
	if not ok:
		for message: String in _errors:
			push_error(message)
		quit(1)
		return
	quit(0)


func _build() -> bool:
	var output_root := _absolute_path(OUTPUT_ROOT)
	if output_root.replace("\\", "/").contains("/Vivhite/Vivhite/skins/ironclad/"):
		return _fail("Semantic probe may not target the live runtime skin.")
	if DirAccess.make_dir_recursive_absolute(output_root) != OK:
		return _fail("Could not create candidate output directory: %s" % output_root)

	var sources := {
		PAGE_BACK_HAIR: SOURCE_BACK_HAIR,
		PAGE_HEAD_FACE: SOURCE_HEAD_FACE,
		PAGE_FRONT_HAIR: SOURCE_FRONT_HAIR,
		PAGE_BUTTERFLY: SOURCE_BUTTERFLY,
	}
	var loaded := {}
	for page_name: String in sources:
		var source_path := _absolute_path(str(sources[page_name]))
		var image := Image.load_from_file(source_path)
		if image == null or image.is_empty():
			return _fail("Could not decode source %s" % source_path)
		if image.get_format() != Image.FORMAT_RGBA8 or image.get_size() != IMAGE_SIZE:
			return _fail("Source must be native 1024x1024 RGBA8: %s" % source_path)
		loaded[page_name] = image
		var copy_error := DirAccess.copy_absolute(source_path, output_root.path_join(page_name))
		if copy_error != OK:
			return _fail("Could not byte-copy source page %s: %s" % [page_name, error_string(copy_error)])

	var butterfly: Image = loaded[PAGE_BUTTERFLY]
	var alpha_metrics := _alpha_metrics(butterfly)
	if alpha_metrics.is_empty():
		return false
	if not _write_sourceover_triptych(butterfly, output_root.path_join(PAGE_SOURCEOVER)):
		return false
	if not _write_setup_layer_probe(loaded, output_root.path_join(PAGE_SETUP_LAYER_PROBE)):
		return false

	var skeleton := _build_skeleton()
	var atlas_data := _build_atlas_data()
	if not _write_text(output_root.path_join(JSON_FILE), JSON.stringify(skeleton, "  ", false) + "\n"):
		return false
	var atlas_wrapper := {
		"atlas_data": atlas_data,
		"normal_texture_prefix": "n",
		"source_path": "%s/%s" % [RESOURCE_ROOT, ATLAS_FILE.replace(".spatlas", ".atlas")],
		"specular_texture_prefix": "s",
	}
	if not _write_text(output_root.path_join(ATLAS_FILE), JSON.stringify(atlas_wrapper, "", false) + "\n"):
		return false
	if not _write_text(output_root.path_join(DATA_FILE), _build_tres()):
		return false

	var analysis := {
		"schema": 1,
		"status": "isolated_graybox_not_runtime",
		"source_0030_sha256": FileAccess.get_sha256(_absolute_path(SOURCE_BUTTERFLY)),
		"runtime_copy_sha256": FileAccess.get_sha256(output_root.path_join(PAGE_BUTTERFLY)),
		"source_pages": sources,
		"alpha": alpha_metrics,
		"consumer_contract": {
			"evidence": [
				"Vivhite/VivhiteCode/Characters/IroncladReplacementAssets.cs",
				"Vivhite/Vivhite/skins/ironclad/scenes/combat.tscn",
				"Vivhite/Vivhite/skins/ironclad/scenes/merchant.tscn",
				"sts2.dll::MegaCrit.Sts2.Core.Nodes.Screens.Shops.NMerchantCharacter._Ready/PlayAnimation",
				"Vivhite/tools/candidates/whole_mesh/vivhite_combat.spjson",
			],
			"combat_scene_scale": 0.28,
			"merchant_scene_scale": 0.28,
			"required_animation_names": ANIMATION_DURATIONS.keys(),
			"merchant_animation": "relaxed_loop",
			"merchant_random_seek": true,
			"merchant_decompile_finding": "NMerchantCharacter._Ready calls PlayAnimation(relaxed_loop, true); PlayAnimation sets the track and seeks to animation_end * Rng.Chaotic.NextFloat(), so the attachment contract must hold at arbitrary loop time.",
			"head_parent": BONE_HEAD,
			"butterfly_parent": BONE_HEAD,
			"head_extreme_source": "whole_mesh vivhite_head/vivhite_butterfly timelines before the die body swap",
			"foreground_order_probe": [
				SLOT_BACK_HAIR,
				SLOT_HEAD_FACE,
				SLOT_BUTTERFLY_UNDER,
				SLOT_FRONT_HAIR,
				SLOT_BUTTERFLY_FRONT,
			],
			"default_visible_butterfly_slot": SLOT_BUTTERFLY_UNDER,
			"death_detach_time": DEATH_DETACH_TIME,
		},
		"layer_order_assessment": {
			"setup_probe_result": "The front-most order exposes the long navy/gold connector over the hair; placing the unchanged one-piece attachment behind the front-hair layer hides the connector while preserving both wing lobes.",
			"preferred_production_order": [
				SLOT_BACK_HAIR,
				SLOT_HEAD_FACE,
				"vivhite_butterfly",
				SLOT_FRONT_HAIR,
			],
			"probe_default_matches_preferred_order": true,
			"direct_runtime_drop_in": false,
			"remaining_gate": "Integrate one real butterfly slot behind the chosen front-hair slot in the shared production head rig, then repeat full-body combat and merchant visual acceptance.",
		},
		"placement": {
			"source_pivot_px": [BUTTERFLY_SOURCE_PIVOT.x, BUTTERFLY_SOURCE_PIVOT.y],
			"head_mount_world": [BUTTERFLY_HEAD_MOUNT.x, BUTTERFLY_HEAD_MOUNT.y],
			"head_canvas_world": HEAD_CANVAS_WORLD,
			"butterfly_canvas_world": BUTTERFLY_CANVAS_WORLD,
			"butterfly_attachment_center_world": [_butterfly_attachment_offset().x, _butterfly_attachment_offset().y],
		},
		"visible_extremes_degrees": {
			"head_negative": HEAD_NEGATIVE_EXTREME,
			"head_positive_before_death_swap": HEAD_POSITIVE_VISIBLE_EXTREME,
			"butterfly_local_negative": BUTTERFLY_NEGATIVE_EXTREME,
			"butterfly_local_positive": BUTTERFLY_POSITIVE_EXTREME,
		},
		"evolink_paid_calls": 0,
		"alpha_modified": false,
		"runtime_skin_modified": false,
		"deployable": false,
	}
	if not _write_text(output_root.path_join(ANALYSIS_FILE), JSON.stringify(analysis, "  ", false) + "\n"):
		return false
	if analysis.source_0030_sha256 != analysis.runtime_copy_sha256:
		return _fail("Butterfly page is not a byte-identical copy of archived 0030.")

	print("[semantic-butterfly] Built isolated head-layer probe.")
	print("[semantic-butterfly] 0030 Alpha metrics: %s" % JSON.stringify(alpha_metrics))
	return true


func _build_skeleton() -> Dictionary:
	var attachment_offset := _butterfly_attachment_offset()
	var attachments := {
		SLOT_BACK_HAIR: {REGION_BACK_HAIR: _region_attachment(REGION_BACK_HAIR, HEAD_CANVAS_WORLD, HEAD_CANVAS_WORLD)},
		SLOT_HEAD_FACE: {REGION_HEAD_FACE: _region_attachment(REGION_HEAD_FACE, HEAD_CANVAS_WORLD, HEAD_CANVAS_WORLD)},
		SLOT_BUTTERFLY_UNDER: {REGION_BUTTERFLY: _region_attachment(REGION_BUTTERFLY, BUTTERFLY_CANVAS_WORLD, BUTTERFLY_CANVAS_WORLD, attachment_offset)},
		SLOT_FRONT_HAIR: {REGION_FRONT_HAIR: _region_attachment(REGION_FRONT_HAIR, HEAD_CANVAS_WORLD, HEAD_CANVAS_WORLD)},
		SLOT_BUTTERFLY_FRONT: {REGION_BUTTERFLY: _region_attachment(REGION_BUTTERFLY, BUTTERFLY_CANVAS_WORLD, BUTTERFLY_CANVAS_WORLD, attachment_offset)},
	}
	return {
		"skeleton": {
			"hash": "vivhite-semantic-butterfly-probe-v1",
			"spine": "4.2.43",
			"x": -320.0,
			"y": -320.0,
			"width": 640.0,
			"height": 640.0,
			"images": "./",
		},
		"bones": [
			{"name": BONE_ROOT},
			{"name": BONE_HEAD, "parent": BONE_ROOT},
			{"name": BONE_BUTTERFLY, "parent": BONE_HEAD, "x": BUTTERFLY_HEAD_MOUNT.x, "y": BUTTERFLY_HEAD_MOUNT.y},
		],
		"slots": [
			{"name": SLOT_BACK_HAIR, "bone": BONE_HEAD, "attachment": REGION_BACK_HAIR},
			{"name": SLOT_HEAD_FACE, "bone": BONE_HEAD, "attachment": REGION_HEAD_FACE},
			{"name": SLOT_BUTTERFLY_UNDER, "bone": BONE_BUTTERFLY, "attachment": REGION_BUTTERFLY},
			{"name": SLOT_FRONT_HAIR, "bone": BONE_HEAD, "attachment": REGION_FRONT_HAIR},
			{"name": SLOT_BUTTERFLY_FRONT, "bone": BONE_BUTTERFLY},
		],
		"skins": [{"name": "default", "attachments": attachments}],
		"animations": _build_animations(),
	}


func _build_animations() -> Dictionary:
	var animations := {
		"idle_loop": {"bones": {
			BONE_HEAD: {"rotate": _keys([0.0, 0.5, 1.0, 1.5, 2.0], [0.0, -1.4, 0.0, 1.0, 0.0])},
			BONE_BUTTERFLY: {"rotate": _keys([0.0, 0.5, 1.0, 1.5, 2.0], [0.0, -4.0, 0.0, 2.8, 0.0])},
		}},
		"low_health_loop": {"bones": {
			BONE_HEAD: {"rotate": _keys([0.0, 0.366666675, 0.73333335, 1.100000025, 1.4666667], [5.0, 7.5, 5.0, 6.4, 5.0])},
		}},
		"relaxed_loop": {
			"slots": _under_slot_resets(12.000001),
			"bones": {
				BONE_HEAD: {"rotate": _keys([0.0, 3.00000025, 6.0000005, 9.00000075, 12.000001], [0.0, -1.008, 0.0, 0.72, 0.0])},
				BONE_BUTTERFLY: {"rotate": _keys([0.0, 3.00000025, 6.0000005, 9.00000075, 12.000001], [0.0, -2.88, 0.0, 2.016, 0.0])},
			},
		},
		"attack": {"bones": {BONE_HEAD: {"rotate": _keys([0.0, 0.036, 0.08, 0.443333346, 0.886666692, 1.1666667], [0.0, 7.0, -13.0, -4.0, -1.56, 0.0])}}},
		"attack_heavy": {"bones": {BONE_HEAD: {"rotate": _keys([0.0, 0.054, 0.12, 0.659333362, 1.165333384, 1.5333334], [0.0, 10.85, -20.15, -6.2, -2.418, 0.0])}}},
		"cast": {"bones": {BONE_HEAD: {"rotate": _keys([0.0, 0.11, 0.25, 0.48, 1.222000026, 1.5666667], [0.0, 5.0, -9.0, -6.0, -1.44, 0.0])}}},
		"hurt": {"bones": {BONE_HEAD: {"rotate": _keys([0.0, 0.1, 0.24, 0.48, 0.72, 1.0], [0.0, 17.0, 12.24, -7.0, -2.1, 0.0])}}},
		"die": {
			"slots": {
				SLOT_BUTTERFLY_UNDER: {"attachment": [{"time": 0.0, "name": REGION_BUTTERFLY}, {"time": DEATH_DETACH_TIME, "name": null}]},
				SLOT_BUTTERFLY_FRONT: {"attachment": [{"time": 0.0, "name": null}]},
			},
			"bones": {BONE_HEAD: {"rotate": _keys([0.0, 0.18, 0.46, 0.82, 0.94, 1.0499, 1.24, 1.78, 2.08, 2.3333335], [0.0, 6.0, 15.0, 25.0, 27.25, 29.5, 34.0, 39.0, 43.05, 42.0])}},
		},
		"layer_probe_front": {"slots": {
			SLOT_BUTTERFLY_UNDER: {"attachment": [{"time": 0.0, "name": null}]},
			SLOT_BUTTERFLY_FRONT: {"attachment": [{"time": 0.0, "name": REGION_BUTTERFLY}]},
		}, "bones": {BONE_HEAD: {"rotate": [{"time": 0.0, "value": 0.0}, {"time": 0.1, "value": 0.0}]}}},
		"max_negative": {"slots": _under_slot_resets(0.1), "bones": {
			BONE_HEAD: {"rotate": [{"time": 0.0, "value": HEAD_NEGATIVE_EXTREME}, {"time": 0.1, "value": HEAD_NEGATIVE_EXTREME}]},
			BONE_BUTTERFLY: {"rotate": [{"time": 0.0, "value": BUTTERFLY_NEGATIVE_EXTREME}, {"time": 0.1, "value": BUTTERFLY_NEGATIVE_EXTREME}]},
		}},
		"max_positive": {"slots": _under_slot_resets(0.1), "bones": {
			BONE_HEAD: {"rotate": [{"time": 0.0, "value": HEAD_POSITIVE_VISIBLE_EXTREME}, {"time": 0.1, "value": HEAD_POSITIVE_VISIBLE_EXTREME}]},
			BONE_BUTTERFLY: {"rotate": [{"time": 0.0, "value": BUTTERFLY_POSITIVE_EXTREME}, {"time": 0.1, "value": BUTTERFLY_POSITIVE_EXTREME}]},
		}},
		"max_negative_front": {"slots": _front_slot_resets(0.1), "bones": {
			BONE_HEAD: {"rotate": [{"time": 0.0, "value": HEAD_NEGATIVE_EXTREME}, {"time": 0.1, "value": HEAD_NEGATIVE_EXTREME}]},
			BONE_BUTTERFLY: {"rotate": [{"time": 0.0, "value": BUTTERFLY_NEGATIVE_EXTREME}, {"time": 0.1, "value": BUTTERFLY_NEGATIVE_EXTREME}]},
		}},
		"max_positive_front": {"slots": _front_slot_resets(0.1), "bones": {
			BONE_HEAD: {"rotate": [{"time": 0.0, "value": HEAD_POSITIVE_VISIBLE_EXTREME}, {"time": 0.1, "value": HEAD_POSITIVE_VISIBLE_EXTREME}]},
			BONE_BUTTERFLY: {"rotate": [{"time": 0.0, "value": BUTTERFLY_POSITIVE_EXTREME}, {"time": 0.1, "value": BUTTERFLY_POSITIVE_EXTREME}]},
		}},
	}
	return animations


func _front_slot_resets(duration: float) -> Dictionary:
	return {
		SLOT_BUTTERFLY_UNDER: {"attachment": [{"time": 0.0, "name": null}, {"time": duration, "name": null}]},
		SLOT_BUTTERFLY_FRONT: {"attachment": [{"time": 0.0, "name": REGION_BUTTERFLY}, {"time": duration, "name": REGION_BUTTERFLY}]},
	}


func _under_slot_resets(duration: float) -> Dictionary:
	return {
		SLOT_BUTTERFLY_UNDER: {"attachment": [{"time": 0.0, "name": REGION_BUTTERFLY}, {"time": duration, "name": REGION_BUTTERFLY}]},
		SLOT_BUTTERFLY_FRONT: {"attachment": [{"time": 0.0, "name": null}, {"time": duration, "name": null}]},
	}


func _keys(times: Array, values: Array) -> Array:
	var result := []
	for index in times.size():
		result.append({"time": times[index], "value": values[index]})
	return result


func _region_attachment(path: String, width: float, height: float, offset := Vector2.ZERO) -> Dictionary:
	var attachment := {"path": path, "width": width, "height": height}
	if not offset.is_zero_approx():
		attachment["x"] = offset.x
		attachment["y"] = offset.y
	return attachment


func _butterfly_attachment_offset() -> Vector2:
	return Vector2(
		(0.5 - BUTTERFLY_SOURCE_PIVOT.x / IMAGE_SIZE.x) * BUTTERFLY_CANVAS_WORLD,
		(BUTTERFLY_SOURCE_PIVOT.y / IMAGE_SIZE.y - 0.5) * BUTTERFLY_CANVAS_WORLD,
	)


func _build_atlas_data() -> String:
	var blocks := []
	for page: Dictionary in [
		{"file": PAGE_BACK_HAIR, "region": REGION_BACK_HAIR},
		{"file": PAGE_HEAD_FACE, "region": REGION_HEAD_FACE},
		{"file": PAGE_FRONT_HAIR, "region": REGION_FRONT_HAIR},
		{"file": PAGE_BUTTERFLY, "region": REGION_BUTTERFLY},
	]:
		blocks.append("%s\nsize:1024,1024\nfilter:Linear,Linear\npma:false\nrepeat:none\n%s\nbounds:0,0,1024,1024\n" % [page.file, page.region])
	return "\n".join(blocks)


func _build_tres() -> String:
	return """[gd_resource type="SpineSkeletonDataResource" load_steps=3 format=3]

[ext_resource type="SpineAtlasResource" path="%s/%s" id="1_atlas"]
[ext_resource type="SpineSkeletonFileResource" path="%s/%s" id="2_skeleton"]

[resource]
atlas_res = ExtResource("1_atlas")
skeleton_file_res = ExtResource("2_skeleton")
default_mix = 0.05
""" % [RESOURCE_ROOT, ATLAS_FILE, RESOURCE_ROOT, JSON_FILE]


func _alpha_metrics(image: Image) -> Dictionary:
	var thresholds := [1, 16, 64, 128]
	var metrics := {}
	for threshold: int in thresholds:
		var min_x := image.get_width()
		var min_y := image.get_height()
		var max_x := -1
		var max_y := -1
		var count := 0
		for y in image.get_height():
			for x in image.get_width():
				var alpha := int(round(image.get_pixel(x, y).a * 255.0))
				if alpha < threshold:
					continue
				count += 1
				min_x = mini(min_x, x)
				min_y = mini(min_y, y)
				max_x = maxi(max_x, x)
				max_y = maxi(max_y, y)
		metrics["a_ge_%d" % threshold] = {
			"count": count,
			"bbox": [min_x, min_y, max_x - min_x + 1, max_y - min_y + 1] if count > 0 else [0, 0, 0, 0],
		}
	var edge_nonzero := 0
	var edge_max := 0
	for x in image.get_width():
		for y: int in [0, image.get_height() - 1]:
			var alpha := int(round(image.get_pixel(x, y).a * 255.0))
			edge_nonzero += 1 if alpha > 0 else 0
			edge_max = maxi(edge_max, alpha)
	for y in range(1, image.get_height() - 1):
		for x: int in [0, image.get_width() - 1]:
			var alpha := int(round(image.get_pixel(x, y).a * 255.0))
			edge_nonzero += 1 if alpha > 0 else 0
			edge_max = maxi(edge_max, alpha)
	var corner_alpha := []
	for point: Vector2i in [Vector2i.ZERO, Vector2i(1023, 0), Vector2i(0, 1023), Vector2i(1023, 1023)]:
		corner_alpha.append(int(round(image.get_pixelv(point).a * 255.0)))
	var pivot_alpha := int(round(image.get_pixelv(Vector2i(int(BUTTERFLY_SOURCE_PIVOT.x), int(BUTTERFLY_SOURCE_PIVOT.y))).a * 255.0))
	var components_16 := _component_count(image, 16)
	if corner_alpha.max() != 0:
		_fail("0030 does not have transparent corners.")
	if edge_nonzero != 0:
		_fail("0030 has non-zero Alpha on its outer edge.")
	if pivot_alpha < 128:
		_fail("Chosen mounting pivot is not inside the solid connector core (alpha=%d)." % pivot_alpha)
	return {
		"size": [image.get_width(), image.get_height()],
		"format": "RGBA8",
		"corner_alpha": corner_alpha,
		"edge_nonzero_count": edge_nonzero,
		"edge_max_alpha": edge_max,
		"pivot_alpha": pivot_alpha,
		"connected_components_a_ge_16": components_16,
		"thresholds": metrics,
	}


func _component_count(image: Image, threshold: int) -> int:
	var width := image.get_width()
	var height := image.get_height()
	var active := PackedByteArray()
	active.resize(width * height)
	for y in height:
		for x in width:
			active[y * width + x] = 1 if int(round(image.get_pixel(x, y).a * 255.0)) >= threshold else 0
	var components := 0
	var stack := PackedInt32Array()
	for start in active.size():
		if active[start] == 0:
			continue
		components += 1
		active[start] = 0
		stack.append(start)
		while not stack.is_empty():
			var current := stack[-1]
			stack.resize(stack.size() - 1)
			var x := current % width
			var y := current / width
			for neighbor: int in [current - 1, current + 1, current - width, current + width]:
				if neighbor < 0 or neighbor >= active.size():
					continue
				var nx := neighbor % width
				var ny := neighbor / width
				if abs(nx - x) + abs(ny - y) != 1 or active[neighbor] == 0:
					continue
				active[neighbor] = 0
				stack.append(neighbor)
	return components


func _write_sourceover_triptych(source: Image, path: String) -> bool:
	const PANEL := Vector2i(256, 256)
	const RUNTIME_FULL_CANVAS_PX := 53
	var sheet := Image.create(PANEL.x * 3, PANEL.y, false, Image.FORMAT_RGBA8)
	var backgrounds := [Color(0, 0, 0, 1), Color(1, 1, 1, 1), Color("2b3f4b")]
	var preview := source.duplicate()
	preview.resize(RUNTIME_FULL_CANVAS_PX, RUNTIME_FULL_CANVAS_PX, Image.INTERPOLATE_LANCZOS)
	for index in backgrounds.size():
		sheet.fill_rect(Rect2i(index * PANEL.x, 0, PANEL.x, PANEL.y), backgrounds[index])
		var target := Vector2i(
			index * PANEL.x + (PANEL.x - preview.get_width()) / 2,
			(PANEL.y - preview.get_height()) / 2,
		)
		sheet.blend_rect(preview, Rect2i(Vector2i.ZERO, preview.get_size()), target)
	var error := sheet.save_png(path)
	if error != OK:
		return _fail("Could not save SourceOver triptych: %s" % error_string(error))
	return true


func _write_setup_layer_probe(loaded: Dictionary, path: String) -> bool:
	const PANEL := Vector2i(640, 640)
	var sheet := Image.create(PANEL.x * 2, PANEL.y, false, Image.FORMAT_RGBA8)
	for panel_index in 2:
		sheet.fill_rect(Rect2i(panel_index * PANEL.x, 0, PANEL.x, PANEL.y), Color("2b3f4b"))
		var head_center := Vector2i(panel_index * PANEL.x + PANEL.x / 2, PANEL.y / 2)
		_blend_scaled_centered(sheet, loaded[PAGE_BACK_HAIR], Vector2i(500, 500), head_center)
		_blend_scaled_centered(sheet, loaded[PAGE_HEAD_FACE], Vector2i(500, 500), head_center)
		if panel_index == 1:
			_blend_butterfly_setup(sheet, loaded[PAGE_BUTTERFLY], panel_index * PANEL.x)
		_blend_scaled_centered(sheet, loaded[PAGE_FRONT_HAIR], Vector2i(500, 500), head_center)
		if panel_index == 0:
			_blend_butterfly_setup(sheet, loaded[PAGE_BUTTERFLY], panel_index * PANEL.x)
	var error := sheet.save_png(path)
	if error != OK:
		return _fail("Could not save setup layer probe: %s" % error_string(error))
	return true


func _blend_butterfly_setup(target: Image, source: Image, panel_x: int) -> void:
	var center_world := BUTTERFLY_HEAD_MOUNT + _butterfly_attachment_offset()
	var center := Vector2i(
		panel_x + 320 + int(round(center_world.x)),
		320 - int(round(center_world.y)),
	)
	_blend_scaled_centered(target, source, Vector2i(int(BUTTERFLY_CANVAS_WORLD), int(BUTTERFLY_CANVAS_WORLD)), center)


func _blend_scaled_centered(target: Image, source: Image, size: Vector2i, center: Vector2i) -> void:
	var resized := source.duplicate()
	resized.resize(size.x, size.y, Image.INTERPOLATE_LANCZOS)
	var destination := center - size / 2
	target.blend_rect(resized, Rect2i(Vector2i.ZERO, size), destination)


func _absolute_path(path: String) -> String:
	if path.is_absolute_path():
		return path.simplify_path()
	return ProjectSettings.globalize_path("res://").path_join("../..").simplify_path().path_join(path).simplify_path()


func _write_text(path: String, content: String) -> bool:
	var file := FileAccess.open(path, FileAccess.WRITE)
	if file == null:
		return _fail("Could not write %s" % path)
	file.store_string(content)
	file.close()
	return true


func _fail(message: String) -> bool:
	_errors.append(message)
	return false
