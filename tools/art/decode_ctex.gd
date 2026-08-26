extends SceneTree

# Runs inside a temporary Godot project created by the Python extractor.
# Input and output paths in the jobs file are res:// paths rooted in that
# temporary project, so ResourceLoader can open .ctex files directly.


func _initialize() -> void:
	var options := _parse_options(OS.get_cmdline_user_args())
	var jobs_path: String = options.get("jobs", "")
	var report_path: String = options.get("report", "")
	if jobs_path.is_empty() or report_path.is_empty():
		printerr("Usage: --jobs <res://jobs.json> --report <res://report.json>")
		quit(2)
		return

	var jobs_value: Variant = JSON.parse_string(FileAccess.get_file_as_string(jobs_path))
	if not jobs_value is Array:
		printerr("Texture job file must contain a JSON array: %s" % jobs_path)
		quit(2)
		return

	var results: Array[Dictionary] = []
	var failed := false
	for job_value: Variant in jobs_value:
		if not job_value is Dictionary:
			results.append({"ok": false, "error": "job is not an object"})
			failed = true
			continue

		var job: Dictionary = job_value
		var result := _decode_one(job)
		results.append(result)
		if not result.get("ok", false):
			failed = true

	var report_file := FileAccess.open(report_path, FileAccess.WRITE)
	if report_file == null:
		printerr("Could not open decoder report for writing: %s" % report_path)
		quit(2)
		return
	var report_payload := JSON.stringify({"results": results}, "  ")
	report_file.store_string(report_payload + "\n")
	report_file.close()

	quit(1 if failed else 0)


func _parse_options(args: PackedStringArray) -> Dictionary:
	var parsed := {}
	var index := 0
	while index < args.size():
		var option := args[index]
		if option in ["--jobs", "--report"] and index + 1 < args.size():
			parsed[option.trim_prefix("--")] = args[index + 1]
			index += 2
		else:
			index += 1
	return parsed


func _decode_one(job: Dictionary) -> Dictionary:
	var input_path := str(job.get("input", ""))
	var output_path := str(job.get("output", ""))
	var job_id := str(job.get("id", ""))
	if input_path.is_empty() or output_path.is_empty():
		return {
			"id": job_id,
			"ok": false,
			"error": "job is missing input or output",
		}

	var resource := ResourceLoader.load(
		input_path,
		"CompressedTexture2D",
		ResourceLoader.CACHE_MODE_IGNORE
	)
	if resource == null or not resource is Texture2D:
		return {
			"id": job_id,
			"ok": false,
			"error": "ResourceLoader could not load texture",
			"input": input_path,
		}

	var texture := resource as Texture2D
	var logical_width := texture.get_width()
	var logical_height := texture.get_height()
	var image := texture.get_image()
	if image == null or image.is_empty():
		return {
			"id": job_id,
			"ok": false,
			"error": "Texture2D.get_image returned no pixels",
			"input": input_path,
		}

	if image.is_compressed():
		var decompress_error := image.decompress()
		if decompress_error != OK:
			return {
				"id": job_id,
				"ok": false,
				"error": "Image.decompress failed: %s" % error_string(decompress_error),
				"input": input_path,
			}

	# VRAM block compression pads storage dimensions to a multiple of four.
	# Texture2D retains the original logical size (for example the Ironclad
	# character-select page is 3713x2427 while its S3TC image is 3716x2428).
	# Crop that transport padding before writing an editable atlas page.
	if image.get_width() != logical_width or image.get_height() != logical_height:
		image.crop(logical_width, logical_height)

	if image.get_format() != Image.FORMAT_RGBA8:
		image.convert(Image.FORMAT_RGBA8)
	var save_error := image.save_png(output_path)
	if save_error != OK:
		return {
			"id": job_id,
			"ok": false,
			"error": "Image.save_png failed: %s" % error_string(save_error),
			"output": output_path,
		}

	return {
		"id": job_id,
		"ok": true,
		"width": image.get_width(),
		"height": image.get_height(),
		"format": "RGBA8",
	}
