extends SceneTree

const CONTRACT_PATH := "res://tools/ironclad-skin.contract.json"

var _errors: Array[String] = []


func _initialize() -> void:
	var contract := _load_contract()
	if contract.is_empty():
		_finish()
		return
	if not _mount_base_game_pack():
		_finish()
		return

	var required_classes: Array[String] = [
		"SpineSkeletonDataResource",
		"SpineSkeletonFileResource",
		"SpineAtlasResource",
	]
	for type_name in required_classes:
		if not ClassDB.class_exists(type_name):
			_errors.append("Game Spine GDExtension did not register class '%s'." % type_name)

	if not _errors.is_empty():
		_finish()
		return

	var resource_root := str(contract.get("resourceRoot", "")).trim_prefix("/").trim_suffix("/")
	for value in contract.get("spineSets", []):
		if typeof(value) != TYPE_DICTIONARY:
			_errors.append("spineSets contains a non-dictionary entry.")
			continue
		_validate_spine_set(
			resource_root,
			str(contract.get("requiredSkin", "default")),
			str(contract.get("requiredPrivateSkeletonExtension", ".spjson")),
			value as Dictionary,
		)

	_finish()


func _load_contract() -> Dictionary:
	if not FileAccess.file_exists(CONTRACT_PATH):
		_errors.append("Contract file does not exist: %s" % CONTRACT_PATH)
		return {}

	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(CONTRACT_PATH))
	if typeof(parsed) != TYPE_DICTIONARY:
		_errors.append("Contract is not valid JSON dictionary: %s" % CONTRACT_PATH)
		return {}
	return _resolve_runtime_layout(parsed as Dictionary)


func _resolve_runtime_layout(contract: Dictionary) -> Dictionary:
	var requested := OS.get_environment("VIVHITE_IRONCLAD_RUNTIME_LAYOUT")
	if requested.is_empty():
		requested = str(contract.get("runtimeLayout", ""))
	var matched_profile: Dictionary = {}
	for value in contract.get("combatRuntimeLayouts", []):
		if typeof(value) == TYPE_DICTIONARY and str(value.get("name", "")) == requested:
			if not matched_profile.is_empty():
				_errors.append("Runtime layout '%s' is declared more than once." % requested)
				return {}
			matched_profile = value as Dictionary
	if matched_profile.is_empty():
		_errors.append("Unknown or missing runtime layout '%s'." % requested)
		return {}

	var page_paths: Array = []
	for value in matched_profile.get("pages", []):
		if typeof(value) != TYPE_DICTIONARY or str(value.get("path", "")).is_empty():
			_errors.append("Runtime layout '%s' contains an invalid combat page." % requested)
			return {}
		page_paths.append(str(value.get("path", "")))
	if page_paths.is_empty():
		_errors.append("Runtime layout '%s' contains no combat pages." % requested)
		return {}

	contract["runtimeLayout"] = requested
	for value in contract.get("spineSets", []):
		if typeof(value) != TYPE_DICTIONARY:
			continue
		var set_data := value as Dictionary
		if str(set_data.get("name", "")) in ["combat", "merchant"]:
			set_data["pages"] = page_paths.duplicate()
	return contract


func _mount_base_game_pack() -> bool:
	var pck_path := OS.get_environment("VIVHITE_STS2_PCK_PATH")
	if pck_path.is_empty():
		_errors.append("VIVHITE_STS2_PCK_PATH is required to load the game's Spine runtime.")
		return false
	if not FileAccess.file_exists(pck_path):
		_errors.append("Base game PCK does not exist: %s" % pck_path)
		return false
	if not ProjectSettings.load_resource_pack(pck_path, false):
		_errors.append("Unable to mount the base game PCK: %s" % pck_path)
		return false
	print("[ironclad-spine] Mounted base game resources without overriding Mod files.")
	return true


func _resource_path(resource_root: String, relative_path: String) -> String:
	return "res://%s/%s" % [resource_root, relative_path.trim_prefix("/")]


func _names(items: Variant) -> Dictionary:
	var result := {}
	if items == null:
		return result
	for item in items:
		if item != null and item.has_method("get_name"):
			result[str(item.call("get_name"))] = true
	return result


func _sorted_names(values: Dictionary) -> Array[String]:
	var result: Array[String] = []
	for value in values.keys():
		result.append(str(value))
	result.sort()
	return result


func _validate_spine_set(
	resource_root: String,
	required_skin: String,
	required_skeleton_extension: String,
	set_data: Dictionary,
) -> void:
	var set_name := str(set_data.get("name", "<unnamed>"))
	var data_path := _resource_path(resource_root, str(set_data.get("skeletonData", "")))
	var skeleton_path := str(set_data.get("skeletonResource", ""))
	var atlas_path := _resource_path(resource_root, str(set_data.get("atlas", "")))
	var private_prefix := "res://%s/" % resource_root

	if not skeleton_path.begins_with(private_prefix):
		_errors.append(
			"Spine set '%s' skeleton must be private below %s; got %s." % [
				set_name,
				private_prefix,
				skeleton_path,
			]
		)
	if not skeleton_path.to_lower().ends_with(required_skeleton_extension.to_lower()):
		_errors.append(
			"Spine set '%s' skeleton must use %s; got %s." % [
				set_name,
				required_skeleton_extension,
				skeleton_path,
			]
		)

	var skeleton: Resource = ResourceLoader.load(skeleton_path)
	if skeleton == null or not skeleton.is_class("SpineSkeletonFileResource"):
		_errors.append("Spine set '%s' cannot load %s as SpineSkeletonFileResource." % [set_name, skeleton_path])

	var atlas: Resource = ResourceLoader.load(atlas_path)
	if atlas == null or not atlas.is_class("SpineAtlasResource"):
		_errors.append("Spine set '%s' cannot load %s as SpineAtlasResource." % [set_name, atlas_path])
	else:
		var textures: Variant = atlas.get("textures")
		var expected_page_count := (set_data.get("pages", []) as Array).size()
		if typeof(textures) != TYPE_ARRAY:
			_errors.append("Spine set '%s' atlas exposes no texture array." % set_name)
		elif textures.size() != expected_page_count:
			_errors.append(
				"Spine set '%s' loaded %d atlas textures; expected %d pages." % [
					set_name,
					textures.size(),
					expected_page_count,
				]
			)
		else:
			for page_index in range(textures.size()):
				if textures[page_index] == null:
					_errors.append("Spine set '%s' atlas texture %d failed to load." % [set_name, page_index])

	var skeleton_data: Resource = ResourceLoader.load(data_path)
	if skeleton_data == null or not skeleton_data.is_class("SpineSkeletonDataResource"):
		_errors.append("Spine set '%s' cannot load %s as SpineSkeletonDataResource." % [set_name, data_path])
		return

	var animations: Variant = skeleton_data.call("get_animations")
	var skins: Variant = skeleton_data.call("get_skins")
	var slots: Variant = skeleton_data.call("get_slots")
	var events: Variant = skeleton_data.call("get_events")
	var bones: Variant = skeleton_data.call("get_bones")
	var animation_names := _names(animations)
	var skin_names := _names(skins)
	var expected_animation_names := {}
	var actual_version := str(skeleton_data.call("get_version"))
	var expected_version := str(set_data.get("expectedSpineVersion", ""))
	if actual_version != expected_version:
		_errors.append(
			"Spine set '%s' uses Spine %s; expected exactly %s." % [
				set_name,
				actual_version,
				expected_version,
			]
		)
	var minimum_bone_count := int(set_data.get("minimumBoneCount", 0))
	if minimum_bone_count > 0 and bones.size() < minimum_bone_count:
		_errors.append(
			"Spine set '%s' has %d bones; expected at least %d." % [
				set_name,
				bones.size(),
				minimum_bone_count,
			]
		)

	if not skin_names.has(required_skin):
		_errors.append("Spine set '%s' is missing skin '%s'." % [set_name, required_skin])

	for required in set_data.get("animations", []):
		var required_name := str(required)
		expected_animation_names[required_name] = true
		if not animation_names.has(required_name):
			_errors.append("Spine set '%s' is missing animation '%s'." % [set_name, required_name])

	var animation_durations: Dictionary = set_data.get("animationDurations", {})
	for animation_name_value in animation_durations:
		var animation_name := str(animation_name_value)
		var animation: Object = skeleton_data.call("find_animation", animation_name)
		if animation == null:
			continue
		var actual_duration := float(animation.call("get_duration"))
		var expected_duration := float(animation_durations[animation_name_value])
		if absf(actual_duration - expected_duration) > 0.00001:
			_errors.append(
				"Spine set '%s' animation '%s' lasts %.7f; expected %.7f." % [
					set_name,
					animation_name,
					actual_duration,
					expected_duration,
				]
			)

	if bool(set_data.get("exactAnimations", false)):
		var expected_names := _sorted_names(expected_animation_names)
		var actual_names := _sorted_names(animation_names)
		if actual_names != expected_names:
			_errors.append(
				"Spine set '%s' must contain exactly animations %s; got %s." % [
					set_name,
					str(expected_names),
					str(actual_names),
				]
			)

	for required in set_data.get("slots", []):
		var required_name := str(required)
		if skeleton_data.call("find_slot", required_name) == null:
			_errors.append("Spine set '%s' is missing slot '%s'." % [set_name, required_name])

	for required in set_data.get("events", []):
		var required_name := str(required)
		if skeleton_data.call("find_event", required_name) == null:
			_errors.append("Spine set '%s' is missing event '%s'." % [set_name, required_name])

	print(
		"[ironclad-spine] %s: version=%s animations=%d skins=%d slots=%d events=%d" % [
			set_name,
			actual_version,
			animations.size(),
			skins.size(),
			slots.size(),
			events.size(),
		]
	)

func _finish() -> void:
	if _errors.is_empty():
		print("[ironclad-spine] Godot Spine contract passed.")
		quit(0)
		return

	for message in _errors:
		push_error("[ironclad-spine] %s" % message)
	quit(1)
