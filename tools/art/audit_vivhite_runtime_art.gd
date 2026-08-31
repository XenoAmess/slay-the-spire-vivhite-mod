extends SceneTree

## Read-only acceptance audit for every player-visible Vivhite runtime image.
##
## The audit decodes the actual PNG consumed by Godot. It never rewrites images,
## repairs Alpha, or treats a generated archive as proof that the runtime asset
## exists. Missing files, wrong dimensions/formats, transparent card scenes,
## and transparent UI pixels touching an edge are all hard failures.

const CARD_NAMES := [
	"LuminousProjection", "ClosedDomainMapping", "VivhiteTransformation",
	"AxiomRing", "ClosedProjection", "TangentStarlight", "OpenSetShelter",
	"LocalHomeomorphism", "ScaleTransformation", "IsoperimetricWard",
	"TopologicalGrowth", "LawOfConservation", "LifeManifold", "MobiusLoop",
	"Invariant", "GeodesicVeil", "ClosedManifold", "AxiomOfLife",
	"InfiniteExtension", "ConservationFirmament", "RecurrentStarlight",
	"TerminationCondition", "ParallelStarfall", "AstralSearch",
	"HeuristicShield", "SuccessorFormula", "BacktrackingSpell",
	"ConvergenceVerdict", "DivideAndConquerCircle", "AstralPursuit",
	"PrefetchFuture", "InductiveCircle", "EventLoop", "ProofOfTermination",
	"DynamicProgramming", "InfiniteStarSequence", "OptimalAlgorithm",
	"CrimsonArea", "TrichromaticWaltz", "CompositeColorWheel",
	"DifferentialSampling", "Chiaroscuro", "NegativeSpace",
	"SpectralIntegral", "GoldenComposition", "RiemannStarArray",
	"ChromaticTransition", "ColorConservation", "CompositeColorField",
	"ComplementaryAfterimage", "DefiniteCrimsonIntegral",
	"CrimsonConservationLaw", "InfiniteCanvas", "PerfectSynthesis",
	"GoldenRatio", "AstralMeasure", "ChromaticSequence", "UnifiedFieldTheory",
	"ConservedRecurrence", "ChromaticLimit",
	"VivhitesCrimsonTransformationRitual"
]

const POWER_NAMES := [
	"AstralPursuitMarginPower", "AstralPursuitPower", "ChiaroscuroPower",
	"ClosedManifoldPower", "ColorConservationPower",
	"CrimsonConservationLawPower", "DynamicProgrammingPower",
	"InductiveCirclePower", "InfiniteCanvasPower",
	"InfiniteDimensionalityPower", "InfiniteDrainPower",
	"InfiniteDrainThisTurnPower", "InfiniteExtensionPower",
	"InfiniteMarginPower", "LawOfConservationPower", "LifeManifoldPower",
	"OptimalAlgorithmPower", "UnifiedFieldTheoryPower",
	"VivhitesCrimsonTransformationRitualPower"
]

const RELIC_NAMES := ["SolitaryCrown", "SolitaryCrownOutline"]

const ENERGY_NAMES := [
	"Vivhite_energy_orb_layer_1", "Vivhite_energy_orb_layer_2",
	"Vivhite_energy_orb_layer_3", "Vivhite_energy_orb_layer_4",
	"Vivhite_energy_orb_layer_5", "energy_big"
]

# These hashes are evidence from the pre-audit runtime package. Some legacy red
# templates happen to satisfy dimensions and corner-Alpha checks, so structural
# validation alone would incorrectly bless them as finished art.
const LEGACY_PLACEHOLDER_SHA256 := {
	"5a0be66752f8d26bd857f11b4e78fb490ac47c93819c259cd8f363dfb73a11e7": "red energy template / layer 1",
	"ded01ebbdf6532f70c338ba3b573e235e26ea73e2fa0c50954c9818ebd6584f6": "red energy template / layer 2",
	"55d944fa7ca5c248bca7670625699368062b26972da9b3aea312022a98907496": "red energy template / layer 3",
	"e59534bb60b30ce517c5d16db715ae460a03330e20fde5ac3f31708eebc52b75": "red energy template / layer 4",
	"12b55e14a01ab7ba318b1a0d77615dfebb18e18aa00580d4ccbcf75eba478ea5": "red energy template / layer 5",
	"4cd2a3ae8fbc7b4369c495597a933ac2a5eaf28dceddb64bc30f2f5375491290": "red energy text template",
	"9071a1f2d4cfdc6e4b90c59d5b5cc65e2ca7e1b6da902d275804d5a31f188fc2": "shared fire relic/power placeholder",
	"decdc1380438eb01fc8448e8e294699cc386b761137184e214af6cffd3039d8c": "retired Vivhite Strike placeholder",
	"4b5c76a2463a8db99e435c3817936b88738a8f571d3f85e7850fd2dfeb5eb225": "retired Vivhite Defend placeholder"
}


func _initialize() -> void:
	var options := _parse_options(OS.get_cmdline_user_args())
	var repo_root: String = options.get("repo-root", "")
	var report_path: String = options.get("report", "")
	if repo_root.is_empty():
		printerr("Usage: --repo-root <absolute repository path> [--report <json>]")
		quit(2)
		return

	var result := _audit(repo_root.simplify_path())
	if not report_path.is_empty():
		var report_dir := report_path.get_base_dir()
		var mkdir_error := DirAccess.make_dir_recursive_absolute(report_dir)
		if mkdir_error != OK:
			printerr("Could not create report directory: %s" % error_string(mkdir_error))
			quit(2)
			return
		var report_file := FileAccess.open(report_path, FileAccess.WRITE)
		if report_file == null:
			printerr("Could not create audit report: %s" % report_path)
			quit(2)
			return
		report_file.store_string(JSON.stringify(result, "  ") + "\n")
		report_file.close()

	for error in result.errors:
		printerr(error)
	print(
		"Vivhite runtime art audit: %d/%d accepted; %d error(s)"
		% [result.accepted, result.expected, result.errors.size()]
	)
	quit(0 if result.errors.is_empty() else 3)


func _parse_options(args: PackedStringArray) -> Dictionary:
	var parsed := {}
	var index := 0
	while index < args.size():
		var option := args[index]
		if option in ["--repo-root", "--report"] and index + 1 < args.size():
			parsed[option.trim_prefix("--")] = args[index + 1]
			index += 2
		else:
			index += 1
	return parsed


func _audit(repo_root: String) -> Dictionary:
	var result := {
		"repo_root": repo_root,
		"expected": CARD_NAMES.size() + POWER_NAMES.size() + RELIC_NAMES.size()
			+ ENERGY_NAMES.size() + 1 + 3,
		"accepted": 0,
		"errors": [],
		"assets": []
	}
	var vivhite_root := repo_root.path_join("Vivhite/Vivhite")

	for card_name in CARD_NAMES:
		_audit_opaque(
			vivhite_root.path_join("images/cards/%s.png" % card_name),
			Vector2i(1000, 760),
			"card",
			result
		)
	for power_name in POWER_NAMES:
		_audit_transparent(
			vivhite_root.path_join("images/powers/%s.png" % power_name),
			Vector2i(256, 256),
			"power",
			result
		)
	for relic_name in RELIC_NAMES:
		_audit_transparent(
			vivhite_root.path_join("images/relics/%s.png" % relic_name),
			Vector2i(256, 256),
			"relic",
			result
		)
	for energy_name in ENERGY_NAMES:
		_audit_transparent(
			vivhite_root.path_join("images/characters/%s.png" % energy_name),
			Vector2i(256, 256),
			"energy",
			result
		)
	_audit_transparent(
		vivhite_root.path_join("images/characters/energy_text.png"),
		Vector2i(24, 24),
		"energy_text",
		result
	)
	_audit_transparent(
		vivhite_root.path_join("skins/ironclad/scenes/vfx/vivhite_eye_lens_glint.png"),
		Vector2i(512, 512),
		"vfx",
		result
	)
	_audit_grayscale_opaque(
		vivhite_root.path_join(
			"skins/ironclad/transitions/vivhite_character_select_transition.png"
		),
		Vector2i(2560, 1200),
		"vfx",
		result
	)
	_audit_transparent(
		vivhite_root.path_join("images/vfx/vivhite_card_trail_mathematical_star_0194.png"),
		Vector2i(256, 256),
		"vfx",
		result
	)
	return result


func _audit_opaque(
	path: String,
	expected_size: Vector2i,
	kind: String,
	result: Dictionary
) -> void:
	var decoded := _decode(path, expected_size, kind, result)
	if decoded.is_empty():
		return
	var image: Image = decoded.image
	var errors: Array = decoded.errors
	if image.get_format() != Image.FORMAT_RGB8:
		errors.append("expected RGB8, got format %d" % int(image.get_format()))
	if not _is_fully_opaque(image):
		errors.append("contains Alpha below 255")
	_finish_asset(path, kind, image, errors, result)


func _audit_transparent(
	path: String,
	expected_size: Vector2i,
	kind: String,
	result: Dictionary
) -> void:
	var decoded := _decode(path, expected_size, kind, result)
	if decoded.is_empty():
		return
	var image: Image = decoded.image
	var errors: Array = decoded.errors
	if image.get_format() != Image.FORMAT_RGBA8:
		errors.append("expected native RGBA8, got format %d" % int(image.get_format()))
	else:
		var alpha := _inspect_alpha(image)
		if alpha.corners != [0, 0, 0, 0]:
			errors.append("corner Alpha is %s, expected [0, 0, 0, 0]" % [alpha.corners])
		if alpha.nonzero_pixels <= 0 or alpha.opaque_pixels <= 0:
			errors.append("has no visible, substantially opaque subject")
		var bbox: Rect2i = alpha.bbox
		if (
			alpha.nonzero_pixels > 0
			and (
				bbox.position.x <= 0
				or bbox.position.y <= 0
				or bbox.end.x >= image.get_width()
				or bbox.end.y >= image.get_height()
			)
		):
			errors.append("nonzero Alpha touches an image edge: %s" % bbox)
	_finish_asset(path, kind, image, errors, result)


func _audit_grayscale_opaque(
	path: String,
	expected_size: Vector2i,
	kind: String,
	result: Dictionary
) -> void:
	var decoded := _decode(path, expected_size, kind, result)
	if decoded.is_empty():
		return
	var image: Image = decoded.image
	var errors: Array = decoded.errors
	if image.get_format() != Image.FORMAT_RGB8:
		errors.append("expected RGB8, got format %d" % int(image.get_format()))
	if not _is_fully_opaque(image):
		errors.append("contains Alpha below 255")
	if not _is_strict_grayscale(image):
		errors.append("contains non-grayscale RGB pixels")
	_finish_asset(path, kind, image, errors, result)


func _decode(
	path: String,
	expected_size: Vector2i,
	kind: String,
	result: Dictionary
) -> Dictionary:
	if not FileAccess.file_exists(path):
		result.errors.append("Missing %s image: %s" % [kind, path])
		result.assets.append({"path": path, "kind": kind, "status": "missing"})
		return {}
	var source_sha256 := FileAccess.get_sha256(path).to_lower()
	if LEGACY_PLACEHOLDER_SHA256.has(source_sha256):
		var legacy_name: String = LEGACY_PLACEHOLDER_SHA256[source_sha256]
		result.errors.append(
			"Rejected %s image %s: still uses %s"
			% [kind, path, legacy_name]
		)
		result.assets.append({
			"path": path,
			"kind": kind,
			"status": "legacy_placeholder",
			"sha256": source_sha256,
			"placeholder": legacy_name
		})
		return {}
	var image := Image.load_from_file(path)
	if image == null or image.is_empty():
		result.errors.append("Could not decode %s image: %s" % [kind, path])
		result.assets.append({"path": path, "kind": kind, "status": "decode_error"})
		return {}
	if image.is_compressed():
		var decompress_error := image.decompress()
		if decompress_error != OK:
			result.errors.append(
				"Could not decompress %s image %s: %s"
				% [kind, path, error_string(decompress_error)]
			)
			result.assets.append({"path": path, "kind": kind, "status": "decode_error"})
			return {}
	var errors := []
	if image.get_size() != expected_size:
		errors.append(
			"expected %dx%d, got %dx%d"
			% [expected_size.x, expected_size.y, image.get_width(), image.get_height()]
		)
	return {"image": image, "errors": errors}


func _finish_asset(
	path: String,
	kind: String,
	image: Image,
	errors: Array,
	result: Dictionary
) -> void:
	var status := "accepted" if errors.is_empty() else "rejected"
	result.assets.append({
		"path": path,
		"kind": kind,
		"status": status,
		"size": [image.get_width(), image.get_height()],
		"format": int(image.get_format()),
		"sha256": FileAccess.get_sha256(path),
		"errors": errors
	})
	if errors.is_empty():
		result.accepted += 1
	else:
		for reason in errors:
			result.errors.append("Rejected %s image %s: %s" % [kind, path, reason])


func _is_fully_opaque(image: Image) -> bool:
	var rgba := image.duplicate()
	if rgba.get_format() != Image.FORMAT_RGBA8:
		rgba.convert(Image.FORMAT_RGBA8)
	var bytes: PackedByteArray = rgba.get_data()
	for index in range(3, bytes.size(), 4):
		if bytes[index] != 255:
			return false
	return true


func _is_strict_grayscale(image: Image) -> bool:
	var rgb := image.duplicate()
	if rgb.get_format() != Image.FORMAT_RGB8:
		rgb.convert(Image.FORMAT_RGB8)
	var bytes: PackedByteArray = rgb.get_data()
	for index in range(0, bytes.size(), 3):
		if bytes[index] != bytes[index + 1] or bytes[index] != bytes[index + 2]:
			return false
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
