extends SceneTree

const PATHS := [
	"res://images/ui/transitions/ironclad_transition.png",
	"res://images/ui/transitions/silent_transition.png",
	"res://images/ui/transitions/necrobinder_transition.png",
]


func _initialize() -> void:
	var args := OS.get_cmdline_user_args()
	if args.size() != 2:
		printerr("usage: extract_transition_references.gd <game-pck> <output-directory>")
		quit(2)
		return
	if not ProjectSettings.load_resource_pack(args[0], true):
		printerr("could not mount game PCK: %s" % args[0])
		quit(3)
		return
	DirAccess.make_dir_recursive_absolute(args[1])
	for path in PATHS:
		var texture := ResourceLoader.load(path, "Texture2D", ResourceLoader.CACHE_MODE_IGNORE) as Texture2D
		if texture == null:
			printerr("could not load transition: %s" % path)
			quit(4)
			return
		var image := texture.get_image()
		if image.is_compressed() and image.decompress() != OK:
			printerr("could not decompress transition: %s" % path)
			quit(5)
			return
		var output_path := args[1].path_join(path.get_file())
		if image.save_png(output_path) != OK:
			printerr("could not save transition: %s" % output_path)
			quit(6)
			return
	print("[PASS] extracted %d transition references" % PATHS.size())
	quit(0)
