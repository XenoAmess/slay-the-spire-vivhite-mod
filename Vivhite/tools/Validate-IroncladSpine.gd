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
	return parsed as Dictionary


func _mount_base_game_pack() -> bool:
	var pck_path := OS.get_environment("VIVHITE_STS2_PCK_PATH")
	if pck_path.is_empty():
		_errors.append("VIVHITE_STS2_PCK_PATH is required for vanilla skeleton validation.")
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


func _validate_spine_set(
	resource_root: String,
	required_skin: String,
	set_data: Dictionary,
) -> void:
	var set_name := str(set_data.get("name", "<unnamed>"))
	var data_path := _resource_path(resource_root, str(set_data.get("skeletonData", "")))
	var skeleton_path := str(set_data.get("skeletonResource", ""))
	var atlas_path := _resource_path(resource_root, str(set_data.get("atlas", "")))

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
	var animation_names := _names(animations)
	var skin_names := _names(skins)
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

	if not skin_names.has(required_skin):
		_errors.append("Spine set '%s' is missing skin '%s'." % [set_name, required_skin])

	for required in set_data.get("animations", []):
		var required_name := str(required)
		if not animation_names.has(required_name):
			_errors.append("Spine set '%s' is missing animation '%s'." % [set_name, required_name])

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
