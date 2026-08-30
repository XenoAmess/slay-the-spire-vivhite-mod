extends SceneTree

const SOURCE_PATH := "res://../../assets/vivhite-ironclad/generated/evolink-paid/2026-08-31/0112-card-vivhite-transformation-attempt-02/evaluation/center-crop-1000x760.png"
const OUTPUT_PATH := "res://../../assets/vivhite-ironclad/generated/evolink-paid/2026-08-31/0112-card-vivhite-transformation-attempt-02/evaluation/safe-area-78pct-overlay-1000x760.png"
const SAFE_LEFT := 110
const SAFE_RIGHT := 889
const SAFE_TOP := 84
const SAFE_BOTTOM := 675
const LINE_COLOR := Color(1.0, 0.08, 0.35, 1.0)


func _initialize() -> void:
	var image := Image.load_from_file(ProjectSettings.globalize_path(SOURCE_PATH))
	if image == null or image.is_empty() or image.get_size() != Vector2i(1000, 760):
		push_error("Expected the deterministic 1000x760 center crop.")
		quit(1)
		return

	for offset in range(-2, 3):
		for x in range(SAFE_LEFT, SAFE_RIGHT + 1):
			image.set_pixel(x, SAFE_TOP + offset, LINE_COLOR)
			image.set_pixel(x, SAFE_BOTTOM + offset, LINE_COLOR)
		for y in range(SAFE_TOP, SAFE_BOTTOM + 1):
			image.set_pixel(SAFE_LEFT + offset, y, LINE_COLOR)
			image.set_pixel(SAFE_RIGHT + offset, y, LINE_COLOR)

	var error := image.save_png(ProjectSettings.globalize_path(OUTPUT_PATH))
	if error != OK:
		push_error("Could not save safe-area diagnostic: %s" % error)
		quit(1)
		return
	quit(0)
