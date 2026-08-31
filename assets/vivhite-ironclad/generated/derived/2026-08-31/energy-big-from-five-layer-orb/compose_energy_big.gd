extends SceneTree

## Deterministically derives Vivhite's standalone large energy icon from the
## five already-approved runtime orb layers. This script performs only:
##
## 1. same-size Layer1 -> Layer2 -> Layer3 -> Layer4 -> Layer5 SourceOver;
## 2. PNG save and byte-identical evidence copies;
## 3. read-only Alpha/hash inspection and SourceOver preview generation.
##
## It never crops, masks, thresholds, recolors, cleans, shrinks, expands, or
## otherwise changes the creative pixels in any source layer.

const CANVAS_SIZE := Vector2i(256, 256)
const SOURCE_RELATIVE_PATHS := [
	"Vivhite/Vivhite/images/characters/Vivhite_energy_orb_layer_1.png",
	"Vivhite/Vivhite/images/characters/Vivhite_energy_orb_layer_2.png",
	"Vivhite/Vivhite/images/characters/Vivhite_energy_orb_layer_3.png",
	"Vivhite/Vivhite/images/characters/Vivhite_energy_orb_layer_4.png",
	"Vivhite/Vivhite/images/characters/Vivhite_energy_orb_layer_5.png"
]
const RUNTIME_OUTPUT_RELATIVE_PATH := "Vivhite/Vivhite/images/characters/energy_big.png"
const ARCHIVE_RELATIVE_PATH := (
	"assets/vivhite-ironclad/generated/derived/2026-08-31/"
	+ "energy-big-from-five-layer-orb"
)
const TIMELINE_SOURCE_RELATIVE_PATH := ".tmp/energy-composite"
const TIMELINE_TIMES := ["0p00", "0p25", "0p50", "1p00", "2p00", "3p00"]
const TIMELINE_BACKGROUNDS := ["black", "white", "game-indigo"]
const TIMELINE_SIZES := [128, 64, 32]
const PREVIEW_SIZES := [256, 64, 32]
const BACKGROUNDS := {
	"black": Color(0, 0, 0, 1),
	"white": Color(1, 1, 1, 1),
	"game-indigo": Color("182139")
}


func _initialize() -> void:
	var options := _parse_options(OS.get_cmdline_user_args())
	var repo_root: String = options.get("repo-root", "")
	if repo_root.is_empty():
		printerr("Usage: --repo-root <absolute repository path>")
		quit(2)
		return
	repo_root = repo_root.simplify_path()
	var exit_code := _derive(repo_root)
	quit(exit_code)


func _parse_options(args: PackedStringArray) -> Dictionary:
	var parsed := {}
	var index := 0
	while index < args.size():
		if args[index] == "--repo-root" and index + 1 < args.size():
			parsed["repo-root"] = args[index + 1]
			index += 2
		else:
			index += 1
	return parsed


func _derive(repo_root: String) -> int:
	var archive_dir := repo_root.path_join(ARCHIVE_RELATIVE_PATH)
	var setup_dir := archive_dir.path_join("setup-pose-sourceover")
	var timeline_dir := archive_dir.path_join("five-layer-runtime-timeline")
	for directory in [archive_dir, setup_dir, timeline_dir]:
		var mkdir_error := DirAccess.make_dir_recursive_absolute(directory)
		if mkdir_error != OK:
			printerr("Could not create %s: %s" % [directory, error_string(mkdir_error)])
			return 2

	var source_records: Array[Dictionary] = []
	var source_images: Array[Image] = []
	for index in SOURCE_RELATIVE_PATHS.size():
		var relative_path: String = SOURCE_RELATIVE_PATHS[index]
		var absolute_path := repo_root.path_join(relative_path)
		var image := Image.load_from_file(absolute_path)
		if image == null or image.is_empty():
			printerr("Could not decode source layer: %s" % absolute_path)
			return 3
		if image.get_size() != CANVAS_SIZE or image.get_format() != Image.FORMAT_RGBA8:
			printerr(
				"Source layer must remain 256x256 RGBA8, got %s format=%d: %s"
				% [image.get_size(), int(image.get_format()), absolute_path]
			)
			return 3
		var alpha := _inspect_alpha(image)
		if alpha.corners != [0, 0, 0, 0]:
			printerr("Source layer corner Alpha changed: %s" % absolute_path)
			return 3
		if _bbox_touches_edge(alpha.bbox, CANVAS_SIZE):
			printerr("Source layer Alpha bbox touches an edge: %s" % absolute_path)
			return 3
		source_images.append(image)
		source_records.append({
			"layer": index + 1,
			"relative_path": relative_path,
			"sha256": FileAccess.get_sha256(absolute_path).to_lower(),
			"size": [image.get_width(), image.get_height()],
			"format": "RGBA8",
			"corner_alpha": alpha.corners,
			"alpha_bbox": _rect_to_array(alpha.bbox)
		})

	# Setup pose is rotation 0 for both rotating layers. Draw order follows the
	# actual scene tree exactly: Layer1, Layer2, Layer3, Layer4, then Layer5.
	var composite := Image.create(CANVAS_SIZE.x, CANVAS_SIZE.y, false, Image.FORMAT_RGBA8)
	composite.fill(Color(0, 0, 0, 0))
	for source in source_images:
		composite.blend_rect(
			source,
			Rect2i(Vector2i.ZERO, CANVAS_SIZE),
			Vector2i.ZERO
		)
	if composite.get_size() != CANVAS_SIZE or composite.get_format() != Image.FORMAT_RGBA8:
		printerr("SourceOver composition changed the required canvas or format")
		return 3
	var output_alpha := _inspect_alpha(composite)
	if output_alpha.corners != [0, 0, 0, 0]:
		printerr("Derived output corners are not Alpha=0: %s" % [output_alpha.corners])
		return 3
	if _bbox_touches_edge(output_alpha.bbox, CANVAS_SIZE):
		printerr("Derived output Alpha bbox touches an edge: %s" % output_alpha.bbox)
		return 3
	if output_alpha.nonzero_pixels <= 0 or output_alpha.opaque_pixels <= 0:
		printerr("Derived output has no visible, substantially opaque subject")
		return 3

	var runtime_output := repo_root.path_join(RUNTIME_OUTPUT_RELATIVE_PATH)
	var previous_runtime_sha256 := ""
	if FileAccess.file_exists(runtime_output):
		previous_runtime_sha256 = FileAccess.get_sha256(runtime_output).to_lower()
	var save_error := composite.save_png(runtime_output)
	if save_error != OK:
		printerr("Could not save runtime output: %s" % error_string(save_error))
		return 2
	var output_sha256 := FileAccess.get_sha256(runtime_output).to_lower()
	var archived_output := archive_dir.path_join("energy_big.png")
	if not _copy_file_byte_identical(runtime_output, archived_output):
		return 2
	if FileAccess.get_sha256(archived_output).to_lower() != output_sha256:
		printerr("Archived output is not byte-identical to runtime output")
		return 3

	var preview_records: Array[Dictionary] = []
	for size in PREVIEW_SIZES:
		var sized := composite.duplicate()
		if size != CANVAS_SIZE.x:
			sized.resize(size, size, Image.INTERPOLATE_LANCZOS)
		for background_name in BACKGROUNDS:
			var preview := Image.create(size, size, false, Image.FORMAT_RGBA8)
			preview.fill(BACKGROUNDS[background_name])
			preview.blend_rect(
				sized,
				Rect2i(Vector2i.ZERO, Vector2i(size, size)),
				Vector2i.ZERO
			)
			var preview_name := "%s-%d.png" % [background_name, size]
			var preview_path := setup_dir.path_join(preview_name)
			if preview.save_png(preview_path) != OK:
				printerr("Could not save SourceOver preview: %s" % preview_path)
				return 2
			preview_records.append({
				"relative_path": "setup-pose-sourceover/" + preview_name,
				"sha256": FileAccess.get_sha256(preview_path).to_lower(),
				"size": [size, size],
				"background": background_name
			})

	var timeline_records := _copy_runtime_timeline(repo_root, timeline_dir)
	if timeline_records.is_empty():
		return 3

	var source_hash_lines := PackedStringArray()
	for record in source_records:
		source_hash_lines.append("%s  %s" % [record.sha256, record.relative_path])
	if not _write_text(
		archive_dir.path_join("source-hashes.sha256"),
		"\n".join(source_hash_lines) + "\n"
	):
		return 2

	var manifest := {
		"asset": "Vivhite energy_big.png",
		"status": "derived_setup_pose_ready_for_visual_review",
		"generated_at_local_date": "2026-08-31",
		"ai_generation": "none",
		"creative_change": "none",
		"operation": (
			"Godot Image.blend_rect standard SourceOver at unchanged 256x256 canvas, "
			+ "setup pose rotation 0, in Layer1 -> Layer2 -> Layer3 -> Layer4 -> Layer5 order"
		),
		"forbidden_operations_confirmed_absent": [
			"crop", "resize of source or runtime output", "threshold", "mask",
			"color key", "Alpha cleanup", "Alpha shrink/expand", "recolor",
			"creative redraw"
		],
		"consumer_evidence": {
			"pool_paths": [
				"Vivhite/VivhiteCode/Characters/VivhiteCardPool.cs:19",
				"Vivhite/VivhiteCode/Characters/VivhiteRelicPool.cs:13",
				"Vivhite/VivhiteCode/Characters/VivhitePotionPool.cs:13"
			],
			"all_pool_big_energy_paths": RUNTIME_OUTPUT_RELATIVE_PATH,
			"ritsulib_contract": (
				"EnergyIconHelper.GetPath(string) is prefix-patched to return the mapped "
				+ "BigEnergyIconPath directly when the pool implements IModBigEnergyIconPool"
			),
			"vanilla_helper_contract": (
				"EnergyIconHelper.GetPath builds images/atlases/ui_atlas.sprites/card/"
				+ "energy_<lowercase>.tres; vanilla Ironclad and Silent regions are 74x74, "
				+ "Defect has a 71x72 region plus margins yielding 74x74 logical size"
			),
			"runtime_audit_contract": (
				"tools/art/audit_vivhite_runtime_art.gd requires energy_big.png to be "
				+ "256x256 native RGBA8 with transparent corners and non-edge-touching Alpha"
			),
			"energy_counter_scene": "Vivhite/Vivhite/scenes/characters/Vivhite_energy_counter.tscn",
			"scene_control_size": [128, 128],
			"source_texture_size": [256, 256],
			"scene_draw_order": ["Layer1", "Layer2", "Layer3", "Layer4", "Layer5"],
			"setup_pose_rotation_degrees": {"Layer2": 0, "Layer3": 0}
		},
		"sources": source_records,
		"runtime_output": {
			"relative_path": RUNTIME_OUTPUT_RELATIVE_PATH,
			"archive_copy": "energy_big.png",
			"previous_sha256": previous_runtime_sha256,
			"sha256": output_sha256,
			"size": [composite.get_width(), composite.get_height()],
			"format": "RGBA8",
			"corner_alpha": output_alpha.corners,
			"alpha_bbox": _rect_to_array(output_alpha.bbox),
			"nonzero_alpha_pixels": output_alpha.nonzero_pixels,
			"opaque_pixels_alpha_ge_250": output_alpha.opaque_pixels
		},
		"setup_pose_sourceover": {
			"background_rgb": {
				"black": "#000000", "white": "#ffffff", "game-indigo": "#182139"
			},
			"sizes": PREVIEW_SIZES,
			"files": preview_records,
			"visual_conclusion": "pending explicit visual inspection"
		},
		"five_layer_runtime_timeline": {
			"source": TIMELINE_SOURCE_RELATIVE_PATH,
			"provenance": "existing five-layer runtime consumer acceptance evidence",
			"time_seconds": [0.0, 0.25, 0.5, 1.0, 2.0, 3.0],
			"rotation_degrees_per_second": {"Layer2": 30.0, "Layer3": 60.0},
			"copy_operation": "byte-identical archive copy; no decode or re-encode",
			"expected_file_count": 60,
			"files": timeline_records
		}
	}
	var manifest_path := archive_dir.path_join("manifest.json")
	if not _write_text(manifest_path, JSON.stringify(manifest, "  ") + "\n"):
		return 2
	print("Derived energy_big.png: %s" % output_sha256)
	print("Archived %d byte-identical runtime timeline files" % timeline_records.size())
	return 0


func _copy_runtime_timeline(repo_root: String, destination_dir: String) -> Array[Dictionary]:
	var source_dir := repo_root.path_join(TIMELINE_SOURCE_RELATIVE_PATH)
	var expected_names := PackedStringArray()
	for time_tag in TIMELINE_TIMES:
		expected_names.append("t%s-actual-128-rgba.png" % time_tag)
		for background in TIMELINE_BACKGROUNDS:
			for size in TIMELINE_SIZES:
				expected_names.append("t%s-%s-%d.png" % [time_tag, background, size])
	if expected_names.size() != 60:
		printerr("Internal timeline contract must contain exactly 60 files")
		return []
	var records: Array[Dictionary] = []
	for file_name in expected_names:
		var source_path := source_dir.path_join(file_name)
		var destination_path := destination_dir.path_join(file_name)
		if not FileAccess.file_exists(source_path):
			printerr("Missing existing runtime timeline evidence: %s" % source_path)
			return []
		if not _copy_file_byte_identical(source_path, destination_path):
			return []
		var source_sha256 := FileAccess.get_sha256(source_path).to_lower()
		var destination_sha256 := FileAccess.get_sha256(destination_path).to_lower()
		if source_sha256 != destination_sha256:
			printerr("Timeline evidence copy changed bytes: %s" % file_name)
			return []
		records.append({
			"file": file_name,
			"sha256": source_sha256,
			"byte_identical": true
		})
	return records


func _copy_file_byte_identical(source_path: String, destination_path: String) -> bool:
	var bytes := FileAccess.get_file_as_bytes(source_path)
	if bytes.is_empty():
		printerr("Could not read file for exact copy: %s" % source_path)
		return false
	var output := FileAccess.open(destination_path, FileAccess.WRITE)
	if output == null:
		printerr("Could not open destination for exact copy: %s" % destination_path)
		return false
	output.store_buffer(bytes)
	output.close()
	return true


func _write_text(path: String, content: String) -> bool:
	var output := FileAccess.open(path, FileAccess.WRITE)
	if output == null:
		printerr("Could not write text file: %s" % path)
		return false
	output.store_string(content)
	output.close()
	return true


func _inspect_alpha(image: Image) -> Dictionary:
	var corners := [
		image.get_pixel(0, 0).a8,
		image.get_pixel(image.get_width() - 1, 0).a8,
		image.get_pixel(0, image.get_height() - 1).a8,
		image.get_pixel(image.get_width() - 1, image.get_height() - 1).a8
	]
	var min_x := image.get_width()
	var min_y := image.get_height()
	var max_x := -1
	var max_y := -1
	var nonzero_pixels := 0
	var opaque_pixels := 0
	for y in image.get_height():
		for x in image.get_width():
			var alpha := image.get_pixel(x, y).a8
			if alpha <= 0:
				continue
			nonzero_pixels += 1
			if alpha >= 250:
				opaque_pixels += 1
			min_x = mini(min_x, x)
			min_y = mini(min_y, y)
			max_x = maxi(max_x, x)
			max_y = maxi(max_y, y)
	var bbox := Rect2i()
	if max_x >= min_x and max_y >= min_y:
		bbox = Rect2i(min_x, min_y, max_x - min_x + 1, max_y - min_y + 1)
	return {
		"corners": corners,
		"bbox": bbox,
		"nonzero_pixels": nonzero_pixels,
		"opaque_pixels": opaque_pixels
	}


func _bbox_touches_edge(rect: Rect2i, canvas_size: Vector2i) -> bool:
	return (
		rect.size.x <= 0
		or rect.size.y <= 0
		or rect.position.x <= 0
		or rect.position.y <= 0
		or rect.end.x >= canvas_size.x
		or rect.end.y >= canvas_size.y
	)


func _rect_to_array(rect: Rect2i) -> Array:
	return [rect.position.x, rect.position.y, rect.size.x, rect.size.y]
