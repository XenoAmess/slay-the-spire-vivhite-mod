extends SceneTree


func _initialize() -> void:
	var args := OS.get_cmdline_user_args()
	if args.size() != 2:
		printerr("usage: resolve_scene_uid.gd <game-pck> <uid-text>")
		quit(2)
		return
	if not ProjectSettings.load_resource_pack(args[0], true):
		printerr("could not mount game PCK")
		quit(3)
		return
	var resource_id := ResourceUID.text_to_id(args[1])
	print(JSON.stringify({
		"uid": args[1],
		"numeric_id": resource_id,
		"path": ResourceUID.get_id_path(resource_id),
	}))
	quit(0)
