extends SceneTree

const SOURCE_PATH := "res://../../assets/vivhite-ironclad/generated/evolink-paid/2026-08-31/0116-card-vivhite-transformation-attempt-03/evaluation/center-crop-1000x760.png"
const SAFE_OUTPUT_PATH := "res://../../assets/vivhite-ironclad/generated/evolink-paid/2026-08-31/0116-card-vivhite-transformation-attempt-03/evaluation/safe-area-70pct-overlay-1000x760.png"
const FACE_OUTPUT_PATH := "res://../../assets/vivhite-ironclad/generated/evolink-paid/2026-08-31/0116-card-vivhite-transformation-attempt-03/evaluation/face-mouth-detail-native-crop.png"
const SAFE_LEFT := 150
const SAFE_RIGHT := 849
const SAFE_TOP := 114
const SAFE_BOTTOM := 645
const LINE_COLOR := Color(1.0, 0.08, 0.35, 1.0)
const FACE_RECT := Rect2i(350, 0, 330, 270)


func _initialize() -> void:
	var source := Image.load_from_file(ProjectSettings.globalize_path(SOURCE_PATH))
	if source == null or source.is_empty() or source.get_size() != Vector2i(1000, 760):
		push_error("Expected the deterministic 1000x760 center crop.")
		quit(1)
		return

	var safe_overlay := source.duplicate()
	for offset in range(-2, 3):
		for x in range(SAFE_LEFT, SAFE_RIGHT + 1):
			safe_overlay.set_pixel(x, SAFE_TOP + offset, LINE_COLOR)
			safe_overlay.set_pixel(x, SAFE_BOTTOM + offset, LINE_COLOR)
		for y in range(SAFE_TOP, SAFE_BOTTOM + 1):
			safe_overlay.set_pixel(SAFE_LEFT + offset, y, LINE_COLOR)
			safe_overlay.set_pixel(SAFE_RIGHT + offset, y, LINE_COLOR)

	if safe_overlay.save_png(ProjectSettings.globalize_path(SAFE_OUTPUT_PATH)) != OK:
		push_error("Could not save the safe-area diagnostic.")
		quit(1)
		return

	var face_detail := source.get_region(FACE_RECT)
	if face_detail.save_png(ProjectSettings.globalize_path(FACE_OUTPUT_PATH)) != OK:
		push_error("Could not save the face-and-mouth diagnostic crop.")
		quit(1)
		return

	quit(0)
