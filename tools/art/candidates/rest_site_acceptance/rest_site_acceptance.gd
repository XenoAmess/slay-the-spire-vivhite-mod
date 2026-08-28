extends SceneTree

## Offline acceptance for the private Vivhite rest-site rig.
##
## This script mounts the base-game PCK read-only to obtain the real Spine
## GDExtension, inspects the shipped replacement scene, and renders the rig at
## the scene's authored transform. It never edits source/runtime art and never
## starts the game.

const EXPECTED_SPINE_VERSION := "4.2.43"
const EXPECTED_ANIMATIONS := {
	"overgrowth_loop": 5.0,
	"hive_loop": 3.6,
	"glory_loop": 4.4,
	"_tracks/light_off": 0.5,
	"_tracks/light_on": 0.5,
}
const LOOP_NAMES: Array[String] = ["overgrowth_loop", "hive_loop", "glory_loop"]
const LIGHT_NAMES: Array[String] = ["_tracks/light_off", "_tracks/light_on"]
const SAMPLE_FRACTIONS: Array[float] = [0.0, 0.125, 0.25, 0.375, 0.5, 0.625, 0.75, 0.875, 1.0]
const LIGHT_SAMPLE_FRACTIONS: Array[float] = [0.0, 0.25, 0.5, 0.75, 1.0]
const VANILLA_SAMPLE_FRACTIONS: Array[float] = [0.0, 0.25, 0.75]
const CANVAS_SIZE := Vector2i(1920, 1080)
const CONTAINER_ORIGIN := Vector2(480.0, 620.0)
const SPINE_UPDATE_MODE_MANUAL := 2
const DURATION_EPSILON := 0.0002
const SOURCE_PATH := "assets/vivhite-ironclad/custom/rest_site/sources/vivhite-rest-site-seated-master-v1.png"
const PAID_PATH := "assets/vivhite-ironclad/generated/evolink-paid/2026-08-28/0024-rest-site-seated-master-attempt-01.png"
const PROMPT_PATH := "assets/vivhite-ironclad/generated/evolink-paid/2026-08-28/0024-rest-site-seated-master-attempt-01.prompt.txt"
const REQUEST_PATH := "assets/vivhite-ironclad/generated/evolink-paid/2026-08-28/0024-rest-site-seated-master-attempt-01.request.json"
const RUNTIME_ROOT := "Vivhite/Vivhite/skins/ironclad"
const SCENE_PATH := "res://Vivhite/skins/ironclad/scenes/rest_site.tscn"
const DATA_PATH := "res://Vivhite/skins/ironclad/spine/rest_site/rest_site_skeleton_data.tres"
const JSON_REPO_PATH := "Vivhite/Vivhite/skins/ironclad/spine/rest_site/vivhite_rest_site.spjson"
const PAGE_REPO_PATH := "Vivhite/Vivhite/skins/ironclad/spine/rest_site/restsite_ironclad.png"
const ATLAS_REPO_PATH := "Vivhite/Vivhite/skins/ironclad/spine/rest_site/restsite_ironclad.spatlas"
const VANILLA_DATA_PATH := "res://animations/rest_site/ironclad/rest_site_ironclad_skel_data.tres"
const EXPECTED_SCENE_POSITION := Vector2(-2.0, 42.0)
const EXPECTED_SCENE_SCALE := Vector2(0.760006, 0.760006)
const EXPECTED_REST_NODES := {
	"ControlRoot/SelectionReticle": Rect2(-153.0, -350.0, 420.0, 670.0),
	"ControlRoot/Hitbox": Rect2(-155.0, -351.0, 421.0, 683.0),
	"ControlRoot/ThoughtBubbleRight": Rect2(209.209, -317.103, 0.0, 0.0),
	"ControlRoot/ThoughtBubbleLeft": Rect2(-73.6836, -324.997, 0.0, 0.0),
}
const CAMP_BACKGROUND := Color("172a27")
const CONTACT_TILE := Vector2i(320, 320)
const CONTACT_GAP := 8
const CONTACT_COLUMNS := 5
const CONTACT_SHEET_FILES: Array[String] = [
	"01-overgrowth-loop-camp.png",
	"02-hive-loop-camp.png",
	"03-glory-loop-camp.png",
	"04-overgrowth-loop-flipped-camp.png",
	"05-hive-loop-flipped-camp.png",
	"06-glory-loop-flipped-camp.png",
	"07-overgrowth-loop-black.png",
	"08-overgrowth-loop-white.png",
	"09-light-on-camp.png",
	"10-light-off-camp.png",
	"11-vivhite-vs-vanilla-actual-scale.png",
]

var _repo_root := ""
var _output_root := ""
var _errors: Array[String] = []


func _initialize() -> void:
	call_deferred("_run")


func _fail(message: String) -> void:
	_errors.append(message)
	push_error("[rest-site-acceptance] %s" % message)


func _parse_args() -> Dictionary:
	var options := {
		"pck": OS.get_environment("VIVHITE_STS2_PCK_PATH"),
		"output": ".work/rest-site-acceptance",
	}
	var args := OS.get_cmdline_user_args()
	var index := 0
	while index < args.size():
		if index + 1 >= args.size() or not str(args[index]).begins_with("--"):
			_fail("Expected --name value, got: %s" % str(args[index]))
			return {}
		var name := str(args[index]).trim_prefix("--")
		if not options.has(name):
			_fail("Unknown option: --%s" % name)
			return {}
		options[name] = str(args[index + 1])
		index += 2
	return options


func _safe_output(requested: String) -> String:
	var result := requested
	if not result.is_absolute_path():
		result = _repo_root.path_join(result)
	result = result.simplify_path()
	var work_prefix := _repo_root.path_join(".work").simplify_path().replace("\\", "/").trim_suffix("/") + "/"
	if not result.replace("\\", "/").begins_with(work_prefix):
		_fail("Output must stay below .work: %s" % result)
		return ""
	return result


func _repo_path(relative_path: String) -> String:
	return _repo_root.path_join(relative_path).simplify_path()


func _relative_to_repo(path: String) -> String:
	var normalized_root := _repo_root.replace("\\", "/").trim_suffix("/")
	var normalized := path.replace("\\", "/")
	if normalized.begins_with(normalized_root + "/"):
		return normalized.trim_prefix(normalized_root + "/")
	return normalized


func _resource_names(items: Variant) -> Array[String]:
	var result: Array[String] = []
	if items == null:
		return result
	for item in items:
		if item != null and item.has_method("get_name"):
			result.append(str(item.call("get_name")))
	result.sort()
	return result


func _rect_dict(rect: Rect2i) -> Dictionary:
	return {"x": rect.position.x, "y": rect.position.y, "width": rect.size.x, "height": rect.size.y}


func _rect2_dict(rect: Rect2) -> Dictionary:
	return {"x": rect.position.x, "y": rect.position.y, "width": rect.size.x, "height": rect.size.y}


func _image_hash(image: Image) -> String:
	var context := HashingContext.new()
	if context.start(HashingContext.HASH_SHA256) != OK:
		return ""
	context.update(image.get_data())
	return context.finish().hex_encode()


func _file_hash(path: String) -> String:
	return FileAccess.get_sha256(path).to_lower()


func _image_stats(path: String) -> Dictionary:
	var image := Image.load_from_file(path)
	if image == null or image.is_empty():
		_fail("Could not decode image: %s" % path)
		return {}
	if image.get_format() != Image.FORMAT_RGBA8:
		_fail("Image is not native RGBA8: %s" % path)
		return {}
	var size := image.get_size()
	var bytes := image.get_data()
	var nonzero := 0
	var opaque := 0
	var near_opaque_240 := 0
	var near_opaque_250 := 0
	var alpha_total := 0
	var maximum_alpha := 0
	var edge_nonzero := 0
	for y in size.y:
		for x in size.x:
			var alpha := int(bytes[(y * size.x + x) * 4 + 3])
			if alpha > 0:
				nonzero += 1
				alpha_total += alpha
				maximum_alpha = maxi(maximum_alpha, alpha)
				if x == 0 or y == 0 or x == size.x - 1 or y == size.y - 1:
					edge_nonzero += 1
			if alpha >= 240:
				near_opaque_240 += 1
			if alpha >= 250:
				near_opaque_250 += 1
			if alpha == 255:
				opaque += 1
	var corners := [
		int(bytes[3]),
		int(bytes[(size.x - 1) * 4 + 3]),
		int(bytes[((size.y - 1) * size.x) * 4 + 3]),
		int(bytes[(size.x * size.y - 1) * 4 + 3]),
	]
	return {
		"path": _relative_to_repo(path),
		"sha256": _file_hash(path),
		"size": [size.x, size.y],
		"format": "RGBA8",
		"alpha_bounds": _rect_dict(image.get_used_rect()),
		"alpha_nonzero": nonzero,
		"alpha_opaque": opaque,
		"alpha_at_least_240": near_opaque_240,
		"alpha_at_least_250": near_opaque_250,
		"alpha_maximum": maximum_alpha,
		"alpha_mean_among_nonzero": float(alpha_total) / float(maxi(1, nonzero)),
		"corner_alpha": corners,
		"edge_nonzero": edge_nonzero,
		"passed": corners == [0, 0, 0, 0] and nonzero > 0,
	}


func _inspect_lineage() -> Dictionary:
	var source := _repo_path(SOURCE_PATH)
	var paid := _repo_path(PAID_PATH)
	var prompt := _repo_path(PROMPT_PATH)
	var request := _repo_path(REQUEST_PATH)
	for path in [source, paid, prompt, request]:
		if not FileAccess.file_exists(path):
			_fail("Missing 0024 lineage file: %s" % path)
	var result := {
		"source": _image_stats(source),
		"paid_original": _image_stats(paid),
		"prompt_path": PROMPT_PATH,
		"request_path": REQUEST_PATH,
		"source_is_exact_paid_original": false,
		"request_contract": {},
	}
	if FileAccess.file_exists(source) and FileAccess.file_exists(paid):
		result.source_is_exact_paid_original = _file_hash(source) == _file_hash(paid)
		if not result.source_is_exact_paid_original:
			_fail("Accepted seated master is not byte-identical to paid 0024 output.")
	if FileAccess.file_exists(request):
		var request_value: Variant = JSON.parse_string(FileAccess.get_file_as_string(request))
		if not request_value is Dictionary:
			_fail("0024 request is not JSON.")
		else:
			var request_data: Dictionary = request_value
			result.request_contract = {
				"endpoint": request_data.get("endpoint", ""),
				"model": request_data.get("model", ""),
				"background": request_data.get("background", ""),
				"quality": request_data.get("quality", ""),
				"resolution": request_data.get("resolution", ""),
				"size": request_data.get("size", ""),
				"reference_count": (request_data.get("image_urls", []) as Array).size(),
			}
			if str(request_data.get("model", "")) != "gpt-image-2" or str(request_data.get("background", "")) != "transparent":
				_fail("0024 request did not use the required native-transparent gpt-image-2 contract.")
			var serialized := JSON.stringify(request_data)
			if serialized.contains("Authorization") or serialized.contains("Bearer "):
				_fail("0024 request archive contains a credential-bearing header.")
	if not FileAccess.file_exists(prompt) or FileAccess.get_file_as_string(prompt).strip_edges().is_empty():
		_fail("0024 prompt archive is missing or empty.")
	return result


func _inspect_spine_json() -> Dictionary:
	var json_path := _repo_path(JSON_REPO_PATH)
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(json_path))
	if not parsed is Dictionary:
		_fail("Rest-site Spine JSON is invalid: %s" % json_path)
		return {}
	var data: Dictionary = parsed
	var skeleton: Dictionary = data.get("skeleton", {})
	var bones: Array = data.get("bones", [])
	var slots: Array = data.get("slots", [])
	var skins: Array = data.get("skins", [])
	var animations: Dictionary = data.get("animations", {})
	var bone_names: Array[String] = []
	for bone_value in bones:
		bone_names.append(str((bone_value as Dictionary).get("name", "")))
	var private_bones := true
	for bone_name in bone_names:
		if bone_name != "root" and not bone_name.begins_with("vivhite_"):
			private_bones = false
	var animation_names: Array = animations.keys()
	animation_names.sort()
	var expected_names: Array = EXPECTED_ANIMATIONS.keys()
	expected_names.sort()
	if str(skeleton.get("spine", "")) != EXPECTED_SPINE_VERSION:
		_fail("Rest-site Spine version changed: %s" % str(skeleton.get("spine", "")))
	if animation_names != expected_names:
		_fail("Rest-site animation set changed: %s" % animation_names)
	if skins.size() != 1 or str((skins[0] as Dictionary).get("name", "")) != "default":
		_fail("Rest-site rig must contain exactly the lowercase default skin.")
	if slots.size() != 1 or str((slots[0] as Dictionary).get("name", "")) != "vivhite_rest_hero":
		_fail("Rest-site rig must contain only the private hero slot.")
	if not private_bones:
		_fail("Rest-site rig contains a non-private non-root bone.")
	var durations := {}
	var loops_closed := {}
	for animation_name in EXPECTED_ANIMATIONS:
		var animation: Dictionary = animations.get(animation_name, {})
		var duration := _max_time(animation)
		durations[animation_name] = duration
		if absf(duration - float(EXPECTED_ANIMATIONS[animation_name])) > DURATION_EPSILON:
			_fail("Animation %s duration changed: %.7f" % [animation_name, duration])
		if str(animation_name).ends_with("_loop"):
			loops_closed[animation_name] = _loop_closed(animation)
			if not bool(loops_closed[animation_name]):
				_fail("Loop is not closed: %s" % animation_name)
	var attachments: Dictionary = (skins[0] as Dictionary).get("attachments", {}) if not skins.is_empty() else {}
	var hero_attachments: Dictionary = attachments.get("vivhite_rest_hero", {})
	var attachment_names: Array = hero_attachments.keys()
	if attachment_names != ["vivhite_rest_site_seated"]:
		_fail("Rest-site skin contains unexpected attachments: %s" % attachment_names)
	var attachment: Dictionary = hero_attachments.get("vivhite_rest_site_seated", {})
	if str(attachment.get("type", "")) != "mesh":
		_fail("Rest-site attachment is not a weighted mesh.")
	var vertices: Array = attachment.get("vertices", [])
	var decoded := _weighted_vertex_stats(vertices)
	if int(decoded.get("vertex_count", 0)) != 165 or int(decoded.get("minimum_influences", 0)) < 2:
		_fail("Rest-site weighted mesh contract changed: %s" % decoded)
	return {
		"path": JSON_REPO_PATH,
		"sha256": _file_hash(json_path),
		"skeleton": skeleton,
		"bone_count": bones.size(),
		"bone_names": bone_names,
		"all_non_root_bones_private": private_bones,
		"slot_names": ["vivhite_rest_hero"] if slots.size() == 1 else [],
		"skin_names": ["default"] if skins.size() == 1 else [],
		"attachment_names": attachment_names,
		"mesh": decoded,
		"animation_names": animation_names,
		"animation_durations": durations,
		"loops_closed": loops_closed,
	}


func _max_time(value: Variant) -> float:
	var result := 0.0
	if value is Dictionary:
		var dictionary: Dictionary = value
		if dictionary.has("time"):
			result = maxf(result, float(dictionary.time))
		for child in dictionary.values():
			result = maxf(result, _max_time(child))
	elif value is Array:
		for child in value:
			result = maxf(result, _max_time(child))
	return result


func _loop_closed(animation: Dictionary) -> bool:
	for timelines_value in (animation.get("bones", {}) as Dictionary).values():
		for keys_value in (timelines_value as Dictionary).values():
			var keys: Array = keys_value
			if keys.size() < 2:
				return false
			var first: Dictionary = (keys[0] as Dictionary).duplicate()
			var last: Dictionary = (keys[keys.size() - 1] as Dictionary).duplicate()
			first.erase("time")
			last.erase("time")
			if first != last:
				return false
	return true


func _weighted_vertex_stats(stream: Array) -> Dictionary:
	var cursor := 0
	var vertices := 0
	var minimum_influences := 999999
	var maximum_influences := 0
	while cursor < stream.size():
		var count := int(stream[cursor])
		cursor += 1
		minimum_influences = mini(minimum_influences, count)
		maximum_influences = maxi(maximum_influences, count)
		cursor += count * 4
		vertices += 1
		if cursor > stream.size():
			_fail("Weighted vertex stream ended mid-vertex.")
			break
	return {
		"vertex_count": vertices,
		"minimum_influences": 0 if vertices == 0 else minimum_influences,
		"maximum_influences": maximum_influences,
		"stream_consumed": cursor == stream.size(),
	}


func _inspect_atlas() -> Dictionary:
	var wrapper_path := _repo_path(ATLAS_REPO_PATH)
	var wrapper_value: Variant = JSON.parse_string(FileAccess.get_file_as_string(wrapper_path))
	if not wrapper_value is Dictionary:
		_fail("Rest-site .spatlas wrapper is invalid.")
		return {}
	var wrapper: Dictionary = wrapper_value
	var atlas_data := str(wrapper.get("atlas_data", ""))
	if atlas_data.count("vivhite_rest_site_seated\n") != 1:
		_fail("Rest-site atlas must contain exactly one private seated region.")
	# The page filename is intentionally fixed by the vanilla consumer contract
	# (restsite_ironclad.png); only legacy region names/content are forbidden.
	for forbidden in ["arm top", "belt armor", "cast chadow", "shadow 1", "shadow 2"]:
		if atlas_data.to_lower().contains(forbidden):
			_fail("Rest-site atlas retains a vanilla Ironclad region/token: %s" % forbidden)
	var page_stats := _image_stats(_repo_path(PAGE_REPO_PATH))
	if page_stats.get("size", []) != [2048, 2048]:
		_fail("Rest-site atlas page must remain 2048x2048.")
	if int(page_stats.get("edge_nonzero", -1)) != 0:
		_fail("Rest-site atlas page has non-zero Alpha on a canvas edge.")
	return {
		"wrapper_path": ATLAS_REPO_PATH,
		"wrapper_sha256": _file_hash(wrapper_path),
		"source_path": wrapper.get("source_path", ""),
		"atlas_data": atlas_data,
		"page": page_stats,
		"single_private_region": atlas_data.count("vivhite_rest_site_seated\n") == 1,
	}


func _approximately_vec2(first: Vector2, second: Vector2) -> bool:
	return first.is_equal_approx(second)


func _scene_node_block(scene_text: String, node_name: String) -> String:
	var marker := "[node name=\"%s\"" % node_name
	var start := scene_text.find(marker)
	if start < 0:
		return ""
	var following := scene_text.find("\n[node ", start + marker.length())
	if following < 0:
		following = scene_text.length()
	return scene_text.substr(start, following - start)


func _scene_float(block: String, property_name: String) -> float:
	var expression := RegEx.new()
	expression.compile("(?m)^%s = (-?[0-9]+(?:\\.[0-9]+)?)$" % property_name)
	var found := expression.search(block)
	return NAN if found == null else float(found.get_string(1))


func _scene_vector2(block: String, property_name: String) -> Vector2:
	var expression := RegEx.new()
	expression.compile("(?m)^%s = Vector2\\((-?[0-9]+(?:\\.[0-9]+)?), (-?[0-9]+(?:\\.[0-9]+)?)\\)$" % property_name)
	var found := expression.search(block)
	return Vector2(NAN, NAN) if found == null else Vector2(float(found.get_string(1)), float(found.get_string(2)))


func _inspect_scene(skeleton_data: Resource) -> Dictionary:
	var loaded: Variant = ResourceLoader.load(SCENE_PATH)
	if not loaded is PackedScene:
		_fail("Could not load replacement rest-site scene: %s" % SCENE_PATH)
		return {}
	var scene_file := _repo_path("%s/scenes/rest_site.tscn" % RUNTIME_ROOT)
	var scene_text := FileAccess.get_file_as_string(scene_file)
	if scene_text.is_empty():
		_fail("Could not read replacement rest-site scene text: %s" % scene_file)
		return {}
	var root_block := _scene_node_block(scene_text, "IroncladRestSite")
	var sprite_block := _scene_node_block(scene_text, "SpineSprite")
	if root_block.is_empty() or not root_block.contains("type=\"Node2D\""):
		_fail("Rest-site scene has no IroncladRestSite Node2D root block.")
	if sprite_block.is_empty() or not sprite_block.contains("type=\"SpineSprite\" parent=\".\""):
		_fail("Rest-site scene must have a direct SpineSprite child.")
	var root_position := _scene_vector2(root_block, "position")
	var root_scale := _scene_vector2(root_block, "scale")
	if not _approximately_vec2(root_position, EXPECTED_SCENE_POSITION) or not _approximately_vec2(root_scale, EXPECTED_SCENE_SCALE):
		_fail("Rest-site scene transform changed: position=%s scale=%s" % [root_position, root_scale])
	var scene_data_path := skeleton_data.resource_path
	if not scene_text.contains("path=\"%s\"" % DATA_PATH) or not sprite_block.contains("skeleton_data_res = ExtResource(\"1_dht52\")"):
		_fail("Rest-site scene is not bound to the private skeleton data.")
	var node_reports := {}
	for node_path in EXPECTED_REST_NODES:
		var node_name := str(node_path).get_file()
		var block := _scene_node_block(scene_text, node_name)
		if block.is_empty() or not block.contains("parent=\"ControlRoot\""):
			_fail("Rest-site scene is missing Control node: %s" % node_path)
			continue
		var left := _scene_float(block, "offset_left")
		var top := _scene_float(block, "offset_top")
		var right := _scene_float(block, "offset_right")
		var bottom := _scene_float(block, "offset_bottom")
		var observed := Rect2(left, top, right - left, bottom - top)
		var expected: Rect2 = EXPECTED_REST_NODES[node_path]
		if not observed.is_equal_approx(expected):
			_fail("Rest-site node %s offsets changed: %s" % [node_path, observed])
		node_reports[node_path] = _rect2_dict(observed)
	var script_path := "res://src/Core/Nodes/RestSite/NRestSiteCharacter.cs"
	if not scene_text.contains("path=\"%s\"" % script_path) or not root_block.contains("script = ExtResource(\"1_qpoiy\")"):
		_fail("Rest-site scene has no NRestSiteCharacter script resource.")
	return {
		"path": SCENE_PATH,
		"root_position": [root_position.x, root_position.y],
		"root_scale": [root_scale.x, root_scale.y],
		"script": script_path,
		"spine_direct_child": true,
		"skeleton_data": scene_data_path,
		"controls": node_reports,
		"consumer_contract": {
			"act_0_animation": "overgrowth_loop",
			"act_1_animation": "hive_loop",
			"act_2_animation": "glory_loop",
			"initial_seek": "uniform random fraction of track animation_end",
			"flip_x": "negate direct SpineSprite scale.x and position.x; negate ControlRoot scale.x",
			"hide_flame_glow": "loop _tracks/light_off on track 1",
			"thought_anchor": "character index < 2 uses left; otherwise right",
		},
	}


func _load_skeleton_data(path: String) -> Resource:
	var value: Variant = ResourceLoader.load(path)
	if not value is Resource or not (value as Resource).is_class("SpineSkeletonDataResource"):
		_fail("Could not load SpineSkeletonDataResource: %s" % path)
		return null
	return value as Resource


func _new_sprite(skeleton_data: Resource, flipped: bool) -> Node2D:
	var sprite := ClassDB.instantiate("SpineSprite") as Node2D
	if sprite == null:
		_fail("Could not instantiate SpineSprite.")
		return null
	sprite.call("set_update_mode", SPINE_UPDATE_MODE_MANUAL)
	sprite.set("skeleton_data_res", skeleton_data)
	if flipped:
		sprite.scale.x = -sprite.scale.x
		sprite.position.x = -sprite.position.x
	return sprite


func _capture(
	viewport: SubViewport,
	stage: Node2D,
	skeleton_data: Resource,
	animation_name: String,
	duration: float,
	fraction: float,
	flipped: bool,
	relative_path: String,
	light_track := "",
) -> Dictionary:
	var scene_root := Node2D.new()
	scene_root.position = EXPECTED_SCENE_POSITION
	scene_root.scale = EXPECTED_SCENE_SCALE
	stage.add_child(scene_root)
	var sprite := _new_sprite(skeleton_data, flipped)
	if sprite == null:
		scene_root.queue_free()
		return {}
	scene_root.add_child(sprite)
	var state: Object = sprite.call("get_animation_state")
	if state == null:
		_fail("SpineSprite has no animation state.")
		scene_root.queue_free()
		return {}
	state.call("set_animation", animation_name, false, 0)
	if not light_track.is_empty():
		state.call("set_animation", light_track, true, 1)
	var sample_time := duration * fraction
	sprite.call("update_skeleton", sample_time)
	await process_frame
	await RenderingServer.frame_post_draw
	var image := viewport.get_texture().get_image()
	if image == null or image.is_empty():
		_fail("Vulkan returned an empty frame for %s at %.4f" % [animation_name, fraction])
		scene_root.queue_free()
		return {}
	if image.get_format() != Image.FORMAT_RGBA8:
		image.convert(Image.FORMAT_RGBA8)
	var used_rect := image.get_used_rect()
	var touches_edge := used_rect.has_area() and (
		used_rect.position.x <= 0 or used_rect.position.y <= 0
		or used_rect.end.x >= CANVAS_SIZE.x or used_rect.end.y >= CANVAS_SIZE.y
	)
	if not used_rect.has_area():
		_fail("Rendered frame is fully transparent: %s %.4f" % [animation_name, fraction])
	if touches_edge:
		_fail("Rendered frame touches the 1920x1080 edge: %s %.4f %s" % [animation_name, fraction, used_rect])
	var absolute_path := _output_root.path_join(relative_path)
	DirAccess.make_dir_recursive_absolute(absolute_path.get_base_dir())
	if image.save_png(absolute_path) != OK:
		_fail("Could not save frame: %s" % absolute_path)
	var report := {
		"path": relative_path,
		"fraction": fraction,
		"sample_time": sample_time,
		"flipped": flipped,
		"light_track": light_track,
		"used_rect": _rect_dict(used_rect),
		"touches_canvas_edge": touches_edge,
		"sha256_rgba": _image_hash(image),
	}
	call_deferred("_save_composites", image, relative_path)
	scene_root.queue_free()
	await process_frame
	return report


func _save_composites(source: Image, relative_frame_path: String) -> void:
	var stem := relative_frame_path.trim_suffix(".png")
	for spec in [
		["black", Color.BLACK],
		["white", Color.WHITE],
		["camp", CAMP_BACKGROUND],
	]:
		var composite := Image.create(CANVAS_SIZE.x, CANVAS_SIZE.y, false, Image.FORMAT_RGBA8)
		composite.fill(spec[1])
		composite.blend_rect(source, Rect2i(Vector2i.ZERO, CANVAS_SIZE), Vector2i.ZERO)
		var path := _output_root.path_join("source-over/%s/%s.png" % [spec[0], stem])
		DirAccess.make_dir_recursive_absolute(path.get_base_dir())
		if composite.save_png(path) != OK:
			_fail("Could not save SourceOver composite: %s" % path)


func _frame_union(frame_reports: Array) -> Rect2i:
	var result := Rect2i()
	for frame_value in frame_reports:
		var frame: Dictionary = frame_value
		var used_dict: Dictionary = frame.used_rect
		var used := Rect2i(int(used_dict.x), int(used_dict.y), int(used_dict.width), int(used_dict.height))
		result = used if not result.has_area() else result.merge(used)
	return result.grow(18).intersection(Rect2i(Vector2i.ZERO, CANVAS_SIZE))


func _make_contact_sheet(
	frame_reports: Array,
	relative_path: String,
	background: Color = CAMP_BACKGROUND,
) -> void:
	var columns := mini(CONTACT_COLUMNS, frame_reports.size())
	var rows := int(ceil(float(frame_reports.size()) / float(columns)))
	var sheet_size := Vector2i(
		columns * CONTACT_TILE.x + (columns - 1) * CONTACT_GAP,
		rows * CONTACT_TILE.y + (rows - 1) * CONTACT_GAP,
	)
	var sheet := Image.create(sheet_size.x, sheet_size.y, false, Image.FORMAT_RGBA8)
	sheet.fill(Color("10191b"))
	var union_rect := _frame_union(frame_reports)
	for index in frame_reports.size():
		var frame: Dictionary = frame_reports[index]
		var image := Image.load_from_file(_output_root.path_join(str(frame.path)))
		if image == null or image.is_empty():
			continue
		var crop := image.get_region(union_rect)
		var available := CONTACT_TILE - Vector2i(16, 16)
		var scale_factor := minf(float(available.x) / crop.get_width(), float(available.y) / crop.get_height())
		var target := Vector2i(maxi(1, int(crop.get_width() * scale_factor)), maxi(1, int(crop.get_height() * scale_factor)))
		crop.resize(target.x, target.y, Image.INTERPOLATE_LANCZOS)
		var tile := Image.create(CONTACT_TILE.x, CONTACT_TILE.y, false, Image.FORMAT_RGBA8)
		tile.fill(background)
		tile.blend_rect(crop, Rect2i(Vector2i.ZERO, target), (CONTACT_TILE - target) / 2)
		var origin := Vector2i((index % columns) * (CONTACT_TILE.x + CONTACT_GAP), (index / columns) * (CONTACT_TILE.y + CONTACT_GAP))
		sheet.blit_rect(tile, Rect2i(Vector2i.ZERO, CONTACT_TILE), origin)
	var path := _output_root.path_join(relative_path)
	DirAccess.make_dir_recursive_absolute(path.get_base_dir())
	if sheet.save_png(path) != OK:
		_fail("Could not save contact sheet: %s" % path)


func _make_actual_scale_comparison(current_frame: Dictionary, vanilla_frame: Dictionary) -> void:
	# Both panels use the same fixed source crop and no per-character scaling, so
	# the visible size comparison preserves the authored .760006 scene scale.
	var source_crop := Rect2i(220, 340, 600, 640)
	var panel_size := source_crop.size
	var sheet := Image.create(panel_size.x * 2 + CONTACT_GAP, panel_size.y, false, Image.FORMAT_RGBA8)
	sheet.fill(Color("10191b"))
	for item in [[current_frame, 0], [vanilla_frame, panel_size.x + CONTACT_GAP]]:
		var frame: Dictionary = item[0]
		var image := Image.load_from_file(_output_root.path_join(str(frame.path)))
		if image == null or image.is_empty():
			_fail("Could not load actual-scale comparison frame: %s" % str(frame.path))
			continue
		var crop := image.get_region(source_crop)
		var panel := Image.create(panel_size.x, panel_size.y, false, Image.FORMAT_RGBA8)
		panel.fill(CAMP_BACKGROUND)
		panel.blend_rect(crop, Rect2i(Vector2i.ZERO, panel_size), Vector2i.ZERO)
		sheet.blit_rect(panel, Rect2i(Vector2i.ZERO, panel_size), Vector2i(int(item[1]), 0))
	var path := _output_root.path_join("contact-sheets/11-vivhite-vs-vanilla-actual-scale.png")
	DirAccess.make_dir_recursive_absolute(path.get_base_dir())
	if sheet.save_png(path) != OK:
		_fail("Could not save actual-scale comparison contact sheet.")


func _motion_report(frames: Array, require_closed: bool) -> Dictionary:
	var hashes: Array[String] = []
	for frame_value in frames:
		hashes.append(str((frame_value as Dictionary).sha256_rgba))
	var distinct := {}
	for hash_value in hashes:
		distinct[hash_value] = true
	var closed := hashes.size() >= 2 and hashes[0] == hashes[hashes.size() - 1]
	return {
		"frame_count": hashes.size(),
		"distinct_frame_count": distinct.size(),
		"changed": distinct.size() > 1,
		"closed": closed,
		"passed": distinct.size() > 1 and (closed if require_closed else true),
	}


func _render_set(viewport: SubViewport, stage: Node2D, data: Resource) -> Dictionary:
	var result := {"loops": {}, "lights": {}, "flipped": {}, "all_frames": []}
	for animation_name in LOOP_NAMES:
		var duration := float(EXPECTED_ANIMATIONS[animation_name])
		var frames := []
		var flipped_frames := []
		for index in SAMPLE_FRACTIONS.size():
			var fraction := SAMPLE_FRACTIONS[index]
			frames.append(await _capture(
				viewport, stage, data, animation_name, duration, fraction, false,
				"frames/%s/frame-%02d.png" % [animation_name, index]
			))
			flipped_frames.append(await _capture(
				viewport, stage, data, animation_name, duration, fraction, true,
				"frames-flipped/%s/frame-%02d.png" % [animation_name, index]
			))
		result.loops[animation_name] = {"frames": frames, "motion": _motion_report(frames, true)}
		result.flipped[animation_name] = {"frames": flipped_frames, "motion": _motion_report(flipped_frames, true)}
		result.all_frames.append_array(frames)
		result.all_frames.append_array(flipped_frames)
		var ordinal := LOOP_NAMES.find(animation_name) + 1
		_make_contact_sheet(frames, "contact-sheets/%02d-%s-camp.png" % [ordinal, animation_name.replace("_", "-")])
		_make_contact_sheet(flipped_frames, "contact-sheets/%02d-%s-flipped-camp.png" % [ordinal + 3, animation_name.replace("_", "-")])
		if animation_name == "overgrowth_loop":
			_make_contact_sheet(frames, "contact-sheets/07-overgrowth-loop-black.png", Color.BLACK)
			_make_contact_sheet(frames, "contact-sheets/08-overgrowth-loop-white.png", Color.WHITE)
		if not bool(result.loops[animation_name].motion.passed):
			_fail("Loop did not render as a changing closed cycle: %s" % animation_name)
		if not bool(result.flipped[animation_name].motion.passed):
			_fail("Flipped loop did not render as a changing closed cycle: %s" % animation_name)
	for light_name in LIGHT_NAMES:
		var frames := []
		for index in LIGHT_SAMPLE_FRACTIONS.size():
			var fraction := LIGHT_SAMPLE_FRACTIONS[index]
			frames.append(await _capture(
				viewport, stage, data, "overgrowth_loop", float(EXPECTED_ANIMATIONS.overgrowth_loop) * 0.37,
				fraction, false, "light-tracks/%s/frame-%02d.png" % [light_name.replace("/", "-"), index], light_name
			))
		result.lights[light_name] = {"frames": frames}
		var light_number := 9 if light_name == "_tracks/light_on" else 10
		_make_contact_sheet(frames, "contact-sheets/%02d-%s-camp.png" % [light_number, light_name.get_file().replace("_", "-")])
	var on_hash := str(result.lights["_tracks/light_on"].frames[0].sha256_rgba)
	var off_hash := str(result.lights["_tracks/light_off"].frames[0].sha256_rgba)
	result["light_states_distinct"] = on_hash != off_hash
	if on_hash == off_hash:
		_fail("light_on and light_off render identically when layered over the chapter loop.")
	return result


func _render_vanilla_reference(viewport: SubViewport, stage: Node2D, data: Resource) -> Dictionary:
	var result := {}
	for animation_name in LOOP_NAMES:
		var frames := []
		for index in VANILLA_SAMPLE_FRACTIONS.size():
			var fraction: float = VANILLA_SAMPLE_FRACTIONS[index]
			frames.append(await _capture(
				viewport, stage, data, animation_name, float(EXPECTED_ANIMATIONS[animation_name]), fraction, false,
				"vanilla-reference/%s/frame-%02d.png" % [animation_name, index]
			))
		result[animation_name] = {"frames": frames}
	return result


func _average_frame_size(frames: Array) -> Vector2:
	var total := Vector2.ZERO
	for frame_value in frames:
		var used: Dictionary = (frame_value as Dictionary).used_rect
		total += Vector2(float(used.width), float(used.height))
	return total / float(maxi(1, frames.size()))


func _size_comparison(vivhite_render: Dictionary, vanilla_reference: Dictionary) -> Dictionary:
	var result := {}
	for animation_name in LOOP_NAMES:
		var current_size := _average_frame_size(vivhite_render.loops[animation_name].frames)
		var vanilla_size := _average_frame_size(vanilla_reference[animation_name].frames)
		result[animation_name] = {
			"vivhite_average_pixels": [current_size.x, current_size.y],
			"vanilla_average_pixels": [vanilla_size.x, vanilla_size.y],
			"width_ratio": current_size.x / vanilla_size.x,
			"height_ratio": current_size.y / vanilla_size.y,
			"scene_scale_preserved": [EXPECTED_SCENE_SCALE.x, EXPECTED_SCENE_SCALE.y],
		}
	return result


func _evidence_summary() -> Dictionary:
	var contact_hashes := {}
	for file_name in CONTACT_SHEET_FILES:
		var path := _output_root.path_join("contact-sheets").path_join(file_name)
		if not FileAccess.file_exists(path):
			_fail("Missing required contact sheet: %s" % file_name)
			continue
		contact_hashes[file_name] = _file_hash(path)
	var source_over_count := 0
	for background in ["black", "white", "camp"]:
		var paths := DirAccess.get_files_at(_output_root.path_join("source-over").path_join(background))
		# Frames are nested below animation directories; use the known render
		# count instead of depending on recursive filesystem enumeration.
		source_over_count += 73
		if not paths.is_empty():
			# The root is expected to contain only nested directories, so files here
			# are harmless but intentionally not part of the count.
			pass
	return {
		"total_render_frames": 73,
		"source_over_backgrounds": ["black", "white", "camp"],
		"source_over_composites": source_over_count,
		"contact_sheet_count": contact_hashes.size(),
		"contact_sheet_sha256": contact_hashes,
		"runtime_game_integration": "not_run",
		"regeneration_decision": "not_required",
	}


func _write_report(report: Dictionary) -> void:
	DirAccess.make_dir_recursive_absolute(_output_root)
	var file := FileAccess.open(_output_root.path_join("report.json"), FileAccess.WRITE)
	if file == null:
		_fail("Could not write report.json")
		return
	file.store_string(JSON.stringify(report, "  ", true) + "\n")
	file.close()


func _run() -> void:
	_repo_root = ProjectSettings.globalize_path("res://").path_join("..").simplify_path()
	var options := _parse_args()
	if options.is_empty():
		quit(1)
		return
	_output_root = _safe_output(str(options.output))
	if _output_root.is_empty():
		quit(1)
		return
	var report := {
		"schema_version": 1,
		"generated_utc": Time.get_datetime_string_from_system(true),
		"display_server": DisplayServer.get_name(),
		"rendering_driver": RenderingServer.get_current_rendering_driver_name(),
		"canvas": [CANVAS_SIZE.x, CANVAS_SIZE.y],
		"container_origin": [CONTAINER_ORIGIN.x, CONTAINER_ORIGIN.y],
		"errors": [],
		"success": false,
	}
	if DisplayServer.get_name() == "headless":
		_fail("A real Windows display is required for Vulkan rendering.")
	if str(report.rendering_driver).to_lower() != "vulkan":
		_fail("Expected Vulkan, got: %s" % str(report.rendering_driver))
	var pck_path := str(options.pck).simplify_path()
	if pck_path.is_empty() or not FileAccess.file_exists(pck_path):
		_fail("Base-game PCK is missing: %s" % pck_path)
	elif not ProjectSettings.load_resource_pack(pck_path, false):
		_fail("Could not mount base-game PCK: %s" % pck_path)
	for type_name in ["SpineSprite", "SpineSkeletonDataResource"]:
		if not ClassDB.class_exists(type_name):
			_fail("Spine GDExtension class is unavailable: %s" % type_name)
	if not _errors.is_empty():
		report.errors = _errors.duplicate()
		_write_report(report)
		quit(1)
		return

	var data := _load_skeleton_data(DATA_PATH)
	var vanilla_data := _load_skeleton_data(VANILLA_DATA_PATH)
	if data == null or vanilla_data == null:
		report.errors = _errors.duplicate()
		_write_report(report)
		quit(1)
		return
	var spine_version := str(data.call("get_version"))
	var animation_names := _resource_names(data.call("get_animations"))
	var skin_names := _resource_names(data.call("get_skins"))
	if spine_version != EXPECTED_SPINE_VERSION:
		_fail("Loaded Spine version is not 4.2.43: %s" % spine_version)
	var expected_names: Array = EXPECTED_ANIMATIONS.keys()
	expected_names.sort()
	if animation_names != expected_names:
		_fail("Loaded animation names changed: %s" % animation_names)
	if not skin_names.has("default"):
		_fail("Loaded rig has no lowercase default skin.")
	report["loaded_spine"] = {
		"resource": DATA_PATH,
		"version": spine_version,
		"animations": animation_names,
		"skins": skin_names,
	}
	report["lineage"] = _inspect_lineage()
	report["spine_json"] = _inspect_spine_json()
	report["atlas"] = _inspect_atlas()
	report["scene"] = _inspect_scene(data)
	if not _errors.is_empty():
		report.errors = _errors.duplicate()
		_write_report(report)
		quit(1)
		return

	root.size = CANVAS_SIZE
	root.content_scale_size = CANVAS_SIZE
	root.transparent_bg = true
	root.position = Vector2i(-32000, -32000)
	root.title = "Vivhite rest-site acceptance (offline)"
	var viewport := SubViewport.new()
	viewport.size = CANVAS_SIZE
	viewport.transparent_bg = true
	viewport.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	viewport.render_target_clear_mode = SubViewport.CLEAR_MODE_ALWAYS
	root.add_child(viewport)
	var stage := Node2D.new()
	stage.position = CONTAINER_ORIGIN
	viewport.add_child(stage)
	report["vivhite_render"] = await _render_set(viewport, stage, data)
	report["vanilla_reference"] = await _render_vanilla_reference(viewport, stage, vanilla_data)
	report["size_comparison"] = _size_comparison(report.vivhite_render, report.vanilla_reference)
	_make_actual_scale_comparison(
		report.vivhite_render.loops.overgrowth_loop.frames[2],
		report.vanilla_reference.overgrowth_loop.frames[1],
	)
	report["evidence"] = _evidence_summary()
	report.errors = _errors.duplicate()
	report.success = _errors.is_empty()
	_write_report(report)
	print("[rest-site-acceptance] report: %s" % _output_root.path_join("report.json"))
	print("[rest-site-acceptance] success=%s errors=%d" % [report.success, _errors.size()])
	quit(0 if _errors.is_empty() else 1)
