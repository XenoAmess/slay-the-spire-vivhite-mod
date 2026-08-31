extends SceneTree


func _initialize() -> void:
	var options := _parse_options(OS.get_cmdline_user_args())
	var pck_path := str(options.get("pck", ""))
	var scene_path := str(options.get("scene", ""))
	var output_path := str(options.get("out", ""))
	if pck_path.is_empty() or scene_path.is_empty() or output_path.is_empty():
		printerr("usage: --pck <SlayTheSpire2.pck> --scene <candidate.tscn> --out <report.json>")
		quit(2)
		return
	if not ProjectSettings.load_resource_pack(pck_path, false):
		printerr("failed to mount base-game PCK: %s" % pck_path)
		quit(3)
		return

	var resource := ResourceLoader.load(scene_path, "PackedScene", ResourceLoader.CACHE_MODE_IGNORE)
	if resource == null or not (resource is PackedScene):
		printerr("candidate did not load as PackedScene: %s" % scene_path)
		quit(4)
		return
	var root := (resource as PackedScene).instantiate(PackedScene.GEN_EDIT_STATE_DISABLED)
	if root == null:
		printerr("candidate scene failed to instantiate")
		quit(5)
		return

	var expected_nodes := {
		"Trails/OuterTrail": "Line2D",
		"Trails/InnerTrail": "Line2D",
		"Sprites/BigSparks": "CPUParticles2D",
		"Sprites/LittleSparks": "CPUParticles2D",
		"Sprites/Sprite2D2": "Sprite2D",
		"Sprites/Sprite2D3": "Sprite2D",
	}
	var nodes := []
	var accepted: bool = root.name == "CardTrailVivhite" and root.show_behind_parent
	for node_path in expected_nodes:
		var node := root.get_node_or_null(NodePath(node_path))
		var valid := node != null and node.is_class(expected_nodes[node_path])
		nodes.append({
			"path": node_path,
			"expected_class": expected_nodes[node_path],
			"actual_class": node.get_class() if node != null else null,
			"valid": valid,
		})
		accepted = accepted and valid

	var outer := root.get_node_or_null(NodePath("Trails/OuterTrail")) as Line2D
	var inner := root.get_node_or_null(NodePath("Trails/InnerTrail")) as Line2D
	var big := root.get_node_or_null(NodePath("Sprites/BigSparks")) as CPUParticles2D
	var little := root.get_node_or_null(NodePath("Sprites/LittleSparks")) as CPUParticles2D
	var primary := root.get_node_or_null(NodePath("Sprites/Sprite2D2")) as Sprite2D
	var secondary := root.get_node_or_null(NodePath("Sprites/Sprite2D3")) as Sprite2D
	accepted = accepted and outer != null and inner != null and big != null and little != null
	accepted = accepted and primary != null and secondary != null

	var big_texture_path := ""
	var big_texture_size := [0, 0]
	if big != null and big.texture != null:
		big_texture_path = big.texture.resource_path
		big_texture_size = [big.texture.get_width(), big.texture.get_height()]
	accepted = accepted and big_texture_path == "res://Vivhite/images/vfx/vivhite_card_trail_mathematical_star_0194.png"
	accepted = accepted and big_texture_size == [256, 256]
	accepted = accepted and outer.width == 84.0 and inner.width == 48.0
	accepted = accepted and big.amount == 36 and little.amount == 64

	var report := {
		"schema": "vivhite.card-trail-scene-contract/v1",
		"base_pck": pck_path,
		"scene": scene_path,
		"root": root.name,
		"show_behind_parent": root.show_behind_parent,
		"nodes": nodes,
		"outer_width": outer.width if outer != null else null,
		"inner_width": inner.width if inner != null else null,
		"big_sparks_amount": big.amount if big != null else null,
		"little_sparks_amount": little.amount if little != null else null,
		"big_sparks_texture": big_texture_path,
		"big_sparks_texture_size": big_texture_size,
		"accepted": accepted,
	}
	var output_dir := output_path.get_base_dir()
	var mkdir_error := DirAccess.make_dir_recursive_absolute(output_dir)
	if mkdir_error != OK:
		printerr("failed to create report directory: %s" % error_string(mkdir_error))
		root.queue_free()
		quit(6)
		return
	var file := FileAccess.open(output_path, FileAccess.WRITE)
	if file == null:
		printerr("failed to open report: %s" % output_path)
		root.queue_free()
		quit(7)
		return
	file.store_string(JSON.stringify(report, "\t") + "\n")
	file.close()
	root.queue_free()
	if not accepted:
		printerr("card-trail scene contract failed; see %s" % output_path)
		quit(8)
		return
	print("[PASS] candidate preserves the six-node NCardTrailVfx scene contract")
	print("[PASS] generated 256x256 mathematical star is bound only to BigSparks")
	quit(0)


func _parse_options(args: PackedStringArray) -> Dictionary:
	var options := {}
	var index := 0
	while index < args.size():
		var key := args[index]
		if key.begins_with("--") and index + 1 < args.size():
			options[key.trim_prefix("--")] = args[index + 1]
			index += 2
		else:
			index += 1
	return options
